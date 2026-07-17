"""代码习语 Agent 的中文提示词与 JSON schema 契约。"""

import unittest

from src.agents import code_assembly_agent
from src.agents import idiom_judge_agent
from src.agents import planning_synthesis_agent
from src.agents import semantic_clarity_agent
from src.agents import syntax_logic_agent


class PromptContractTests(unittest.TestCase):
    MODULES = (
        code_assembly_agent,
        idiom_judge_agent,
        planning_synthesis_agent,
        semantic_clarity_agent,
        syntax_logic_agent,
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


if __name__ == "__main__":
    unittest.main()
