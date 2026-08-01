import json
import pickle
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.evaluation.idiom_metrics import (
    _code_match,
    _parse_extent,
    compute_avg_idiom_size,
    compute_coverage_stats,
    compute_f1,
    compute_idiom_set_precision,
    compute_idiom_library_stats,
    evaluate_mock_cluster_file_split,
    evaluate_cpp,
)


def _leaf(depth, extent, kind, code):
    return {
        "depth": depth,
        "extent": extent,
        "kind": kind,
        "code_snippet": code,
        "ast_num": 0,
    }


def _function_ast(prefix, condition_name, number, operator="if"):
    function_extent = f"{prefix}-0-{prefix + 2}-1"
    candidate_extent = f"{prefix + 1}-2-{prefix + 1}-30"
    candidate_code = f"{operator} ({condition_name}) {{ return {number}; }}"
    return [
        {
            "depth": 0,
            "extent": function_extent,
            "kind": "function_definition",
            "code_snippet": f"void sample() {{ {candidate_code} }}",
            "ast_num": 4,
            "subtree_size": 20,
        },
        {
            "depth": 1,
            "extent": candidate_extent,
            "kind": "if_statement",
            "code_snippet": candidate_code,
            "ast_num": 5,
            "subtree_size": 10,
        },
        _leaf(2, f"{prefix + 1}-2-{prefix + 1}-4", "if", operator),
        _leaf(2, f"{prefix + 1}-5-{prefix + 1}-15", "condition_clause", condition_name),
        _leaf(2, f"{prefix + 1}-16-{prefix + 1}-17", "{", "{"),
        _leaf(2, f"{prefix + 1}-18-{prefix + 1}-27", "return_statement", f"return {number};"),
        _leaf(2, f"{prefix + 1}-28-{prefix + 1}-29", "}", "}"),
    ]


class MetricHelperTests(unittest.TestCase):
    def test_extent_parsing(self):
        self.assertEqual(_parse_extent("1-2-3-4"), (1, 2, 3, 4))
        with self.assertRaises(ValueError):
            _parse_extent("1-2-3-4-trailing")

    def test_code_matching_abstracts_names_and_literals_but_preserves_structure(self):
        self.assertTrue(
            _code_match(
                "if (value) { return 1; }",
                "void f() { if (ready) { return 2; } }",
            )
        )
        self.assertTrue(_code_match("return other;", "return value;"))
        self.assertFalse(_code_match("return other + 1;", "return value - 2;"))

    def test_f1_handles_zero_and_balanced_inputs(self):
        self.assertEqual(compute_f1(0.0, 0.0), 0.0)
        self.assertAlmostEqual(compute_f1(0.5, 0.5), 0.5)

    def test_coverage_uses_candidate_extent(self):
        train_ast = _function_ast(1, "value", 1)
        test_ast = _function_ast(10, "ready", 2)
        unmatched_ast = [
            {
                "depth": 0,
                "extent": "20-0-20-20",
                "kind": "function_definition",
                "code_snippet": "void empty() {}",
                "ast_num": 2,
            }
        ]
        data = pd.DataFrame(
            [
                {
                    "project": "train",
                    "cppFile": ["train.cpp"],
                    "func_ast": [[train_ast]],
                    "func_src": [[train_ast[0]["code_snippet"]]],
                },
                {
                    "project": "test",
                    "cppFile": ["test.cpp"],
                    "func_ast": [[test_ast, unmatched_ast]],
                    "func_src": [[
                        test_ast[0]["code_snippet"],
                        unmatched_ast[0]["code_snippet"],
                    ]],
                },
            ]
        )
        candidate_info = ["train", "train.cpp", train_ast[0]["extent"], train_ast[1]]
        idiom = {
            "center_point": train_ast[1]["code_snippet"],
            "info": candidate_info,
            "source_infos": [candidate_info],
            "cnt": 1,
            "avg_ast_num": 5,
        }

        coverage = compute_coverage_stats([idiom], data, "test", 1)
        self.assertAlmostEqual(coverage["IC_macro"], 3 / 7)
        self.assertAlmostEqual(coverage["IC_micro"], 6 / 8)
        self.assertAlmostEqual(coverage["IC"], ((3 / 7) + (6 / 8)) / 2)
        self.assertEqual(coverage["matched_idiom_indices"], {0})
        self.assertAlmostEqual(
            compute_idiom_set_precision([idiom], data.iloc[1]["func_src"][0]),
            1.0,
        )
        self.assertEqual(compute_avg_idiom_size([idiom], data, "train", 0), 10.0)

    def test_mock_cluster_split_uses_candidate_evidence_not_function_root(self):
        first_ast = _function_ast(1, "value", 1)
        second_ast = _function_ast(10, "ready", 2)
        files = ["a.cpp", "b.cpp"]
        data = pd.DataFrame(
            [{
                "project": "sample",
                "cppFile": files,
                "func_ast": [[first_ast], [second_ast]],
                "func_src": [[first_ast[0]["code_snippet"]], [second_ast[0]["code_snippet"]]],
            }]
        )
        idiom = {
            "center_point": first_ast[1]["code_snippet"],
            "info": ["sample", files[0], first_ast[0]["extent"], first_ast[1]],
            "source_infos": [
                ["sample", files[0], first_ast[0]["extent"], first_ast[1]],
                ["sample", files[1], second_ast[0]["extent"], second_ast[1]],
            ],
            "mock_provenance": {
                "kind": "frozen_cluster_selection_without_llm"
            },
        }
        result = evaluate_mock_cluster_file_split(
            "sample", data, 0, [idiom], test_fraction=0.5
        )
        self.assertEqual(result["ISP"], 1.0)
        self.assertEqual(result["matched_idiom_count"], 1)
        self.assertAlmostEqual(result["IC"], round(6 / 7, 4))
        self.assertEqual(result["avg_idiom_size"], 10.0)
        library = compute_idiom_library_stats([idiom], data, "sample", 0)
        self.assertEqual(library["idiom_type_count"], 1)
        self.assertEqual(library["avg_cluster_size"], 2)
        self.assertEqual(library["avg_cross_file_support"], 2)
        self.assertEqual(library["AvgAST"], 10)

    def test_quality_semantic_slice_maps_back_to_ast_coverage(self):
        semantic_slice = {
            "depth": 1,
            "extent": "2-2-3-18",
            "kind": "semantic_slice",
            "code_snippet": "auto value = load();\nuse(value);",
            "ast_num": 2,
            "subtree_size": 6,
            "start_byte": 20,
            "end_byte": 60,
            "source_path": "sample.cpp",
            "source_file_id": "sample.cpp",
            "mapping_exact": True,
            "parse_origin": "raw",
            "candidate_level": "region",
            "candidate_origin": "semantic_def_use",
            "parse_flags": 0,
        }
        function_ast = [
            {
                "depth": 0,
                "extent": "1-0-5-1",
                "kind": "function_definition",
                "code_snippet": "void sample() { auto value = load(); use(value); }",
                "ast_num": 3,
                "subtree_size": 10,
                "start_byte": 0,
                "end_byte": 80,
                "mapping_exact": True,
                "source_path": "sample.cpp",
                "source_file_id": "sample.cpp",
                "parse_origin": "raw",
                "parse_flags": 0,
                "semantic_slices": [semantic_slice],
            },
            {
                "depth": 1,
                "extent": "1-14-5-1",
                "kind": "compound_statement",
                "code_snippet": "{ auto value = load(); use(value); }",
                "ast_num": 2,
                "subtree_size": 9,
                "start_byte": 14,
                "end_byte": 80,
                "parse_flags": 0,
            },
        ]
        for index in range(8):
            function_ast.append(
                {
                    "depth": 2,
                    "extent": f"{2 + index // 4}-{index}-{2 + index // 4}-{index + 1}",
                    "kind": "identifier",
                    "code_snippet": "value",
                    "ast_num": 0,
                    "subtree_size": 1,
                    "start_byte": 20 + index * 4,
                    "end_byte": 23 + index * 4,
                    "parse_flags": 0,
                }
            )
        data = pd.DataFrame(
            [{
                "project": "sample",
                "cppFile": ["sample.cpp"],
                "func_ast": [[function_ast]],
                "func_src": [[function_ast[0]["code_snippet"]]],
            }]
        )
        info = [
            "sample",
            "sample.cpp",
            function_ast[0]["extent"],
            semantic_slice,
        ]
        idiom = {
            "center_point": semantic_slice["code_snippet"],
            "info": info,
            "source_infos": [info],
            "cnt": 1,
        }

        coverage = compute_coverage_stats([idiom], data, "sample", 0)

        self.assertEqual(coverage["matched_idiom_indices"], {0})
        self.assertEqual(coverage["match_count"], 1)
        self.assertGreater(coverage["matched_node_count"], 0)
        self.assertGreater(coverage["IC"], 0)

    def test_repository_macro_and_global_summary_use_final_ic(self):
        rows = []
        idioms_by_project = {}
        for offset, project in ((1, "first"), (30, "second")):
            first_ast = _function_ast(offset, "value", 1)
            second_ast = _function_ast(offset + 10, "ready", 2)
            files = [f"{project}-a.cpp", f"{project}-b.cpp"]
            rows.append({
                "project": project,
                "cppFile": files,
                "func_ast": [[first_ast], [second_ast]],
                "func_src": [[first_ast[0]["code_snippet"]], [second_ast[0]["code_snippet"]]],
            })
            infos = [
                [project, files[0], first_ast[0]["extent"], first_ast[1]],
                [project, files[1], second_ast[0]["extent"], second_ast[1]],
            ]
            idioms_by_project[project] = [{
                "center_point": first_ast[1]["code_snippet"],
                "info": infos[0],
                "source_infos": infos,
                "cnt": 2,
                "mock_provenance": {
                    "kind": "frozen_cluster_selection_without_llm"
                },
            }]

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            idiom_dir = root / "idioms"
            idiom_dir.mkdir()
            dataset_path = root / "dataset.pkl"
            pd.DataFrame(rows).to_pickle(dataset_path)
            for project, idioms in idioms_by_project.items():
                with (idiom_dir / f"{project}_idiom.pkl").open("wb") as file:
                    pickle.dump(
                        {
                            "artifact_type": "idiom_judgment",
                            "project": project,
                            "accepted": idioms,
                        },
                        file,
                    )
            result = evaluate_cpp(
                str(idiom_dir),
                str(dataset_path),
                str(root / "eval.json"),
                evaluation_mode="mock_cluster_file_split",
                test_fraction=0.5,
            )

        expected_ic = round(6 / 7, 4)
        self.assertEqual(result["repository_macro"]["IC_macro"], expected_ic)
        self.assertEqual(result["repository_macro"]["IC_micro"], expected_ic)
        self.assertEqual(result["repository_macro"]["IC"], expected_ic)
        self.assertEqual(
            result["repository_macro"]["F1"],
            round(compute_f1(6 / 7, 1.0), 4),
        )
        self.assertEqual(result["global"]["idiom_type_count"], 2)
        self.assertEqual(result["global"]["total_cluster_instances"], 4)
        self.assertNotIn('"rank"', json.dumps(result))

    def test_evaluator_reads_recursive_synthesis_artifact(self):
        first_ast = _function_ast(1, "value", 1)
        second_ast = _function_ast(10, "ready", 2)
        files = ["sample-a.cpp", "sample-b.cpp"]
        data = pd.DataFrame(
            [
                {
                    "project": "sample",
                    "cppFile": files,
                    "func_ast": [[first_ast], [second_ast]],
                    "func_src": [
                        [first_ast[0]["code_snippet"]],
                        [second_ast[0]["code_snippet"]],
                    ],
                }
            ]
        )
        infos = [
            ["sample", files[0], first_ast[0]["extent"], first_ast[1]],
            ["sample", files[1], second_ast[0]["extent"], second_ast[1]],
        ]
        artifact = {
            "artifact_type": "idiom_synthesis",
            "project": "sample",
            "accepted": [
                {
                    "center_point": first_ast[1]["code_snippet"],
                    "info": infos[0],
                    "source_infos": infos,
                    "cnt": 2,
                }
            ],
            "rejected": [],
        }

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            idiom_dir = root / "idioms" / "sample"
            idiom_dir.mkdir(parents=True)
            dataset_path = root / "dataset.pkl"
            data.to_pickle(dataset_path)
            with (idiom_dir / "idiom-synthesis.pkl").open("wb") as file:
                pickle.dump(artifact, file)
            result = evaluate_cpp(
                str(root / "idioms"),
                str(dataset_path),
                str(root / "eval.json"),
                artifact_stage="synthesis",
                test_fraction=0.5,
            )

        self.assertEqual(result["artifact_stage"], "synthesis")
        self.assertEqual(result["projects"][0]["project"], "sample")
        self.assertEqual(result["projects"][0]["idiom_type_count"], 1)


if __name__ == "__main__":
    unittest.main()
