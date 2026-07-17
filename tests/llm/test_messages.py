import unittest

from src.llm.message import MessageBuilder, MessageRole


class MessageBuilderTests(unittest.TestCase):
    def test_builds_ordered_role_messages(self):
        builder = MessageBuilder()
        builder.add_system_message("system").add_user_message("user")

        self.assertEqual(
            builder.build(),
            [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "user"},
            ],
        )
        self.assertEqual(len(builder.get_messages_by_role(MessageRole.USER)), 1)


if __name__ == "__main__":
    unittest.main()
