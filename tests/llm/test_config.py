import os
import unittest
from unittest.mock import patch

from src.llm.client import LLMClient
from src.llm.config import LLMConfig, load_project_env


class LLMConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_project_env()

    def test_default_model_uses_low_tier(self):
        env = {
            "OPENAI_API_KEY": "test-key",
            "OPENAI_MODEL_LOW": "gpt-5.6-luna",
        }
        with patch.dict(os.environ, env, clear=True):
            config = LLMConfig()

        self.assertEqual(config.model, "gpt-5.6-luna")

    @patch("src.llm.client.OpenAIChatCompletionClient")
    def test_wrapper_supplies_gpt5_metadata(self, client_class):
        env = {
            "OPENAI_API_KEY": "test-key",
            "OPENAI_MODEL_LOW": "gpt-5.6-luna",
        }
        with patch.dict(os.environ, env, clear=True):
            LLMClient(LLMConfig())

        kwargs = client_class.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-5.6-luna")
        self.assertEqual(kwargs["model_info"]["family"], "gpt-5")


if __name__ == "__main__":
    unittest.main()
