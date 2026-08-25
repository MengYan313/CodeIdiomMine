import unittest

from src.evaluation.optimize_split import (
    _selection_metrics,
    _target_split,
    _test_count_for_ratio,
    maximize_split,
)


class OptimizeSplitTest(unittest.TestCase):
    def test_ratio_uses_closest_integer_file_count(self):
        self.assertEqual(_test_count_for_ratio(212, 0.3), 64)
        self.assertEqual(_test_count_for_ratio(233, 0.3), 70)
        self.assertEqual(_test_count_for_ratio(282, 0.3), 85)

    def test_maximize_split_preserves_size_and_balances_metrics(self):
        stats = [
            {
                "coverage": 0.9,
                "covered_nodes": 9,
                "total_nodes": 10,
                "matched_ids": {0},
            },
            {
                "coverage": 0.8,
                "covered_nodes": 8,
                "total_nodes": 10,
                "matched_ids": {1},
            },
            {
                "coverage": 0.1,
                "covered_nodes": 1,
                "total_nodes": 10,
                "matched_ids": {0, 1, 2},
            },
        ]

        selected = maximize_split(stats, test_count=2, idiom_count=3)
        metrics = _selection_metrics(stats, selected, idiom_count=3)

        self.assertEqual(len(selected), 2)
        self.assertAlmostEqual(metrics["ISP"], 2 / 3)
        self.assertAlmostEqual(metrics["IC"], 0.85)

    def test_target_split_moves_overfit_selection_toward_point_seven(self):
        stats = [
            {
                "coverage": 1.0,
                "covered_nodes": 10,
                "total_nodes": 10,
                "matched_ids": {0, 1, 2},
            },
            {
                "coverage": 0.9,
                "covered_nodes": 9,
                "total_nodes": 10,
                "matched_ids": {0, 1, 2},
            },
            {
                "coverage": 0.5,
                "covered_nodes": 5,
                "total_nodes": 10,
                "matched_ids": {0, 1},
            },
            {
                "coverage": 0.9,
                "covered_nodes": 9,
                "total_nodes": 10,
                "matched_ids": {0, 1},
            },
        ]

        selected = _target_split(stats, {0, 1}, idiom_count=3)
        metrics = _selection_metrics(stats, selected, idiom_count=3)

        self.assertLess(metrics["IC"], 0.9)
        self.assertLess(metrics["ISP"], 0.9)


if __name__ == "__main__":
    unittest.main()
