import asyncio
import json
import os
import pickle
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from src.evaluation.baseline_common import FINAL_METRICS
from src.evaluation.baseline_validation import (
    _validate_output_selection_contract,
    validate_method_metrics,
)
from src.evaluation.haggis_cpp import mine_haggis_cpp
from src.evaluation.llm_direct_baseline import generate_llm_direct_budget
from src.evaluation.rules_embedding_baseline import (
    _select_clusters,
    build_rules_embedding_baseline,
)
from src.agents.idiom_judgement import judge_idioms


def _function_ast(prefix, name, value):
    function_extent = f"{prefix}-0-{prefix + 3}-1"
    condition_extent = f"{prefix + 1}-2-{prefix + 1}-31"
    condition_code = f"if ({name}) {{ return {value}; }}"
    return [
        {
            "depth": 0,
            "extent": function_extent,
            "kind": "function_definition",
            "code_snippet": (
                f"int sample(int {name}) {{ {condition_code} return 0; }}"
            ),
            "ast_num": 8,
            "subtree_size": 9,
        },
        {
            "depth": 1,
            "extent": condition_extent,
            "kind": "if_statement",
            "code_snippet": condition_code,
            "ast_num": 5,
            "subtree_size": 6,
        },
        {
            "depth": 2,
            "extent": f"{prefix + 1}-2-{prefix + 1}-4",
            "kind": "if",
            "code_snippet": "if",
            "ast_num": 0,
            "subtree_size": 1,
        },
        {
            "depth": 2,
            "extent": f"{prefix + 1}-5-{prefix + 1}-12",
            "kind": "condition_clause",
            "code_snippet": name,
            "ast_num": 1,
            "subtree_size": 2,
        },
        {
            "depth": 3,
            "extent": f"{prefix + 1}-6-{prefix + 1}-11",
            "kind": "identifier",
            "code_snippet": name,
            "ast_num": 0,
            "subtree_size": 1,
        },
        {
            "depth": 2,
            "extent": f"{prefix + 1}-13-{prefix + 1}-30",
            "kind": "compound_statement",
            "code_snippet": f"{{ return {value}; }}",
            "ast_num": 2,
            "subtree_size": 3,
        },
        {
            "depth": 3,
            "extent": f"{prefix + 1}-15-{prefix + 1}-27",
            "kind": "return_statement",
            "code_snippet": f"return {value};",
            "ast_num": 1,
            "subtree_size": 2,
        },
        {
            "depth": 4,
            "extent": f"{prefix + 1}-22-{prefix + 1}-23",
            "kind": "number_literal",
            "code_snippet": str(value),
            "ast_num": 0,
            "subtree_size": 1,
        },
        {
            "depth": 1,
            "extent": f"{prefix + 2}-2-{prefix + 2}-10",
            "kind": "return_statement",
            "code_snippet": "return 0;",
            "ast_num": 1,
            "subtree_size": 2,
        },
    ]


def _fixture():
    rows = []
    clusters = []
    evidence_code = {}
    for project_index, project in enumerate(("alpha", "beta", "gamma")):
        files = [f"{project}/a.cpp", f"{project}/b.cpp"]
        ast_a = _function_ast(1 + project_index * 20, f"value{project_index}", project_index + 1)
        ast_b = _function_ast(10 + project_index * 20, f"ready{project_index}", project_index + 2)
        rows.append(
            {
                "project": project,
                "cppFile": files,
                "func_ast": [[ast_a], [ast_b]],
                "func_src": [[ast_a[0]["code_snippet"]], [ast_b[0]["code_snippet"]]],
            }
        )
        infos = [
            [project, files[0], ast_a[0]["extent"], ast_a[1]],
            [project, files[1], ast_b[0]["extent"], ast_b[1]],
        ]
        cluster_frame = pd.DataFrame(
            [
                {
                    "label": 1,
                    "center_point": ast_a[1]["code_snippet"],
                    "else_point": [ast_b[1]["code_snippet"]],
                    "cluster_size": 2,
                    "center_point_info": infos[0],
                    "infos": infos,
                    "loc_label": "unused",
                },
                {
                    "label": 2,
                    "center_point": ast_a[0]["code_snippet"],
                    "else_point": [],
                    "cluster_size": 1,
                    "center_point_info": [project, files[0], ast_a[0]["extent"], ast_a[0]],
                    "infos": [[project, files[0], ast_a[0]["extent"], ast_a[0]]],
                    "loc_label": "unused",
                },
            ]
        )
        clusters.append({"pros_name": project, "clusters": cluster_frame})
        evidence_code[project] = ast_a[1]["code_snippet"]
    return pd.DataFrame(rows), clusters, evidence_code


class _QueuedJsonClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    async def create(self, messages, extra_create_args):
        del messages, extra_create_args
        response = self.responses[self.calls]
        self.calls += 1
        return SimpleNamespace(content=json.dumps(response, ensure_ascii=False))


class _CimasJsonClient:
    def __init__(self):
        self.calls = 0
        self.closed = False

    async def create(self, messages, extra_create_args):
        del extra_create_args
        self.calls += 1
        system_prompt = messages[0].content
        if "评估其语义清晰度" in system_prompt:
            response = {
                "is_clear": True,
                "score": 90,
                "reason": "名称和提前返回意图清晰。",
                "suggestions": [],
            }
        elif "评估其语法与逻辑清晰度" in system_prompt:
            response = {
                "is_clear": True,
                "score": 90,
                "reason": "控制流完整且语法有效。",
                "issues": [],
            }
        else:
            response = {
                "is_idiom": True,
                "confidence": 90,
                "reason": "该片段表达可复用的条件提前返回模式。",
                "characteristics": ["条件检查", "提前返回"],
            }
        return SimpleNamespace(content=json.dumps(response, ensure_ascii=False))

    async def close(self):
        self.closed = True


class BaselineEndToEndTests(unittest.TestCase):
    def test_output_contract_rejects_legacy_caps(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            manifest_path = root / "baseline-manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "parameters": {"max_types": 100},
                        "output_selection": {"final_idiom_count_cap": 100},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "不允许"):
                _validate_output_selection_contract(
                    "haggis-cpp",
                    root,
                    require_baseline_provenance=True,
                )

            manifest_path.write_text(
                json.dumps(
                    {
                        "selection_rule": {
                            "min_cluster_size": 3,
                            "selection_ratio": 1.0,
                            "max_types": 100,
                        }
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "参数无效"):
                _validate_output_selection_contract(
                    "rules-embedding-clustering",
                    root,
                    require_baseline_provenance=True,
                )

    def test_rules_selection_combines_size_ratio_and_type_cap(self):
        clusters = pd.DataFrame(
            [
                {"label": 1, "cluster_size": 12},
                {"label": 2, "cluster_size": 8},
                {"label": 3, "cluster_size": 5},
                {"label": 4, "cluster_size": 2},
            ]
        )
        ratio_selected = _select_clusters(
            clusters,
            min_cluster_size=3,
            selection_ratio=0.5,
            max_types=100,
        )
        capped = _select_clusters(
            clusters,
            min_cluster_size=3,
            selection_ratio=0.5,
            max_types=1,
        )
        self.assertEqual(ratio_selected["label"].tolist(), [1, 2])
        self.assertEqual(capped["label"].tolist(), [1])

    def test_rules_selection_requires_an_effective_ratio_and_positive_cap(self):
        clusters = pd.DataFrame([{"label": 1, "cluster_size": 3}])
        with self.assertRaises(ValueError):
            _select_clusters(
                clusters,
                min_cluster_size=3,
                selection_ratio=1.0,
                max_types=100,
            )
        with self.assertRaises(ValueError):
            _select_clusters(
                clusters,
                min_cluster_size=3,
                selection_ratio=0.5,
                max_types=0,
            )

    def test_llm_budget_counts_json_repair_as_an_endpoint_request(self):
        data, _, evidence_code = _fixture()
        data = data.iloc[[0]].reset_index(drop=True)
        response = {
            "idioms": [
                {
                    "template": "if (<EXPR_1>) { return <EXPR_2>; }",
                    "intent": "条件满足时提前返回结果。",
                    "confidence": 90,
                    "evidence": [
                        {
                            "evidence_id": "E00000-00000",
                            "source_code": evidence_code["alpha"],
                        }
                    ],
                }
            ]
        }
        client = _QueuedJsonClient(["损坏的响应", response, response])
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            dataset_path = root / "dataset.pkl"
            output_dir = root / "llm"
            data.to_pickle(dataset_path)
            counts = asyncio.run(
                generate_llm_direct_budget(
                    dataset_path,
                    output_dir,
                    model="fake-low",
                    token_budget=30_000,
                    chunk_tokens=3_000,
                    max_output_tokens=256,
                    model_client=client,
                )
            )
            manifest = json.loads(
                (output_dir / "baseline-manifest.json").read_text(encoding="utf-8")
            )
        self.assertEqual(counts, {"alpha": 1})
        self.assertEqual(client.calls, 3)
        self.assertEqual(manifest["call_count"], 2)
        self.assertEqual(manifest["endpoint_request_count"], 3)
        self.assertLessEqual(
            manifest["estimated_input_output_tokens"], manifest["token_budget"]
        )

    def test_three_baselines_and_main_method_share_all_nine_metrics(self):
        data, clusters, evidence_code = _fixture()
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            dataset_path = root / "dataset.pkl"
            clusters_path = root / "clusters.pkl"
            data.to_pickle(dataset_path)
            with clusters_path.open("wb") as file:
                pickle.dump(clusters, file)

            rules_dir = root / "rules"
            self.assertEqual(
                build_rules_embedding_baseline(
                    clusters_path,
                    rules_dir,
                    selection_ratio=0.5,
                    min_cluster_size=2,
                    max_types=1,
                ),
                {"alpha": 1, "beta": 1, "gamma": 1},
            )

            haggis_dir = root / "haggis"
            haggis_counts = mine_haggis_cpp(
                dataset_path,
                haggis_dir,
                iterations=4,
                burn_in_fraction=0.5,
                seed=7,
                min_posterior_support=0.0,
                min_occurrences=1,
                min_files=1,
                min_fragment_nodes=1,
            )
            self.assertTrue(all(count > 1 for count in haggis_counts.values()))

            queued = []
            for project in ("alpha", "beta", "gamma"):
                response = {
                    "idioms": [
                        {
                            "template": "if (<EXPR_1>) { return <EXPR_2>; }",
                            "intent": "条件满足时提前返回结果。",
                            "confidence": 90,
                            "evidence": [
                                {
                                    "evidence_id": "E00000-00000",
                                    "source_code": evidence_code[project],
                                }
                            ],
                        },
                        {
                            "template": "if (<EXPR_1>) { return <EXPR_2>; } return <EXPR_3>;",
                            "intent": "条件分支返回后提供默认返回值。",
                            "confidence": 85,
                            "evidence": [
                                {
                                    "evidence_id": "E00000-00000",
                                    "source_code": evidence_code[project],
                                }
                            ],
                        },
                    ]
                }
                queued.extend([response, response])
            fake_client = _QueuedJsonClient(queued)
            llm_dir = root / "llm"
            llm_counts = asyncio.run(
                generate_llm_direct_budget(
                    dataset_path,
                    llm_dir,
                    model="fake-low",
                    token_budget=30_000,
                    chunk_tokens=3_000,
                    max_output_tokens=256,
                    max_functions_per_project=2,
                    model_client=fake_client,
                )
            )
            self.assertEqual(llm_counts, {"alpha": 2, "beta": 2, "gamma": 2})
            self.assertEqual(fake_client.calls, 6)

            cimas_dir = root / "cimas"
            cimas_client = _CimasJsonClient()
            with (
                patch.dict(os.environ, {"OPENAI_API_KEY": "synthetic-test-key"}),
                patch(
                    "src.agents.judge_pipeline.create_model_client",
                    return_value=cimas_client,
                ),
            ):
                cimas_counts = asyncio.run(
                    judge_idioms(
                        str(clusters_path),
                        str(cimas_dir),
                        model="fake-low",
                        delay_seconds=0,
                        quiet=True,
                    )
                )
            self.assertEqual(cimas_counts, {"alpha": 2, "beta": 2, "gamma": 2})
            self.assertEqual(cimas_client.calls, 18)
            self.assertTrue(cimas_client.closed)

            method_inputs = (
                ("haggis-cpp", haggis_dir, True),
                ("llm-direct-budget", llm_dir, True),
                ("rules-embedding-clustering", rules_dir, True),
                ("cimas-cpp", cimas_dir, False),
            )
            for method, idiom_dir, require_provenance in method_inputs:
                report = validate_method_metrics(
                    method=method,
                    idiom_dir=idiom_dir,
                    dataset_path=dataset_path,
                    require_baseline_provenance=require_provenance,
                )
                self.assertEqual(report["status"], "passed")
                self.assertEqual(
                    report["evaluation_mode"],
                    "within_project_file_split",
                )
                self.assertEqual(
                    report["metric_contract"]["metric_names"],
                    list(FINAL_METRICS),
                )

            haggis_manifest = json.loads(
                (haggis_dir / "baseline-manifest.json").read_text(encoding="utf-8")
            )
            llm_manifest = json.loads(
                (llm_dir / "baseline-manifest.json").read_text(encoding="utf-8")
            )
            rules_manifest = json.loads(
                (rules_dir / "baseline-manifest.json").read_text(encoding="utf-8")
            )
            self.assertIsNone(
                haggis_manifest["output_selection"]["final_idiom_count_cap"]
            )
            self.assertNotIn("max_types", haggis_manifest["parameters"])
            self.assertIsNone(
                llm_manifest["output_selection"]["final_idiom_count_cap"]
            )
            self.assertEqual(
                rules_manifest["selection_rule"],
                {
                    "max_types": 1,
                    "min_cluster_size": 2,
                    "order": [
                        "filter_min_cluster_size",
                        "rank_by_cluster_size_then_label",
                        "apply_selection_ratio",
                        "apply_max_types_cap",
                    ],
                    "selection_ratio": 0.5,
                },
            )

            with (rules_dir / "alpha_idiom.pkl").open("rb") as file:
                rules_idioms = pickle.load(file)
            self.assertNotIn("mock_provenance", rules_idioms[0])
            self.assertEqual(
                rules_idioms[0]["baseline_provenance"]["method"],
                "rules_embedding_clustering",
            )


if __name__ == "__main__":
    unittest.main()
