import unittest

from src.agents.idiom_judge_agent import patent_programming_pattern_valid


class IdiomRuleTests(unittest.TestCase):
    def test_accepts_boundary_scores_in_either_order(self):
        self.assertTrue(patent_programming_pattern_valid(70, 50))
        self.assertTrue(patent_programming_pattern_valid(50, 70))

    def test_rejects_scores_below_either_boundary(self):
        self.assertFalse(patent_programming_pattern_valid(69.9, 69.9))
        self.assertFalse(patent_programming_pattern_valid(100, 49.9))


if __name__ == "__main__":
    unittest.main()
