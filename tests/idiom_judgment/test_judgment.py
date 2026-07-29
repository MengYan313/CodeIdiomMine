import asyncio
import hashlib
import json
import math
import pickle
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from src.idiom_judgment.abstraction import (
    apply_approved_abstractions,
    propose_abstractions,
)
from src.idiom_judgment.judge_clusters import judge_clusters
from src.idiom_judgment.idiom_taxonomy import (
    IDIOM_TAXONOMY_VERSION,
    KNOWN_IDIOM_TYPES,
    REPOSITORY_SPECIFIC_IDIOM_LABEL,
    normalize_idiom_classification,
)
from src.idiom_judgment.pipeline import (
    IdiomJudgmentPipeline,
    decide_judgment_status,
)
from src.idiom_judgment.rules import evaluate_cluster_rules
from src.idiom_judgment.schema import (
    IDIOM_JUDGMENT_SCHEMA_VERSION,
    ClusterCandidate,
    IdiomJudgmentResult,
    build_judgment_artifact,
)
from src.idiom_judgment.source_context import (
    load_verified_source_context,
)


def _candidate(codes, *, files=None, kinds=None):
    files = files or [f"f{index}.cpp" for index in range(len(codes))]
    kinds = kinds or ["expression_statement"] * len(codes)
    infos = [
        [
            "sample",
            files[index],
            "1-0-3-1",
            {
                "code_snippet": code,
                "kind": kinds[index],
                "ast_num": 4,
                "subtree_size": 12,
                "start_byte": index * 100,
                "end_byte": index * 100 + len(code),
                "extent": f"{index + 1}-0-{index + 1}-80",
            },
        ]
        for index, code in enumerate(codes)
    ]
    return ClusterCandidate(
        project="sample",
        cluster_id="7",
        representative_code=codes[0],
        member_codes=list(codes),
        representative_info=infos[0],
        source_infos=infos,
        loc_label="sample:f0.cpp:1-0-3-1",
        declared_cluster_size=len(codes),
    )


class IdiomJudgmentTests(unittest.TestCase):
    def test_taxonomy_source_refs_use_only_thesis_global_ids(self):
        for idiom_type in KNOWN_IDIOM_TYPES:
            self.assertTrue(idiom_type.source_refs, idiom_type.type_id)
            for source_ref in idiom_type.source_refs:
                self.assertRegex(source_ref, r"^E\d{3}$", idiom_type.type_id)

        refs_by_type = {
            idiom_type.type_id: set(idiom_type.source_refs)
            for idiom_type in KNOWN_IDIOM_TYPES
        }
        self.assertEqual(refs_by_type["raii"], {"E025", "E112", "E113"})
        self.assertEqual(refs_by_type["scope-guard"], {"E025", "E115"})
        self.assertEqual(
            refs_by_type["rule-of-three-five"],
            {"E025", "E112", "E114"},
        )

    def test_known_and_repository_specific_idiom_classification(self):
        known, invalid = normalize_idiom_classification(
            {
                "kind": "cataloged",
                "catalog_ids": ["raii"],
                "confidence": 92,
                "reason": "资源生命周期与局部对象作用域绑定。",
            },
            is_idiom=True,
        )
        self.assertFalse(invalid)
        self.assertEqual(known.taxonomy_version, IDIOM_TAXONOMY_VERSION)
        self.assertEqual(known.catalog_ids, ["raii"])
        self.assertIn("RAII", known.label)

        specific, invalid = normalize_idiom_classification(
            {
                "kind": "repository_specific",
                "catalog_ids": [],
                "confidence": 80,
                "reason": "组合依赖仓库私有 API 与稳定顺序。",
            },
            is_idiom=True,
        )
        self.assertFalse(invalid)
        self.assertEqual(specific.label, REPOSITORY_SPECIFIC_IDIOM_LABEL)

        _, invalid = normalize_idiom_classification(
            {
                "kind": "cataloged",
                "catalog_ids": ["invented-type"],
                "confidence": 100,
                "reason": "强行套用。",
            },
            is_idiom=True,
        )
        self.assertTrue(invalid)

        normalized, invalid = normalize_idiom_classification(
            {
                "kind": "repository_specific",
                "catalog_ids": [],
                "confidence": math.nan,
                "reason": "置信度不是有限数。",
            },
            is_idiom=True,
        )
        self.assertTrue(invalid)
        self.assertEqual(normalized.confidence, 0.0)

    def test_judgment_loads_project_env_before_processing(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_path = root / "clusters.pkl"
            with input_path.open("wb") as stream:
                pickle.dump(
                    [
                        {
                            "pros_name": "sample",
                            "clusters": pd.DataFrame(),
                        }
                    ],
                    stream,
                )
            with patch(
                "src.idiom_judgment.judge_clusters.load_project_env"
            ) as load_env:
                report = asyncio.run(
                    judge_clusters(
                        str(input_path),
                        str(root / "judgment.pkl"),
                        rule_only=True,
                    )
                )
            load_env.assert_called_once_with()
            self.assertEqual(report["summary"]["input_cluster_count"], 0)
            self.assertIn("prompt_contracts", report["run"])

    def test_rule_only_checkpoint_can_resume_without_reprocessing(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            code = "guard.lock();"
            info = [
                "sample",
                "sample.cpp",
                "1-0-1-13",
                {
                    "code_snippet": code,
                    "kind": "expression_statement",
                    "ast_num": 4,
                    "subtree_size": 12,
                },
            ]
            frame = pd.DataFrame(
                [
                    {
                        "label": 1,
                        "center_point": code,
                        "else_point": [code],
                        "cluster_size": 2,
                        "center_point_info": info,
                        "infos": [info, info],
                        "loc_label": "same",
                    }
                ]
            )
            input_path = root / "clusters.pkl"
            with input_path.open("wb") as stream:
                pickle.dump(
                    [{"pros_name": "sample", "clusters": frame}],
                    stream,
                )
            checkpoint = root / "judgment.sqlite3"
            asyncio.run(
                judge_clusters(
                    str(input_path),
                    str(root / "first.pkl"),
                    rule_only=True,
                    checkpoint_path=str(checkpoint),
                )
            )
            report = asyncio.run(
                judge_clusters(
                    str(input_path),
                    str(root / "resumed.pkl"),
                    rule_only=True,
                    checkpoint_path=str(checkpoint),
                    resume=True,
                )
            )
            self.assertTrue(report["run"]["resumed"])
            self.assertEqual(report["run"]["resumed_record_count"], 1)
            self.assertEqual(report["summary"]["pending_llm_count"], 1)

    def test_verified_context_gates_stage3_without_entering_llm_prompts(self):
        class ContextClient:
            def __init__(self):
                self.prompts = []

            async def create(self, messages, extra_create_args):
                del extra_create_args
                system_prompt = messages[0].content
                self.prompts.append(messages[-1].content)
                if "习语语义、类型与抽象决策专家" in system_prompt:
                    response = {
                        "is_idiom": True,
                        "semantic_score": 90,
                        "reuse_score": 85,
                        "intent": "获取值后消费。",
                        "preconditions": [],
                        "abstraction_decision": "keep",
                        "approved_abstraction_ids": [],
                        "abstraction_reason": "保持代表代码。",
                        "idiom_classification": {
                            "kind": "repository_specific",
                            "catalog_ids": [],
                            "confidence": 86,
                            "reason": "该加载与消费组合依赖当前仓库 API。",
                        },
                        "reason": "意图完整。",
                    }
                else:
                    response = {
                        "findings": [],
                        "reason": "未发现可定位异味。",
                    }
                return SimpleNamespace(
                    content=json.dumps(response, ensure_ascii=False)
                )

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = (
                "void f() {\n"
                "  int result = load(a);\n"
                "  consume(result);\n"
                "}\n"
            )
            (root / "sample.cpp").write_text(source, encoding="utf-8")
            digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
            base = _candidate(
                [
                    "int result = load(a); consume(result);",
                    "int value = load(b); consume(value);",
                    "int item = load(c); consume(item);",
                ]
            )
            representative_info = [
                "sample",
                "sample.cpp",
                "1-0-4-1",
                {
                    "code_snippet": base.representative_code,
                    "kind": "compound_statement",
                    "ast_num": 12,
                    "subtree_size": 12,
                    "source_sha256": digest,
                },
            ]
            candidate = ClusterCandidate(
                **{
                    **base.__dict__,
                    "representative_info": representative_info,
                }
            )
            context, evidence = load_verified_source_context(
                project="sample",
                representative_info=representative_info,
                source_root=root,
            )
            self.assertEqual(context, source.rstrip())
            self.assertTrue(evidence["verified"])

            client = ContextClient()

            async def run_pipeline():
                pipeline = IdiomJudgmentPipeline(
                    model_client=client,
                    source_root=str(root),
                    require_context=True,
                )
                try:
                    return await pipeline.evaluate(candidate)
                finally:
                    await pipeline.shutdown()

            result = asyncio.run(run_pipeline())
            self.assertEqual(result.status, "accepted")
            self.assertTrue(result.context_evidence["verified"])
            self.assertEqual(len(client.prompts), 2)
            self.assertTrue(
                all("void f()" not in prompt for prompt in client.prompts)
            )
            self.assertTrue(
                all(
                    base.representative_code in prompt
                    for prompt in client.prompts
                )
            )

            no_call_client = ContextClient()

            async def run_missing_context():
                pipeline = IdiomJudgmentPipeline(
                    model_client=no_call_client,
                    source_root=str(root / "missing"),
                    require_context=True,
                )
                try:
                    return await pipeline.evaluate(candidate)
                finally:
                    await pipeline.shutdown()

            missing = asyncio.run(run_missing_context())
            self.assertEqual(missing.status, "rejected")
            self.assertEqual(no_call_client.prompts, [])
            self.assertTrue(
                all(
                    trace["status"] == "not_run"
                    for trace in missing.agent_trace.values()
                )
            )

    def test_artifact_builder_declares_semantic_type(self):
        artifact = build_judgment_artifact("sample", [], rule_only=True)
        self.assertEqual(artifact["artifact_type"], "idiom_judgment")
        self.assertEqual(artifact["stage"], 3)
        self.assertEqual(
            artifact["idiom_judgment_schema_version"],
            IDIOM_JUDGMENT_SCHEMA_VERSION,
        )
        self.assertNotIn("manual_review", artifact)

    def test_cluster_candidate_uses_complete_stage2_member_sources(self):
        candidate = ClusterCandidate.from_cluster_row(
            "sample",
            {
                "label": 3,
                "center_point": "consume(alpha);",
                "else_point": ["consume(beta);", "consume(gamma);"],
                "cluster_size": 3,
                "center_point_info": [
                    "sample",
                    "f.cpp",
                    "1-0-1-15",
                    {"code_snippet": "consume(alpha);"},
                ],
                # 模拟旧产物中部分 info 缺少 code_snippet；成员源码仍须完整。
                "infos": [
                    [
                        "sample",
                        "f.cpp",
                        "1-0-1-15",
                        {"code_snippet": "consume(alpha);"},
                    ],
                    ["sample", "f.cpp", "2-0-2-14", {}],
                    ["sample", "f.cpp", "3-0-3-15", {}],
                ],
                "loc_label": "sample-f.cpp-1-0-1-15",
            },
        )
        self.assertEqual(
            candidate.member_codes,
            ["consume(alpha);", "consume(beta);", "consume(gamma);"],
        )

    def test_cluster_candidate_builds_lexically_deduplicated_llm_view(self):
        candidate = _candidate(
            [
                'emit("a b");',
                'emit ( "a b" ) ; // formatting-only',
                'emit("a c");',
                'send("a b");',
            ],
            files=["a.cpp", "a.cpp", "b.cpp", "b.cpp"],
        )

        self.assertEqual(
            candidate.lexical_variants,
            ['emit("a c");', 'send("a b");'],
        )
        self.assertEqual(
            candidate.cluster_statistics,
            {
                "original_member_count": 4,
                "variant_count": 3,
                "file_count": 2,
                "source_location_count": 4,
            },
        )

    def test_artifact_builder_rejects_third_runtime_status(self):
        candidate = _candidate(
            ["guard.lock();", "guard.lock();", "guard.lock();"]
        )
        result = IdiomJudgmentResult(
            candidate=candidate,
            rules=evaluate_cluster_rules(candidate),
            proposals=[],
            status="manual_review",
            template_code=candidate.representative_code,
        )
        with self.assertRaisesRegex(ValueError, "阶段3不支持状态"):
            build_judgment_artifact("sample", [result], rule_only=False)

    def test_rules_reject_only_deterministically_trivial_cluster(self):
        result = evaluate_cluster_rules(
            _candidate(
                ["break;", "break;"],
                kinds=["break_statement", "break_statement"],
            )
        )
        self.assertFalse(result.eligible_for_llm)
        self.assertIn("trivial_control_only", result.hard_failures)

    def test_exact_duplicate_is_warning_not_automatic_rejection(self):
        result = evaluate_cluster_rules(
            _candidate(["guard.lock();", "guard.lock();"])
        )
        self.assertTrue(result.eligible_for_llm)
        self.assertTrue(result.exact_duplicate)
        self.assertIn("exact_source_duplicate", result.warnings)

    def test_only_frequent_local_alpha_names_are_proposed(self):
        candidate = _candidate(
            [
                "int result = load(a); consume(result);",
                "int value = load(b); consume(value);",
                "int item = load(c); consume(item);",
            ]
        )
        proposals = propose_abstractions(candidate)
        self.assertEqual(len(proposals), 1)
        proposal = proposals[0]
        self.assertEqual(proposal.category, "VAR")
        self.assertEqual(proposal.values, ["item", "result", "value"])
        self.assertEqual(len(proposal.anchor_ranges), 2)

        unchanged = apply_approved_abstractions(
            candidate.representative_code,
            proposals,
            [],
        )
        self.assertEqual(unchanged, candidate.representative_code)
        abstracted = apply_approved_abstractions(
            candidate.representative_code,
            proposals,
            [proposal.proposal_id],
        )
        self.assertEqual(abstracted.count("<VAR_1>"), 2)
        self.assertIn("load(a)", abstracted)
        self.assertIn("consume(<VAR_1>)", abstracted)

    def test_two_instances_and_semantic_calls_are_not_abstracted(self):
        two = _candidate(
            [
                "int result = open_resource();",
                "int value = create_socket();",
            ]
        )
        self.assertEqual(propose_abstractions(two), [])

    def test_deterministic_decision_only_scores_idiom_value(self):
        accepted, _ = decide_judgment_status(
            rule_eligible=True,
            rule_score=80,
            semantic_is_idiom=True,
            semantic_score=75,
            reuse_score=65,
        )
        self.assertEqual(accepted, "accepted")
        rejected, _ = decide_judgment_status(
            rule_eligible=True,
            rule_score=90,
            semantic_is_idiom=True,
            semantic_score=49,
            reuse_score=90,
        )
        self.assertEqual(rejected, "rejected")
        boundary, _ = decide_judgment_status(
            rule_eligible=True,
            rule_score=50,
            semantic_is_idiom=True,
            semantic_score=60,
            reuse_score=60,
        )
        self.assertEqual(boundary, "rejected")
        semantic_veto, _ = decide_judgment_status(
            rule_eligible=True,
            rule_score=100,
            semantic_is_idiom=False,
            semantic_score=100,
            reuse_score=100,
        )
        self.assertEqual(semantic_veto, "rejected")

    def test_multi_agent_judgment_applies_only_approved_proposal(self):
        class FakeClient:
            def __init__(self):
                self.calls = 0
                self.smell_findings = []
                self.abstraction_decision = "abstract"
                self.prompts = []
                self.semantic_reason = "局部变量名称不影响稳定意图。"
                self.smell_reason = "未见可定位的代码异味。"

            async def create(self, messages, extra_create_args):
                del extra_create_args
                self.calls += 1
                system_prompt = messages[0].content
                self.prompts.append(messages[-1].content)
                if "习语语义、类型与抽象决策专家" in system_prompt:
                    response = {
                        "is_idiom": True,
                        "semantic_score": 85,
                        "reuse_score": 80,
                        "intent": "加载值后交给消费者。",
                        "preconditions": ["load返回可消费的值。"],
                        "abstraction_decision": self.abstraction_decision,
                        "approved_abstraction_ids": [
                            "var-1",
                            "invented-id",
                        ],
                        "abstraction_reason": "局部变量名称不承载稳定语义。",
                        "idiom_classification": {
                            "kind": "repository_specific",
                            "catalog_ids": [],
                            "confidence": 82,
                            "reason": "该加载与消费组合未对应目录中的通用习语。",
                        },
                        "reason": self.semantic_reason,
                    }
                else:
                    response = {
                        "findings": self.smell_findings,
                        "reason": self.smell_reason,
                    }
                return SimpleNamespace(
                    content=json.dumps(response, ensure_ascii=False)
                )

        candidate = _candidate(
            [
                "int result = load(a); consume(result);",
                "int value = load(b); consume(value);",
                "int item = load(c); consume(item);",
            ]
        )
        client = FakeClient()

        async def run_pipeline(active_client):
            pipeline = IdiomJudgmentPipeline(model_client=active_client)
            try:
                return await pipeline.evaluate(candidate)
            finally:
                await pipeline.shutdown()

        result = asyncio.run(run_pipeline(client))
        self.assertEqual(result.status, "accepted")
        self.assertEqual(result.approved_abstraction_ids, ["var-1"])
        self.assertTrue(result.abstraction_applied)
        self.assertEqual(result.template_code.count("<VAR_1>"), 2)
        self.assertGreaterEqual(result.scorecard["final_score"], 70)
        self.assertNotIn("smell_risk_score", result.scorecard)
        self.assertFalse(result.smell_gate["rejected"])
        self.assertEqual(
            result.semantic.idiom_classification.kind,
            "repository_specific",
        )
        self.assertIn("语义判断依据", result.decision_reason)
        self.assertEqual(
            result.agent_trace["semantic_review"]["status"],
            "completed",
        )
        self.assertEqual(
            result.agent_trace["semantic_review"]["logical_attempts"],
            1,
        )
        self.assertEqual(
            result.smell_review_input["candidate_id"],
            "cluster:7",
        )
        self.assertEqual(client.calls, 2)
        semantic_prompt = next(
            prompt
            for prompt in client.prompts
            if "去重后的其他代码变体（共 2 个）" in prompt
        )
        self.assertIn(candidate.representative_code, semantic_prompt)
        for code in candidate.lexical_variants:
            self.assertIn(code, semantic_prompt)
        self.assertIn('"original_member_count": 3', semantic_prompt)
        self.assertIn('"eligible_for_llm": true', semantic_prompt)
        self.assertEqual(
            result.semantic_review_input["code_variants"],
            candidate.lexical_variants,
        )
        self.assertNotIn("cluster_members", result.semantic_review_input)
        self.assertNotIn("context_code", result.semantic_review_input)
        self.assertEqual(
            result.smell_review_input["related_examples"],
            candidate.lexical_variants,
        )
        self.assertEqual(
            result.smell_review_input["deterministic_evidence"],
            candidate.cluster_statistics,
        )
        record = result.to_record()
        self.assertEqual(record["member_codes"], candidate.member_codes)
        self.assertEqual(record["source_infos"], candidate.source_infos)

        keep_client = FakeClient()
        keep_client.abstraction_decision = "keep"
        kept_result = asyncio.run(run_pipeline(keep_client))
        self.assertEqual(kept_result.status, "accepted")
        self.assertFalse(kept_result.abstraction_applied)
        self.assertEqual(kept_result.approved_abstraction_ids, [])
        self.assertEqual(
            kept_result.template_code,
            candidate.representative_code,
        )
        artifact = build_judgment_artifact(
            "sample",
            [result, kept_result],
            rule_only=False,
        )
        self.assertEqual(artifact["summary"]["accepted_count"], 2)
        self.assertEqual(
            artifact["summary"]["accepted_abstracted_count"],
            1,
        )
        self.assertEqual(
            artifact["summary"]["accepted_unchanged_count"],
            1,
        )
        self.assertEqual(
            artifact["summary"]["accepted_classification_kind_counts"][
                "repository_specific"
            ],
            2,
        )

        risky_client = FakeClient()
        risky_client.smell_findings = [
            {
                "category": "error_handling",
                "severity": "critical",
                "confidence": 90,
                "evidence": "失败返回值被直接忽略。",
                "impact": "后续操作可能使用无效结果。",
                "remediation": "检查并传播失败结果。",
            }
        ]
        risky_result = asyncio.run(run_pipeline(risky_client))
        self.assertEqual(risky_result.status, "rejected")
        self.assertTrue(risky_result.smell_gate["rejected"])
        self.assertGreaterEqual(risky_result.scorecard["final_score"], 70)

        missing_semantic_reason = FakeClient()
        missing_semantic_reason.semantic_reason = ""
        missing_semantic_result = asyncio.run(
            run_pipeline(missing_semantic_reason)
        )
        self.assertEqual(missing_semantic_result.status, "rejected")
        self.assertEqual(
            missing_semantic_result.agent_trace["semantic_review"][
                "failure_kind"
            ],
            "invalid_domain_payload",
        )

        missing_smell_reason = FakeClient()
        missing_smell_reason.smell_reason = ""
        missing_smell_result = asyncio.run(
            run_pipeline(missing_smell_reason)
        )
        self.assertEqual(missing_smell_result.status, "rejected")
        self.assertEqual(
            missing_smell_result.agent_trace["smell_review"][
                "failure_kind"
            ],
            "invalid_domain_payload",
        )

    def test_request_failure_retries_once_then_recovers(self):
        class RetryClient:
            def __init__(self):
                self.semantic_calls = 0
                self.smell_calls = 0

            async def create(self, messages, extra_create_args):
                del extra_create_args
                system_prompt = messages[0].content
                if "习语语义、类型与抽象决策专家" in system_prompt:
                    self.semantic_calls += 1
                    if self.semantic_calls == 1:
                        raise TimeoutError("synthetic timeout")
                    response = {
                        "is_idiom": True,
                        "semantic_score": 85,
                        "reuse_score": 80,
                        "intent": "加载值后交给消费者。",
                        "preconditions": [],
                        "abstraction_decision": "keep",
                        "approved_abstraction_ids": [],
                        "abstraction_reason": "保持原代码。",
                        "idiom_classification": {
                            "kind": "repository_specific",
                            "catalog_ids": [],
                            "confidence": 80,
                            "reason": "没有与已知目录精确对应。",
                        },
                        "reason": "意图稳定且具有复用价值。",
                    }
                else:
                    self.smell_calls += 1
                    response = {
                        "findings": [],
                        "reason": "未见可定位的代码异味。",
                    }
                return SimpleNamespace(
                    content=json.dumps(response, ensure_ascii=False)
                )

        candidate = _candidate(
            [
                "int result = load(a); consume(result);",
                "int value = load(b); consume(value);",
                "int item = load(c); consume(item);",
            ]
        )
        client = RetryClient()

        async def run_pipeline():
            pipeline = IdiomJudgmentPipeline(model_client=client)
            try:
                return await pipeline.evaluate(candidate)
            finally:
                await pipeline.shutdown()

        result = asyncio.run(run_pipeline())
        self.assertEqual(result.status, "accepted")
        self.assertEqual(client.semantic_calls, 2)
        self.assertEqual(client.smell_calls, 1)
        self.assertEqual(
            result.agent_trace["semantic_review"]["logical_attempts"],
            2,
        )
        self.assertEqual(
            result.agent_trace["semantic_review"]["status"],
            "completed",
        )

    def test_json_repair_and_retry_exhaustion_rejects_only_current_cluster(self):
        class InvalidSemanticClient:
            def __init__(self):
                self.semantic_endpoint_calls = 0
                self.smell_calls = 0

            async def create(self, messages, extra_create_args):
                del extra_create_args
                system_prompt = messages[0].content
                if "代码异味与复用风险审查专家" in system_prompt:
                    self.smell_calls += 1
                    return SimpleNamespace(
                        content=json.dumps(
                            {
                                "findings": [],
                                "reason": "未见可定位的代码异味。",
                            },
                            ensure_ascii=False,
                        )
                    )
                self.semantic_endpoint_calls += 1
                return SimpleNamespace(content="not-json")

        candidate = _candidate(
            [
                "int result = load(a); consume(result);",
                "int value = load(b); consume(value);",
                "int item = load(c); consume(item);",
            ]
        )
        client = InvalidSemanticClient()

        async def run_pipeline():
            pipeline = IdiomJudgmentPipeline(model_client=client)
            try:
                return await pipeline.evaluate(candidate)
            finally:
                await pipeline.shutdown()

        result = asyncio.run(run_pipeline())
        self.assertEqual(result.status, "rejected")
        # 两次逻辑尝试，每次包含首次响应和一次 JSON 修复。
        self.assertEqual(client.semantic_endpoint_calls, 4)
        self.assertEqual(client.smell_calls, 1)
        self.assertEqual(
            result.agent_trace["semantic_review"],
            {
                "status": "failed",
                "logical_attempts": 2,
                "failure_kind": "json_invalid_after_repair",
                "failure_action": "reject_cluster",
            },
        )
        self.assertEqual(
            result.agent_trace["smell_review"]["status"],
            "completed",
        )
        artifact = build_judgment_artifact(
            "sample",
            [result],
            rule_only=False,
        )
        self.assertEqual(
            artifact["summary"]["technical_failure_count"],
            1,
        )


if __name__ == "__main__":
    unittest.main()
