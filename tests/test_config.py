import tempfile
import unittest

from app_config.loader import resolve_output_dir_path
from config_schema import app_config_from_dict


def _base_config() -> dict:
    return {
        "user": {"name": "monitor_a"},
        "sources": {"arxiv": {"enabled": True}},
        "llm": {"provider": "claude", "model": "fake-model"},
        "email": {"recipient": "user@example.com"},
    }


class ConfigSchemaTests(unittest.TestCase):
    def test_defaults_are_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = app_config_from_dict(_base_config(), config_path=f"{tmp}/config.json")
        self.assertEqual(config.schedule.cron, "0 8 * * *")
        self.assertEqual(config.schedule.timezone, "Asia/Hong_Kong")
        self.assertFalse(config.schedule.run_on_start)
        self.assertEqual(config.output_dir, "output/monitor_a")
        self.assertTrue(config.email.send_empty_notification)
        self.assertEqual(config.retention.days, 30)
        self.assertEqual(config.abstract_selection.method, "candidate_score")
        self.assertEqual(config.abstract_selection.three_llm_voting.required_votes, 2)
        self.assertEqual(len(config.abstract_selection.three_llm_voting.judges), 3)
        self.assertIsNone(config.content_analysis.llm)
        self.assertEqual(config.candidate_scoring.threshold, 0.6)
        self.assertFalse(hasattr(config, "relevance_scoring"))

    def test_email_send_empty_notification_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = _base_config()
            payload["email"]["send_empty_notification"] = False
            config = app_config_from_dict(payload, config_path=f"{tmp}/config.json")
        self.assertFalse(config.email.send_empty_notification)

    def test_resolve_output_dir_path_uses_app_root_for_container_instance_mount(self):
        path = resolve_output_dir_path("output/bio-monitor", config_path="/app/instance/config.json")
        self.assertEqual(str(path), "/app/output/bio-monitor")

    def test_output_dir_must_not_resolve_under_instances_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = f"{tmp}/instances/bio-monitor/config.json"
            payload = _base_config()
            payload["output_dir"] = "instances/output/bio-monitor"
            with self.assertRaises(ValueError) as exc:
                app_config_from_dict(payload, config_path=config_path)
        self.assertIn("output_dir must resolve outside the instance definition tree", str(exc.exception))

    def test_absolute_output_dir_must_not_point_into_instances_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = f"{tmp}/instances/bio-monitor/config.json"
            payload = _base_config()
            payload["output_dir"] = f"{tmp}/instances/output/bio-monitor"
            with self.assertRaises(ValueError) as exc:
                app_config_from_dict(payload, config_path=config_path)
        self.assertIn("output_dir must resolve outside the instance definition tree", str(exc.exception))

    def test_query_expansion_constraints_and_scoring_parse(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = _base_config()
            payload["interest_profile_query"] = {
                "expand_synonyms": False,
                "max_query_synonyms": 5,
            }
            payload["retention"] = {"days": 14}
            payload["candidate_scoring"] = {
                "threshold": 0.5,
                "fail_open": True,
                "exclude_penalty_weight": 0.25,
                "weights": {
                    "topic_match": 0.35,
                    "must_have_match": 0.25,
                    "evidence_strength": 0.25,
                    "focus_specificity": 0.15,
                },
            }
            config = app_config_from_dict(payload, config_path=f"{tmp}/config.json")
        self.assertFalse(config.interest_profile_query.expand_synonyms)
        self.assertEqual(config.interest_profile_query.max_query_synonyms, 5)
        self.assertEqual(config.retention.days, 14)
        self.assertEqual(config.abstract_selection.method, "candidate_score")
        self.assertEqual(config.candidate_scoring.threshold, 0.5)
        self.assertTrue(config.candidate_scoring.fail_open)

    def test_invalid_retention_days_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = _base_config()
            payload["retention"] = {"days": 0}
            with self.assertRaises(ValueError) as exc:
                app_config_from_dict(payload, config_path=f"{tmp}/config.json")
        self.assertIn("retention.days must be a positive integer", str(exc.exception))

    def test_legacy_interest_fields_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = _base_config()
            payload["topics"] = ["protein folding"]
            payload["must_have"] = ["experimental validation"]
            with self.assertRaises(ValueError) as exc:
                app_config_from_dict(payload, config_path=f"{tmp}/config.json")
        self.assertIn("Interest fields must be stored in instances/<instance>/interest_profile.json", str(exc.exception))
        self.assertIn("topics", str(exc.exception))
        self.assertIn("must_have", str(exc.exception))

    def test_legacy_relevance_scoring_is_ignored_with_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = _base_config()
            payload["relevance_scoring"] = {
                "threshold": 0.7,
                "exclude_penalty_weight": 0.2,
                "weights": {
                    "topic_match": 0.30,
                    "must_have_match": 0.20,
                    "evidence_quality": 0.25,
                    "content_alignment": 0.15,
                    "actionability": 0.10,
                },
            }
            with self.assertLogs("app_config.loader", level="WARNING") as logs:
                config = app_config_from_dict(payload, config_path=f"{tmp}/config.json")
        self.assertIn("Ignoring deprecated config field 'relevance_scoring'", "\n".join(logs.output))
        self.assertFalse(hasattr(config, "relevance_scoring"))
        self.assertNotIn("relevance_scoring", config.to_dict())

    def test_abstract_selection_supports_candidate_score_override_and_future_judge_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = _base_config()
            payload["abstract_selection"] = {
                "method": "candidate_score",
                "three_llm_voting": {
                    "required_votes": 3,
                    "judges": [
                        {"name": "j1", "provider": "claude", "model": "m1"},
                        {"name": "j2", "provider": "claude", "model": "m2"},
                        {"name": "j3", "provider": "openai_compatible", "model": "m3"},
                        {"name": "j4", "provider": "claude", "model": "m4"},
                    ],
                },
            }
            config = app_config_from_dict(payload, config_path=f"{tmp}/config.json")
        self.assertEqual(config.abstract_selection.method, "candidate_score")
        self.assertEqual(config.abstract_selection.three_llm_voting.required_votes, 3)
        self.assertEqual(len(config.abstract_selection.three_llm_voting.judges), 4)

    def test_content_analysis_llm_override_parses(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = _base_config()
            payload["content_analysis"] = {
                "llm": {"provider": "openai_compatible", "model": "gpt-x", "base_url": "https://example.test/v1"}
            }
            config = app_config_from_dict(payload, config_path=f"{tmp}/config.json")
        self.assertEqual(config.content_analysis.llm.provider, "openai_compatible")
        self.assertEqual(config.content_analysis.llm.model, "gpt-x")

    def test_invalid_candidate_weights_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = _base_config()
            payload["candidate_scoring"] = {
                "weights": {
                    "topic_match": 0.5,
                    "must_have_match": 0.5,
                    "evidence_strength": 0.25,
                    "focus_specificity": 0.15,
                }
            }
            with self.assertRaises(ValueError):
                app_config_from_dict(payload, config_path=f"{tmp}/config.json")

    def test_invalid_timezone_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = _base_config()
            payload["schedule"] = {"timezone": "Europe/London"}
            with self.assertRaises(ValueError):
                app_config_from_dict(payload, config_path=f"{tmp}/config.json")

    def test_authenticated_access_mode_fails_until_implemented(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = _base_config()
            payload["access"] = {"mode": "authenticated"}
            with self.assertRaises(ValueError) as exc:
                app_config_from_dict(payload, config_path=f"{tmp}/config.json")
        self.assertIn("not implemented yet", str(exc.exception))

    def test_unknown_top_level_field_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = _base_config()
            payload["unexpected"] = True
            with self.assertRaises(ValueError):
                app_config_from_dict(payload, config_path=f"{tmp}/config.json")

    def test_interest_profile_confirmed_is_rejected_as_unknown_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload = _base_config()
            payload["interest_profile_confirmed"] = {"confirmed": True, "profile": {}}
            with self.assertRaises(ValueError) as exc:
                app_config_from_dict(payload, config_path=f"{tmp}/config.json")
        self.assertIn("Unknown top-level config field(s): interest_profile_confirmed", str(exc.exception))
