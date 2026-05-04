import json
import tempfile
import unittest

from config_schema import app_config_from_dict
from interest_profile import (
    _extract_json,
    build_profile_fingerprint,
    load_or_create_interest_profile,
    parse_interest_profile,
)


class InterestProfileTests(unittest.TestCase):
    def _config(self, tmp: str):
        return app_config_from_dict(
            {
                "user": {"name": "monitor_a"},
                "sources": {"arxiv": {"enabled": True}},
                "interest_description": "关注 protein folding 与 drug discovery",
                "topics": ["protein folding"],
                "llm": {"provider": "claude", "model": "fake-model"},
                "email": {"recipient": "user@example.com"},
                "output_dir": tmp,
            },
            config_path=f"{tmp}/config.json",
        )

    def test_parse_interest_profile(self):
        profile = parse_interest_profile(
            {
                "core_topics": ["protein folding"],
                "synonyms": ["folding"],
                "must_have": ["protein"],
                "nice_to_have": [],
                "exclude": ["review"],
                "summary": "关注蛋白折叠",
            }
        )
        self.assertEqual(profile.core_topics, ["protein folding"])
        self.assertEqual(profile.exclude, ["review"])

    def test_extract_json_reuses_shared_parser_behavior(self):
        raw = 'prefix {"summary": "关注蛋白折叠", "core_topics": [], "synonyms": [], "must_have": [], "nice_to_have": [], "exclude": []} suffix'
        parsed = _extract_json(raw)
        self.assertEqual(parsed["summary"], "关注蛋白折叠")

    def test_cache_is_reused_when_fingerprint_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._config(tmp)
            profile = load_or_create_interest_profile(config, provider=None)
            cache_path = f"{tmp}/interest_profile.json"
            with open(cache_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            self.assertEqual(payload["fingerprint"], build_profile_fingerprint(config))
            cached = load_or_create_interest_profile(config, provider=None)
            self.assertEqual(cached.summary, profile.summary)

    def test_fingerprint_changes_when_model_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_a = self._config(tmp)
            config_b = self._config(tmp)
            config_b.llm.model = "other-model"
            self.assertNotEqual(build_profile_fingerprint(config_a), build_profile_fingerprint(config_b))
