import asyncio
import pickle
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from src.idiom_synthesis.context import (
    call_targets,
    load_group_context_with_evidence,
    syntax_structure_valid,
    unsupported_call_targets,
)
from src.idiom_synthesis.pipeline import (
    IdiomSynthesisPipeline,
    decide_synthesis_status,
)
from src.idiom_synthesis.schema import (
    IDIOM_SYNTHESIS_SCHEMA_VERSION,
    IdiomCandidate,
    SynthesisResult,
    build_synthesis_artifact,
)
from src.idiom_synthesis.sources import (
    group_related_idioms,
    load_idiom_candidates,
)
from src.idiom_synthesis.synthesize_idioms import synthesize_idioms
from src.evaluation.idiom_metrics import load_idiom_artifact


def _info(project, path, extent, code, *, source_sha256=""):
    node = {"code_snippet": code, "ast_num": 3, "subtree_size": 8}
    if source_sha256:
        node["source_sha256"] = source_sha256
    return [
        project,
        path,
        extent,
        node,
    ]


class IdiomSynthesisTests(unittest.TestCase):
    def test_loads_stage2_and_judgment_inputs(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            code_a = "auto handle = open_resource();"
            code_b = "close_resource(handle);"
            info_a = _info("sample", "a.cpp", "1-0-5-1", code_a)
            info_b = _info("sample", "a.cpp", "1-0-5-1", code_b)
            frame = pd.DataFrame(
                [
                    {
                        "label": 1,
                        "center_point": code_a,
                        "else_point": [code_a],
                        "cluster_size": 2,
                        "center_point_info": info_a,
                        "infos": [info_a, info_a],
                        "loc_label": "sample-a.cpp-1-0-5-1",
                    },
                    {
                        "label": 2,
                        "center_point": code_b,
                        "else_point": [code_b],
                        "cluster_size": 2,
                        "center_point_info": info_b,
                        "infos": [info_b, info_b],
                        "loc_label": "sample-a.cpp-1-0-5-1",
                    },
                ]
            )
            stage2_path = root / "clusters.pkl"
            with stage2_path.open("wb") as stream:
                pickle.dump([{"pros_name": "sample", "clusters": frame}], stream)
            project, candidates, kind = load_idiom_candidates(stage2_path)
            self.assertEqual((project, kind), ("sample", "stage2"))
            self.assertTrue(all(item.input_stage == 2 for item in candidates))
            self.assertEqual(len(group_related_idioms(candidates)), 1)
            contract_output = root / "stage2-contract.pkl"
            with patch(
                "src.idiom_synthesis.synthesize_idioms.load_project_env"
            ) as load_env:
                contract_report = asyncio.run(
                    synthesize_idioms(
                        str(stage2_path),
                        str(contract_output),
                        input_kind="stage2",
                    )
                )
            load_env.assert_called_once_with()
            self.assertEqual(
                contract_report["execution_status"],
                "contract_only_not_executed",
            )
            with contract_output.open("rb") as stream:
                contract_artifact = pickle.load(stream)
            self.assertEqual(
                contract_artifact["execution_status"],
                "contract_only_not_executed",
            )
            self.assertEqual(
                contract_artifact["summary"]["attempt_count"],
                0,
            )

            judgment_path = root / "judgment.pkl"
            with judgment_path.open("wb") as stream:
                pickle.dump(
                    {
                        "artifact_type": "idiom_judgment",
                        "project": "sample",
                        "accepted": [
                            {
                                "cluster_id": "1",
                                "template_code": code_a,
                                "loc_label": "same",
                                "source_infos": [info_a],
                                "info": info_a,
                                "cnt": 2,
                                "status": "accepted",
                                "semantic": {"intent": "获取资源"},
                                "decision_reason": "语义与异味门禁均通过。",
                                "idiom_classification": {
                                    "kind": "repository_specific",
                                    "label": "仓库特有习语",
                                    "catalog_ids": [],
                                },
                                "agent_reasons": {
                                    "semantic_review": "意图稳定。",
                                    "smell_review": "未见异味。",
                                },
                                "abstraction_proposals": [
                                    {
                                        "proposal_id": "var-1",
                                        "placeholder": "<VAR_1>",
                                    },
                                    {
                                        "proposal_id": "lit-1",
                                        "placeholder": "<LIT_1>",
                                    },
                                ],
                                "approved_abstraction_ids": ["var-1"],
                                "abstraction_applied": True,
                            },
                            {
                                "cluster_id": "2",
                                "template_code": code_b,
                                "loc_label": "same",
                                "source_infos": [info_b],
                                "info": info_b,
                                "cnt": 2,
                                "status": "accepted",
                                "semantic": {"intent": "释放资源"},
                                "decision_reason": "语义与异味门禁均通过。",
                                "idiom_classification": {
                                    "kind": "repository_specific",
                                    "label": "仓库特有习语",
                                    "catalog_ids": [],
                                },
                                "agent_reasons": {
                                    "semantic_review": "意图稳定。",
                                    "smell_review": "未见异味。",
                                },
                            },
                        ],
                    },
                    stream,
                )
            project, candidates, kind = load_idiom_candidates(judgment_path)
            self.assertEqual((project, kind), ("sample", "judgment"))
            self.assertTrue(all(item.input_stage == 3 for item in candidates))
            self.assertEqual(
                candidates[0].idiom_classification["kind"],
                "repository_specific",
            )
            self.assertEqual(
                candidates[0].agent_reasons["semantic_review"],
                "意图稳定。",
            )
            self.assertEqual(
                candidates[0].placeholders,
                [
                    {
                        "proposal_id": "var-1",
                        "placeholder": "<VAR_1>",
                    }
                ],
            )
            self.assertEqual(len(group_related_idioms(candidates)), 1)
            artifact_project, accepted = load_idiom_artifact(
                str(judgment_path)
            )
            self.assertEqual(artifact_project, "sample")
            self.assertEqual(len(accepted), 2)

    def test_deterministic_checks_reject_invented_calls(self):
        unsupported = unsupported_call_targets(
            "open_resource(); audit_secret();",
            ["open_resource();"],
            "",
        )
        self.assertEqual(unsupported, ["audit_secret"])
        self.assertEqual(
            call_targets(
                "auto handle = open_resource(); close_resource(handle);"
            ),
            {"open_resource", "close_resource"},
        )
        self.assertTrue(
            syntax_structure_valid(
                "auto <VAR_1> = open_resource(); close_resource(<VAR_1>);"
            )
        )

    def test_context_requires_matching_source_hash(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = "void f() {\n  acquire();\n  release();\n}\n"
            source_path = root / "sample.cpp"
            source_path.write_text(source, encoding="utf-8")
            digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
            candidate = IdiomCandidate(
                candidate_id="judgment:1",
                project="sample",
                code="acquire();",
                loc_label="same",
                source_infos=[],
                representative_info=[
                    "sample",
                    "sample.cpp",
                    "1-0-4-1",
                    {"source_sha256": digest},
                ],
                support_count=3,
                input_stage=3,
            )
            self.assertIn(
                "release();",
                load_group_context_with_evidence([candidate], root)[0],
            )
            missing_hash = IdiomCandidate(
                **{
                    **candidate.__dict__,
                    "representative_info": [
                        "sample",
                        "sample.cpp",
                        "1-0-4-1",
                        {},
                    ],
                }
            )
            self.assertEqual(
                load_group_context_with_evidence([missing_hash], root)[0],
                "",
            )
            mismatched_hash = IdiomCandidate(
                **{
                    **candidate.__dict__,
                    "candidate_id": "judgment:2",
                    "representative_info": [
                        "sample",
                        "sample.cpp",
                        "1-0-4-1",
                        {"source_sha256": "0" * 64},
                    ],
                }
            )
            self.assertEqual(
                load_group_context_with_evidence(
                    [candidate, mismatched_hash],
                    root,
                )[0],
                "",
            )
            self.assertEqual(
                load_group_context_with_evidence(
                    [candidate],
                    root,
                    max_chars=10,
                )[0],
                "",
            )

    def test_stage2_contract_input_uses_stricter_quality_threshold(self):
        common = dict(
            merged_code_present=True,
            syntax_valid=True,
            unsupported_calls=[],
            context_contract_valid=True,
            review_is_idiom=True,
            improves_quality=True,
            preserves_intents=True,
            review_unsupported_additions=[],
        )
        status, _ = decide_synthesis_status(
            contains_stage2_input=True,
            quality_score=70,
            **common,
        )
        self.assertEqual(status, "rejected")
        status, _ = decide_synthesis_status(
            contains_stage2_input=False,
            quality_score=70,
            **common,
        )
        self.assertEqual(status, "accepted")
        status, _ = decide_synthesis_status(
            contains_stage2_input=False,
            quality_score=100,
            **{**common, "review_is_idiom": False},
        )
        self.assertEqual(status, "rejected")

    def test_multi_agent_pipeline_accepts_supported_synthesis(self):
        class FakeClient:
            def __init__(self):
                self.calls = 0
                self.user_prompts = []
                self.requests = []
                self.smell_findings = []
                self.quality_reason = "合成补全了资源获取与释放。"
                self.smell_reason = "未见可定位的代码异味。"

            async def create(self, messages, extra_create_args):
                del extra_create_args
                self.calls += 1
                system_prompt = messages[0].content
                self.user_prompts.append(messages[-1].content)
                self.requests.append(
                    (system_prompt, messages[-1].content)
                )
                if "多习语合成规划 Agent" in system_prompt:
                    response = {
                        "should_synthesize": True,
                        "selected_indices": [0, 1],
                        "synthesis_goal": "形成完整资源生命周期。",
                        "ordering_constraints": ["先获取，后释放。"],
                        "expected_improvement": "补全获取与释放配对。",
                        "reason": "两个习语具有资源生命周期关系。",
                    }
                elif "代码组装 Agent" in system_prompt:
                    response = {
                        "merged_code": (
                            "auto handle = open_resource();\n"
                            "close_resource(handle);"
                        ),
                        "used_context": False,
                        "added_from_context": [],
                        "reason": "按生命周期顺序合成。",
                    }
                elif "独立质量、有效性与类型复审 Agent" in system_prompt:
                    response = {
                        "is_idiom": True,
                        "quality_score": 90,
                        "improves_quality": True,
                        "preserves_intents": True,
                        "unsupported_additions": [],
                        "issues": [],
                        "idiom_classification": {
                            "kind": "repository_specific",
                            "catalog_ids": [],
                            "confidence": 84,
                            "reason": "显式资源配对依赖当前仓库 API。",
                        },
                        "reason": self.quality_reason,
                    }
                else:
                    response = {
                        "findings": self.smell_findings,
                        "reason": self.smell_reason,
                    }
                return SimpleNamespace(
                    content=json.dumps(response, ensure_ascii=False)
                )

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = (
                "void f() {\n"
                "  audit_context();\n"
                "  auto handle = open_resource();\n"
                "  close_resource(handle);\n"
                "}\n"
            )
            (root / "sample.cpp").write_text(source, encoding="utf-8")
            digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
            info = _info(
                "sample",
                "sample.cpp",
                "1-0-5-1",
                "auto handle = open_resource();",
                source_sha256=digest,
            )
            candidates = [
                IdiomCandidate(
                    candidate_id="judgment:1",
                    project="sample",
                    code="auto handle = open_resource();",
                    loc_label="same",
                    source_infos=[info],
                    representative_info=info,
                    support_count=3,
                    input_stage=3,
                    intent="获取资源",
                    judgment_status="accepted",
                    judgment_reason="获取资源候选已通过阶段3门禁。",
                    idiom_classification={
                        "kind": "repository_specific",
                        "label": "仓库特有习语",
                        "catalog_ids": [],
                    },
                    agent_reasons={
                        "semantic_review": "获取意图稳定。",
                        "smell_review": "未见异味。",
                    },
                ),
                IdiomCandidate(
                    candidate_id="judgment:2",
                    project="sample",
                    code="close_resource(handle);",
                    loc_label="same",
                    source_infos=[info],
                    representative_info=info,
                    support_count=3,
                    input_stage=3,
                    intent="释放资源",
                    judgment_status="accepted",
                    judgment_reason="释放资源候选已通过阶段3门禁。",
                    idiom_classification={
                        "kind": "repository_specific",
                        "label": "仓库特有习语",
                        "catalog_ids": [],
                    },
                    agent_reasons={
                        "semantic_review": "释放意图稳定。",
                        "smell_review": "未见异味。",
                    },
                ),
            ]
            client = FakeClient()

            async def run_pipeline(active_client):
                pipeline = IdiomSynthesisPipeline(model_client=active_client)
                try:
                    return await pipeline.synthesize(
                        candidates,
                        source_root=str(root),
                    )
                finally:
                    await pipeline.shutdown()

            result = asyncio.run(run_pipeline(client))
            self.assertEqual(result.status, "accepted")
            self.assertEqual(client.calls, 4)
            self.assertTrue(result.context_evidence["available"])
            self.assertTrue(
                any("audit_context();" in prompt for prompt in client.user_prompts)
            )
            smell_prompts = [
                prompt
                for system_prompt, prompt in client.requests
                if "代码异味与复用风险审查专家" in system_prompt
            ]
            self.assertEqual(len(smell_prompts), 1)
            self.assertIn("audit_context();", smell_prompts[0])
            self.assertEqual(
                result.deterministic_checks["unsupported_call_targets"],
                [],
            )
            self.assertFalse(result.smell_gate["rejected"])
            self.assertEqual(
                result.review["idiom_classification"]["kind"],
                "repository_specific",
            )
            self.assertIn("质量复审依据", result.decision_reason)
            self.assertNotIn("smell_risk_score", result.scorecard)
            self.assertEqual(
                result.agent_trace["planning"]["status"],
                "completed",
            )
            self.assertEqual(
                result.agent_trace["quality_review"]["logical_attempts"],
                1,
            )
            self.assertIn(
                "audit_context();",
                result.smell_review_input["related_examples"][0],
            )
            artifact = build_synthesis_artifact(
                "sample",
                [result],
                input_kind="judgment",
            )
            self.assertEqual(
                artifact["idiom_synthesis_schema_version"],
                IDIOM_SYNTHESIS_SCHEMA_VERSION,
            )
            self.assertEqual(
                artifact["artifact_semantics"],
                "synthesis_delta",
            )
            self.assertFalse(artifact["passthrough_included"])
            self.assertNotIn("manual_review", artifact)
            self.assertEqual(
                artifact["summary"]["accepted_classification_kind_counts"][
                    "repository_specific"
                ],
                1,
            )
            source_judgments = artifact["accepted"][0][
                "source_judgments"
            ]
            self.assertEqual(len(source_judgments), 2)
            self.assertTrue(
                all(
                    item["judgment_reason"]
                    and item["idiom_classification"]["kind"]
                    == "repository_specific"
                    and item["agent_reasons"]["semantic_review"]
                    for item in source_judgments
                )
            )

            risky_client = FakeClient()
            risky_client.smell_findings = [
                {
                    "category": "resource_lifetime",
                    "severity": "high",
                    "confidence": 90,
                    "evidence": "资源获取后存在可见的未配对失败路径。",
                    "impact": "可能泄漏资源。",
                    "remediation": "使用 RAII 句柄封装资源。",
                }
            ]
            risky_result = asyncio.run(run_pipeline(risky_client))
            self.assertEqual(risky_result.status, "rejected")
            self.assertTrue(risky_result.smell_gate["rejected"])
            self.assertEqual(
                risky_result.smell_gate["trigger_kind"],
                "risk_threshold",
            )
            self.assertEqual(risky_result.scorecard["final_score"], 90)

            missing_quality_reason = FakeClient()
            missing_quality_reason.quality_reason = ""
            missing_quality_result = asyncio.run(
                run_pipeline(missing_quality_reason)
            )
            self.assertEqual(missing_quality_result.status, "rejected")
            self.assertEqual(
                missing_quality_result.agent_trace["quality_review"][
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

    def test_grouping_never_crosses_representative_region(self):
        base = {
            "project": "sample",
            "code": "work();",
            "loc_label": "same-label",
            "source_infos": [],
            "support_count": 3,
            "input_stage": 3,
            "judgment_status": "accepted",
        }
        candidates = [
            IdiomCandidate(
                candidate_id="judgment:1",
                representative_info=_info(
                    "sample",
                    "same.cpp",
                    "1-0-5-1",
                    "work();",
                ),
                **base,
            ),
            IdiomCandidate(
                candidate_id="judgment:2",
                representative_info=_info(
                    "sample",
                    "same.cpp",
                    "1-0-5-1",
                    "work();",
                ),
                **base,
            ),
            IdiomCandidate(
                candidate_id="judgment:3",
                representative_info=_info(
                    "sample",
                    "same.cpp",
                    "8-0-12-1",
                    "work();",
                ),
                **base,
            ),
        ]
        groups = group_related_idioms(candidates)
        self.assertEqual(len(groups), 1)
        self.assertEqual(
            {candidate.candidate_id for candidate in groups[0]},
            {"judgment:1", "judgment:2"},
        )

    def test_unverified_location_label_never_forms_group(self):
        candidates = [
            IdiomCandidate(
                candidate_id=f"unlocated:{index}",
                project="sample",
                code=code,
                loc_label="same-display-label",
                source_infos=[],
                representative_info=None,
                support_count=2,
                input_stage=3,
            )
            for index, code in enumerate(("acquire();", "release();"))
        ]
        self.assertEqual(group_related_idioms(candidates), [])

    def test_candidate_limit_rejects_without_truncation_or_calls(self):
        class NoCallClient:
            def __init__(self):
                self.calls = 0

            async def create(self, messages, extra_create_args):
                del messages, extra_create_args
                self.calls += 1
                raise AssertionError("候选上限门禁不得调用 LLM")

        candidates = [
            IdiomCandidate(
                candidate_id=f"judgment:{index}",
                project="sample",
                code=f"step_{index}();",
                loc_label="same",
                source_infos=[],
                representative_info=_info(
                    "sample",
                    "same.cpp",
                    "1-0-5-1",
                    f"step_{index}();",
                ),
                support_count=3,
                input_stage=3,
                judgment_status="accepted",
            )
            for index in range(3)
        ]
        client = NoCallClient()

        async def run_pipeline():
            pipeline = IdiomSynthesisPipeline(
                model_client=client,
                max_group_candidates=2,
            )
            try:
                return await pipeline.synthesize(candidates)
            finally:
                await pipeline.shutdown()

        result = asyncio.run(run_pipeline())
        self.assertEqual(result.status, "rejected")
        self.assertEqual(client.calls, 0)
        self.assertEqual(len(result.selected), 3)
        self.assertTrue(
            result.deterministic_checks["candidate_limit_exceeded"]
        )
        self.assertEqual(
            result.agent_trace["planning"]["failure_kind"],
            "candidate_limit_exceeded",
        )

    def test_artifact_builder_rejects_third_status(self):
        result = SynthesisResult(
            project="sample",
            status="manual_review",
            selected=[],
            merged_code="",
            context_evidence={},
            plan={},
            assembly={},
            review={},
            smell={},
            smell_gate={},
            smell_review_input={},
            agent_trace={},
            scorecard={},
            deterministic_checks={},
            decision_reason="",
        )
        with self.assertRaisesRegex(
            ValueError,
            "阶段4只支持 accepted/rejected",
        ):
            build_synthesis_artifact(
                "sample",
                [result],
                input_kind="judgment",
            )

    def test_missing_context_is_rejected_without_llm_calls(self):
        candidate = IdiomCandidate(
            candidate_id="judgment:1",
            project="sample",
            code="acquire();",
            loc_label="same",
            source_infos=[],
            representative_info=["sample", "missing.cpp", "1-0-2-1", {}],
            support_count=3,
            input_stage=3,
        )

        class NoCallClient:
            async def create(self, messages, extra_create_args):
                raise AssertionError("上下文失败时不应调用 LLM")

        async def run_pipeline():
            pipeline = IdiomSynthesisPipeline(model_client=NoCallClient())
            try:
                return await pipeline.synthesize([candidate, candidate])
            finally:
                await pipeline.shutdown()

        result = asyncio.run(run_pipeline())
        self.assertEqual(result.status, "rejected")
        self.assertFalse(result.context_evidence["available"])
        self.assertTrue(
            all(
                trace["status"] == "not_run"
                for trace in result.agent_trace.values()
            )
        )

    def test_planning_failure_retries_then_skips_downstream_agents(self):
        class PlanningFailureClient:
            def __init__(self):
                self.calls = 0

            async def create(self, messages, extra_create_args):
                del messages, extra_create_args
                self.calls += 1
                raise TimeoutError("synthetic timeout")

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = (
                "void f() {\n"
                "  auto handle = open_resource();\n"
                "  close_resource(handle);\n"
                "}\n"
            )
            (root / "sample.cpp").write_text(source, encoding="utf-8")
            digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
            info = _info(
                "sample",
                "sample.cpp",
                "1-0-4-1",
                "auto handle = open_resource();",
                source_sha256=digest,
            )
            candidates = [
                IdiomCandidate(
                    candidate_id="judgment:1",
                    project="sample",
                    code="auto handle = open_resource();",
                    loc_label="same",
                    source_infos=[info],
                    representative_info=info,
                    support_count=3,
                    input_stage=3,
                ),
                IdiomCandidate(
                    candidate_id="judgment:2",
                    project="sample",
                    code="close_resource(handle);",
                    loc_label="same",
                    source_infos=[info],
                    representative_info=info,
                    support_count=3,
                    input_stage=3,
                ),
            ]
            client = PlanningFailureClient()

            async def run_pipeline():
                pipeline = IdiomSynthesisPipeline(model_client=client)
                try:
                    return await pipeline.synthesize(
                        candidates,
                        source_root=str(root),
                    )
                finally:
                    await pipeline.shutdown()

            result = asyncio.run(run_pipeline())
            self.assertEqual(result.status, "rejected")
            self.assertEqual(client.calls, 2)
            self.assertEqual(
                result.agent_trace["planning"],
                {
                    "status": "failed",
                    "logical_attempts": 2,
                    "failure_kind": "request_error",
                    "failure_action": "skip_group",
                },
            )
            for name in ("assembly", "quality_review", "smell_review"):
                self.assertEqual(
                    result.agent_trace[name]["status"],
                    "not_run",
                )
            artifact = build_synthesis_artifact(
                "sample",
                [result],
                input_kind="judgment",
            )
            self.assertEqual(
                artifact["summary"]["technical_failure_count"],
                1,
            )


if __name__ == "__main__":
    unittest.main()
