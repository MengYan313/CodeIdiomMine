import os
import unittest
from unittest.mock import patch

from src.llm.config import (
    DEFAULT_MODEL_HIGH,
    DEFAULT_MODEL_LOW,
    DEFAULT_MODEL_MEDIUM,
    get_model_tiers,
    load_project_env,
    resolve_model,
)


class ModelConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_project_env()

    def test_defaults_match_gpt_56_tiers(self):
        with patch.dict(os.environ, {}, clear=True):
            tiers = get_model_tiers()

        self.assertEqual(tiers.low, DEFAULT_MODEL_LOW)
        self.assertEqual(tiers.medium, DEFAULT_MODEL_MEDIUM)
        self.assertEqual(tiers.high, DEFAULT_MODEL_HIGH)

    def test_environment_overrides_each_tier(self):
        overrides = {
            "OPENAI_MODEL_LOW": "low-test",
            "OPENAI_MODEL_MEDIUM": "medium-test",
            "OPENAI_MODEL_HIGH": "high-test",
        }
        with patch.dict(os.environ, overrides, clear=True):
            tiers = get_model_tiers()

        self.assertEqual((tiers.low, tiers.medium, tiers.high), tuple(overrides.values()))

    def test_resolve_model_uses_low_tier_unless_explicit(self):
        with patch.dict(os.environ, {"OPENAI_MODEL_LOW": "low-test"}, clear=True):
            self.assertEqual(resolve_model(), "low-test")
            self.assertEqual(resolve_model("explicit-test"), "explicit-test")


if __name__ == "__main__":
    unittest.main()
