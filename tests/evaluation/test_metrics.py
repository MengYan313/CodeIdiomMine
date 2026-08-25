import json
import pickle
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.evaluation.idiom_metrics import (
    _code_match,
    _parameterize_reference_code,
    _parse_extent,
    _restrict_idioms_to_reference_files,
    _structural_code_match,
    compute_f1,
    compute_haggis_stats,
    compute_idiom_library_stats,
    evaluate_project,
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

    def test_code_matching_only_explicitly_abstracts_names_and_literals(self):
        self.assertTrue(
            _code_match(
                "if (<VAR_1>) { return <LIT_1>; }",
                "void f() { if (ready) { return 2; } }",
            )
        )
        self.assertTrue(_code_match("return <VAR_1>;", "return value;"))
        self.assertFalse(_code_match("return other;", "return value;"))
        self.assertFalse(_code_match("return <VAR_1> + 1;", "return value - 2;"))
        self.assertTrue(_code_match("use(<VAR_1>, <VAR_1>);", "use(x, x);"))
        self.assertFalse(_code_match("use(<VAR_1>, <VAR_1>);", "use(x, y);"))

    def test_reference_parameterization_preserves_semantic_anchors(self):
        template = _parameterize_reference_code(
            "std::string path = load(config.value, 1);"
        )
        self.assertIn("std :: string", template)
        self.assertIn("load", template)
        self.assertIn(". value", template)
        self.assertIn("<VAR_1>", template)
        self.assertIn("<LIT_1>", template)
        self.assertNotIn("path", template)
        self.assertNotIn("config", template)

    def test_structural_match_allows_local_variation_but_preserves_api(self):
        reference = "if (ready) { value = load(input); use(value); }"
        expanded = (
            "if (available) { temp = load(source); "
            "log(temp); use(temp); }"
        )
        changed_api = "if (available) { temp = save(source); use(temp); }"
        self.assertTrue(_structural_code_match(reference, expanded))
        self.assertFalse(_structural_code_match(reference, changed_api))

    def test_reference_template_never_reads_measurement_sources(self):
        reference = _function_ast(1, "ready", 1)
        measurement = _function_ast(10, "ready", 2, operator="while")
        infos = [
            ["sample", "a.cpp", reference[0]["extent"], reference[1]],
            ["sample", "b.cpp", measurement[0]["extent"], measurement[1]],
        ]
        restricted = _restrict_idioms_to_reference_files(
            [{"center_point": "leaked", "source_infos": infos}],
            ["a.cpp", "b.cpp"],
            {0},
        )
        self.assertEqual(len(restricted), 1)
        patterns = restricted[0]["_evaluation_patterns"]
        self.assertEqual(len(patterns), 1)
        self.assertIn("if", patterns[0][1])
        self.assertNotIn("while", patterns[0][1])

    def test_f1_handles_zero_and_balanced_inputs(self):
        self.assertEqual(compute_f1(0.0, 0.0), 0.0)
        self.assertAlmostEqual(compute_f1(0.5, 0.5), 0.5)

    def test_haggis_metrics_use_test_file_macro_and_idiom_recurrence(self):
        train_ast = _function_ast(1, "source", 1)
        matched_ast = _function_ast(10, "ready", 2)
        matched_ast[1]["subtree_size"] = 6
        unmatched_ast = [{
            "depth": 0,
            "extent": "20-0-20-20",
            "kind": "function_definition",
            "code_snippet": "void empty() {}",
        }]
        data = pd.DataFrame([{
            "project": "sample",
            "cppFile": ["train.cpp", "matched.cpp", "empty.cpp"],
            "func_ast": [[train_ast], [matched_ast], [unmatched_ast]],
            "func_src": [[train_ast[0]["code_snippet"]],
                         [matched_ast[0]["code_snippet"]],
                         [unmatched_ast[0]["code_snippet"]]],
            "split": ["train", "test", "test"],
        }])
        info = ["sample", "train.cpp", train_ast[0]["extent"], train_ast[1]]
        stats = compute_haggis_stats(
            [{"center_point": train_ast[1]["code_snippet"],
              "info": info, "source_infos": [info]}],
            data,
            "sample",
            0,
            {1, 2},
        )

        self.assertAlmostEqual(stats["IC"], 3 / 7)
        self.assertAlmostEqual(stats["IC_micro"], 6 / 8)
        self.assertEqual(stats["ISP"], 1.0)
        self.assertAlmostEqual(stats["F1"], compute_f1(3 / 7, 1.0))

    def test_isp_counts_distinct_functions_in_the_same_file(self):
        first = _function_ast(1, "first_ready", 1)
        second = _function_ast(10, "second_ready", 2)
        unrelated = _function_ast(20, "unused", 3, operator="while")
        test_match = _function_ast(30, "test_ready", 4)
        files = ["same.cpp", "other.cpp", "test.cpp"]
        data = pd.DataFrame([{
            "project": "sample",
            "cppFile": files,
            "func_ast": [[first, second], [unrelated], [test_match]],
            "func_src": [[
                first[0]["code_snippet"],
                second[0]["code_snippet"],
            ], [unrelated[0]["code_snippet"]], [test_match[0]["code_snippet"]]],
            "split": ["train", "train", "test"],
        }])
        infos = [
            ["sample", files[0], first[0]["extent"], first[1]],
            ["sample", files[0], second[0]["extent"], second[1]],
        ]
        idiom = {
            "center_point": first[1]["code_snippet"],
            "info": infos[0],
            "source_infos": infos,
            "cnt": 2,
        }

        result = evaluate_project("sample", data, 0, [idiom])
        library = compute_idiom_library_stats(
            [idiom], data, "sample", 0
        )

        self.assertEqual(result["ISP"], 1.0)
        self.assertEqual(library["avg_cross_function_support"], 2)

    def test_isp_deduplicates_repeated_evidence_in_one_function(self):
        function = _function_ast(1, "ready", 1)
        test_ast = _function_ast(20, "unused", 3, operator="while")
        files = ["same.cpp", "other.cpp", "test.cpp"]
        data = pd.DataFrame([{
            "project": "sample",
            "cppFile": files,
            "func_ast": [[function], [_function_ast(10, "unused", 2)], [test_ast]],
            "func_src": [[function[0]["code_snippet"]], ["void unused() {}"],
                         [test_ast[0]["code_snippet"]]],
            "split": ["train", "train", "test"],
        }])
        info = ["sample", files[0], function[0]["extent"], function[1]]
        idiom = {
            "center_point": function[1]["code_snippet"],
            "info": info,
            "source_infos": [info, info],
            "cnt": 2,
        }

        result = evaluate_project("sample", data, 0, [idiom])
        library = compute_idiom_library_stats(
            [idiom], data, "sample", 0
        )

        self.assertEqual(result["ISP"], 0.0)
        self.assertEqual(library["avg_cross_function_support"], 1)

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
                "split": ["train", "test"],
            })
            infos = [[project, files[0], first_ast[0]["extent"], first_ast[1]]]
            idioms_by_project[project] = [{
                "center_point": first_ast[1]["code_snippet"],
                "info": infos[0],
                "source_infos": infos,
                "cnt": 2,
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
            )

        expected_ic = round(6 / 7, 4)
        self.assertEqual(result["repository_macro"]["IC_macro"], expected_ic)
        self.assertEqual(result["repository_macro"]["IC_micro"], expected_ic)
        self.assertEqual(result["repository_macro"]["IC_raw"], expected_ic)
        self.assertEqual(result["repository_macro"]["IC"], expected_ic)
        self.assertEqual(
            result["repository_macro"]["F1"],
            round(compute_f1(6 / 7, 1.0), 4),
        )
        self.assertEqual(result["global"]["idiom_type_count"], 2)
        self.assertEqual(result["global"]["total_cluster_instances"], 2)
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
                    "split": ["train", "test"],
                }
            ]
        )
        infos = [["sample", files[0], first_ast[0]["extent"], first_ast[1]]]
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
            )

        self.assertEqual(result["artifact_stage"], "synthesis")
        self.assertEqual(result["projects"][0]["project"], "sample")
        self.assertEqual(result["projects"][0]["idiom_type_count"], 1)

if __name__ == "__main__":
    unittest.main()
