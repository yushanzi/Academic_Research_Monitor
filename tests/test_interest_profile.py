import json
import tempfile
import unittest
from pathlib import Path

from config_schema import app_config_from_dict
from interest_profile import (
    _extract_json,
    build_simple_interest_profile,
    build_interest_profile_payload,
    build_profile_fingerprint,
    load_or_create_interest_profile,
    parse_interest_profile,
    select_query_synonyms,
    write_interest_profile,
)
from models import InterestProfile


class InterestProfileTests(unittest.TestCase):
    def _config(self, tmp: str):
        instance_dir = Path(tmp) / "instance"
        instance_dir.mkdir(parents=True, exist_ok=True)
        return app_config_from_dict(
            {
                "user": {"name": "monitor_a"},
                "sources": {"arxiv": {"enabled": True}},
                "llm": {"provider": "openai_compatible", "model": "gemini-3-flash", "base_url": "https://api.poe.com/v1"},
                "email": {"recipient": "user@example.com"},
                "output_dir": tmp,
            },
            config_path=str(instance_dir / "config.json"),
        ), instance_dir

    def test_parse_interest_profile(self):
        profile = parse_interest_profile(
            {
                "core_topics": ["protein folding"],
                "synonyms": ["folding"],
                "must_have": ["protein"],
                "nice_to_have": [],
                "exclude": ["review"],
                "summary": "Track protein folding.",
            }
        )
        self.assertEqual(profile.core_topics, ["protein folding"])
        self.assertEqual(profile.exclude, ["review"])

    def test_extract_json_reuses_shared_parser_behavior(self):
        raw = 'prefix {"summary": "Track protein folding.", "core_topics": [], "synonyms": [], "must_have": [], "nice_to_have": [], "exclude": []} suffix'
        parsed = _extract_json(raw)
        self.assertEqual(parsed["summary"], "Track protein folding.")

    def test_build_profile_fingerprint_changes_when_profile_changes(self):
        profile_a = InterestProfile(core_topics=["protein folding"], summary="A")
        profile_b = InterestProfile(core_topics=["drug discovery"], summary="B")
        self.assertNotEqual(build_profile_fingerprint(profile_a), build_profile_fingerprint(profile_b))

    def test_load_requires_profile_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            config, instance_dir = self._config(tmp)
            with self.assertRaises(RuntimeError) as exc:
                load_or_create_interest_profile(config, config_path=str(instance_dir / "config.json"))
        self.assertIn("Missing required interest profile file", str(exc.exception))

    def test_load_requires_confirmed_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            config, instance_dir = self._config(tmp)
            profile_path = instance_dir / "interest_profile.json"
            write_interest_profile(
                profile_path,
                build_interest_profile_payload(InterestProfile(core_topics=["protein folding"], summary="Track protein folding."), confirmed=False),
            )
            with self.assertRaises(RuntimeError) as exc:
                load_or_create_interest_profile(config, config_path=str(instance_dir / "config.json"))
        self.assertIn("not confirmed", str(exc.exception))

    def test_load_reads_confirmed_profile_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            config, instance_dir = self._config(tmp)
            profile_path = instance_dir / "interest_profile.json"
            write_interest_profile(
                profile_path,
                build_interest_profile_payload(
                    InterestProfile(
                        core_topics=["confirmed core topic"],
                        synonyms=["confirmed synonym"],
                        must_have=["confirmed must have"],
                        exclude=["confirmed exclude"],
                        summary="User-confirmed research interest profile.",
                    )
                ),
            )

            profile = load_or_create_interest_profile(config, config_path=str(instance_dir / "config.json"))

        self.assertEqual(profile.core_topics, ["confirmed core topic"])
        self.assertEqual(profile.must_have, ["confirmed must have"])
        self.assertEqual(profile.exclude, ["confirmed exclude"])

    def test_profile_payload_contains_versions_and_profile(self):
        payload = build_interest_profile_payload(InterestProfile(core_topics=["protein folding"], summary="Track protein folding."))
        self.assertTrue(payload["confirmed"])
        self.assertIn("versions", payload)
        self.assertEqual(payload["profile"]["core_topics"], ["protein folding"])
        self.assertEqual(payload["versions"]["prompt_version"], "interest-profile-v4")

    def test_build_simple_interest_profile_uses_english_summary(self):
        profile = build_simple_interest_profile(
            interest_description="Focus on protein design.",
            topics=["protein design", "de novo design"],
            must_have=["experimental validation"],
            exclude=["review article"],
        )
        self.assertEqual(
            profile.summary,
            "Focus on protein design.; Focus topics: protein design, de novo design",
        )

    def test_select_query_synonyms_keeps_specific_phrases_only(self):
        profile = InterestProfile(
            core_topics=["protein structure prediction"],
            synonyms=[
                "protein folding",
                "folding",
                "structure modeling",
                "protein structure prediction",
            ],
        )

        selected = select_query_synonyms(profile, existing_topics=["protein design"], limit=3)

        self.assertEqual(selected, ["protein folding", "structure modeling"])

    def test_select_query_synonyms_respects_limit(self):
        profile = InterestProfile(
            core_topics=["protein structure prediction"],
            synonyms=[
                "protein folding",
                "structure modeling",
                "computational protein design",
            ],
        )

        selected = select_query_synonyms(profile, limit=2)

        self.assertEqual(selected, ["protein folding", "structure modeling"])


if __name__ == "__main__":
    unittest.main()
