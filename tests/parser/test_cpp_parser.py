import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.parser.ast_parser import ASTParser
from src.parser.audit import audit_parser
from src.parser.candidates import QUALITY_PROFILE, select_candidates
from src.parser.cpp_adapter import CPP_ADAPTER
from src.parser.file_scanner import FileScanner
from src.parser.repo2data import parse_repository


class CppParserTests(unittest.TestCase):
    def test_cpp_adapter_masks_directives_without_changing_coordinates(self):
        source = (
            b"#define WRAP(value) \\\n"
            b"  call(value)\n"
            b"int kept() { return WRAP(1); }\n"
        )
        shadow, ranges = CPP_ADAPTER.mask_preprocessor(source)

        self.assertEqual(len(shadow), len(source))
        self.assertEqual(shadow.count(b"\n"), source.count(b"\n"))
        self.assertEqual(
            shadow.find(b"int kept()"),
            source.find(b"int kept()"),
        )
        self.assertEqual(len(ranges), 2)
        self.assertNotIn(b"#define", shadow)

    def test_parser_extracts_cpp_function_nodes(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source_path = Path(temporary_directory) / "sample.cpp"
            source_path.write_text(
                "int add(int left, int right) { return left + right; }\n",
                encoding="utf-8",
            )

            parser = ASTParser()
            tree = parser.parse_file(str(source_path))
            functions = parser.get_function_nodes(tree, str(source_path))

            self.assertTrue(functions)
            node_infos = []
            parser.traverse_ast(functions[0], str(source_path), node_infos)
            parser.calculate_ast_num(node_infos)
            self.assertEqual(node_infos[0]["kind"], "function_definition")
            self.assertEqual(node_infos[0]["subtree_size"], len(node_infos))
            self.assertIn("return left + right", node_infos[0]["code_snippet"])
            self.assertTrue(node_infos[0]["mapping_exact"])
            self.assertEqual(
                node_infos[0]["code_snippet"].encode("utf-8"),
                source_path.read_bytes()[
                    node_infos[0]["start_byte"] : node_infos[0]["end_byte"]
                ],
            )

    def test_scanner_keeps_cpp_and_filters_tests_and_other_languages(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory) / "sample"
            project.mkdir()
            (project / "main.cpp").write_text("int main() {}", encoding="utf-8")
            (project / "main_test.cpp").write_text("int test() {}", encoding="utf-8")
            (project / "module.py").write_text("pass", encoding="utf-8")

            scanner = FileScanner()
            files = scanner.get_all_source_files(temporary_directory)

            self.assertEqual(scanner.projects, ["sample"])
            self.assertEqual([Path(path).name for path in files[0]], ["main.cpp"])

    def test_scanner_uses_segment_rules_extensions_and_safe_paths(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project = root / "sample"
            (project / "src" / "contest").mkdir(parents=True)
            (project / "tests").mkdir()
            (project / "vendor").mkdir()
            (project / "generated").mkdir()
            (project / "build").mkdir()
            (project / "include").mkdir()
            (project / "src" / "contest" / "latest.cpp").write_text(
                "int latest() { return 1; }\n",
                encoding="utf-8",
            )
            (project / "include" / "public.hh").write_text(
                "inline int public_api() { return 2; }\n",
                encoding="utf-8",
            )
            (project / "src" / "compat.c").write_text(
                "int compat(void) { return 3; }\n",
                encoding="utf-8",
            )
            (project / "src" / "value_test.cpp").write_text(
                "int ignored_test() { return 0; }\n",
                encoding="utf-8",
            )
            (project / "tests" / "ignored.cpp").write_text(
                "int ignored_dir() { return 0; }\n",
                encoding="utf-8",
            )
            (project / "vendor" / "ignored.cpp").write_text(
                "int ignored_vendor() { return 0; }\n",
                encoding="utf-8",
            )
            (project / "generated" / "ignored.cpp").write_text(
                "int ignored_generated() { return 0; }\n",
                encoding="utf-8",
            )
            (project / "build" / "ignored.cpp").write_text(
                "int ignored_build() { return 0; }\n",
                encoding="utf-8",
            )
            outside = root / "outside.hh"
            outside.write_text("int outside() { return 0; }\n", encoding="utf-8")
            (project / "include" / "linked.hh").symlink_to(outside)

            scanner = FileScanner()
            files = scanner.get_all_source_files(str(root))
            relative = [
                Path(path)
                .resolve()
                .relative_to(project.resolve())
                .as_posix()
                for path in files[0]
            ]

            self.assertEqual(
                relative,
                ["include/public.hh", "src/compat.c", "src/contest/latest.cpp"],
            )
            summary = scanner.last_scan_diagnostics["summary"]
            self.assertGreaterEqual(summary["excluded_directory_count"], 4)
            self.assertEqual(summary["excluded_test_file_count"], 1)
            self.assertEqual(summary["excluded_symlink_count"], 1)

    def test_repository_uses_repo_relative_posix_ids_without_basename_loss(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project = root / "sample"
            (project / "include").mkdir(parents=True)
            (project / "src").mkdir()
            (project / "include" / "same.hh").write_text(
                "inline int header_value() { return 1; }\n",
                encoding="utf-8",
            )
            (project / "src" / "same.cpp").write_text(
                "int source_value() { return 2; }\n",
                encoding="utf-8",
            )
            output = root / "dataset.pkl"
            audit_output = root / "dataset.audit.json"

            parse_repository(
                str(root),
                str(output),
                str(audit_output),
            )

            data = pd.read_pickle(output)
            self.assertEqual(
                data.iloc[0]["cppFile"],
                ["include/same.hh", "src/same.cpp"],
            )
            source_paths = [
                function_ast[0]["source_path"]
                for file_functions in data.iloc[0]["func_ast"]
                for function_ast in file_functions
            ]
            self.assertEqual(
                source_paths,
                ["include/same.hh", "src/same.cpp"],
            )
            audit = json.loads(audit_output.read_text(encoding="utf-8"))
            self.assertEqual(audit["scan"]["summary"]["selected_file_count"], 2)
            self.assertEqual(
                [record["source_path"] for record in audit["files"]],
                ["include/same.hh", "src/same.cpp"],
            )

    def test_repository_can_select_exact_project_without_path_traversal(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for project_name in ("alpha", "beta"):
                project = root / project_name
                project.mkdir()
                (project / "main.cpp").write_text(
                    f"int {project_name}() {{ return 1; }}\n",
                    encoding="utf-8",
                )
            output = root / "alpha.pkl"
            audit_output = root / "alpha.audit.json"

            parse_repository(
                str(root),
                str(output),
                str(audit_output),
                projects=["alpha"],
            )

            data = pd.read_pickle(output)
            self.assertEqual(data["project"].tolist(), ["alpha"])
            audit = json.loads(audit_output.read_text(encoding="utf-8"))
            self.assertEqual(audit["projects"], ["alpha"])
            self.assertEqual(
                audit["scan"]["summary"]["selected_file_count"],
                1,
            )

            scanner = FileScanner()
            with self.assertRaises(ValueError):
                scanner.get_projects(str(root), ["../alpha"])

    def test_only_real_function_definitions_become_function_roots(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source_path = Path(temporary_directory) / "complex.cpp"
            source_path.write_text(
                """
template <typename T>
concept Addable = requires(T value) { value + value; };

class Example {
 public:
  int declaration(int value);
  int method(int value) {
    struct LocalVisitor {
      int operator()(int current) { return current + 1; }
    };
    auto lambda = [value](int offset) { return value + offset; };
    return LocalVisitor{}(lambda(1));
  }
};

template <Addable T>
T twice(T value) {
  return value + value;
}
""",
                encoding="utf-8",
            )

            parser = ASTParser()
            tree = parser.parse_file(str(source_path), temporary_directory)
            functions = parser.get_function_nodes(tree, str(source_path))

            self.assertEqual(len(functions), 3)
            self.assertTrue(all(node.type == "function_definition" for node in functions))
            snippets = [
                parser.get_code_snippet(node, str(source_path)) for node in functions
            ]
            self.assertTrue(any("method(int value)" in value for value in snippets))
            self.assertTrue(any("operator()(int current)" in value for value in snippets))
            self.assertTrue(any("T twice(T value)" in value for value in snippets))
            self.assertFalse(any("declaration(int value)" in value for value in snippets))

    def test_comments_strings_and_preprocessor_text_remain_verbatim(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source_path = Path(temporary_directory) / "mapping.cpp"
            source_path.write_text(
                """
#define IDENTITY(value) value
int mapped() {
  const char* url = "https://example.test/a//b";
  // 该注释属于原始片段，不能被重写。
  return IDENTITY(7);
}
""",
                encoding="utf-8",
            )

            parser = ASTParser()
            tree = parser.parse_file(str(source_path), temporary_directory)
            function = parser.get_function_nodes(tree, str(source_path))[0]
            node_infos = []
            parser.traverse_ast(function, str(source_path), node_infos)
            parser.calculate_ast_num(node_infos)

            root = node_infos[0]
            self.assertIn('"https://example.test/a//b"', root["code_snippet"])
            self.assertIn("// 该注释属于原始片段", root["code_snippet"])
            self.assertEqual(root["source_path"], "mapping.cpp")
            self.assertEqual(len(root["source_file_id"]), 64)
            self.assertEqual(root["mapping_version"], 2)

    def test_incomplete_code_is_recovered_and_auditable(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source_path = Path(temporary_directory) / "incomplete.cpp"
            source_path.write_text(
                "int incomplete(int value) { if (value) { return 1;\n",
                encoding="utf-8",
            )

            parser = ASTParser()
            tree = parser.parse_file(str(source_path), temporary_directory)
            functions = parser.get_function_nodes(tree, str(source_path))

            self.assertIsNotNone(tree)
            self.assertTrue(functions)
            raw = parser.last_file_diagnostics["raw"]
            self.assertGreater(raw["error_count"] + raw["missing_count"], 0)
            self.assertGreater(raw["uncovered_significant_byte_count"], 0)
            self.assertTrue(raw["uncovered_ranges"])

    def test_conditional_compilation_uses_position_preserving_recovery(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source_path = Path(temporary_directory) / "conditional.cpp"
            source_path.write_text(
                """
int conditional(int value) {
#if ENABLE_BRANCH
  if (value) {
#endif
  return value;
#if ENABLE_BRANCH
  }
#endif
}
""",
                encoding="utf-8",
            )

            parser = ASTParser()
            tree = parser.parse_file(str(source_path), temporary_directory)
            functions = parser.get_function_nodes(tree, str(source_path))

            self.assertEqual(len(functions), 1)
            recovery = parser.last_file_diagnostics["recovery"]
            self.assertTrue(recovery["used"])
            self.assertEqual(recovery["strategy"], "preprocessor-shadow-v1")
            self.assertGreater(parser.last_file_diagnostics["raw"]["missing_count"], 0)
            self.assertEqual(recovery["shadow"]["missing_count"], 0)

            node_infos = []
            parser.traverse_ast(functions[0], str(source_path), node_infos)
            parser.calculate_ast_num(node_infos)
            root = node_infos[0]
            self.assertEqual(root["parse_origin"], "preprocessor-shadow")
            self.assertIn("#if ENABLE_BRANCH", root["code_snippet"])
            self.assertEqual(
                root["code_snippet"].encode("utf-8"),
                source_path.read_bytes()[root["start_byte"] : root["end_byte"]],
            )

    def test_long_function_gets_def_use_semantic_core_with_exact_mapping(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source_path = Path(temporary_directory) / "semantic.cpp"
            padding = "\n".join(
                f"  // 用于构造长函数的审计注释 {index}" for index in range(45)
            )
            source_path.write_text(
                f"""
int load_value() {{
{padding}
  auto handle = open_resource();
  if (!handle) {{ return -1; }}
  auto value = read_value(handle);
  record(value);
  close_resource(handle);
  return value;
}}
""",
                encoding="utf-8",
            )

            parser = ASTParser()
            tree = parser.parse_file(str(source_path), temporary_directory)
            function = parser.get_function_nodes(tree, str(source_path))[0]
            node_infos = []
            parser.traverse_ast(function, str(source_path), node_infos)
            parser.calculate_ast_num(node_infos)

            semantic_slices = node_infos[0]["semantic_slices"]
            self.assertTrue(semantic_slices)
            core = next(
                value
                for value in semantic_slices
                if "handle" in value["dependency_summary"]["shared_symbols"]
            )
            self.assertIn("open_resource()", core["code_snippet"])
            self.assertIn("read_value(handle)", core["code_snippet"])
            self.assertIn("close_resource(handle)", core["code_snippet"])
            source = source_path.read_bytes()
            self.assertEqual(
                core["code_snippet"].encode("utf-8"),
                source[core["start_byte"] : core["end_byte"]],
            )

            selected = select_candidates(
                node_infos,
                profile=QUALITY_PROFILE,
                min_nodes=10,
                min_ast_num=5,
            )
            self.assertEqual(
                {"function", "region", "statement"},
                {candidate.level for candidate in selected},
            )
            self.assertTrue(
                any(candidate.origin == "semantic_def_use" for candidate in selected)
            )

    def test_quality_candidates_use_only_root_function_and_bound_statements(self):
        root = {
            "depth": 0,
            "extent": "1-0-120-1",
            "kind": "function_definition",
            "code_snippet": "void outer() {}",
            "ast_num": 3,
            "subtree_size": 20,
            "start_byte": 0,
            "end_byte": 6000,
            "mapping_version": 2,
            "mapping_exact": True,
            "source_path": "sample.cpp",
            "source_file_id": "f" * 64,
            "source_sha256": "a" * 64,
            "parse_origin": "raw",
            "parse_flags": 0,
        }
        nested = {
            "depth": 1,
            "extent": "2-0-3-1",
            "kind": "function_definition",
            "code_snippet": "void nested() {}",
            "ast_num": 2,
            "subtree_size": 2,
            "start_byte": 10,
            "end_byte": 30,
            "parse_flags": 0,
        }
        oversized_statement = {
            "depth": 1,
            "extent": "4-0-100-1",
            "kind": "expression_statement",
            "code_snippet": "\n".join("call();" for _ in range(81)),
            "ast_num": 5,
            "subtree_size": 17,
            "start_byte": 31,
            "end_byte": 5900,
            "parse_flags": 0,
        }
        leaves = [
            {
                "depth": 2,
                "extent": f"{101 + index}-0-{101 + index}-1",
                "kind": "identifier",
                "code_snippet": "x",
                "ast_num": 0,
                "subtree_size": 1,
                "start_byte": 5901 + index,
                "end_byte": 5902 + index,
                "parse_flags": 0,
            }
            for index in range(17)
        ]

        selected = select_candidates(
            [root, nested, oversized_statement, *leaves],
            profile=QUALITY_PROFILE,
            min_nodes=10,
        )

        self.assertEqual(
            [root["extent"]],
            [
                candidate.node_info["extent"]
                for candidate in selected
                if candidate.level == "function"
            ],
        )
        self.assertFalse(
            any(candidate.level == "statement" for candidate in selected)
        )

    def test_repository_keeps_four_column_schema_and_writes_file_audit(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project = root / "sample"
            project.mkdir()
            (project / "valid.cpp").write_text(
                "int valid() { return 1; }\n", encoding="utf-8"
            )
            (project / "header.h").write_text(
                "struct Header { int value; };\n", encoding="utf-8"
            )
            (project / "broken.cpp").write_text(
                "int broken() { return 1;\n", encoding="utf-8"
            )
            output = root / "dataset.pkl"
            audit_output = root / "dataset.audit.json"

            parse_repository(
                str(root),
                str(output),
                str(audit_output),
            )

            data = pd.read_pickle(output)
            self.assertEqual(
                list(data.columns),
                ["project", "cppFile", "func_ast", "func_src"],
            )
            audit = json.loads(audit_output.read_text(encoding="utf-8"))
            self.assertEqual(audit["summary"]["scanned_file_count"], 3)
            self.assertEqual(audit["summary"]["diagnostic_file_count"], 3)
            self.assertEqual(len(audit["files"]), 3)
            self.assertGreaterEqual(audit["summary"]["missing_count"], 1)

    def test_full_audit_is_reproducible_and_matches_v2_dataset(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project = root / "sample"
            project.mkdir()
            (project / "sample.cpp").write_text(
                """
int sample(int value) {
  int result = value + 1;
  if (result > 2) {
    result *= 2;
  }
  return result;
}
""",
                encoding="utf-8",
            )
            first = root / "first.pkl"
            second = root / "second.pkl"
            parse_repository(str(root), str(first))
            parse_repository(str(root), str(second))
            report_path = root / "audit.json"

            report = audit_parser(
                source_root=root,
                dataset_path=first,
                repeat_dataset_path=second,
                output_path=report_path,
                candidate_profile=QUALITY_PROFILE,
            )

            self.assertTrue(report["performance"]["byte_identical_repeat"])
            self.assertEqual(report["source_summary"]["scanned_file_count"], 1)
            self.assertEqual(report["source_summary"]["failed_file_count"], 0)
            self.assertEqual(report["mapping"]["verbatim_match_rate"], 1.0)
            self.assertEqual(
                report["candidates"]["function"]["exact_mapping_rate"],
                1.0,
            )
            self.assertEqual(
                json.loads(report_path.read_text(encoding="utf-8")),
                report,
            )


if __name__ == "__main__":
    unittest.main()
