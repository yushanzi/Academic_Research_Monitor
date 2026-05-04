import unittest

from json_utils import extract_json_object_text, parse_json_object


class JsonUtilsTests(unittest.TestCase):
    def test_extract_json_object_text_from_markdown_fence(self):
        raw = """```json
        {"key": "value"}
        ```"""

        self.assertEqual(extract_json_object_text(raw), '{"key": "value"}')

    def test_parse_json_object_ignores_prefix_and_suffix_text(self):
        raw = 'prefix {"key": "value", "n": 1} suffix'

        self.assertEqual(parse_json_object(raw), {"key": "value", "n": 1})
