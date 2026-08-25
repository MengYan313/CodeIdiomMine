import asyncio
import importlib.util
import json
import pickle
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from src.evaluation.baseline_common import make_idiom_record
from src.evaluation._idiomine_cpp_candidates import (
    build_idiomine_cpp_candidate_artifacts,
)
from src.evaluation.idiomine_cpp import (
    _record_regions,
    _representative_region,
    estimate_idiomine_cpp_run,
    run_idiomine_cpp_baseline,
)


class _QueuedJsonClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    async def create(self, messages, extra_create_args):
        del messages, extra_create_args
        response = self.responses[self.calls]
        self.calls += 1
        return SimpleNamespace(content=json.dumps(response, ensure_ascii=False))


class _FailingClient:
    def __init__(self):
        self.calls = 0

    async def create(self, messages, extra_create_args):
        del messages, extra_create_args
        self.calls += 1
        raise TimeoutError("temporary endpoint failure")


def _source_info(
    *,
    function_extent: str,
    candidate_extent: str,
    code: str,
    source_path: str = "src/sample.cpp",
):
    return [
        "sample",
        source_path,
        function_extent,
        {
            "kind": "semantic_slice",
            "extent": candidate_extent,
            "code_snippet": code,
            "candidate_origin": "semantic_def_use",
            "candidate_level": "region",
            "ast_num": 8,
            "subtree_size": 9,
        },
    ]


class IdioMineCppTests(unittest.TestCase):
    def test_removed_variant_modules_are_not_public_entries(self):
        for suffix in ("core", "simple"):
            with self.subTest(suffix=suffix):
                self.assertIsNone(
                    importlib.util.find_spec(
                        f"src.evaluation.idiomine_cpp_{suffix}"
                    )
                )

    def test_candidate_region_follows_center_code_evidence(self):
        first = _source_info(
            function_extent="1-0-10-1",
            candidate_extent="2-2-3-3",
            code="first();",
        )
        representative = _source_info(
            function_extent="20-0-30-1",
            candidate_extent="22-2-23-3",
            code="representative();",
        )
        record = make_idiom_record(
            center_point="representative();",
            source_infos=[first, representative],
            provenance={
                "method": "idiomine_cpp",
                "output_kind": "cluster_candidate",
            },
        )

        self.assertEqual(
            _representative_region(record),
            ("sample", "src/sample.cpp", "20-0-30-1"),
        )
        self.assertEqual(
            _record_regions(record),
            [
                ("sample", "src/sample.cpp", "1-0-10-1"),
                ("sample", "src/sample.cpp", "20-0-30-1"),
            ],
        )

    def test_candidate_generation_adds_reusable_ast_fragment_clusters(self):
        semantic_infos = [
            _source_info(
                function_extent=f"{index}-0-{index + 5}-1",
                candidate_extent=f"{index + 1}-2-{index + 2}-3",
                code=f"use(value_{index});",
            )
            for index in range(2)
        ]
        ast_infos = [
            _source_info(
                function_extent=f"{index + 10}-0-{index + 15}-1",
                candidate_extent=f"{index + 11}-2-{index + 12}-3",
                code=f"if (ready_{index}) {{ consume(); }}",
            )
            for index in range(2)
        ]
        for info in ast_infos:
            info[3].pop("candidate_origin")
            info[3]["kind"] = "if_statement"

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            dataset_path = root / "dataset.pkl"
            embeddings_path = root / "embeddings.pkl"
            output_dir = root / "candidates"
            pd.DataFrame(
                [
                    {
                        "project": "sample",
                        "cppFile": ["src/sample.cpp"],
                        "func_ast": [[]],
                        "func_src": [[]],
                        "split": ["train"],
                    }
                ]
            ).to_pickle(dataset_path)
            infos = semantic_infos + ast_infos
            pd.DataFrame(
                [
                    {
                        "pros_name": "sample",
                        "pros_src": [info[3]["code_snippet"] for info in infos],
                        "pros_emb": [
                            np.array([1.0, 0.0]),
                            np.array([0.999, 0.001]),
                            np.array([0.0, 1.0]),
                            np.array([0.001, 0.999]),
                        ],
                        "pros_info": infos,
                    }
                ]
            ).to_pickle(embeddings_path)

            counts = build_idiomine_cpp_candidate_artifacts(
                [embeddings_path],
                dataset_path,
                output_dir,
                embedding_model="synthetic-test-embedding",
            )
            manifest = json.loads(
                (output_dir / "baseline-manifest.json").read_text(encoding="utf-8")
            )

        self.assertEqual(counts, {"sample": 2})
        self.assertEqual(
            manifest["projects"][0]["candidate_group_counts"],
            {"if_statement": 2, "semantic_def_use": 2},
        )

    def test_independent_judgment_then_same_region_direct_synthesis(self):
        same_function = "1-0-30-1"
        candidate_specs = [
            (same_function, "4-2-6-3", "auto resource = acquire();"),
            (same_function, "7-2-9-3", "auto handle = acquire();"),
            (same_function, "20-2-22-3", "release(resource);"),
            (same_function, "23-2-25-3", "release(handle);"),
            ("40-0-50-1", "42-2-43-3", "return status;"),
            ("40-0-50-1", "45-2-46-3", "return result;"),
        ]
        embeddings = [
            np.array([1.0, 0.0, 0.0]),
            np.array([0.999, 0.001, 0.0]),
            np.array([0.0, 1.0, 0.0]),
            np.array([0.001, 0.999, 0.0]),
            np.array([0.0, 0.0, 1.0]),
            np.array([0.001, 0.0, 0.999]),
        ]
        responses = [
            {"is_idiom": True, "reason": "资源获取操作具有稳定意图。"},
            {"is_idiom": True, "reason": "资源释放操作具有稳定意图。"},
            {"is_idiom": False, "reason": "单独返回缺少可复用意图。"},
            {
                "can_synthesize": True,
                "synthesized_code": (
                    "auto resource = acquire();\nrelease(resource);"
                ),
                "intent": "在同一区域中成对获取并释放资源。",
                "reason": "",
                "source_ids": ["I00000", "I00001"],
            },
        ]
        client = _QueuedJsonClient(responses)

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            embeddings_path = root / "embeddings.pkl"
            dataset_path = root / "dataset.pkl"
            output_dir = root / "idiomine"
            checkpoint_path = root / "checkpoint.sqlite3"
            pd.DataFrame(
                [
                    {
                        "project": "sample",
                        "cppFile": ["src/sample.cpp"],
                        "func_ast": [[]],
                        "func_src": [[]],
                        "split": ["train"],
                    }
                ]
            ).to_pickle(dataset_path)
            pd.DataFrame(
                [
                    {
                        "pros_name": "sample",
                        "pros_src": [spec[2] for spec in candidate_specs],
                        "pros_emb": embeddings,
                        "pros_info": [
                            _source_info(
                                function_extent=function_extent,
                                candidate_extent=candidate_extent,
                                code=code,
                            )
                            for function_extent, candidate_extent, code in candidate_specs
                        ],
                    }
                ]
            ).to_pickle(embeddings_path)

            estimate = estimate_idiomine_cpp_run(
                [embeddings_path],
                dataset_path,
                embedding_model="synthetic-test-embedding",
                eps=0.01,
                min_samples=2,
            )
            counts = asyncio.run(
                run_idiomine_cpp_baseline(
                    [embeddings_path],
                    dataset_path,
                    output_dir,
                    embedding_model="synthetic-test-embedding",
                    eps=0.01,
                    min_samples=2,
                    model="fake-low",
                    token_budget=50_000,
                    max_output_tokens=256,
                    model_client=client,
                    checkpoint_path=checkpoint_path,
                )
            )
            with (output_dir / "sample_idiom.pkl").open("rb") as file:
                final_records = pickle.load(file)["accepted"]
            manifest = json.loads(
                (output_dir / "baseline-manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            audit = json.loads(
                (output_dir / "idiomine-decisions.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(estimate["judgment_call_count"], 3)
        self.assertEqual(estimate["synthesis_call_upper_bound"], 1)
        self.assertEqual(counts, {"sample": 3})
        self.assertEqual(client.calls, 4)
        self.assertEqual(
            [
                record["baseline_provenance"]["output_kind"]
                for record in final_records
            ],
            [
                "independent_judgment",
                "independent_judgment",
                "direct_synthesis",
            ],
        )
        synthesized = final_records[-1]
        self.assertTrue(
            synthesized["baseline_provenance"][
                "directly_accepted_after_synthesis"
            ]
        )
        self.assertFalse(
            synthesized["baseline_provenance"]["post_synthesis_judgment"]
        )
        self.assertEqual(synthesized["cnt"], 4)
        self.assertEqual(manifest["judgment_call_count"], 3)
        self.assertEqual(manifest["synthesis_call_count"], 1)
        self.assertEqual(manifest["endpoint_request_count"], 4)
        self.assertEqual(
            synthesized["baseline_provenance"]["synthesis_reason"],
            "在同一区域中成对获取并释放资源。",
        )
        self.assertEqual(manifest["technical_failure_count"], 0)
        self.assertEqual(manifest["dataset"], str(dataset_path))
        self.assertEqual(manifest["checkpoint"], str(checkpoint_path))
        self.assertEqual(
            manifest["candidate_generation"]["artifact_kind"],
            "internal_candidate_clusters",
        )
        self.assertEqual(
            manifest["parameters"]["embedding_model"],
            "synthetic-test-embedding",
        )
        self.assertEqual(manifest["projects"][0]["judgment_rejected_count"], 1)
        self.assertEqual(manifest["projects"][0]["synthesis_accepted_count"], 1)
        self.assertEqual(
            [
                item["is_idiom"]
                for item in audit["projects"][0]["judgment_decisions"]
            ],
            [True, True, False],
        )
        self.assertEqual(
            audit["projects"][0]["synthesis_decisions"][0]["status"],
            "completed_direct_acceptance",
        )

    def test_train_filter_and_resume_keep_technical_failure_out_of_decisions(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            dataset_path = root / "dataset.pkl"
            embeddings_path = root / "embeddings.pkl"
            output_dir = root / "idiomine"
            checkpoint_path = root / "checkpoint.sqlite3"
            pd.DataFrame(
                [
                    {
                        "project": "sample",
                        "cppFile": ["src/sample.cpp", "src/test.cpp"],
                        "func_ast": [[], []],
                        "func_src": [[], []],
                        "split": ["train", "test"],
                    }
                ]
            ).to_pickle(dataset_path)
            sources = ["train_a();", "train_b();", "test_a();", "test_b();"]
            pd.DataFrame(
                [
                    {
                        "pros_name": "sample",
                        "pros_src": sources,
                        "pros_emb": [
                            np.array([1.0, 0.0]),
                            np.array([0.999, 0.001]),
                            np.array([0.0, 1.0]),
                            np.array([0.001, 0.999]),
                        ],
                        "pros_info": [
                            _source_info(
                                function_extent=f"{index}-0-{index + 1}-1",
                                candidate_extent=f"{index}-0-{index}-1",
                                code=code,
                                source_path=(
                                    "src/sample.cpp" if index < 2 else "src/test.cpp"
                                ),
                            )
                            for index, code in enumerate(sources)
                        ],
                    }
                ]
            ).to_pickle(embeddings_path)

            failing_client = _FailingClient()
            with self.assertRaises(TimeoutError):
                asyncio.run(
                    run_idiomine_cpp_baseline(
                        [embeddings_path],
                        dataset_path,
                        output_dir,
                        embedding_model="synthetic-test-embedding",
                        eps=0.01,
                        min_samples=2,
                        model="fake-low",
                        token_budget=50_000,
                        max_output_tokens=256,
                        model_client=failing_client,
                        checkpoint_path=checkpoint_path,
                    )
                )

            resumed_client = _QueuedJsonClient(
                [{"is_idiom": True, "reason": "训练证据稳定重复。"}]
            )
            counts = asyncio.run(
                run_idiomine_cpp_baseline(
                    [embeddings_path],
                    dataset_path,
                    output_dir,
                    embedding_model="synthetic-test-embedding",
                    eps=0.01,
                    min_samples=2,
                    model="fake-low",
                    token_budget=50_000,
                    max_output_tokens=256,
                    model_client=resumed_client,
                    checkpoint_path=checkpoint_path,
                    resume=True,
                )
            )
            manifest = json.loads(
                (output_dir / "baseline-manifest.json").read_text(encoding="utf-8")
            )
            with (output_dir / "sample_idiom.pkl").open("rb") as file:
                records = pickle.load(file)["accepted"]

        self.assertEqual(counts, {"sample": 1})
        self.assertEqual(failing_client.calls, 1)
        self.assertEqual(resumed_client.calls, 1)
        self.assertEqual(manifest["endpoint_request_count"], 2)
        self.assertEqual(manifest["technical_failure_count"], 0)
        self.assertTrue(manifest["resumed"])
        self.assertEqual(
            manifest["projects"][0]["candidate_generation"][
                "selected_candidate_count"
            ],
            2,
        )
        self.assertTrue(
            all(info[1] == "src/sample.cpp" for info in records[0]["source_infos"])
        )


if __name__ == "__main__":
    unittest.main()
