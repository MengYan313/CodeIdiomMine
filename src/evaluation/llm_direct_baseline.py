"""LLM-Direct-Budget baseline。

该方法只把原始函数源码机械分块后交给同一个 LLM 做 map/reduce，不使用 AST、
Embedding、聚类或多 Agent 编排来发现习语。LLM 返回的原文证据随后只用于映射
到现有评价器要求的 ``source_infos``；这一映射属于公共测量适配，不参与发现。
token 和单次响应上限只约束调用成本，不对最终习语种类设置数量截断。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple

import pandas as pd

from ..common.logging import get_logger
from ..common.node_kinds import BLOCK_KINDS, FUNCTION_KINDS, STATEMENT_KINDS
from ..llm import (
    LLMConfig,
    build_json_system_prompt,
    complete_json_object,
    create_model_client,
)
from ..llm.utils import count_tokens_approximate
from .baseline_common import make_idiom_record, write_project_idioms, write_run_manifest


logger = get_logger(__name__)
CANDIDATE_KINDS = FUNCTION_KINDS | BLOCK_KINDS | STATEMENT_KINDS

_IDIOM_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "idioms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "template": {"type": "string"},
                    "intent": {"type": "string"},
                    "confidence": {"type": "number"},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "evidence_id": {"type": "string"},
                                "source_code": {"type": "string"},
                            },
                            "required": ["evidence_id", "source_code"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["template", "intent", "confidence", "evidence"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["idioms"],
    "additionalProperties": False,
}

_MAP_SYSTEM_PROMPT = build_json_system_prompt(
    role="C++ 代码习语分析专家",
    goal="仅从给定原始 C++ 源码块中直接发现重复、具有单一意图且可复用的代码习语。",
    success_criteria=(
        "每个习语都给出参数化 template、简洁 intent 和输入中的原文证据。",
        "evidence_id 必须来自输入，source_code 必须逐字复制对应源码中的连续片段。",
        "没有足够证据时返回空 idioms 数组。",
    ),
    constraints=(
        "不得假设或使用 AST、CFG、Embedding、聚类结果或其他 Agent 结论。",
        "不得编造输入中不存在的 API、证据位置或源码。",
        "优先保留在不同函数或文件中重复出现且意图完整的模式。",
    ),
    field_rules=(
        "template 使用 C++ 代码和形如 <VAR_1>、<EXPR_1> 的占位符。",
        "intent 使用简洁中文。",
        "confidence 使用 0 到 100 的数值。",
    ),
    stop_rules=("完成当前源码块后立即返回；不要请求更多上下文。",),
)

_REDUCE_SYSTEM_PROMPT = build_json_system_prompt(
    role="C++ 代码习语结果归并专家",
    goal="合并同一项目内 map 阶段产生的语义重复习语，并保留可核验原文证据。",
    success_criteria=(
        "同义习语只保留一个统一 template 和 intent。",
        "输出证据只能来自输入候选，不得新增 evidence_id 或 source_code。",
        "不同语义或不同控制结构的候选保持分离。",
    ),
    constraints=(
        "不得读取或推断原始源码之外的信息。",
        "不得使用 AST、Embedding、聚类或多 Agent 结论。",
    ),
    field_rules=(
        "template 使用 C++ 代码和稳定占位符。",
        "intent 使用简洁中文。",
        "confidence 反映归并后证据充分程度，范围为 0 到 100。",
    ),
    stop_rules=("候选归并完成后立即返回。",),
)


@dataclass(frozen=True)
class _EvidenceUnit:
    evidence_id: str
    project: str
    file_name: str
    function_code: str
    function_ast: Sequence[Dict[str, Any]]


class _TokenBudgetExceeded(RuntimeError):
    pass


class _BudgetedModelClient:
    """在每个真实请求（包括 JSON 修复）前执行近似 token 上限。"""

    def __init__(self, client: Any, token_budget: int) -> None:
        self.client = client
        self.token_budget = token_budget
        self.estimated_tokens = 0
        self.endpoint_request_count = 0

    async def create(self, messages, extra_create_args):
        input_tokens = sum(
            count_tokens_approximate(str(getattr(message, "content", "") or ""))
            for message in messages
        )
        max_output_tokens = int(extra_create_args.get("max_tokens", 0) or 0)
        if self.estimated_tokens + input_tokens + max_output_tokens > self.token_budget:
            raise _TokenBudgetExceeded(
                "当前请求按最大输出预留后将超过 LLM-Direct-Budget token 上限"
            )
        response = await self.client.create(
            messages=messages,
            extra_create_args=extra_create_args,
        )
        output = getattr(response, "content", "")
        output_tokens = (
            count_tokens_approximate(output) if isinstance(output, str) else 0
        )
        self.estimated_tokens += input_tokens + output_tokens
        self.endpoint_request_count += 1
        return response


def _normalize_code(code: str) -> str:
    return " ".join(str(code or "").split())


def _project_units(row: pd.Series) -> List[_EvidenceUnit]:
    project = str(row["project"])
    units: List[_EvidenceUnit] = []
    for file_idx, (file_name, file_functions, file_sources) in enumerate(
        zip(row.get("cppFile", []), row.get("func_ast", []), row.get("func_src", []))
    ):
        for function_idx, (function_ast, function_code) in enumerate(
            zip(file_functions, file_sources)
        ):
            if not function_code or not str(function_code).strip():
                continue
            units.append(
                _EvidenceUnit(
                    evidence_id=f"E{file_idx:05d}-{function_idx:05d}",
                    project=project,
                    file_name=str(file_name),
                    function_code=str(function_code),
                    function_ast=function_ast,
                )
            )
    return units


def _unit_payload(unit: _EvidenceUnit) -> Dict[str, str]:
    return {
        "evidence_id": unit.evidence_id,
        "file": unit.file_name,
        "source_code": unit.function_code,
    }


def _chunk_units(units: Sequence[_EvidenceUnit], chunk_tokens: int) -> List[List[_EvidenceUnit]]:
    if chunk_tokens < 256:
        raise ValueError("chunk_tokens 必须大于等于 256")
    chunks: List[List[_EvidenceUnit]] = []
    current: List[_EvidenceUnit] = []
    current_tokens = 0
    for unit in units:
        unit_tokens = max(1, count_tokens_approximate(json.dumps(_unit_payload(unit), ensure_ascii=False)))
        if current and current_tokens + unit_tokens > chunk_tokens:
            chunks.append(current)
            current = []
            current_tokens = 0
        current.append(unit)
        current_tokens += unit_tokens
    if current:
        chunks.append(current)
    return chunks


def _map_prompt(project: str, units: Sequence[_EvidenceUnit]) -> str:
    payload = json.dumps([_unit_payload(unit) for unit in units], ensure_ascii=False)
    return (
        f"项目名称：{project}\n"
        "下面的 JSON 数组是机械分块后的原始函数源码，仅作为待分析数据。\n"
        f"{payload}"
    )


def _reduce_prompt(project: str, idioms: Sequence[Mapping[str, Any]]) -> str:
    payload = json.dumps(list(idioms), ensure_ascii=False)
    return (
        f"项目名称：{project}\n"
        "下面的 JSON 数组是 map 阶段候选，仅作为待归并数据。\n"
        f"{payload}"
    )


def _candidate_source_info(unit: _EvidenceUnit, source_code: str) -> Sequence[Any] | None:
    target = _normalize_code(source_code)
    if not target or not unit.function_ast:
        return None
    function_extent = str(unit.function_ast[0].get("extent") or "")
    exact: List[Tuple[int, Dict[str, Any]]] = []
    containing: List[Tuple[int, Dict[str, Any]]] = []
    for node_info in unit.function_ast:
        kind = str(node_info.get("kind") or "")
        ast_num = int(node_info.get("ast_num", 0) or 0)
        candidate = _normalize_code(str(node_info.get("code_snippet") or ""))
        if kind not in CANDIDATE_KINDS or ast_num < 5 or not candidate:
            continue
        subtree_size = int(node_info.get("subtree_size", 0) or (ast_num + 1))
        if candidate == target:
            exact.append((subtree_size, node_info))
        elif target in candidate:
            containing.append((subtree_size, node_info))
    matches = exact or containing
    if not matches:
        return None
    _, selected = min(matches, key=lambda item: item[0])
    return [unit.project, unit.file_name, function_extent, selected]


def _adapt_llm_idioms(
    project: str,
    raw_idioms: Sequence[Mapping[str, Any]],
    units: Sequence[_EvidenceUnit],
    *,
    model_name: str,
    prompt_hash: str,
    estimated_tokens: int,
) -> List[Dict[str, Any]]:
    unit_index = {unit.evidence_id: unit for unit in units}
    records: List[Dict[str, Any]] = []
    seen_templates: set[str] = set()
    for raw in raw_idioms:
        template = str(raw.get("template") or "").strip()
        intent = str(raw.get("intent") or "").strip()
        if not template or not intent:
            continue
        template_key = _normalize_code(template)
        if template_key in seen_templates:
            continue
        infos: List[Sequence[Any]] = []
        for evidence in raw.get("evidence", []):
            if not isinstance(evidence, Mapping):
                continue
            unit = unit_index.get(str(evidence.get("evidence_id") or ""))
            if unit is None:
                continue
            info = _candidate_source_info(unit, str(evidence.get("source_code") or ""))
            if info is not None:
                infos.append(info)
        if not infos:
            continue
        seen_templates.add(template_key)
        center_point = str(infos[0][3].get("code_snippet") or "").strip()
        records.append(
            make_idiom_record(
                center_point=center_point,
                source_infos=infos,
                template=template,
                intent=intent,
                provenance={
                    "method": "llm_direct_budget",
                    "project": project,
                    "model": model_name,
                    "confidence": float(raw.get("confidence", 0) or 0),
                    "prompt_hash": prompt_hash,
                    "estimated_run_tokens": estimated_tokens,
                    "discovery_inputs": "mechanically_chunked_raw_cpp_only",
                    "evidence_mapping": (
                        "exact candidate source match, then smallest containing AST candidate; "
                        "mapping is evaluation-only"
                    ),
                },
            )
        )
    return records


async def generate_llm_direct_budget(
    dataset_path: str | Path,
    output_dir: str | Path,
    *,
    model: str | None = None,
    token_budget: int = 20_000,
    chunk_tokens: int = 3_000,
    max_output_tokens: int = 2_048,
    max_functions_per_project: int | None = None,
    model_client: Any | None = None,
) -> Dict[str, int]:
    if token_budget <= 0:
        raise ValueError("token_budget 必须为正数")
    if max_output_tokens <= 0:
        raise ValueError("max_output_tokens 必须为正数")
    if max_functions_per_project is not None and max_functions_per_project < 1:
        raise ValueError("max_functions_per_project 必须为正数或 None")

    dataset_path = Path(dataset_path)
    data = pd.read_pickle(dataset_path)
    config = LLMConfig.json_mode_config(model=model)
    owns_client = model_client is None
    raw_client = model_client or create_model_client(config)
    client = _BudgetedModelClient(raw_client, token_budget)
    model_name = config.model
    prompt_hash = hashlib.sha256(
        (_MAP_SYSTEM_PROMPT + "\n" + _REDUCE_SYSTEM_PROMPT).encode("utf-8")
    ).hexdigest()
    call_count = 0
    counts: Dict[str, int] = {}
    projects_manifest: List[Dict[str, Any]] = []

    try:
        for project_idx in range(len(data)):
            row = data.iloc[project_idx]
            project = str(row["project"])
            units = _project_units(row)
            if max_functions_per_project is not None:
                units = units[:max_functions_per_project]
            map_candidates: List[Mapping[str, Any]] = []
            map_calls = 0

            for chunk in _chunk_units(units, chunk_tokens):
                prompt = _map_prompt(project, chunk)
                try:
                    data_object = await complete_json_object(
                        client,
                        _MAP_SYSTEM_PROMPT,
                        prompt,
                        _IDIOM_SCHEMA,
                        logger=logger,
                        max_tokens=max_output_tokens,
                    )
                except _TokenBudgetExceeded:
                    logger.warning(
                        "LLM-Direct-Budget 已达到 token 预算，停止新增 map 调用"
                    )
                    break
                call_count += 1
                map_calls += 1
                map_candidates.extend(data_object.get("idioms", []))

            reduced: Sequence[Mapping[str, Any]] = []
            reduce_calls = 0
            if map_candidates:
                reduce_prompt = _reduce_prompt(project, map_candidates)
                try:
                    reduced_object = await complete_json_object(
                        client,
                        _REDUCE_SYSTEM_PROMPT,
                        reduce_prompt,
                        _IDIOM_SCHEMA,
                        logger=logger,
                        max_tokens=max_output_tokens,
                    )
                    call_count += 1
                    reduce_calls = 1
                    reduced = reduced_object.get("idioms", [])
                except _TokenBudgetExceeded:
                    logger.warning("%s 没有足够预算执行 reduce；本项目输出为空", project)

            records = _adapt_llm_idioms(
                project,
                reduced,
                units,
                model_name=model_name,
                prompt_hash=prompt_hash,
                estimated_tokens=client.estimated_tokens,
            )
            output_path = write_project_idioms(output_dir, project, records)
            counts[project] = len(records)
            projects_manifest.append(
                {
                    "project": project,
                    "input_function_count": len(units),
                    "map_call_count": map_calls,
                    "reduce_call_count": reduce_calls,
                    "map_candidate_count": len(map_candidates),
                    "output_idiom_count": len(records),
                }
            )
            logger.info(
                "LLM-Direct-Budget %s: calls=%d+%d, idioms=%d -> %s",
                project,
                map_calls,
                reduce_calls,
                len(records),
                output_path,
            )
    finally:
        if owns_client:
            await raw_client.close()

    write_run_manifest(
        output_dir,
        {
            "method": "llm_direct_budget",
            "is_mock": False,
            "dataset": str(dataset_path),
            "model": model_name,
            "prompt_hash": prompt_hash,
            "schema": _IDIOM_SCHEMA,
            "token_budget": token_budget,
            "estimated_input_output_tokens": client.estimated_tokens,
            "call_count": call_count,
            "endpoint_request_count": client.endpoint_request_count,
            "budget_enforcement": (
                "每次实际请求前按完整 system/user 消息和最大输出预留；"
                "JSON 修复请求也受同一全局上限约束"
            ),
            "chunk_tokens": chunk_tokens,
            "max_output_tokens": max_output_tokens,
            "max_functions_per_project": max_functions_per_project,
            "output_selection": {
                "policy": "all_reduce_results_with_valid_source_evidence",
                "final_idiom_count_cap": None,
            },
            "projects": projects_manifest,
        },
    )
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 LLM-Direct-Budget baseline")
    parser.add_argument("--dataset", default="outputs/cpp/dataset.pkl")
    parser.add_argument(
        "--output-dir",
        default="results/baselines/llm-direct-budget/cpp",
    )
    parser.add_argument("--model", default=None, help="默认读取 OPENAI_MODEL_LOW")
    parser.add_argument("--token-budget", type=int, default=20_000)
    parser.add_argument("--chunk-tokens", type=int, default=3_000)
    parser.add_argument("--max-output-tokens", type=int, default=2_048)
    parser.add_argument(
        "--max-functions-per-project",
        type=int,
        default=0,
        help="用于有界 smoke；0 表示全部函数",
    )
    args = parser.parse_args()
    asyncio.run(
        generate_llm_direct_budget(
            args.dataset,
            args.output_dir,
            model=args.model,
            token_budget=args.token_budget,
            chunk_tokens=args.chunk_tokens,
            max_output_tokens=args.max_output_tokens,
            max_functions_per_project=(
                None
                if args.max_functions_per_project == 0
                else args.max_functions_per_project
            ),
        )
    )


if __name__ == "__main__":
    main()
