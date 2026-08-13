import json
import pickle
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
            (inputs / "stage0").mkdir(parents=True)
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
            dataset.to_pickle(inputs / "stage0" / "dataset.pkl")

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

    def test_exports_semantic_judgment_artifact(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            inputs = root / "inputs"
            results = inputs / "stage3" / "sample"
            outputs = root / "outputs"
            results.mkdir(parents=True)
            info = [
                "sample",
                "sample.cpp",
                "1-0-1-10",
                {"kind": "expression_statement", "ast_num": 2},
            ]
            artifact = {
                "artifact_type": "idiom_judgment",
                "project": "sample",
                "accepted": [
                    {
                        "center_point": "release(value);",
                        "info": info,
                        "source_infos": [info, info],
                        "cnt": 2,
                        "avg_ast_num": 2.0,
                        "loc_label": "sample:sample.cpp:1",
                        "rules": {},
                        "abstraction_proposals": [],
                        "approved_abstraction_ids": [],
                        "abstraction_applied": False,
                        "semantic": {},
                        "semantic_review_input": {},
                        "smell": {},
                        "smell_gate": {},
                        "smell_review_input": {},
                        "agent_trace": {},
                        "scorecard": {},
                    }
                ],
                "rejected": [],
                "pending_llm": [],
            }
            with (results / "idiom-judgment.pkl").open("wb") as stream:
                pickle.dump(artifact, stream)

            summaries = export_artifacts(
                input_dir=inputs,
                output_dir=outputs,
                stages=["judgment"],
                result_dir=root / "results",
                limit=10,
            )

            self.assertEqual(summaries["judgment"]["totals"]["records"], 1)
            self.assertTrue((outputs / "judgment.preview.json").is_file())


if __name__ == "__main__":
    unittest.main()
