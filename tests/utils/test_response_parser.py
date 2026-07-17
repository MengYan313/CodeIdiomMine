import unittest

from src.utils.response_parser import extract_json, extract_tag_content


class ResponseParserTests(unittest.TestCase):
    def test_extracts_tagged_content(self):
        response = "[JSON]\n{\"score\": 90}\n[/JSON]"
        self.assertEqual(extract_tag_content(response, "JSON"), '{"score": 90}')

    def test_extracts_json_code_block(self):
        self.assertEqual(extract_json('```json\n{"ok": true}\n```'), {"ok": True})


if __name__ == "__main__":
    unittest.main()
