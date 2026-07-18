import unittest

from src.agents.idiom_judge_agent import patent_programming_pattern_valid
from src.agents.idiom_judgement import simplify_infos
from src.agents.idiom_synthesis import _aggregate_sources


class IdiomRuleTests(unittest.TestCase):
    def test_accepts_boundary_scores_in_either_order(self):
        self.assertTrue(patent_programming_pattern_valid(70, 50))
        self.assertTrue(patent_programming_pattern_valid(50, 70))

    def test_rejects_scores_below_either_boundary(self):
        self.assertFalse(patent_programming_pattern_valid(69.9, 69.9))
        self.assertFalse(patent_programming_pattern_valid(100, 49.9))

    def test_simplified_idiom_preserves_medoid_and_all_source_evidence(self):
        first = ["sample", "a.cpp", "1-0-3-1", {"ast_num": 2, "subtree_size": 5}]
        medoid = ["sample", "b.cpp", "4-0-8-1", {"ast_num": 4, "subtree_size": 9}]
        result = simplify_infos([first, medoid], representative_info=medoid)
        self.assertIs(result["info"], medoid)
        self.assertEqual(result["source_infos"], [first, medoid])
        self.assertEqual(result["cnt"], 2)
        self.assertEqual(result["avg_ast_num"], 3)
        self.assertEqual(result["avg_subtree_size"], 7)

    def test_synthesis_metadata_uses_weighted_averages(self):
        result = _aggregate_sources([
            {"info": ["p", "a.cpp", "1-0-1-1", {}], "cnt": 1,
             "avg_ast_num": 2, "avg_subtree_size": 5},
            {"info": ["p", "b.cpp", "2-0-2-1", {}], "cnt": 3,
             "avg_ast_num": 6, "avg_subtree_size": 9},
        ])
        self.assertEqual(result["cnt"], 4)
        self.assertEqual(result["avg_ast_num"], 5)
        self.assertEqual(result["avg_subtree_size"], 8)


if __name__ == "__main__":
    unittest.main()
