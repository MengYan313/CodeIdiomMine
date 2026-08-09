import asyncio
import json
import pickle
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from src.evaluation.baseline_common import FINAL_METRICS
from src.evaluation.baseline_validation import (
    _validate_output_selection_contract,
    validate_method_metrics,
)
from src.evaluation.haggis_cpp import mine_haggis_cpp
from src.evaluation.idiomine_cpp import (
    run_idiomine_cpp_baseline,
)
from src.evaluation.llm_direct_baseline import generate_llm_direct_budget
from src.evaluation.rules_embedding_baseline import (
    _select_clusters,
    build_rules_embedding_baseline,
)


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


def _idiomine_embedding_fixture(data):
    rows = []
    for _, row in data.iterrows():
        project = row["project"]
        files = row["cppFile"]
        ast_a = row["func_ast"][0][0]
        ast_b = row["func_ast"][1][0]
        semantic_a = {
            **ast_a[1],
            "candidate_level": "region",
            "candidate_origin": "semantic_def_use",
        }
        semantic_b = {
            **ast_b[1],
            "candidate_level": "region",
            "candidate_origin": "semantic_def_use",
        }
        infos = [
            [project, files[0], ast_a[0]["extent"], semantic_a],
            [project, files[1], ast_b[0]["extent"], semantic_b],
            [project, files[0], ast_a[0]["extent"], ast_a[0]],
        ]
        rows.append(
            {
                "pros_name": project,
                "pros_src": [
                    semantic_a["code_snippet"],
                    semantic_b["code_snippet"],
                    ast_a[0]["code_snippet"],
                ],
                "pros_emb": [
                    np.array([[1.0, 0.01, 0.0]]),
                    np.array([[1.0, 0.02, 0.0]]),
                    np.array([[0.0, 1.0, 0.0]]),
                ],
                "pros_info": infos,
            }
        )
    return pd.DataFrame(rows)


class _QueuedJsonClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    async def create(self, messages, extra_create_args):
        del messages, extra_create_args
        response = self.responses[self.calls]
        self.calls += 1
        return SimpleNamespace(content=json.dumps(response, ensure_ascii=False))


class BaselineEndToEndTests(unittest.TestCase):
    def test_output_contract_rejects_invalid_caps(self):
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

            manifest_path.write_text(
                json.dumps(
                    {
                        "parameters": {
                            "candidate_origin": "semantic_def_use",
                            "embedding_model": "synthetic",
                            "eps": 0.25,
                            "min_samples": 2,
                            "metric": "cosine",
                            "region_grouping": (
                                "exact_representative_project_file_function_extent"
                            ),
                            "token_budget": 10_000,
                            "max_output_tokens": 256,
                            "max_examples_per_judgment": 5,
                        },
                        "output_selection": {
                            "policy": (
                                "accepted_independent_idioms_plus_direct_syntheses"
                            ),
                            "final_idiom_count_cap": 100,
                        },
                        "adaptation": {
                            "claim": (
                                "simplified_cpp_migration_not_full_reproduction"
                            )
                        },
                        "pipeline": {
                            "judgment": (
                                "one_independent_call_per_candidate_cluster"
                            ),
                            "synthesis": (
                                "one_attempt_per_same_region_group_of_accepted_idioms"
                            ),
                            "post_synthesis_judgment": False,
                            "final_output": (
                                "accepted_independent_idioms_plus_direct_syntheses"
                            ),
                        },
                        "candidate_generation": {
                            "output_selection": {
                                "policy": "all_non_noise_dbscan_clusters"
                            }
                        },
                        "token_budget_exhausted": False,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "不允许"):
                _validate_output_selection_contract(
                    "idiomine-cpp",
                    root,
                    require_baseline_provenance=True,
                )

            manifest_path.write_text(
                json.dumps(
                    {
                        "parameters": {
                            "candidate_origin": "semantic_def_use",
                            "embedding_model": "synthetic",
                            "eps": 0.25,
                            "min_samples": 2,
                            "metric": "cosine",
                            "region_grouping": (
                                "exact_representative_project_file_function_extent"
                            ),
                            "token_budget": 10_000,
                            "max_output_tokens": 256,
                            "max_examples_per_judgment": 5,
                        },
                        "adaptation": {
                            "claim": (
                                "simplified_cpp_migration_not_full_reproduction"
                            )
                        },
                        "output_selection": {
                            "policy": (
                                "accepted_independent_idioms_plus_direct_syntheses"
                            ),
                            "final_idiom_count_cap": None,
                        },
                        "pipeline": {
                            "judgment": (
                                "one_independent_call_per_candidate_cluster"
                            ),
                            "synthesis": (
                                "one_attempt_per_same_region_group_of_accepted_idioms"
                            ),
                            "post_synthesis_judgment": True,
                            "final_output": (
                                "accepted_independent_idioms_plus_direct_syntheses"
                            ),
                        },
                        "candidate_generation": {
                            "output_selection": {
                                "policy": "all_non_noise_dbscan_clusters"
                            }
                        },
                        "token_budget_exhausted": False,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "顺序无效"):
                _validate_output_selection_contract(
                    "idiomine-cpp",
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

    def test_baselines_and_main_method_share_all_nine_metrics(self):
        data, clusters, evidence_code = _fixture()
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            dataset_path = root / "dataset.pkl"
            clusters_path = root / "clusters.pkl"
            embeddings_path = root / "embeddings.pkl"
            data.to_pickle(dataset_path)
            with clusters_path.open("wb") as file:
                pickle.dump(clusters, file)
            _idiomine_embedding_fixture(data).to_pickle(embeddings_path)

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

            idiomine_dir = root / "idiomine"
            idiomine_client = _QueuedJsonClient(
                [
                    {"is_idiom": True, "reason": "候选重复且意图完整。"},
                    {"is_idiom": True, "reason": "候选重复且意图完整。"},
                    {"is_idiom": True, "reason": "候选重复且意图完整。"},
                ]
            )
            self.assertEqual(
                asyncio.run(
                    run_idiomine_cpp_baseline(
                        [embeddings_path],
                        idiomine_dir,
                        embedding_model="synthetic-test-embedding",
                        eps=0.1,
                        min_samples=2,
                        model="fake-low",
                        token_budget=30_000,
                        max_output_tokens=256,
                        model_client=idiomine_client,
                    )
                ),
                {"alpha": 1, "beta": 1, "gamma": 1},
            )
            self.assertEqual(idiomine_client.calls, 3)

            cimas_dir = root / "cimas"
            cimas_dir.mkdir()
            cimas_counts = {}
            for item in clusters:
                project = item["pros_name"]
                accepted = []
                for _, row in item["clusters"].iterrows():
                    infos = list(row["infos"])
                    accepted.append(
                        {
                            "center_point": row["center_point"],
                            "info": row["center_point_info"],
                            "source_infos": infos,
                            "cnt": len(infos),
                            "avg_ast_num": 6.0,
                            "loc_label": row["loc_label"],
                        }
                    )
                with (cimas_dir / f"{project}_idiom.pkl").open("wb") as file:
                    pickle.dump(
                        {
                            "artifact_type": "idiom_judgment",
                            "project": project,
                            "accepted": accepted,
                        },
                        file,
                    )
                cimas_counts[project] = len(accepted)
            self.assertEqual(cimas_counts, {"alpha": 2, "beta": 2, "gamma": 2})

            method_inputs = (
                ("haggis-cpp", haggis_dir, True),
                ("llm-direct-budget", llm_dir, True),
                ("rules-embedding-clustering", rules_dir, True),
                ("idiomine-cpp", idiomine_dir, True),
                ("cimas-cpp", cimas_dir, False),
            )
            for method, idiom_dir, require_provenance in method_inputs:
                report = validate_method_metrics(
                    method=method,
                    idiom_dir=idiom_dir,
                    dataset_path=dataset_path,
                    cluster_path=clusters_path,
                    require_baseline_provenance=require_provenance,
                )
                self.assertEqual(report["status"], "passed")
                self.assertEqual(
                    report["evaluation_mode"],
                    "within_project_kfold",
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
            idiomine_manifest = json.loads(
                (idiomine_dir / "baseline-manifest.json").read_text(
                    encoding="utf-8"
                )
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
            self.assertIsNone(
                idiomine_manifest["output_selection"]["final_idiom_count_cap"]
            )
            self.assertEqual(
                idiomine_manifest["adaptation"]["claim"],
                "simplified_cpp_migration_not_full_reproduction",
            )
            self.assertFalse(
                idiomine_manifest["pipeline"]["post_synthesis_judgment"]
            )
            self.assertEqual(
                idiomine_manifest["output_selection"]["policy"],
                "accepted_independent_idioms_plus_direct_syntheses",
            )

            with (rules_dir / "alpha_idiom.pkl").open("rb") as file:
                rules_idioms = pickle.load(file)["accepted"]
            self.assertNotIn("mock_provenance", rules_idioms[0])
            self.assertEqual(
                rules_idioms[0]["baseline_provenance"]["method"],
                "rules_embedding_clustering",
            )
            with (idiomine_dir / "alpha_idiom.pkl").open("rb") as file:
                idiomine_idioms = pickle.load(file)["accepted"]
            self.assertEqual(
                idiomine_idioms[0]["baseline_provenance"]["method"],
                "idiomine_cpp",
            )
            self.assertEqual(
                idiomine_idioms[0]["baseline_provenance"][
                    "candidate_provenance"
                ]["embedding_model"],
                "synthetic-test-embedding",
            )
            self.assertEqual(idiomine_idioms[0]["cnt"], 2)


if __name__ == "__main__":
    unittest.main()
