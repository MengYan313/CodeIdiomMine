"""LLM-Direct-Budget baseline。

该方法只把原始函数源码机械分块后交给同一个 LLM 做 map/reduce，不使用 AST、
Embedding、聚类或多 Agent 编排来发现习语。LLM 返回的原文证据随后只用于映射
到现有评价器要求的 ``source_infos``；这一映射属于公共测量适配，不参与发现。
token 和单次响应上限只约束调用成本，不对最终习语种类设置数量截断。
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple

import pandas as pd

from ..common.logging import get_logger
from ..common.node_kinds import BLOCK_KINDS, FUNCTION_KINDS, STATEMENT_KINDS
from ..common.run_checkpoint import RunCheckpoint
from ..llm import (
    LLMConfig,
    build_json_system_prompt,
    complete_json_object,
    create_model_client,
)
from ..llm.json_output import append_json_output_contract
from ..llm.utils import count_tokens_approximate
from ..parser.dataset import select_split
from .baseline_common import make_idiom_record, write_project_idioms, write_run_manifest


logger = get_logger(__name__)
CANDIDATE_KINDS = FUNCTION_KINDS | BLOCK_KINDS | STATEMENT_KINDS
DEFAULT_CHECKPOINT_PATH = Path(
    "outputs/cli11/llm-direct-budget/checkpoint.sqlite3"
)

_MAP_IDIOM_SCHEMA: Dict[str, Any] = {
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

_REDUCE_IDIOM_SCHEMA: Dict[str, Any] = {
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
                    "evidence_refs": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "template",
                    "intent",
                    "confidence",
                    "evidence_refs",
                ],
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
        "输出 evidence_refs 的并集必须与输入并集完全相等，不得遗漏。",
        "不同语义或不同控制结构的候选保持分离。",
    ),
    constraints=(
        "不得读取或推断原始源码之外的信息。",
        "不得使用 AST、Embedding、聚类或多 Agent 结论。",
        "不得新增、猜测或改写 evidence_refs。",
    ),
    field_rules=(
        "template 使用 C++ 代码和稳定占位符。",
        "intent 使用简洁中文。",
        "confidence 反映归并后证据充分程度，范围为 0 到 100。",
        "evidence_refs 是输入候选 ref 的稳定并集。",
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
        self.endpoint_request_count += 1
        try:
            response = await self.client.create(
                messages=messages,
                extra_create_args=extra_create_args,
            )
        except Exception:
            self.estimated_tokens += input_tokens
            raise
        output = getattr(response, "content", "")
        output_tokens = (
            count_tokens_approximate(output) if isinstance(output, str) else 0
        )
        self.estimated_tokens += input_tokens + output_tokens
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
        "下面的 JSON 数组是 map 或上一层 reduce 产生的候选，仅作为待归并数据。"
        "请尽量合并语义重复项，但不得为减少数量而合并不同语义的候选。"
        "输出 refs 并集必须与输入完全相等，不得遗漏、新增、猜测或改写。\n"
        f"{payload}"
    )


def _register_reduce_evidence(
    idioms: Sequence[Mapping[str, Any]],
) -> tuple[List[Dict[str, Any]], Dict[str, Dict[str, str]]]:
    refs_by_evidence: Dict[tuple[str, str], str] = {}
    evidence_by_ref: Dict[str, Dict[str, str]] = {}
    reduced: List[Dict[str, Any]] = []
    for idiom in idioms:
        evidence_refs: List[str] = []
        for evidence in idiom["evidence"]:
            key = (str(evidence["evidence_id"]), str(evidence["source_code"]))
            ref = refs_by_evidence.get(key)
            if ref is None:
                ref = f"R{len(refs_by_evidence):06d}"
                refs_by_evidence[key] = ref
                evidence_by_ref[ref] = {
                    "evidence_id": key[0],
                    "source_code": key[1],
                }
            if ref not in evidence_refs:
                evidence_refs.append(ref)
        reduced.append(
            {
                "template": idiom["template"],
                "intent": idiom["intent"],
                "confidence": idiom["confidence"],
                "evidence_refs": evidence_refs,
            }
        )
    return reduced, evidence_by_ref


def _validate_reduce_refs(
    idioms: Sequence[Mapping[str, Any]],
    allowed_refs: set[str],
) -> None:
    output_refs = {
        str(ref) for idiom in idioms for ref in idiom["evidence_refs"]
    }
    missing = sorted(allowed_refs - output_refs)
    unknown = sorted(output_refs - allowed_refs)
    if missing or unknown:
        details = []
        if missing:
            details.append("遗漏 " + ", ".join(missing))
        if unknown:
            details.append("不存在 " + ", ".join(unknown))
        raise ValueError("reduce evidence_refs 与输入不一致: " + "; ".join(details))


def _deduplicate_reduce_idioms(
    idioms: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    deduplicated: Dict[str, Dict[str, Any]] = {}
    for idiom in idioms:
        template = str(idiom["template"])
        template_key = _normalize_code(template)
        existing = deduplicated.get(template_key)
        if existing is None:
            deduplicated[template_key] = {
                "template": template,
                "intent": idiom["intent"],
                "confidence": idiom["confidence"],
                "evidence_refs": list(dict.fromkeys(idiom["evidence_refs"])),
            }
            continue
        existing_refs = existing["evidence_refs"]
        existing_refs.extend(
            ref for ref in idiom["evidence_refs"] if ref not in existing_refs
        )
    return list(deduplicated.values())


def _restore_reduce_evidence(
    idioms: Sequence[Mapping[str, Any]],
    evidence_by_ref: Mapping[str, Mapping[str, str]],
) -> List[Dict[str, Any]]:
    _validate_reduce_refs(idioms, set(evidence_by_ref))
    return [
        {
            "template": idiom["template"],
            "intent": idiom["intent"],
            "confidence": idiom["confidence"],
            "evidence": [
                dict(evidence_by_ref[ref]) for ref in idiom["evidence_refs"]
            ],
        }
        for idiom in idioms
    ]


def _reduce_input_tokens(
    project: str,
    idioms: Sequence[Mapping[str, Any]],
) -> int:
    user_prompt = append_json_output_contract(
        _reduce_prompt(project, idioms),
        _REDUCE_IDIOM_SCHEMA,
    )
    return count_tokens_approximate(_REDUCE_SYSTEM_PROMPT) + count_tokens_approximate(
        user_prompt
    )


def _chunk_reduce_candidates(
    project: str,
    idioms: Sequence[Mapping[str, Any]],
    chunk_tokens: int,
) -> List[List[Mapping[str, Any]]]:
    if chunk_tokens < 256:
        raise ValueError("reduce_chunk_tokens 必须大于等于 256")
    chunks: List[List[Mapping[str, Any]]] = []
    current: List[Mapping[str, Any]] = []
    for idiom in idioms:
        candidate = [*current, idiom]
        if current and _reduce_input_tokens(project, candidate) > chunk_tokens:
            chunks.append(current)
            current = [idiom]
        else:
            current = candidate
    if current:
        chunks.append(current)
    if any(_reduce_input_tokens(project, chunk) > chunk_tokens for chunk in chunks):
        raise ValueError("单个 reduce 候选超过 reduce_chunk_tokens，无法安全分块")
    return chunks


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
    reduce_chunk_tokens: int = 4_000,
    max_output_tokens: int = 2_048,
    max_functions_per_project: int | None = None,
    model_client: Any | None = None,
    checkpoint_path: str | Path | None = None,
    resume: bool = False,
) -> Dict[str, int]:
    if token_budget <= 0:
        raise ValueError("token_budget 必须为正数")
    if max_output_tokens <= 0:
        raise ValueError("max_output_tokens 必须为正数")
    if reduce_chunk_tokens < 256:
        raise ValueError("reduce_chunk_tokens 必须大于等于 256")
    if max_functions_per_project is not None and max_functions_per_project < 1:
        raise ValueError("max_functions_per_project 必须为正数或 None")

    dataset_path = Path(dataset_path)
    output_dir = Path(output_dir)
    checkpoint_path = Path(checkpoint_path or DEFAULT_CHECKPOINT_PATH)
    data = select_split(pd.read_pickle(dataset_path), "train")
    config = LLMConfig.json_mode_config(model=model)
    owns_client = model_client is None
    raw_client = model_client or create_model_client(config)
    client = _BudgetedModelClient(raw_client, token_budget)
    model_name = config.model
    counts: Dict[str, int] = {}
    projects_manifest: List[Dict[str, Any]] = []
    token_budget_exhausted = False

    try:
        with RunCheckpoint(checkpoint_path, resume=resume) as checkpoint:
            saved = checkpoint.load_records()
            next_position = max(saved, default=-1) + 1
            llm_records = [
                record
                for record in saved.values()
                if record["kind"] in {"map", "reduce", "request_failure"}
            ]
            if llm_records:
                client.estimated_tokens = llm_records[-1][
                    "estimated_input_output_tokens"
                ]
                client.endpoint_request_count = llm_records[-1][
                    "endpoint_request_count"
                ]

            map_records = {
                (record["project"], record["chunk_index"]): record
                for record in saved.values()
                if record["kind"] == "map"
            }
            reduce_records = {
                (record["project"], record["level"], record["chunk_index"]): record
                for record in saved.values()
                if record["kind"] == "reduce"
            }
            project_records = {
                record["project"]: record
                for record in saved.values()
                if record["kind"] == "project"
            }

            def save_checkpoint(record: Dict[str, Any]) -> None:
                nonlocal next_position
                checkpoint.save_record(next_position, record)
                next_position += 1

            def save_failure(
                project: str,
                stage: str,
                chunk_index: int | None = None,
                level: int | None = None,
            ) -> None:
                save_checkpoint(
                    {
                        "kind": "request_failure",
                        "project": project,
                        "stage": stage,
                        "chunk_index": chunk_index,
                        "level": level,
                        "estimated_input_output_tokens": client.estimated_tokens,
                        "endpoint_request_count": client.endpoint_request_count,
                    }
                )

            async def run_reduce(
                project: str,
                idioms: Sequence[Mapping[str, Any]],
                *,
                level: int,
                chunk_index: int,
            ) -> Sequence[Mapping[str, Any]] | None:
                nonlocal token_budget_exhausted
                try:
                    reduced_object = await complete_json_object(
                        client,
                        _REDUCE_SYSTEM_PROMPT,
                        _reduce_prompt(project, idioms),
                        _REDUCE_IDIOM_SCHEMA,
                        logger=logger,
                        max_tokens=max_output_tokens,
                    )
                    reduced_idioms = reduced_object.get("idioms", [])
                    _validate_reduce_refs(
                        reduced_idioms,
                        {
                            str(ref)
                            for idiom in idioms
                            for ref in idiom["evidence_refs"]
                        },
                    )
                except _TokenBudgetExceeded:
                    token_budget_exhausted = True
                    save_failure(project, "reduce_budget", chunk_index, level)
                    logger.warning("%s 没有足够预算执行 reduce；本项目输出为空", project)
                    return None
                except Exception:
                    save_failure(project, "reduce", chunk_index, level)
                    raise
                save_checkpoint(
                    {
                        "kind": "reduce",
                        "project": project,
                        "level": level,
                        "chunk_index": chunk_index,
                        "idioms": reduced_idioms,
                        "estimated_input_output_tokens": client.estimated_tokens,
                        "endpoint_request_count": client.endpoint_request_count,
                    }
                )
                return reduced_idioms

            async def reduce_hierarchy(
                project: str,
                idioms: Sequence[Mapping[str, Any]],
            ) -> tuple[Sequence[Mapping[str, Any]], int, bool]:
                current = list(idioms)
                level = 0
                call_count = 0
                while current:
                    chunks = _chunk_reduce_candidates(
                        project,
                        current,
                        reduce_chunk_tokens,
                    )
                    next_level: List[Mapping[str, Any]] = []
                    for chunk_index, chunk in enumerate(chunks):
                        completed = reduce_records.get(
                            (project, level, chunk_index)
                        )
                        if completed is None:
                            result = await run_reduce(
                                project,
                                chunk,
                                level=level,
                                chunk_index=chunk_index,
                            )
                            if result is None:
                                return [], call_count, False
                        else:
                            result = completed["idioms"]
                        _validate_reduce_refs(
                            result,
                            {
                                str(ref)
                                for idiom in chunk
                                for ref in idiom["evidence_refs"]
                            },
                        )
                        next_level.extend(result)
                        call_count += 1
                    next_level = _deduplicate_reduce_idioms(next_level)
                    if len(chunks) == 1:
                        return next_level, call_count, True
                    if next_level and len(
                        _chunk_reduce_candidates(
                            project,
                            next_level,
                            reduce_chunk_tokens,
                        )
                    ) >= len(chunks):
                        return next_level, call_count, True
                    current = next_level
                    level += 1
                return [], call_count, True

            for project_idx in range(len(data)):
                row = data.iloc[project_idx]
                project = str(row["project"])
                completed_project = project_records.get(project)
                if completed_project is not None:
                    counts[completed_project["project"]] = completed_project[
                        "output_idiom_count"
                    ]
                    projects_manifest.append(completed_project["manifest"])
                    continue

                units = _project_units(row)
                if max_functions_per_project is not None:
                    units = units[:max_functions_per_project]
                map_chunks = _chunk_units(units, chunk_tokens)
                map_candidates: List[Mapping[str, Any]] = []
                map_calls = 0
                processed_function_count = 0

                for chunk_idx, chunk in enumerate(map_chunks):
                    completed_map = map_records.get((project, chunk_idx))
                    if completed_map is not None:
                        map_candidates.extend(completed_map["idioms"])
                        map_calls += 1
                        processed_function_count += len(chunk)
                        continue
                    if token_budget_exhausted:
                        break
                    prompt = _map_prompt(project, chunk)
                    try:
                        data_object = await complete_json_object(
                            client,
                            _MAP_SYSTEM_PROMPT,
                            prompt,
                            _MAP_IDIOM_SCHEMA,
                            logger=logger,
                            max_tokens=max_output_tokens,
                        )
                    except _TokenBudgetExceeded:
                        token_budget_exhausted = True
                        save_failure(project, "map_budget", chunk_idx)
                        logger.warning(
                            "LLM-Direct-Budget 已达到 token 预算，停止新增 map 调用"
                        )
                        break
                    except Exception:
                        save_failure(project, "map", chunk_idx)
                        raise
                    idioms = data_object.get("idioms", [])
                    save_checkpoint(
                        {
                            "kind": "map",
                            "project": project,
                            "chunk_index": chunk_idx,
                            "idioms": idioms,
                            "estimated_input_output_tokens": client.estimated_tokens,
                            "endpoint_request_count": client.endpoint_request_count,
                        }
                    )
                    map_candidates.extend(idioms)
                    map_calls += 1
                    processed_function_count += len(chunk)

                reduced: Sequence[Mapping[str, Any]] = []
                reduce_calls = 0
                map_complete = map_calls == len(map_chunks)
                reduce_complete = map_complete
                if map_complete and map_candidates:
                    reduce_candidates, evidence_by_ref = _register_reduce_evidence(
                        map_candidates
                    )
                    reduced_refs, reduce_calls, reduce_complete = await reduce_hierarchy(
                        project,
                        reduce_candidates,
                    )
                    if reduce_complete:
                        reduced = _restore_reduce_evidence(
                            reduced_refs,
                            evidence_by_ref,
                        )

                complete = map_complete and reduce_complete
                output_idiom_count = 0
                if complete:
                    records = _adapt_llm_idioms(
                        project,
                        reduced,
                        units,
                        model_name=model_name,
                        estimated_tokens=client.estimated_tokens,
                    )
                    output_path = write_project_idioms(output_dir, project, records)
                    output_idiom_count = len(records)
                    counts[project] = output_idiom_count
                else:
                    counts[project] = 0
                project_manifest = {
                    "project": project,
                    "complete": complete,
                    "input_function_count": len(units),
                    "processed_function_count": processed_function_count,
                    "map_chunk_count": len(map_chunks),
                    "processed_map_chunk_count": map_calls,
                    "map_call_count": map_calls,
                    "reduce_call_count": reduce_calls,
                    "map_candidate_count": len(map_candidates),
                    "output_idiom_count": output_idiom_count,
                    "token_budget_exhausted": token_budget_exhausted,
                }
                projects_manifest.append(project_manifest)
                if complete:
                    save_checkpoint(
                        {
                            "kind": "project",
                            "project": project,
                            "output_idiom_count": output_idiom_count,
                            "manifest": project_manifest,
                        }
                    )
                    logger.info(
                        "LLM-Direct-Budget %s: calls=%d+%d, idioms=%d -> %s",
                        project,
                        map_calls,
                        reduce_calls,
                        output_idiom_count,
                        output_path,
                    )
    finally:
        if owns_client:
            await raw_client.close()

    call_count = sum(
        project["map_call_count"] + project["reduce_call_count"]
        for project in projects_manifest
    )
    write_run_manifest(
        output_dir,
        {
            "method": "llm_direct_budget",
            "is_mock": False,
            "complete": all(project["complete"] for project in projects_manifest),
            "project_count": len(projects_manifest),
            "processed_project_count": sum(
                bool(project["complete"]) for project in projects_manifest
            ),
            "input_function_count": sum(
                project["input_function_count"] for project in projects_manifest
            ),
            "processed_function_count": sum(
                project["processed_function_count"] for project in projects_manifest
            ),
            "token_budget_exhausted": token_budget_exhausted,
            "dataset": str(dataset_path),
            "training_split": "train",
            "model": model_name,
            "schemas": {
                "map": _MAP_IDIOM_SCHEMA,
                "reduce": _REDUCE_IDIOM_SCHEMA,
            },
            "token_budget": token_budget,
            "estimated_input_output_tokens": client.estimated_tokens,
            "call_count": call_count,
            "reduce_call_count": sum(
                project["reduce_call_count"] for project in projects_manifest
            ),
            "endpoint_request_count": client.endpoint_request_count,
            "budget_enforcement": (
                "每次实际请求前按完整 system/user 消息和最大输出预留；"
                "JSON 修复请求也受同一全局上限约束"
            ),
            "chunk_tokens": chunk_tokens,
            "reduce_chunk_tokens": reduce_chunk_tokens,
            "max_output_tokens": max_output_tokens,
            "max_functions_per_project": max_functions_per_project,
            "checkpoint": str(checkpoint_path),
            "resumed": resume,
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
    parser.add_argument("--dataset", default="outputs/library/cli11/stage0/dataset.pkl")
    parser.add_argument(
        "--output-dir",
        default="results/baselines/llm-direct-budget/cli11",
    )
    parser.add_argument("--model", default=None, help="默认读取 OPENAI_MODEL_LOW")
    parser.add_argument("--token-budget", type=int, default=20_000)
    parser.add_argument("--chunk-tokens", type=int, default=3_000)
    parser.add_argument("--reduce-chunk-tokens", type=int, default=4_000)
    parser.add_argument("--max-output-tokens", type=int, default=2_048)
    parser.add_argument("--checkpoint", default=str(DEFAULT_CHECKPOINT_PATH))
    parser.add_argument("--resume", action="store_true")
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
            reduce_chunk_tokens=args.reduce_chunk_tokens,
            max_output_tokens=args.max_output_tokens,
            checkpoint_path=args.checkpoint,
            resume=args.resume,
            max_functions_per_project=(
                None
                if args.max_functions_per_project == 0
                else args.max_functions_per_project
            ),
        )
    )


if __name__ == "__main__":
    main()
