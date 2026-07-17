import unittest

from src.common.node_kinds import BLOCK_KINDS, FUNCTION_KINDS, STATEMENT_KINDS


class NodeKindTests(unittest.TestCase):
    def test_cpp_node_kind_groups_are_nonempty_sets(self):
        for kinds in (FUNCTION_KINDS, BLOCK_KINDS, STATEMENT_KINDS):
            self.assertIsInstance(kinds, set)
            self.assertTrue(kinds)

    def test_expected_cpp_nodes_are_present(self):
        self.assertIn("function_definition", FUNCTION_KINDS)
        self.assertIn("if_statement", BLOCK_KINDS)
        self.assertIn("return_statement", STATEMENT_KINDS)


if __name__ == "__main__":
    unittest.main()
