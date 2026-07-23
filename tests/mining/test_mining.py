import tempfile
import unittest
from pathlib import Path

import pandas as pd
import torch

from src.mining.clustering import ClusteringProcessor
from src.mining.code_embedding import (
    get_fragment_src_and_embedding,
    get_pros_src_and_embedding,
    is_within_extent,
    parse_extent,
)
from src.parser.fragment_builder import prepare_fragment_data
from src.parser.token_budget import TokenBudget
from src.parser.token_length_audit import summarize_token_lengths
from src.parser.candidates import LEGACY_PROFILE, QUALITY_PROFILE
from src.parser.repo2data import parse_repository


class _FakeEmbedder:
    def get_embeddings(self, snippets, batch_size=8):
        del batch_size
        return [
            torch.tensor([[float(index), float(len(snippet))]])
            for index, snippet in enumerate(snippets)
        ]


class _WhitespaceTokenizer:
    def __call__(
        self,
        snippets,
        *,
        add_special_tokens,
        truncation,
        padding,
    ):
        del padding
        if not add_special_tokens or truncation:
            raise AssertionError("测试 tokenizer 必须包含特殊 token 且不得截断")
        return {
            "input_ids": [
                [0, *range(2, len(snippet.split()) + 2), 1]
                for snippet in snippets
            ]
        }


class _BudgetFakeEmbedder(_FakeEmbedder):
    model_name = "fake-tokenizer"

    def __init__(self, max_input_tokens):
        self.max_input_tokens = max_input_tokens
        self.token_budget = TokenBudget(
            _WhitespaceTokenizer(),
            self.model_name,
            max_input_tokens,
        )

    def get_token_count(self, snippet):
        return self.token_budget.count(snippet)

    def fits_token_budget(self, snippet_or_node):
        if isinstance(snippet_or_node, str):
            snippet = snippet_or_node
        else:
            snippet = str(snippet_or_node.get("code_snippet") or "")
        return bool(snippet) and self.get_token_count(snippet) <= self.max_input_tokens


class MiningHelperTests(unittest.TestCase):
    def test_extent_helpers(self):
        self.assertEqual(parse_extent("1-0-4-1"), (1, 0, 4, 1))
        self.assertTrue(is_within_extent("1-0-4-1", "2-2-3-4"))
        self.assertFalse(is_within_extent("2-2-3-4", "1-0-4-1"))

    def test_dbscan_preserves_cluster_schema(self):
        embeddings = [
            torch.tensor([[1.0, 0.0]]),
            torch.tensor([[0.9, 0.1]]),
            torch.tensor([[0.0, 1.0]]),
        ]
        sources = ["return first;", "return medoid;", "return third;"]
        infos = [
            ["sample", "sample.cpp", "1-0-1-13", {}],
            ["sample", "sample.cpp", "2-0-2-14", {}],
            ["sample", "sample.cpp", "3-0-3-13", {}],
        ]

        labels, clusters = ClusteringProcessor.perform_dbscan_clustering(
            "sample",
            sources,
            embeddings,
            infos,
            eps=1.0,
            min_samples=2,
        )

        self.assertEqual(labels.tolist(), [0, 0, 0])
        self.assertEqual(len(clusters), 1)
        self.assertEqual(int(clusters.iloc[0]["cluster_size"]), 3)
        self.assertEqual(clusters.iloc[0]["center_point"], "return medoid;")
        self.assertEqual(
            clusters.columns.tolist(),
            [
                "label",
                "center_point",
                "else_point",
                "cluster_size",
                "center_point_info",
                "infos",
                "loc_label",
            ],
        )

    def test_embedding_profiles_preserve_mapping_and_semantic_candidates(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project = root / "sample"
            project.mkdir()
            padding = "\n".join(
                f"  // 长函数审计填充 {index}" for index in range(35)
            )
            (project / "sample.cpp").write_text(
                f"""
int sample() {{
{padding}
  auto handle = open_resource();
  auto value = read_value(handle);
  record(value);
  close_resource(handle);
  return value;
}}
""",
                encoding="utf-8",
            )
            dataset_path = root / "dataset.pkl"
            parse_repository(str(root), str(dataset_path))
            data = pd.read_pickle(dataset_path)

            quality = get_pros_src_and_embedding(
                data,
                _FakeEmbedder(),
                min_project_size=1,
                candidate_profile=QUALITY_PROFILE,
            )
            quality_infos = quality[3][0]
            self.assertTrue(
                any(info[3]["kind"] == "semantic_slice" for info in quality_infos)
            )
            self.assertTrue(
                all(
                    info[3].get("source_file_id")
                    and info[3].get("start_byte") is not None
                    and info[3].get("end_byte") is not None
                    for info in quality_infos
                )
            )

            legacy = get_pros_src_and_embedding(
                data,
                _FakeEmbedder(),
                min_nodes=1,
                min_ast_num=1,
                min_project_size=1,
                candidate_profile=LEGACY_PROFILE,
            )
            self.assertTrue(legacy[3][0])
            self.assertFalse(
                any(info[3]["kind"] == "semantic_slice" for info in legacy[3][0])
            )

    def test_token_budget_counts_special_tokens_and_rejects_overflow(self):
        budget = TokenBudget(
            _WhitespaceTokenizer(),
            "fake-tokenizer",
            max_input_tokens=5,
        )

        self.assertEqual(budget.count("one two three"), 5)
        self.assertTrue(budget.fits("one two three"))
        self.assertFalse(budget.fits("one two three four"))
        with self.assertRaisesRegex(ValueError, "拒绝静默截断"):
            budget.validate(["one two three four"])
        summary = summarize_token_lengths([2, 5, 7], token_budget=5)
        self.assertEqual(summary["over_budget_count"], 1)
        self.assertEqual(summary["max"], 7)

    def test_overlong_function_degrades_to_traceable_smaller_candidates(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project = root / "sample"
            project.mkdir()
            padding = "\n".join(
                f"  int padding_{index} = {index};" for index in range(35)
            )
            (project / "long.cpp").write_text(
                f"""
int load_value() {{
{padding}
  auto handle = open_resource();
  auto value = read_value(handle);
  record(value);
  close_resource(handle);
  return value;
}}
""",
                encoding="utf-8",
            )
            dataset_path = root / "dataset.pkl"
            parse_repository(str(root), str(dataset_path))
            data = pd.read_pickle(dataset_path)

            embedder = _BudgetFakeEmbedder(max_input_tokens=40)
            with self.assertRaisesRegex(ValueError, "必须先由"):
                get_pros_src_and_embedding(
                    data,
                    embedder,
                    min_project_size=1,
                    candidate_profile=QUALITY_PROFILE,
                )
            fragments = prepare_fragment_data(
                data,
                embedder.token_budget,
                candidate_profile=QUALITY_PROFILE,
            )
            result = get_fragment_src_and_embedding(
                fragments,
                embedder,
                min_project_size=1,
                candidate_profile=QUALITY_PROFILE,
            )
            infos = result[3][0]

            self.assertTrue(infos)
            self.assertFalse(
                any(info[3]["kind"] == "function_definition" for info in infos)
            )
            self.assertTrue(
                any(
                    info[3]["length_control"].get("degraded_from")
                    == "function"
                    for info in infos
                )
            )
            self.assertTrue(
                all(
                    info[3]["length_control"]["decision_stage"] == "parser"
                    for info in infos
                )
            )
            self.assertTrue(fragments.iloc[0]["fragment_rejections"])
            self.assertTrue(
                all(
                    info[3]["length_control"]["token_count"] <= 40
                    and info[3]["length_control"]["within_budget"]
                    for info in infos
                )
            )


if __name__ == "__main__":
    unittest.main()
