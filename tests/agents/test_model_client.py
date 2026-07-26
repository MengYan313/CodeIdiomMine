import os
import unittest
from unittest.mock import patch

from src.agents._base import create_model_client
from src.llm.config import load_project_env


class AgentModelClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_project_env()

    @patch("src.llm.client.OpenAIChatCompletionClient")
    def test_default_client_uses_low_model_with_gpt5_metadata(self, client_class):
        env = {
            "OPENAI_API_KEY": "test-key",
            "OPENAI_BASE_URL": "https://example.invalid/v1",
            "OPENAI_MODEL_LOW": "gpt-5.6-luna",
        }
        with patch.dict(os.environ, env, clear=True):
            create_model_client()

        kwargs = client_class.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-5.6-luna")
        self.assertEqual(kwargs["model_info"]["family"], "gpt-5")


if __name__ == "__main__":
    unittest.main()
