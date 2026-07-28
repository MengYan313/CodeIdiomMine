"""代码习语 Agent 的中文提示词与 JSON schema 契约。"""

import unittest

from src.idiom_synthesis import assembly_agent
from src.idiom_synthesis import planning_agent as synthesis_planning_agent
from src.idiom_synthesis import review_agent
from src.idiom_judgment import semantic_review_agent
from src.idiom_judgment import smell_review_agent


class PromptContractTests(unittest.TestCase):
    MODULES = (
        semantic_review_agent,
        smell_review_agent,
        synthesis_planning_agent,
        assembly_agent,
        review_agent,
    )

    def test_system_prompts_are_chinese_and_marker_free(self):
        for module in self.MODULES:
            prompt = module._SYSTEM_MESSAGE
            self.assertRegex(prompt, r"[\u4e00-\u9fff]")
            for section in ("# 角色", "# 目标", "# 成功标准", "# 约束", "# 输出"):
                self.assertIn(section, prompt)
            for forbidden in ("[JSON]", "[/JSON]", "[Code Idiom]", "You are ", "Please "):
                self.assertNotIn(forbidden, prompt)

    def test_each_agent_declares_a_complete_object_schema(self):
        for module in self.MODULES:
            schema = module._RESPONSE_SCHEMA
            self.assertEqual(schema["type"], "object")
            self.assertFalse(schema["additionalProperties"])
            self.assertEqual(
                set(schema["required"]),
                set(schema["properties"]),
            )

    def test_validity_agents_require_reasons_and_type_classification(self):
        for module in (
            semantic_review_agent,
            smell_review_agent,
            synthesis_planning_agent,
            assembly_agent,
            review_agent,
        ):
            self.assertIn("reason", module._RESPONSE_SCHEMA["required"])
        for module in (semantic_review_agent, review_agent):
            self.assertIn("is_idiom", module._RESPONSE_SCHEMA["required"])
            self.assertIn(
                "idiom_classification",
                module._RESPONSE_SCHEMA["required"],
            )
            prompt = module._SYSTEM_MESSAGE
            self.assertIn("repository_specific", prompt)
            self.assertIn("raii", prompt)


if __name__ == "__main__":
    unittest.main()
