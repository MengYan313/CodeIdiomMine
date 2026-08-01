import asyncio
import os
import unittest
from unittest.mock import patch

from src.agents.base import dispatch_with_fallback
from src.llm.client import create_model_client
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

    def test_runtime_dispatch_failure_uses_explicit_fallback(self):
        async def fail():
            raise RuntimeError("route failed")

        result = asyncio.run(dispatch_with_fallback(fail(), "fallback"))
        self.assertEqual(result, "fallback")

    def test_runtime_dispatch_does_not_swallow_cancellation(self):
        async def cancel():
            raise asyncio.CancelledError

        with self.assertRaises(asyncio.CancelledError):
            asyncio.run(dispatch_with_fallback(cancel(), "fallback"))


if __name__ == "__main__":
    unittest.main()
