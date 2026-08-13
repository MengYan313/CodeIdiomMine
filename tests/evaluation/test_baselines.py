import asyncio
import json
import pickle
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from src.common.run_checkpoint import RunCheckpoint
from src.evaluation.baseline_common import FINAL_METRICS
from src.evaluation.baseline_validation import (
    _validate_output_selection_contract,
    validate_method_metrics,
)
from src.evaluation.haggis_cpp import mine_haggis_cpp
from src.evaluation.idiomine_cpp import (
    run_idiomine_cpp_baseline,
)
from src.evaluation.llm_direct_baseline import (
    DEFAULT_CHECKPOINT_PATH,
    _MAP_IDIOM_SCHEMA,
    _MAP_SYSTEM_PROMPT,
    _chunk_reduce_candidates,
    _map_prompt,
    _project_units,
    _reduce_input_tokens,
    _register_reduce_evidence,
    _restore_reduce_evidence,
    _validate_reduce_refs,
    generate_llm_direct_budget,
)
from src.evaluation.stage2_frequency_ablation import (
    _select_clusters,
    build_stage2_frequency_ablation,
)
from src.llm.json_output import append_json_output_contract
from src.llm.utils import count_tokens_approximate


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
        if isinstance(response, Exception):
            raise response
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

            manifest_path = root / "ablation-manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "comparison_role": "quality_ablation",
                        "automatic_metrics_role": (
                            "stage2_coverage_upper_bound_diagnostic"
                        ),
                        "primary_comparison": (
                            "blinded_manual_idiom_quality_annotation"
                        ),
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
                    "stage2-frequency-ablation",
                    root,
                    require_baseline_provenance=True,
                )

            manifest_path.write_text(
                json.dumps(
                    {
                        "selection_rule": {
                            "min_cluster_size": 3,
                            "selection_ratio": 0.5,
                            "max_types": 100,
                        }
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "缺少质量实验定位"):
                _validate_output_selection_contract(
                    "stage2-frequency-ablation",
                    root,
                    require_baseline_provenance=True,
                )

            manifest_path = root / "baseline-manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "parameters": {
                            "candidate_origin": "semantic_def_use",
                            "embedding_model": "synthetic",
                            "eps": 0.5,
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
                            "eps": 0.5,
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

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["pipeline"]["post_synthesis_judgment"] = False
            manifest["parameters"]["eps"] = 0.25
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "eps=0.5"):
                _validate_output_selection_contract(
                    "idiomine-cpp",
                    root,
                    require_baseline_provenance=True,
                )

    def test_stage2_ablation_combines_size_ratio_and_type_cap(self):
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

    def test_stage2_ablation_requires_effective_ratio_and_positive_cap(self):
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
        reduced, _ = _register_reduce_evidence(response["idioms"])
        client = _QueuedJsonClient(
            ["损坏的响应", response, {"idioms": reduced}]
        )
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
                    checkpoint_path=output_dir / "checkpoint.sqlite3",
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

    def test_llm_budget_checkpoints_usage_when_json_repair_exceeds_budget(self):
        data, _, _ = _fixture()
        data = data.iloc[[0]].reset_index(drop=True)
        units = _project_units(data.iloc[0])
        map_input_tokens = count_tokens_approximate(
            _MAP_SYSTEM_PROMPT
        ) + count_tokens_approximate(
            append_json_output_contract(
                _map_prompt("alpha", units),
                _MAP_IDIOM_SCHEMA,
            )
        )
        token_budget = map_input_tokens + 256

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            dataset_path = root / "dataset.pkl"
            output_dir = root / "llm"
            checkpoint_path = root / "checkpoint.sqlite3"
            data.to_pickle(dataset_path)

            interrupted_client = _QueuedJsonClient(["损坏的响应"])
            counts = asyncio.run(
                generate_llm_direct_budget(
                    dataset_path,
                    output_dir,
                    model="fake-low",
                    token_budget=token_budget,
                    chunk_tokens=3_000,
                    max_output_tokens=256,
                    model_client=interrupted_client,
                    checkpoint_path=checkpoint_path,
                )
            )
            first_manifest = json.loads(
                (output_dir / "baseline-manifest.json").read_text(encoding="utf-8")
            )
            resumed_client = _QueuedJsonClient([])
            resumed_counts = asyncio.run(
                generate_llm_direct_budget(
                    dataset_path,
                    output_dir,
                    model="fake-low",
                    token_budget=token_budget,
                    chunk_tokens=3_000,
                    max_output_tokens=256,
                    model_client=resumed_client,
                    checkpoint_path=checkpoint_path,
                    resume=True,
                )
            )
            resumed_manifest = json.loads(
                (output_dir / "baseline-manifest.json").read_text(encoding="utf-8")
            )

        self.assertEqual(counts, {"alpha": 0})
        self.assertEqual(resumed_counts, {"alpha": 0})
        self.assertEqual(interrupted_client.calls, 1)
        self.assertEqual(resumed_client.calls, 0)
        self.assertTrue(first_manifest["token_budget_exhausted"])
        self.assertFalse(first_manifest["complete"])
        self.assertEqual(
            resumed_manifest["estimated_input_output_tokens"],
            first_manifest["estimated_input_output_tokens"],
        )

    def test_llm_budget_marks_partial_map_output_incomplete(self):
        data, _, _ = _fixture()
        data = data.iloc[[0]].reset_index(drop=True)
        data.at[0, "func_src"] = [
            [data.iloc[0]["func_src"][0][0] + " padding" * 300],
            [data.iloc[0]["func_src"][1][0] + " padding" * 300],
        ]
        units = _project_units(data.iloc[0])
        map_chunks = [units[:1], units[1:]]
        first_input_tokens = count_tokens_approximate(
            _MAP_SYSTEM_PROMPT
        ) + count_tokens_approximate(
            append_json_output_contract(
                _map_prompt("alpha", map_chunks[0]),
                _MAP_IDIOM_SCHEMA,
            )
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            dataset_path = root / "dataset.pkl"
            output_dir = root / "llm"
            data.to_pickle(dataset_path)
            client = _QueuedJsonClient([{"idioms": []}])
            counts = asyncio.run(
                generate_llm_direct_budget(
                    dataset_path,
                    output_dir,
                    model="fake-low",
                    token_budget=first_input_tokens + 256,
                    chunk_tokens=256,
                    max_output_tokens=256,
                    model_client=client,
                    checkpoint_path=output_dir / "checkpoint.sqlite3",
                )
            )
            manifest = json.loads(
                (output_dir / "baseline-manifest.json").read_text(encoding="utf-8")
            )

            with self.assertRaisesRegex(ValueError, "不完整"):
                _validate_output_selection_contract(
                    "llm-direct-budget",
                    output_dir,
                    require_baseline_provenance=True,
                )

        self.assertEqual(DEFAULT_CHECKPOINT_PATH, Path(
            "outputs/cli11/llm-direct-budget/checkpoint.sqlite3"
        ))
        self.assertEqual(counts, {"alpha": 0})
        self.assertEqual(client.calls, 1)
        self.assertFalse(manifest["complete"])
        self.assertTrue(manifest["token_budget_exhausted"])
        self.assertEqual(manifest["processed_project_count"], 0)
        self.assertEqual(manifest["processed_function_count"], 1)
        self.assertEqual(manifest["projects"][0]["map_chunk_count"], 2)
        self.assertEqual(manifest["projects"][0]["processed_map_chunk_count"], 1)
        self.assertFalse((output_dir / "alpha_idiom.pkl").exists())

    def test_llm_budget_resumes_reduce_without_repeating_completed_map(self):
        data, _, evidence_code = _fixture()
        data = data.iloc[:2].reset_index(drop=True)

        def response(project):
            return {
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
                    }
                ]
            }

        alpha_response = response("alpha")
        beta_response = response("beta")
        alpha_reduce, _ = _register_reduce_evidence(alpha_response["idioms"])
        beta_reduce, _ = _register_reduce_evidence(beta_response["idioms"])
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            dataset_path = root / "dataset.pkl"
            output_dir = root / "llm"
            checkpoint_path = root / "llm.sqlite3"
            data.to_pickle(dataset_path)

            interrupted_client = _QueuedJsonClient(
                [
                    alpha_response,
                    {"idioms": alpha_reduce},
                    beta_response,
                    ConnectionError("reduce connection closed"),
                ]
            )
            with self.assertRaisesRegex(ConnectionError, "connection closed"):
                asyncio.run(
                    generate_llm_direct_budget(
                        dataset_path,
                        output_dir,
                        model="fake-low",
                        token_budget=30_000,
                        chunk_tokens=3_000,
                        max_output_tokens=256,
                        model_client=interrupted_client,
                        checkpoint_path=checkpoint_path,
                    )
                )
            self.assertEqual(interrupted_client.calls, 4)

            data.iloc[::-1].reset_index(drop=True).to_pickle(dataset_path)
            resumed_client = _QueuedJsonClient([{"idioms": beta_reduce}])
            counts = asyncio.run(
                generate_llm_direct_budget(
                    dataset_path,
                    output_dir,
                    model="fake-low",
                    token_budget=30_000,
                    chunk_tokens=3_000,
                    max_output_tokens=256,
                    model_client=resumed_client,
                    checkpoint_path=checkpoint_path,
                    resume=True,
                )
            )
            manifest = json.loads(
                (output_dir / "baseline-manifest.json").read_text(encoding="utf-8")
            )
            with (output_dir / "alpha_idiom.pkl").open("rb") as file:
                alpha_artifact = pickle.load(file)
            with (output_dir / "beta_idiom.pkl").open("rb") as file:
                beta_artifact = pickle.load(file)

        self.assertEqual(resumed_client.calls, 1)
        self.assertEqual(counts, {"alpha": 1, "beta": 1})
        self.assertEqual(manifest["call_count"], 4)
        self.assertEqual(manifest["endpoint_request_count"], 5)
        self.assertTrue(manifest["resumed"])
        self.assertEqual(alpha_artifact["artifact_type"], "idiom_judgment")
        self.assertEqual(alpha_artifact["project"], "alpha")
        self.assertEqual(len(alpha_artifact["accepted"]), 1)
        self.assertEqual(beta_artifact["artifact_type"], "idiom_judgment")
        self.assertEqual(beta_artifact["project"], "beta")
        self.assertEqual(len(beta_artifact["accepted"]), 1)

    def test_llm_budget_resumes_recursive_reduce_across_multiple_levels(self):
        data, _, evidence_code = _fixture()
        data = data.iloc[[0]].reset_index(drop=True)

        def candidate(index, repetitions):
            return {
                "template": (
                    f"if (<EXPR_{index}>) {{ "
                    + "result += value; " * repetitions
                    + "}"
                ),
                "intent": f"归并候选 {index}。",
                "confidence": 90,
                "evidence": [
                    {
                        "evidence_id": "E00000-00000",
                        "source_code": evidence_code["alpha"],
                    }
                ],
            }

        reduce_chunk_tokens = 800
        map_candidates = [candidate(index, 30) for index in range(4)]
        candidates, _ = _register_reduce_evidence(map_candidates)
        level_zero_outputs, _ = _register_reduce_evidence(
            [candidate(index, 20) for index in range(4)]
        )
        level_one_outputs, _ = _register_reduce_evidence(
            [candidate(index, 5) for index in range(2)]
        )
        self.assertEqual(
            len(
                _chunk_reduce_candidates(
                    "alpha", candidates, reduce_chunk_tokens
                )
            ),
            4,
        )
        self.assertEqual(
            len(
                _chunk_reduce_candidates(
                    "alpha", level_zero_outputs, reduce_chunk_tokens
                )
            ),
            2,
        )
        self.assertEqual(
            len(
                _chunk_reduce_candidates(
                    "alpha", level_one_outputs, reduce_chunk_tokens
                )
            ),
            1,
        )
        with self.assertRaisesRegex(ValueError, "无法安全分块"):
            _chunk_reduce_candidates(
                "alpha",
                _register_reduce_evidence([candidate(99, 200)])[0],
                reduce_chunk_tokens,
            )
        map_response = {"idioms": map_candidates}
        level_zero_responses = [
            {"idioms": [item]} for item in level_zero_outputs
        ]
        level_one_responses = [
            {"idioms": [item]} for item in level_one_outputs
        ]
        final_response = {"idioms": level_one_outputs}

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            dataset_path = root / "dataset.pkl"
            output_dir = root / "llm"
            checkpoint_path = root / "llm.sqlite3"
            data.to_pickle(dataset_path)

            interrupted_client = _QueuedJsonClient(
                [
                    map_response,
                    level_zero_responses[0],
                    ConnectionError("reduce chunk connection closed"),
                ]
            )
            with self.assertRaisesRegex(ConnectionError, "connection closed"):
                asyncio.run(
                    generate_llm_direct_budget(
                        dataset_path,
                        output_dir,
                        model="fake-low",
                        token_budget=100_000,
                        chunk_tokens=3_000,
                        reduce_chunk_tokens=reduce_chunk_tokens,
                        max_output_tokens=256,
                        model_client=interrupted_client,
                        checkpoint_path=checkpoint_path,
                    )
                )
            self.assertEqual(interrupted_client.calls, 3)

            resumed_client = _QueuedJsonClient(
                [
                    *level_zero_responses[1:],
                    *level_one_responses,
                    final_response,
                ]
            )
            counts = asyncio.run(
                generate_llm_direct_budget(
                    dataset_path,
                    output_dir,
                    model="fake-low",
                    token_budget=100_000,
                    chunk_tokens=3_000,
                    reduce_chunk_tokens=reduce_chunk_tokens,
                    max_output_tokens=256,
                    model_client=resumed_client,
                    checkpoint_path=checkpoint_path,
                    resume=True,
                )
            )
            manifest = json.loads(
                (output_dir / "baseline-manifest.json").read_text(encoding="utf-8")
            )
            with (output_dir / "alpha_idiom.pkl").open("rb") as file:
                artifact = pickle.load(file)
            with RunCheckpoint(checkpoint_path, resume=True) as checkpoint:
                reduce_keys = {
                    (
                        record["project"],
                        record["level"],
                        record["chunk_index"],
                    )
                    for record in checkpoint.load_records().values()
                    if record["kind"] == "reduce"
                }

        self.assertEqual(resumed_client.calls, 6)
        self.assertEqual(counts, {"alpha": 2})
        self.assertEqual(manifest["projects"][0]["map_call_count"], 1)
        self.assertEqual(manifest["projects"][0]["reduce_call_count"], 7)
        self.assertEqual(manifest["call_count"], 8)
        self.assertEqual(manifest["endpoint_request_count"], 9)
        self.assertEqual(manifest["reduce_chunk_tokens"], reduce_chunk_tokens)
        self.assertEqual(len(artifact["accepted"]), 2)
        self.assertEqual(
            reduce_keys,
            {
                ("alpha", 0, 0),
                ("alpha", 0, 1),
                ("alpha", 0, 2),
                ("alpha", 0, 3),
                ("alpha", 1, 0),
                ("alpha", 1, 1),
                ("alpha", 2, 0),
            },
        )

    def test_reduce_evidence_refs_restore_completely_and_reject_unknown_refs(self):
        source_code = "if (ready) { return value; } " * 80
        full = [
            {
                "template": "if (<EXPR_1>) { return <EXPR_2>; }",
                "intent": "条件满足时返回。",
                "confidence": 90,
                "evidence": [
                    {"evidence_id": "E00000-00000", "source_code": source_code},
                    {"evidence_id": "E00000-00000", "source_code": source_code},
                ],
            }
        ]
        reduced, registry = _register_reduce_evidence(full)

        self.assertEqual(reduced[0]["evidence_refs"], ["R000000"])
        self.assertEqual(_restore_reduce_evidence(reduced, registry), [
            {
                **full[0],
                "evidence": [full[0]["evidence"][0]],
            }
        ])
        self.assertLess(
            _reduce_input_tokens("alpha", reduced),
            _reduce_input_tokens("alpha", full) / 2,
        )
        with self.assertRaisesRegex(ValueError, "不存在"):
            _restore_reduce_evidence(
                [{**reduced[0], "evidence_refs": ["R999999"]}],
                registry,
            )
        with self.assertRaisesRegex(ValueError, "遗漏 R000000"):
            _validate_reduce_refs([], {"R000000"})
        with self.assertRaisesRegex(ValueError, "遗漏 R000001"):
            _validate_reduce_refs(reduced, {"R000000", "R000001"})

    def test_llm_budget_checkpoints_usage_when_reduce_returns_unknown_ref(self):
        data, _, evidence_code = _fixture()
        data = data.iloc[[0]].reset_index(drop=True)
        map_response = {
            "idioms": [
                {
                    "template": "if (<EXPR_1>) { return <EXPR_2>; }",
                    "intent": "条件满足时返回。",
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
        unknown_ref_response = {
            "idioms": [
                {
                    "template": "if (<EXPR_1>) { return <EXPR_2>; }",
                    "intent": "条件满足时返回。",
                    "confidence": 90,
                    "evidence_refs": ["R999999"],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            dataset_path = root / "dataset.pkl"
            output_dir = root / "llm"
            data.to_pickle(dataset_path)
            client = _QueuedJsonClient([map_response, unknown_ref_response])

            with self.assertRaisesRegex(ValueError, "不存在"):
                asyncio.run(
                    generate_llm_direct_budget(
                        dataset_path,
                        output_dir,
                        model="fake-low",
                        token_budget=30_000,
                        chunk_tokens=3_000,
                        max_output_tokens=256,
                        model_client=client,
                        checkpoint_path=output_dir / "checkpoint.sqlite3",
                    )
                )
            with RunCheckpoint(
                output_dir / "checkpoint.sqlite3", resume=True
            ) as checkpoint:
                last_record = list(checkpoint.load_records().values())[-1]

        self.assertEqual(client.calls, 2)
        self.assertEqual(last_record["kind"], "request_failure")
        self.assertEqual(last_record["endpoint_request_count"], 2)
        self.assertGreater(last_record["estimated_input_output_tokens"], 0)

    def test_llm_budget_finishes_no_progress_with_stable_union(self):
        data, _, evidence_code = _fixture()
        data = data.iloc[[0]].reset_index(drop=True)
        second_code = data.iloc[0]["func_ast"][1][0][1]["code_snippet"]

        def candidate(index, evidence_id, source_code):
            return {
                "template": (
                    f"if (<EXPR_{index}>) {{ "
                    + "result += value; " * 30
                    + "}"
                ),
                "intent": "累加满足条件的值。",
                "confidence": 90,
                "evidence": [
                    {
                        "evidence_id": evidence_id,
                        "source_code": source_code,
                    }
                ],
            }

        map_candidates = [
            candidate(1, "E00000-00000", evidence_code["alpha"]),
            candidate(2, "E00001-00000", second_code),
        ]
        candidates, _ = _register_reduce_evidence(map_candidates)
        self.assertEqual(
            len(_chunk_reduce_candidates("alpha", candidates, 800)),
            2,
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            dataset_path = root / "dataset.pkl"
            output_dir = root / "llm"
            data.to_pickle(dataset_path)
            client = _QueuedJsonClient(
                [
                    {"idioms": map_candidates},
                    {"idioms": [candidates[0]]},
                    {"idioms": [candidates[1]]},
                ]
            )

            counts = asyncio.run(
                generate_llm_direct_budget(
                    dataset_path,
                    output_dir,
                    model="fake-low",
                    token_budget=100_000,
                    chunk_tokens=3_000,
                    reduce_chunk_tokens=800,
                    max_output_tokens=256,
                    model_client=client,
                    checkpoint_path=output_dir / "checkpoint.sqlite3",
                )
            )
            with (output_dir / "alpha_idiom.pkl").open("rb") as file:
                artifact = pickle.load(file)
            with RunCheckpoint(
                output_dir / "checkpoint.sqlite3", resume=True
            ) as checkpoint:
                completed = [
                    record
                    for record in checkpoint.load_records().values()
                    if record["kind"] == "project"
                ]

        self.assertEqual(client.calls, 3)
        self.assertEqual(counts, {"alpha": 2})
        self.assertEqual(len(artifact["accepted"]), 2)
        self.assertTrue(all(item["cnt"] == 1 for item in artifact["accepted"]))
        self.assertEqual(len(completed), 1)

    def test_llm_budget_deduplicates_before_deciding_reduce_progress(self):
        data, _, evidence_code = _fixture()
        data = data.iloc[[0]].reset_index(drop=True)
        second_code = data.iloc[0]["func_ast"][1][0][1]["code_snippet"]
        body = "result += value; " * 30
        map_candidates = [
            {
                "template": f"if (<EXPR_1>) {{ {body}}}",
                "intent": "累加满足条件的值。",
                "confidence": 90,
                "evidence": [
                    {
                        "evidence_id": "E00000-00000",
                        "source_code": evidence_code["alpha"],
                    }
                ],
            },
            {
                "template": f"if   (<EXPR_1>)  {{  {body}}}",
                "intent": "累加满足条件的值。",
                "confidence": 90,
                "evidence": [
                    {
                        "evidence_id": "E00001-00000",
                        "source_code": second_code,
                    }
                ],
            },
        ]
        candidates, _ = _register_reduce_evidence(map_candidates)
        self.assertEqual(
            len(_chunk_reduce_candidates("alpha", candidates, 800)),
            2,
        )
        merged = {
            **candidates[0],
            "evidence_refs": ["R000000", "R000001"],
        }
        client = _QueuedJsonClient(
            [
                {"idioms": map_candidates},
                {"idioms": [candidates[0]]},
                {"idioms": [candidates[1]]},
                {"idioms": [merged]},
            ]
        )
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
                    token_budget=100_000,
                    chunk_tokens=3_000,
                    reduce_chunk_tokens=800,
                    max_output_tokens=256,
                    model_client=client,
                    checkpoint_path=output_dir / "checkpoint.sqlite3",
                )
            )
            with (output_dir / "alpha_idiom.pkl").open("rb") as file:
                artifact = pickle.load(file)

        self.assertEqual(client.calls, 4)
        self.assertEqual(counts, {"alpha": 1})
        self.assertEqual(artifact["accepted"][0]["cnt"], 2)

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

            stage2_ablation_dir = root / "stage2-ablation"
            self.assertEqual(
                build_stage2_frequency_ablation(
                    clusters_path,
                    stage2_ablation_dir,
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
                reduced_response, _ = _register_reduce_evidence(response["idioms"])
                queued.extend([response, {"idioms": reduced_response}])
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
                    checkpoint_path=llm_dir / "checkpoint.sqlite3",
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
                        eps=0.5,
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
                ("stage2-frequency-ablation", stage2_ablation_dir, True),
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
            stage2_ablation_manifest = json.loads(
                (stage2_ablation_dir / "ablation-manifest.json").read_text(
                    encoding="utf-8"
                )
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
                stage2_ablation_manifest["selection_rule"],
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

            with (stage2_ablation_dir / "alpha_idiom.pkl").open("rb") as file:
                stage2_ablation_idioms = pickle.load(file)["accepted"]
            self.assertNotIn("mock_provenance", stage2_ablation_idioms[0])
            self.assertEqual(
                stage2_ablation_idioms[0]["ablation_provenance"]["method"],
                "stage2_frequency_ablation",
            )
            self.assertEqual(
                stage2_ablation_idioms[0]["ablation_provenance"][
                    "comparison_role"
                ],
                "quality_ablation",
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
