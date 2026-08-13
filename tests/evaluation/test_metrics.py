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
    _round_robin_file_folds,
    _structural_code_match,
    build_cluster_opportunity_domain,
    compute_avg_idiom_size,
    compute_coverage_stats,
    compute_f1,
    compute_idiom_set_precision,
    compute_idiom_library_stats,
    evaluate_project_kfold,
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


def _opportunity(data, project, project_idx, infos):
    return build_cluster_opportunity_domain(
        project,
        data,
        project_idx,
        infos,
    )


def _cluster_payload(project_infos):
    return [
        {
            "pros_name": project,
            "clusters": pd.DataFrame([{"label": 0, "infos": infos}]),
        }
        for project, infos in project_infos.items()
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

    def test_round_robin_folds_measure_every_file_once(self):
        folds = _round_robin_file_folds(
            "sample",
            ["e.cpp", "a.cpp", "d.cpp", "b.cpp", "c.cpp", "f.cpp"],
            5,
        )
        self.assertEqual(len(folds), 5)
        self.assertEqual(set.union(*folds), set(range(6)))
        self.assertEqual(sum(map(len, folds)), 6)

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
            "center_point": "if (<VAR_1>) { return <LIT_1>; }",
            "info": candidate_info,
            "source_infos": [candidate_info],
            "cnt": 1,
            "avg_ast_num": 5,
        }

        opportunity = _opportunity(
            data,
            "test",
            1,
            [["test", "test.cpp", test_ast[0]["extent"], test_ast[1]]],
        )
        coverage = compute_coverage_stats(
            [idiom], data, "test", 1, opportunity
        )
        self.assertEqual(coverage["IC_macro"], 1.0)
        self.assertEqual(coverage["IC_micro"], 1.0)
        self.assertEqual(coverage["IC"], 1.0)
        self.assertAlmostEqual(coverage["IC_all_macro"], 3 / 7)
        self.assertAlmostEqual(coverage["IC_all_micro"], 6 / 8)
        self.assertEqual(coverage["matched_idiom_indices"], {0})
        self.assertAlmostEqual(
            compute_idiom_set_precision([idiom], data.iloc[1]["func_src"][0]),
            1.0,
        )
        self.assertEqual(compute_avg_idiom_size([idiom], data, "train", 0), 10.0)

    def test_synthesized_sequence_maps_source_match_back_to_ast_nodes(self):
        source = "void f() {\n  first();\n  second();\n}"
        base = 100
        first_start = base + source.index("first")
        second_start = base + source.index("second")
        func_ast = [
            {
                "depth": 0,
                "extent": "1-0-4-1",
                "kind": "function_definition",
                "code_snippet": source,
                "start_byte": base,
                "end_byte": base + len(source),
            },
            {
                "depth": 1,
                "extent": "2-2-2-10",
                "kind": "expression_statement",
                "code_snippet": "first();",
                "start_byte": first_start,
                "end_byte": first_start + len("first();"),
            },
            {
                "depth": 1,
                "extent": "3-2-3-11",
                "kind": "expression_statement",
                "code_snippet": "second();",
                "start_byte": second_start,
                "end_byte": second_start + len("second();"),
            },
        ]
        info = [
            "sample",
            "sample.cpp",
            "1-0-4-1",
            {
                "kind": "synthesized_sequence",
                "code_snippet": "first();\nsecond();",
                "extent": "1-0-4-1",
                "subtree_size": 2,
            },
        ]
        data = pd.DataFrame([
            {
                "project": "sample",
                "cppFile": ["sample.cpp"],
                "func_ast": [[func_ast]],
                "func_src": [[source]],
            }
        ])
        cluster_infos = [
            ["sample", "sample.cpp", "1-0-4-1", func_ast[1]],
            ["sample", "sample.cpp", "1-0-4-1", func_ast[2]],
        ]
        coverage = compute_coverage_stats(
            [{"center_point": "first();\nsecond();", "source_infos": [info]}],
            data,
            "sample",
            0,
            _opportunity(data, "sample", 0, cluster_infos),
        )
        self.assertEqual(coverage["matched_idiom_indices"], {0})
        self.assertEqual(coverage["IC_macro"], 1.0)
        self.assertEqual(coverage["IC_micro"], 1.0)
        self.assertAlmostEqual(coverage["IC_all_macro"], 2 / 3)
        self.assertAlmostEqual(coverage["IC_all_micro"], 2 / 3)

    def test_support_and_generalization_isp_have_distinct_denominators(self):
        source_ast = _function_ast(1, "source_value", 1)
        repeat_ast = _function_ast(10, "other_value", 2)
        unrelated_ast = _function_ast(20, "unused", 3, operator="while")
        files = ["a.cpp", "b.cpp", "c.cpp"]
        data = pd.DataFrame([{
            "project": "sample",
            "cppFile": files,
            "func_ast": [[source_ast], [repeat_ast], [unrelated_ast]],
            "func_src": [[source_ast[0]["code_snippet"]],
                         [repeat_ast[0]["code_snippet"]],
                         [unrelated_ast[0]["code_snippet"]]],
        }])
        info = ["sample", files[0], source_ast[0]["extent"], source_ast[1]]
        opportunity = _opportunity(
            data,
            "sample",
            0,
            [
                info,
                ["sample", files[1], repeat_ast[0]["extent"], repeat_ast[1]],
                ["sample", files[2], unrelated_ast[0]["extent"], unrelated_ast[1]],
            ],
        )
        result = evaluate_project_kfold(
            "sample",
            data,
            0,
            [{"center_point": source_ast[1]["code_snippet"],
              "info": info, "source_infos": [info], "cnt": 1}],
            opportunity,
            fold_count=3,
        )
        self.assertEqual(result["ISP"], 0.0)
        self.assertEqual(result["ISP_generalization"], 1.0)
        self.assertEqual(result["ISP_fold"], 0.5)

    def test_isp_counts_distinct_functions_in_the_same_file(self):
        first = _function_ast(1, "first_ready", 1)
        second = _function_ast(10, "second_ready", 2)
        unrelated = _function_ast(20, "unused", 3, operator="while")
        files = ["same.cpp", "other.cpp"]
        data = pd.DataFrame([{
            "project": "sample",
            "cppFile": files,
            "func_ast": [[first, second], [unrelated]],
            "func_src": [[
                first[0]["code_snippet"],
                second[0]["code_snippet"],
            ], [unrelated[0]["code_snippet"]]],
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

        result = evaluate_project_kfold(
            "sample",
            data,
            0,
            [idiom],
            _opportunity(data, "sample", 0, infos),
            fold_count=2,
        )
        library = compute_idiom_library_stats(
            [idiom], data, "sample", 0
        )

        self.assertEqual(result["ISP"], 1.0)
        self.assertEqual(library["avg_cross_function_support"], 2)

    def test_isp_deduplicates_repeated_evidence_in_one_function(self):
        function = _function_ast(1, "ready", 1)
        files = ["same.cpp", "other.cpp"]
        data = pd.DataFrame([{
            "project": "sample",
            "cppFile": files,
            "func_ast": [[function], [_function_ast(10, "unused", 2)]],
            "func_src": [[function[0]["code_snippet"]], ["void unused() {}"]],
        }])
        info = ["sample", files[0], function[0]["extent"], function[1]]
        idiom = {
            "center_point": function[1]["code_snippet"],
            "info": info,
            "source_infos": [info, info],
            "cnt": 2,
        }

        result = evaluate_project_kfold(
            "sample",
            data,
            0,
            [idiom],
            _opportunity(data, "sample", 0, [info]),
            fold_count=2,
        )
        library = compute_idiom_library_stats(
            [idiom], data, "sample", 0
        )

        self.assertEqual(result["ISP"], 0.0)
        self.assertEqual(library["avg_cross_function_support"], 1)

    def test_opportunity_excludes_unclustered_functions_and_candidates(self):
        clustered = _function_ast(1, "value", 1)
        unclustered = _function_ast(10, "ready", 2)
        extra_candidate = {
            "depth": 1,
            "extent": "3-2-3-12",
            "kind": "expression_statement",
            "code_snippet": "extra();",
            "ast_num": 0,
        }
        clustered.insert(2, extra_candidate)
        data = pd.DataFrame([{
            "project": "sample",
            "cppFile": ["a.cpp", "b.cpp"],
            "func_ast": [[clustered], [unclustered]],
            "func_src": [[clustered[0]["code_snippet"]], [unclustered[0]["code_snippet"]]],
        }])
        info = ["sample", "a.cpp", clustered[0]["extent"], clustered[1]]

        opportunity = _opportunity(data, "sample", 0, [info])

        self.assertEqual(set(opportunity), {("a.cpp", clustered[0]["extent"])})
        self.assertNotIn(2, opportunity[("a.cpp", clustered[0]["extent"])])

    def test_rejected_cluster_member_function_remains_in_denominator(self):
        first = _function_ast(1, "value", 1)
        second = _function_ast(10, "ready", 2)
        files = ["a.cpp", "b.cpp"]
        data = pd.DataFrame([{
            "project": "sample",
            "cppFile": files,
            "func_ast": [[first], [second]],
            "func_src": [[first[0]["code_snippet"]], [second[0]["code_snippet"]]],
        }])
        infos = [
            ["sample", files[0], first[0]["extent"], first[1]],
            ["sample", files[1], second[0]["extent"], second[1]],
        ]
        idiom = {
            "center_point": first[1]["code_snippet"],
            "info": infos[0],
            "source_infos": [infos[0]],
            "cnt": 1,
        }
        coverage = compute_coverage_stats(
            [idiom],
            data,
            "sample",
            0,
            _opportunity(data, "sample", 0, infos),
            evidence_by_file={0: [(0, infos[0])]},
        )

        self.assertEqual(coverage["opportunity_function_count"], 2)
        self.assertAlmostEqual(coverage["IC_macro"], 0.5)
        self.assertAlmostEqual(coverage["IC_micro"], 0.5)
        self.assertEqual(coverage["IC"], coverage["IC_raw"])

    def test_overlapping_cluster_members_deduplicate_ast_nodes(self):
        function = _function_ast(1, "value", 1)
        data = pd.DataFrame([{
            "project": "sample",
            "cppFile": ["a.cpp"],
            "func_ast": [[function]],
            "func_src": [[function[0]["code_snippet"]]],
        }])
        infos = [
            ["sample", "a.cpp", function[0]["extent"], function[0]],
            ["sample", "a.cpp", function[0]["extent"], function[1]],
        ]

        opportunity = _opportunity(data, "sample", 0, infos)

        self.assertEqual(
            len(opportunity[("a.cpp", function[0]["extent"])]),
            len(function),
        )

    def test_opportunity_mapping_failure_has_no_broad_fallback(self):
        function = _function_ast(1, "value", 1)
        data = pd.DataFrame([{
            "project": "sample",
            "cppFile": ["a.cpp"],
            "func_ast": [[function]],
            "func_src": [[function[0]["code_snippet"]]],
        }])
        invalid_info = [
            "sample",
            "a.cpp",
            function[0]["extent"],
            {"kind": "if_statement", "extent": "99-0-99-1"},
        ]

        with self.assertRaisesRegex(ValueError, "无法精确映射 AST 节点"):
            _opportunity(data, "sample", 0, [invalid_info])

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

        coverage = compute_coverage_stats(
            [idiom],
            data,
            "sample",
            0,
            _opportunity(data, "sample", 0, [info]),
        )

        self.assertEqual(coverage["matched_idiom_indices"], {0})
        self.assertEqual(coverage["match_count"], 1)
        self.assertGreater(coverage["covered_node_count"], 0)
        self.assertGreater(coverage["IC"], 0)

    def test_repository_macro_and_global_summary_use_final_ic(self):
        rows = []
        idioms_by_project = {}
        cluster_infos_by_project = {}
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
            }]
            cluster_infos_by_project[project] = infos

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            idiom_dir = root / "idioms"
            idiom_dir.mkdir()
            dataset_path = root / "dataset.pkl"
            cluster_path = root / "clusters.pkl"
            pd.DataFrame(rows).to_pickle(dataset_path)
            with cluster_path.open("wb") as file:
                pickle.dump(_cluster_payload(cluster_infos_by_project), file)
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
                str(cluster_path),
                fold_count=2,
            )

        expected_ic = 1.0
        self.assertEqual(result["repository_macro"]["IC_macro"], expected_ic)
        self.assertEqual(result["repository_macro"]["IC_micro"], expected_ic)
        self.assertEqual(result["repository_macro"]["IC_raw"], expected_ic)
        self.assertEqual(result["repository_macro"]["IC"], expected_ic)
        self.assertEqual(result["repository_macro"]["F1"], 1.0)
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
            cluster_path = root / "clusters.pkl"
            data.to_pickle(dataset_path)
            with cluster_path.open("wb") as file:
                pickle.dump(_cluster_payload({"sample": infos}), file)
            with (idiom_dir / "idiom-synthesis.pkl").open("wb") as file:
                pickle.dump(artifact, file)
            result = evaluate_cpp(
                str(root / "idioms"),
                str(dataset_path),
                str(root / "eval.json"),
                str(cluster_path),
                artifact_stage="synthesis",
                fold_count=2,
            )

        self.assertEqual(result["artifact_stage"], "synthesis")
        self.assertEqual(result["projects"][0]["project"], "sample")
        self.assertEqual(result["projects"][0]["idiom_type_count"], 1)

    def test_existing_three_repository_artifacts_can_be_reevaluated(self):
        root = Path(__file__).resolve().parents[2]
        output_root = root / "outputs"
        result_root = root / "results" / "main"
        repositories = ("leveldb", "ninja", "tomlplusplus")
        paths = [
            (
                result_root / repository,
                output_root / repository / "stage0" / "dataset.pkl",
                output_root / repository / "stage2" / "clusters.pkl",
            )
            for repository in repositories
        ]
        if any(not path.exists() for triple in paths for path in triple):
            self.skipTest("本地三仓实验产物不完整")

        with tempfile.TemporaryDirectory() as temporary_directory:
            for repository, (idiom_dir, dataset_path, cluster_path) in zip(
                repositories, paths
            ):
                result = evaluate_cpp(
                    str(idiom_dir),
                    str(dataset_path),
                    str(Path(temporary_directory) / f"{repository}.json"),
                    str(cluster_path),
                    artifact_stage="synthesis",
                    fold_count=5,
                )
                project = result["projects"][0]
                self.assertEqual(project["IC"], project["IC_raw"])
                self.assertGreater(project["opportunity_function_count"], 0)
                self.assertGreater(project["opportunity_node_count"], 0)


if __name__ == "__main__":
    unittest.main()
