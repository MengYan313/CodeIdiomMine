import unittest

from src.evaluation.idiom_metrics import _code_match, _parse_extent, compute_f1


class MetricHelperTests(unittest.TestCase):
    def test_extent_parsing(self):
        self.assertEqual(_parse_extent("1-2-3-4"), (1, 2, 3, 4))
        with self.assertRaises(ValueError):
            _parse_extent("invalid")

    def test_code_matching_normalizes_whitespace(self):
        self.assertTrue(_code_match("return value;", "if (ok) {\n  return   value;\n}"))
        self.assertFalse(_code_match("return other;", "return value;"))

    def test_f1_handles_zero_and_balanced_inputs(self):
        self.assertEqual(compute_f1(0.0, 0.0), 0.0)
        self.assertAlmostEqual(compute_f1(0.5, 0.5), 0.5)


if __name__ == "__main__":
    unittest.main()
