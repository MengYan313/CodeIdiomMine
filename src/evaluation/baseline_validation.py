"""对 baseline/CIMAS 产物执行统一评价并验证九项指标合同。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Mapping

from ..common.logging import get_logger
from .baseline_common import is_source_info, validate_metric_payload
from .idiom_metrics import (
    DEFAULT_EVALUATION_MODE,
    evaluate_cpp,
    load_idiom_artifact,
)


logger = get_logger(__name__)


def _validate_output_selection_contract(
    method: str,
    idiom_dir: str | Path,
    *,
    require_baseline_provenance: bool,
) -> Dict[str, Any]:
    """拒绝把公共种类上限套到非规则方法或沿用旧规则配置。"""
    normalized_method = method.strip().lower().replace("_", "-")
    manifest_path = Path(idiom_dir) / "baseline-manifest.json"
    if not manifest_path.exists():
        if require_baseline_provenance:
            raise ValueError(f"{manifest_path} 不存在，无法核对 baseline 输出选择合同")
        return {
            "policy": "main_method_complete_output",
            "final_idiom_count_cap": None,
        }

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if normalized_method.startswith(("haggis-cpp", "llm-direct-budget")):
        output_selection = manifest.get("output_selection")
        if not isinstance(output_selection, Mapping):
            raise ValueError(f"{manifest_path} 缺少 output_selection")
        if output_selection.get("final_idiom_count_cap", "missing") is not None:
            raise ValueError(f"{method} 不允许最终习语种类数量上限")
        parameters = manifest.get("parameters")
        if isinstance(parameters, Mapping) and "max_types" in parameters:
            raise ValueError(f"{method} manifest 含有旧 max_types 截断")
        return dict(output_selection)

    if normalized_method.startswith("rules-embedding-clustering"):
        selection_rule = manifest.get("selection_rule")
        if not isinstance(selection_rule, Mapping):
            raise ValueError(f"{manifest_path} 缺少规则 baseline 组合截断配置")
        if "max_cluster_size" in selection_rule:
            raise ValueError("规则 baseline 只能使用最小簇大小、比例和数量上限组合")
        try:
            min_cluster_size = int(selection_rule["min_cluster_size"])
            selection_ratio = float(selection_rule["selection_ratio"])
            max_types = int(selection_rule["max_types"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("规则 baseline 组合截断参数不完整") from error
        if min_cluster_size < 1 or not 0 < selection_ratio < 1 or max_types < 1:
            raise ValueError("规则 baseline 组合截断参数无效")
        return dict(selection_rule)

    if normalized_method.startswith("idiomine-cpp-"):
        raise ValueError("不支持 IdioMine-CPP 派生方法名，仅支持单一正式名称")

    if normalized_method.startswith("idiomine-cpp"):
        output_selection = manifest.get("output_selection")
        if not isinstance(output_selection, Mapping):
            raise ValueError(f"{manifest_path} 缺少 output_selection")
        if (
            output_selection.get("policy")
            != "accepted_independent_idioms_plus_direct_syntheses"
        ):
            raise ValueError("IdioMine-CPP 最终输出策略无效")
        if output_selection.get("final_idiom_count_cap", "missing") is not None:
            raise ValueError("IdioMine-CPP 不允许最终习语种类数量上限")

        parameters = manifest.get("parameters")
        if not isinstance(parameters, Mapping):
            raise ValueError(f"{manifest_path} 缺少 IdioMine-CPP 参数")
        if (
            parameters.get("candidate_origin") != "semantic_def_use"
            or parameters.get("metric") != "cosine"
            or not str(parameters.get("embedding_model") or "").strip()
            or parameters.get("region_grouping")
            != "exact_representative_project_file_function_extent"
        ):
            raise ValueError("IdioMine-CPP 的候选、embedding 或分组参数无效")
        try:
            eps = float(parameters["eps"])
            min_samples = int(parameters["min_samples"])
            token_budget = int(parameters["token_budget"])
            max_output_tokens = int(parameters["max_output_tokens"])
            max_examples = int(parameters["max_examples_per_judgment"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("IdioMine-CPP 参数不完整") from error
        if (
            not 0 < eps <= 1
            or min_samples < 2
            or token_budget < 1
            or max_output_tokens < 1
            or max_examples < 1
        ):
            raise ValueError("IdioMine-CPP 参数无效")

        adaptation = manifest.get("adaptation")
        if (
            not isinstance(adaptation, Mapping)
            or adaptation.get("claim")
            != "simplified_cpp_migration_not_full_reproduction"
        ):
            raise ValueError("IdioMine-CPP 必须标明简化迁移边界")

        pipeline = manifest.get("pipeline")
        if not isinstance(pipeline, Mapping):
            raise ValueError(f"{manifest_path} 缺少 IdioMine-CPP 流程")
        if (
            pipeline.get("judgment")
            != "one_independent_call_per_candidate_cluster"
            or pipeline.get("synthesis")
            != "one_attempt_per_same_region_group_of_accepted_idioms"
            or pipeline.get("post_synthesis_judgment") is not False
            or pipeline.get("final_output")
            != "accepted_independent_idioms_plus_direct_syntheses"
        ):
            raise ValueError("IdioMine-CPP 判断或合成顺序无效")
        candidate_generation = manifest.get("candidate_generation")
        candidate_selection = (
            candidate_generation.get("output_selection")
            if isinstance(candidate_generation, Mapping)
            else None
        )
        if (
            not isinstance(candidate_selection, Mapping)
            or candidate_selection.get("policy")
            != "all_non_noise_dbscan_clusters"
        ):
            raise ValueError("IdioMine-CPP 内部候选选择合同无效")
        if manifest.get("token_budget_exhausted") is True:
            raise ValueError("IdioMine-CPP token 预算耗尽，产物不完整")
        return dict(output_selection)

    return {"policy": "method_specific", "final_idiom_count_cap": None}


def _validate_artifacts(
    idiom_dir: str | Path,
    *,
    artifact_stage: str,
    require_baseline_provenance: bool,
) -> Dict[str, int]:
    root = Path(idiom_dir)
    pattern = "*_idiom.pkl" if artifact_stage == "judgment" else "*_idiom_syn.pkl"
    counts: Dict[str, int] = {}
    for path in sorted(root.glob(pattern)):
        suffix = "_idiom" if artifact_stage == "judgment" else "_idiom_syn"
        project = path.stem.removesuffix(suffix)
        artifact_project, idioms = load_idiom_artifact(str(path))
        if artifact_project and artifact_project != project:
            raise ValueError(
                f"{path} 文件名项目 {project} 与 artifact 项目 "
                f"{artifact_project} 不一致"
            )
        for index, idiom in enumerate(idioms):
            if not isinstance(idiom, Mapping):
                raise ValueError(f"{path}[{index}] 不是对象")
            required = {"center_point", "info", "source_infos", "cnt"}
            missing = required - idiom.keys()
            if missing:
                raise ValueError(f"{path}[{index}] 缺少字段: {sorted(missing)}")
            if not str(idiom.get("center_point") or "").strip():
                raise ValueError(f"{path}[{index}] center_point 为空")
            infos = idiom.get("source_infos")
            if not isinstance(infos, list) or not infos:
                raise ValueError(f"{path}[{index}] 没有完整 source_infos")
            if not all(is_source_info(info) for info in infos):
                raise ValueError(f"{path}[{index}] source_infos 格式错误")
            if int(idiom.get("cnt", 0) or 0) != len(infos):
                raise ValueError(f"{path}[{index}] cnt 与 source_infos 数量不一致")
            if "mock_provenance" in idiom:
                raise ValueError(f"{path}[{index}] 是 mock，不能作为正式方法产物")
            if require_baseline_provenance and "baseline_provenance" not in idiom:
                raise ValueError(f"{path}[{index}] 缺少 baseline_provenance")
        counts[project] = len(idioms)
    if not counts:
        raise ValueError(f"{root} 下没有 {pattern}")
    return counts


def validate_method_metrics(
    *,
    method: str,
    idiom_dir: str | Path,
    dataset_path: str | Path,
    output_path: str | Path | None = None,
    artifact_stage: str = "judgment",
    evaluation_mode: str = DEFAULT_EVALUATION_MODE,
    fold_count: int = 5,
    require_baseline_provenance: bool = True,
) -> Dict[str, Any]:
    idiom_dir = Path(idiom_dir)
    output_path = Path(output_path) if output_path else idiom_dir / "eval.json"
    output_selection_contract = _validate_output_selection_contract(
        method,
        idiom_dir,
        require_baseline_provenance=require_baseline_provenance,
    )
    artifact_counts = _validate_artifacts(
        idiom_dir,
        artifact_stage=artifact_stage,
        require_baseline_provenance=require_baseline_provenance,
    )
    payload = evaluate_cpp(
        str(idiom_dir),
        str(dataset_path),
        str(output_path),
        artifact_stage=artifact_stage,
        evaluation_mode=evaluation_mode,
        fold_count=fold_count,
    )
    metric_contract = validate_metric_payload(payload)
    report = {
        "method": method,
        "artifact_stage": artifact_stage,
        "evaluation_mode": evaluation_mode,
        "artifact_counts": artifact_counts,
        "output_selection_contract": output_selection_contract,
        "metric_contract": metric_contract,
        "evaluation_output": str(output_path),
        "status": "passed",
    }
    report_path = idiom_dir / "metric-validation.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    logger.info(
        "%s 九项指标合同验证通过：%s",
        method,
        ", ".join(metric_contract["metric_names"]),
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="评价一个方法并验证固定九项指标")
    parser.add_argument("--method", required=True)
    parser.add_argument("--idiom-dir", required=True)
    parser.add_argument("--dataset", default="outputs/cpp/dataset.pkl")
    parser.add_argument("--output", default=None)
    parser.add_argument(
        "--stage", choices=("judgment", "synthesis"), default="judgment"
    )
    parser.add_argument(
        "--mode",
        choices=("within_project_kfold",),
        default=DEFAULT_EVALUATION_MODE,
        help="仓库内文件五折",
    )
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument(
        "--allow-main-method",
        action="store_true",
        help="CIMAS 现有产物没有 baseline_provenance 时使用",
    )
    args = parser.parse_args()
    validate_method_metrics(
        method=args.method,
        idiom_dir=args.idiom_dir,
        dataset_path=args.dataset,
        output_path=args.output,
        artifact_stage=args.stage,
        evaluation_mode=args.mode,
        fold_count=args.folds,
        require_baseline_provenance=not args.allow_main_method,
    )


if __name__ == "__main__":
    main()
