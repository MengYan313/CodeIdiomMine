import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.utils.export_artifacts import export_artifacts


class ArtifactExportTests(unittest.TestCase):
    def test_exports_minimal_dataset_summary_and_preview(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            inputs = root / "inputs"
            outputs = root / "outputs"
            inputs.mkdir()
            node_infos = [
                {
                    "depth": 0,
                    "extent": "1-0-1-25",
                    "kind": "function_definition",
                    "code_snippet": "int value() { return 1; }",
                    "ast_num": 1,
                }
            ]
            dataset = pd.DataFrame(
                [
                    {
                        "project": "sample",
                        "cppFile": ["sample.cpp"],
                        "func_ast": [[node_infos]],
                        "func_src": [["int value() { return 1; }"]],
                    }
                ]
            )
            dataset.to_pickle(inputs / "dataset.pkl")

            summaries = export_artifacts(
                input_dir=inputs,
                output_dir=outputs,
                stages=["dataset"],
                result_dir=root / "results",
                limit=10,
            )

            self.assertEqual(summaries["dataset"]["totals"]["functions"], 1)
            self.assertTrue((outputs / "dataset.summary.json").is_file())
            self.assertTrue((outputs / "dataset.preview.json").is_file())
            manifest = json.loads((outputs / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["stages"], ["dataset"])


if __name__ == "__main__":
    unittest.main()
