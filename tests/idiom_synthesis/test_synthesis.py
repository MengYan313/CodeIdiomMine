import asyncio
import pickle
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
    normalize_synthesis_plans,
)
from src.idiom_synthesis.planning_agent import SynthesisPlan
from src.idiom_synthesis.schema import (
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


def _info(
    project,
    path,
    extent,
    code,
    *,
    candidate_extent="",
    start_byte=None,
    end_byte=None,
):
    node = {
        "code_snippet": code,
        "extent": candidate_extent or extent,
        "ast_num": 3,
        "subtree_size": 8,
    }
    if start_byte is not None:
        node["start_byte"] = start_byte
    if end_byte is not None:
        node["end_byte"] = end_byte
    return [
        project,
        path,
        extent,
        node,
    ]


class IdiomSynthesisTests(unittest.TestCase):
    def test_pipeline_passes_explicit_model_by_keyword(self):
        client = SimpleNamespace()

        async def run_pipeline():
            pipeline = IdiomSynthesisPipeline(model="gpt-5.6-luna")
            with patch(
                "src.idiom_synthesis.pipeline.create_model_client",
                return_value=client,
            ) as factory:
                await pipeline.initialize()
                factory.assert_called_once_with(model="gpt-5.6-luna")
                pipeline._owns_model_client = False
                await pipeline.shutdown()

        asyncio.run(run_pipeline())

    def test_group_limit_rejects_invalid_configuration(self):
        with self.assertRaisesRegex(
            ValueError,
            "max_group_candidates 必须至少为 2",
        ):
            IdiomSynthesisPipeline(max_group_candidates=1)
        with self.assertRaisesRegex(
            ValueError,
            "max_plans_per_region 必须至少为 1",
        ):
            IdiomSynthesisPipeline(max_plans_per_region=0)

    def test_loads_judgment_input(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            code_a = "auto handle = open_resource();"
            code_b = "close_resource(handle);"
            info_a = _info("sample", "a.cpp", "1-0-5-1", code_a)
            info_b = _info("sample", "a.cpp", "1-0-5-1", code_b)
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
            project, candidates = load_idiom_candidates(judgment_path)
            self.assertEqual(project, "sample")
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

    def test_context_uses_matching_source_identity_and_bounds(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = "void f() {\n  acquire();\n  release();\n}\n"
            source_path = root / "sample.cpp"
            source_path.write_text(source, encoding="utf-8")
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
                    {},
                ],
                support_count=3,
            )
            self.assertIn(
                "release();",
                load_group_context_with_evidence([candidate], root)[0],
            )
            mismatched_path = IdiomCandidate(
                **{
                    **candidate.__dict__,
                    "candidate_id": "judgment:2",
                    "representative_info": [
                        "sample",
                        "other.cpp",
                        "1-0-4-1",
                        {},
                    ],
                }
            )
            self.assertEqual(
                load_group_context_with_evidence(
                    [candidate, mismatched_path],
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

    def test_synthesis_quality_threshold(self):
        common = dict(
            merged_code_present=True,
            syntax_valid=True,
            unsupported_calls=[],
            context_contract_valid=True,
            review_is_idiom=True,
            improves_quality=True,
            preserves_intents=True,
            review_unsupported_additions=[],
            review_issues=[],
            adds_semantic_content=True,
            located_in_context=True,
        )
        status, _ = decide_synthesis_status(
            quality_score=70,
            **common,
        )
        self.assertEqual(status, "accepted")
        status, _ = decide_synthesis_status(
            quality_score=100,
            **{**common, "review_is_idiom": False},
        )
        self.assertEqual(status, "rejected")

    def test_plan_normalization_sorts_deduplicates_and_validates_indices(self):
        info = _info("sample", "same.cpp", "1-0-5-1", "work();")
        candidates = [
            IdiomCandidate(
                candidate_id=f"judgment:{index}",
                project="sample",
                code=f"step_{index}();",
                loc_label="",
                source_infos=[info],
                representative_info=info,
                support_count=3,
            )
            for index in range(3)
        ]

        def plan(indices, ordering=("保持源码顺序。",)):
            return SynthesisPlan(
                selected_indices=list(indices),
                relation_kind="稳定源码顺序",
                synthesis_goal="形成连续操作。",
                ordering_constraints=list(ordering),
                expected_improvement="保留关联操作。",
                reason="候选在当前区域具有稳定顺序。",
            )

        normalized, validation = normalize_synthesis_plans(
            [
                plan([1, 0, 1]),
                plan([0, 1]),
                plan([0, 2]),
                plan([0]),
                plan([0, 3]),
                plan([1, 2], ordering=()),
            ],
            candidates,
            max_plans_per_region=8,
        )

        self.assertEqual(
            [item["selected_indices"] for item in normalized],
            [[0, 1], [0, 2]],
        )
        self.assertEqual(
            len({item["combination_key"] for item in normalized}),
            2,
        )
        self.assertEqual(validation["raw_plan_count"], 6)
        self.assertEqual(validation["valid_unique_plan_count"], 2)
        self.assertEqual(validation["rejected_plan_count"], 4)
        limited, limit_validation = normalize_synthesis_plans(
            [plan([0, 1]), plan([0, 2])],
            candidates,
            max_plans_per_region=1,
        )
        self.assertEqual(limited, [])
        self.assertTrue(limit_validation["limit_exceeded"])

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
                        "plans": [
                            {
                                "selected_indices": [0, 1],
                                "relation_kind": "生命周期配对",
                                "synthesis_goal": "形成完整资源生命周期。",
                                "ordering_constraints": ["先获取，后释放。"],
                                "expected_improvement": "补全获取与释放配对。",
                                "reason": "两个习语具有资源生命周期关系。",
                            }
                        ],
                        "reason": "发现一组明确的生命周期配对计划。",
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
            info_a = _info(
                "sample",
                "sample.cpp",
                "1-0-5-1",
                "auto handle = open_resource();",
                candidate_extent="3-2-3-40",
                start_byte=32,
                end_byte=70,
            )
            info_b = _info(
                "sample",
                "sample.cpp",
                "1-0-5-1",
                "close_resource(handle);",
                candidate_extent="4-2-4-25",
                start_byte=73,
                end_byte=96,
            )
            candidates = [
                IdiomCandidate(
                    candidate_id="judgment:1",
                    project="sample",
                    code="auto handle = open_resource();",
                    loc_label="same",
                    source_infos=[info_a],
                    representative_info=info_a,
                    support_count=3,
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
                    source_infos=[info_b],
                    representative_info=info_b,
                    support_count=3,
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
            groups = group_related_idioms(candidates)
            self.assertEqual(len(groups), 1)
            grouped_candidates = groups[0]

            async def run_pipeline(active_client):
                pipeline = IdiomSynthesisPipeline(model_client=active_client)
                try:
                    results = await pipeline.synthesize(
                        grouped_candidates,
                        source_root=str(root),
                    )
                    self.assertEqual(len(results), 1)
                    return results[0]
                finally:
                    await pipeline.shutdown()

            result = asyncio.run(run_pipeline(client))
            self.assertEqual(result.status, "accepted")
            self.assertEqual(client.calls, 4)
            self.assertTrue(result.context_evidence["available"])
            self.assertTrue(
                any("audit_context();" in prompt for prompt in client.user_prompts)
            )
            self.assertTrue(
                any(
                    '"matched_occurrences"' in prompt
                    and '"start_byte": 32' in prompt
                    and '"start_byte": 73' in prompt
                    for prompt in client.user_prompts
                )
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
            )
            self.assertEqual(
                artifact["artifact_semantics"],
                "final_library",
            )
            self.assertNotIn("passthrough_included", artifact)
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
            accepted_record = artifact["accepted"][0]
            self.assertEqual(
                accepted_record["source_order_candidate_ids"],
                ["judgment:1", "judgment:2"],
            )
            self.assertEqual(
                len(accepted_record["matched_occurrences"]),
                2,
            )
            self.assertEqual(
                accepted_record["region_identity"]["extent"],
                "1-0-5-1",
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

    def test_region_planning_runs_once_and_executes_all_unique_plans(self):
        class MultiPlanClient:
            def __init__(self):
                self.calls = {
                    "planning": 0,
                    "assembly": 0,
                    "quality": 0,
                    "smell": 0,
                }
                self.planning_prompts = []

            async def create(self, messages, extra_create_args):
                del extra_create_args
                system_prompt = messages[0].content
                user_prompt = messages[-1].content
                if "多习语合成规划 Agent" in system_prompt:
                    self.calls["planning"] += 1
                    self.planning_prompts.append(user_prompt)

                    def plan(indices, relation):
                        return {
                            "selected_indices": indices,
                            "relation_kind": relation,
                            "synthesis_goal": "保留相关操作的完整语义。",
                            "ordering_constraints": ["保持当前源码顺序。"],
                            "expected_improvement": "形成可复用的关联操作。",
                            "reason": "候选之间存在可验证关系。",
                        }

                    response = {
                        "plans": [
                            plan([0, 1], "数据依赖"),
                            plan([1, 0], "重复的数据依赖"),
                            plan([1, 2], "稳定源码顺序"),
                            plan([2], "候选不足"),
                            plan([0, 5], "索引越界"),
                        ],
                        "reason": "已审查全部三个候选并返回相关组合。",
                    }
                elif "代码组装 Agent" in system_prompt:
                    self.calls["assembly"] += 1
                    merged = (
                        ""
                        if self.calls["assembly"] == 1
                        else "second();\nthird();"
                    )
                    response = {
                        "merged_code": merged,
                        "used_context": False,
                        "added_from_context": [],
                        "reason": (
                            "第一组证据不足，停止组装。"
                            if not merged
                            else "按稳定源码顺序完成组装。"
                        ),
                    }
                elif "独立质量、有效性与类型复审 Agent" in system_prompt:
                    self.calls["quality"] += 1
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
                            "confidence": 85,
                            "reason": "组合依赖当前仓库操作。",
                        },
                        "reason": "组合保持了来源意图并提高完整性。",
                    }
                else:
                    self.calls["smell"] += 1
                    response = {
                        "findings": [],
                        "reason": "未见阻断复用的代码异味。",
                    }
                return SimpleNamespace(
                    content=json.dumps(response, ensure_ascii=False)
                )

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = (
                "void f() {\n"
                "  first();\n"
                "  second();\n"
                "  third();\n"
                "}\n"
            )
            (root / "sample.cpp").write_text(source, encoding="utf-8")
            codes = ["first();", "second();", "third();"]
            candidates = [
                IdiomCandidate(
                    candidate_id=f"judgment:{index}",
                    project="sample",
                    code=code,
                    loc_label="same",
                    source_infos=[
                        _info(
                            "sample",
                            "sample.cpp",
                            "1-0-5-1",
                            code,
                            candidate_extent=f"{index + 1}-2-{index + 1}-10",
                            start_byte=index * 12,
                            end_byte=index * 12 + 8,
                        )
                    ],
                    representative_info=_info(
                        "sample",
                        "sample.cpp",
                        "1-0-5-1",
                        code,
                    ),
                    support_count=3,
                    judgment_status="accepted",
                )
                for index, code in enumerate(codes)
            ]
            client = MultiPlanClient()

            async def run_pipeline():
                pipeline = IdiomSynthesisPipeline(
                    model_client=client,
                    max_plans_per_region=8,
                )
                try:
                    return await pipeline.synthesize(
                        candidates,
                        source_root=str(root),
                    )
                finally:
                    await pipeline.shutdown()

            results = asyncio.run(run_pipeline())

        self.assertEqual([result.status for result in results], [
            "rejected",
            "accepted",
        ])
        self.assertEqual(
            client.calls,
            {"planning": 1, "assembly": 2, "quality": 1, "smell": 1},
        )
        self.assertEqual(len(client.planning_prompts), 1)
        self.assertTrue(
            all(
                f'"candidate_id": "judgment:{index}"'
                in client.planning_prompts[0]
                for index in range(3)
            )
        )
        self.assertEqual(
            [result.plan["selected_indices"] for result in results],
            [[0, 1], [1, 2]],
        )
        self.assertEqual(
            results[1].plan["selected_candidate_ids"],
            ["judgment:1", "judgment:2"],
        )
        validation = results[0].region_planning["validation"]
        self.assertEqual(validation["raw_plan_count"], 5)
        self.assertEqual(validation["valid_unique_plan_count"], 2)
        self.assertEqual(validation["rejected_plan_count"], 3)
        artifact = build_synthesis_artifact(
            "sample",
            results,
        )
        self.assertEqual(artifact["summary"]["planning_call_count"], 1)
        self.assertEqual(
            artifact["summary"]["valid_unique_plan_count"],
            2,
        )
        self.assertEqual(
            artifact["summary"]["rejected_planning_plan_count"],
            3,
        )
        self.assertEqual(
            len(
                {
                    record["combination_key"]
                    for partition in ("accepted", "rejected")
                    for record in artifact[partition]
                }
            ),
            2,
        )

    def test_grouping_uses_all_member_regions(self):
        base = {
            "project": "sample",
            "code": "work();",
            "loc_label": "same-label",
            "support_count": 3,
            "judgment_status": "accepted",
        }
        shared_a = _info(
            "sample",
            "shared.cpp",
            "20-0-30-1",
            "acquire();",
            candidate_extent="22-2-22-12",
            start_byte=220,
            end_byte=230,
        )
        shared_b = _info(
            "sample",
            "shared.cpp",
            "20-0-30-1",
            "release();",
            candidate_extent="28-2-28-12",
            start_byte=280,
            end_byte=290,
        )
        candidates = [
            IdiomCandidate(
                candidate_id="judgment:1",
                representative_info=_info(
                    "sample",
                    "center-a.cpp",
                    "1-0-5-1",
                    "work();",
                ),
                source_infos=[
                    _info(
                        "sample",
                        "center-a.cpp",
                        "1-0-5-1",
                        "work();",
                    ),
                    shared_a,
                ],
                **base,
            ),
            IdiomCandidate(
                candidate_id="judgment:2",
                representative_info=_info(
                    "sample",
                    "center-b.cpp",
                    "8-0-12-1",
                    "work();",
                ),
                source_infos=[
                    _info(
                        "sample",
                        "center-b.cpp",
                        "8-0-12-1",
                        "work();",
                    ),
                    shared_b,
                ],
                **base,
            ),
            IdiomCandidate(
                candidate_id="judgment:3",
                representative_info=_info(
                    "sample",
                    "shared.cpp",
                    "40-0-50-1",
                    "work();",
                ),
                source_infos=[
                    _info(
                        "sample",
                        "shared.cpp",
                        "40-0-50-1",
                        "work();",
                    )
                ],
                **base,
            ),
        ]
        groups = group_related_idioms(candidates)
        self.assertEqual(len(groups), 1)
        self.assertEqual(
            {candidate.candidate_id for candidate in groups[0]},
            {"judgment:1", "judgment:2"},
        )
        self.assertTrue(
            all(
                candidate.context_key
                == ("sample", "shared.cpp", "20-0-30-1")
                for candidate in groups[0]
            )
        )
        self.assertEqual(
            [
                occurrence["start_byte"]
                for candidate in groups[0]
                for occurrence in candidate.occurrence_records()
            ],
            [220, 280],
        )

    def test_candidate_can_participate_in_multiple_member_regions(self):
        def candidate(candidate_id, infos):
            return IdiomCandidate(
                candidate_id=candidate_id,
                project="sample",
                code="work();",
                loc_label="",
                source_infos=infos,
                representative_info=infos[0],
                support_count=len(infos),
                judgment_status="accepted",
            )

        region_a_1 = _info("sample", "same.cpp", "1-0-5-1", "a();")
        region_a_2 = _info("sample", "same.cpp", "1-0-5-1", "b();")
        region_b_1 = _info("sample", "same.cpp", "8-0-12-1", "a();")
        region_b_2 = _info("sample", "same.cpp", "8-0-12-1", "c();")
        groups = group_related_idioms(
            [
                candidate("judgment:1", [region_a_1, region_b_1]),
                candidate("judgment:2", [region_a_2]),
                candidate("judgment:3", [region_b_2]),
            ]
        )
        self.assertEqual(len(groups), 2)
        self.assertEqual(
            [
                {candidate.candidate_id for candidate in group}
                for group in groups
            ],
            [
                {"judgment:1", "judgment:2"},
                {"judgment:1", "judgment:3"},
            ],
        )

    def test_same_candidate_set_across_regions_is_planned_once(self):
        def candidate(candidate_id, code):
            infos = [
                _info("sample", "same.cpp", extent, code)
                for extent in ("1-0-5-1", "8-0-12-1")
            ]
            return IdiomCandidate(
                candidate_id=candidate_id,
                project="sample",
                code=code,
                loc_label="",
                source_infos=infos,
                representative_info=infos[0],
                support_count=2,
            )

        groups = group_related_idioms(
            [candidate("judgment:1", "first();"), candidate("judgment:2", "second();")]
        )
        self.assertEqual(len(groups), 1)
        self.assertEqual(
            {item.candidate_id for item in groups[0]},
            {"judgment:1", "judgment:2"},
        )

    def test_context_loads_shared_non_center_member_region(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = "void f() {\n  acquire();\n  release();\n}\n"
            (root / "shared.cpp").write_text(source, encoding="utf-8")
            shared_infos = [
                _info(
                    "sample",
                    "shared.cpp",
                    "1-0-4-1",
                    "acquire();",
                    candidate_extent="2-2-2-12",
                    start_byte=13,
                    end_byte=23,
                ),
                _info(
                    "sample",
                    "shared.cpp",
                    "1-0-4-1",
                    "release();",
                    candidate_extent="3-2-3-12",
                    start_byte=26,
                    end_byte=36,
                ),
            ]
            candidates = [
                IdiomCandidate(
                    candidate_id=f"judgment:{index}",
                    project="sample",
                    code=code,
                    loc_label="",
                    source_infos=[
                        _info(
                            "sample",
                            f"center-{index}.cpp",
                            "1-0-2-1",
                            code,
                        ),
                        shared_infos[index - 1],
                    ],
                    representative_info=_info(
                        "sample",
                        f"center-{index}.cpp",
                        "1-0-2-1",
                        code,
                    ),
                    support_count=2,
                    judgment_status="accepted",
                )
                for index, code in enumerate(
                    ["acquire();", "release();"],
                    start=1,
                )
            ]

            groups = group_related_idioms(candidates)
            context, evidence = load_group_context_with_evidence(
                groups[0],
                root,
            )

            self.assertEqual(len(groups), 1)
            self.assertIn("acquire();", context)
            self.assertIn("release();", context)
            self.assertTrue(evidence["verified"])
            self.assertEqual(
                {
                    occurrence["candidate_id"]
                    for occurrence in evidence["matched_occurrences"]
                },
                {"judgment:1", "judgment:2"},
            )

    def test_duplicate_members_from_one_cluster_do_not_form_group(self):
        info = _info("sample", "same.cpp", "1-0-5-1", "work();")
        candidate = IdiomCandidate(
            candidate_id="judgment:1",
            project="sample",
            code="work();",
            loc_label="",
            source_infos=[info, info],
            representative_info=info,
            support_count=2,
        )
        self.assertEqual(group_related_idioms([candidate]), [])

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
                return (await pipeline.synthesize(candidates))[0]
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
        )
        with self.assertRaisesRegex(
            ValueError,
            "阶段4只支持 accepted/rejected",
        ):
            build_synthesis_artifact(
                "sample",
                [result],
            )

    def test_artifact_builder_returns_base_plus_synthesized_final_library(self):
        base = {
            "center_point": "first();",
            "idiom_classification": {"kind": "repository_specific"},
        }
        result = SynthesisResult(
            project="sample",
            status="accepted",
            merged_code="first();\nsecond();",
            context_evidence={
                "source_identity": {
                    "relative_path": "sample.cpp",
                    "extent": "1-0-4-1",
                }
            },
            plan={"combination_key": "combination:1+2"},
            deterministic_checks={"synthesized_ast_node_count": 4},
        )
        artifact = build_synthesis_artifact(
            "sample",
            [result],
            base_records=[base],
        )
        self.assertEqual(
            [record["center_point"] for record in artifact["accepted"]],
            ["first();", "first();\nsecond();"],
        )
        self.assertEqual(len(artifact["synthesized"]), 1)
        self.assertEqual(artifact["summary"]["accepted_count"], 2)
        self.assertEqual(artifact["summary"]["synthesis_accepted_count"], 1)
        self.assertEqual(artifact["summary"]["base_candidate_count"], 1)
        self.assertEqual(
            artifact["synthesized"][0]["source_infos"][0][3]["code_snippet"],
            "first();\nsecond();",
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
        )

        class NoCallClient:
            async def create(self, messages, extra_create_args):
                raise AssertionError("上下文失败时不应调用 LLM")

        async def run_pipeline():
            pipeline = IdiomSynthesisPipeline(model_client=NoCallClient())
            try:
                return (
                    await pipeline.synthesize([candidate, candidate])
                )[0]
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
            info = _info(
                "sample",
                "sample.cpp",
                "1-0-4-1",
                "auto handle = open_resource();",
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
                ),
                IdiomCandidate(
                    candidate_id="judgment:2",
                    project="sample",
                    code="close_resource(handle);",
                    loc_label="same",
                    source_infos=[info],
                    representative_info=info,
                    support_count=3,
                ),
            ]
            client = PlanningFailureClient()

            async def run_pipeline():
                pipeline = IdiomSynthesisPipeline(model_client=client)
                try:
                    return (
                        await pipeline.synthesize(
                            candidates,
                            source_root=str(root),
                        )
                    )[0]
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
                    "failure_action": "skip_region",
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
            )
            self.assertEqual(
                artifact["summary"]["technical_failure_count"],
                1,
            )

    def test_empty_plan_response_stops_region_with_reason(self):
        class EmptyPlanClient:
            def __init__(self):
                self.calls = 0

            async def create(self, messages, extra_create_args):
                del messages, extra_create_args
                self.calls += 1
                return SimpleNamespace(
                    content=json.dumps(
                        {
                            "plans": [],
                            "reason": "区域内候选之间没有值得尝试的明确语义关系。",
                        },
                        ensure_ascii=False,
                    )
                )

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = "void f() {\n  first();\n  second();\n}\n"
            (root / "sample.cpp").write_text(source, encoding="utf-8")
            info = _info(
                "sample",
                "sample.cpp",
                "1-0-4-1",
                "first();",
            )
            candidates = [
                IdiomCandidate(
                    candidate_id=f"judgment:{index}",
                    project="sample",
                    code=code,
                    loc_label="same",
                    source_infos=[info],
                    representative_info=info,
                    support_count=3,
                )
                for index, code in enumerate(("first();", "second();"))
            ]
            client = EmptyPlanClient()

            async def run_pipeline():
                pipeline = IdiomSynthesisPipeline(model_client=client)
                try:
                    return await pipeline.synthesize(
                        candidates,
                        source_root=str(root),
                    )
                finally:
                    await pipeline.shutdown()

            results = asyncio.run(run_pipeline())

        self.assertEqual(client.calls, 1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "rejected")
        self.assertEqual(
            results[0].decision_reason,
            "区域内候选之间没有值得尝试的明确语义关系。",
        )
        self.assertTrue(
            all(
                results[0].agent_trace[name]["status"] == "not_run"
                for name in ("assembly", "quality_review", "smell_review")
            )
        )


if __name__ == "__main__":
    unittest.main()
