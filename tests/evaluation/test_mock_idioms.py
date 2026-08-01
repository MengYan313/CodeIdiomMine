import json
import pickle
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.evaluation.mock_idioms import build_mock_idioms


class MockIdiomBuilderTests(unittest.TestCase):
    def test_frozen_output_is_explicitly_marked_and_keeps_cluster_evidence(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            clusters_path = root / "clusters.pkl"
            manifest_path = root / "clusters.top100.json"
            output_dir = root / "results"
            info = [
                "sample",
                "sample.cpp",
                "1-0-3-1",
                {
                    "extent": "2-2-2-20",
                    "kind": "if_statement",
                    "code_snippet": "if (ok) { return; }",
                    "ast_num": 5,
                    "subtree_size": 8,
                },
            ]
            second_info = [
                "sample",
                "other.cpp",
                "10-0-12-1",
                {
                    "extent": "11-2-11-20",
                    "kind": "if_statement",
                    "code_snippet": "if (ready) { return; }",
                    "ast_num": 5,
                    "subtree_size": 10,
                },
            ]
            clusters = pd.DataFrame(
                [
                    {
                        "label": 7,
                        "center_point": "if (ok) { return; }",
                        "cluster_size": 2,
                        "center_point_info": info,
                        "infos": [info, second_info],
                        "loc_label": "sample-location",
                    },
                    {
                        "label": 9,
                        "center_point": "return false;",
                        "cluster_size": 1,
                        "center_point_info": info,
                        "infos": [info],
                        "loc_label": "excluded",
                    },
                ]
            )
            with clusters_path.open("wb") as file:
                pickle.dump([{"pros_name": "sample", "clusters": clusters}], file)
            manifest_path.write_text(
                json.dumps([{"project": "sample", "label": 7, "rank": 1}]),
                encoding="utf-8",
            )

            self.assertEqual(
                build_mock_idioms(clusters_path, output_dir, manifest_path),
                {"sample": 1},
            )
            with (output_dir / "sample_idiom.pkl").open("rb") as file:
                idioms = pickle.load(file)["accepted"]
            self.assertEqual(idioms[0]["source_infos"], [info, second_info])
            self.assertEqual(idioms[0]["avg_subtree_size"], 9)
            self.assertEqual(
                idioms[0]["mock_provenance"]["kind"],
                "frozen_cluster_selection_without_llm",
            )
            self.assertNotIn("rank", idioms[0]["mock_provenance"])


if __name__ == "__main__":
    unittest.main()
