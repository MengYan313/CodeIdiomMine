"""Offline contract tests for infrastructure shared by both repositories."""

import os
import unittest
from unittest.mock import patch

from src.agents.base import register_agent
from src.common.logging import AppLogger
from src.llm.client import create_model_client
from src.llm.config import LLMConfig, get_openai_model_info


class SharedConfigurationTests(unittest.TestCase):
    def test_model_tiers_and_modes(self):
        environment = {
            "OPENAI_API_KEY": "test-key",
            "OPENAI_MODEL_LOW": "low-test",
            "OPENAI_MODEL_MEDIUM": "medium-test",
            "OPENAI_MODEL_HIGH": "high-test",
        }
        with patch.dict(os.environ, environment, clear=True):
            self.assertEqual(LLMConfig.model_for_tier("low"), "low-test")
            self.assertEqual(LLMConfig.model_for_tier("medium"), "medium-test")
            self.assertEqual(LLMConfig.model_for_tier("high"), "high-test")
            self.assertFalse(LLMConfig.marker_mode().json_mode)
            self.assertTrue(LLMConfig.json_mode_config().json_mode)

    @patch("src.llm.client.OpenAIChatCompletionClient")
    def test_raw_client_uses_shared_metadata(self, client_class):
        environment = {
            "OPENAI_API_KEY": "test-key",
            "OPENAI_MODEL_LOW": "gpt-5.6-luna",
        }
        with patch.dict(os.environ, environment, clear=True):
            create_model_client()

        kwargs = client_class.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-5.6-luna")
        self.assertEqual(kwargs["model_info"]["family"], "gpt-5")
        self.assertIsNotNone(get_openai_model_info("gpt-5.6-luna"))

    def test_log_file_name_is_normalized(self):
        log_path = AppLogger.get_log_path("migration smoke")
        self.assertEqual(log_path.parent.name, "logs")
        self.assertEqual(log_path.name, "migration_smoke.log")


class SharedAgentRegistrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_registration_uses_factory_api(self):
        class FakeRuntime:
            def __init__(self):
                self.registration = None

            async def register_factory(self, agent_type, factory):
                self.registration = (agent_type, factory)

        runtime = FakeRuntime()
        factory = lambda: object()
        await register_agent(runtime, "ExampleAgent", factory)
        self.assertEqual(runtime.registration, ("ExampleAgent", factory))


if __name__ == "__main__":
    unittest.main()
