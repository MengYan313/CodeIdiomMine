import tempfile
import unittest
from pathlib import Path

from src.parser.ast_parser import ASTParser
from src.parser.file_scanner import FileScanner


class CppParserTests(unittest.TestCase):
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
            self.assertIn("return left + right", node_infos[0]["code_snippet"])

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


if __name__ == "__main__":
    unittest.main()
