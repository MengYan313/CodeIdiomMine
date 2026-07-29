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
from src.evaluation.idiomine_cpp import (
    PROMPT_VERSION,
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


def _source_info(
    *,
    function_extent: str,
    candidate_extent: str,
    code: str,
):
    return [
        "sample",
        "src/sample.cpp",
        function_extent,
        {
            "kind": "semantic_slice",
            "extent": candidate_extent,
            "code_snippet": code,
            "candidate_origin": "semantic_def_use",
            "analysis_version": "def-use-v1",
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
                "reason": "两个习语具有稳定的生命周期顺序关系。",
                "source_ids": ["I00000", "I00001"],
            },
        ]
        client = _QueuedJsonClient(responses)

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            embeddings_path = root / "embeddings.pkl"
            output_dir = root / "idiomine"
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
                embedding_model="synthetic-test-embedding",
                eps=0.01,
                min_samples=2,
            )
            counts = asyncio.run(
                run_idiomine_cpp_baseline(
                    [embeddings_path],
                    output_dir,
                    embedding_model="synthetic-test-embedding",
                    eps=0.01,
                    min_samples=2,
                    model="fake-low",
                    token_budget=50_000,
                    max_output_tokens=256,
                    model_client=client,
                )
            )
            with (output_dir / "sample_idiom.pkl").open("rb") as file:
                final_records = pickle.load(file)
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
        self.assertEqual(manifest["prompt_version"], PROMPT_VERSION)
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


if __name__ == "__main__":
    unittest.main()
