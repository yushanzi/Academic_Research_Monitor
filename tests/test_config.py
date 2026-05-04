import tempfile
import unittest

from config_schema import app_config_from_dict


class ConfigSchemaTests(unittest.TestCase):
    def test_defaults_are_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = app_config_from_dict(
                {
                    "user": {"name": "monitor_a"},
                    "sources": {"arxiv": {"enabled": True}},
                    "topics": ["protein folding"],
                    "llm": {"provider": "claude", "model": "fake-model"},
                    "email": {"recipient": "user@example.com"},
                },
                config_path=f"{tmp}/config.json",
            )
        self.assertEqual(config.schedule.cron, "0 8 * * *")
        self.assertEqual(config.schedule.timezone, "UTC")
        self.assertFalse(config.schedule.run_on_start)
        self.assertEqual(config.output_dir, "output/monitor_a")

    def test_invalid_timezone_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                app_config_from_dict(
                    {
                        "user": {"name": "monitor_a"},
                        "schedule": {"timezone": "Asia/Hong_Kong"},
                        "sources": {"arxiv": {"enabled": True}},
                        "topics": ["protein folding"],
                        "llm": {"provider": "claude", "model": "fake-model"},
                        "email": {"recipient": "user@example.com"},
                    },
                    config_path=f"{tmp}/config.json",
                )

    def test_authenticated_access_mode_fails_until_implemented(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError) as exc:
                app_config_from_dict(
                    {
                        "user": {"name": "monitor_a"},
                        "sources": {"arxiv": {"enabled": True}},
                        "topics": ["protein folding"],
                        "llm": {"provider": "claude", "model": "fake-model"},
                        "email": {"recipient": "user@example.com"},
                        "access": {"mode": "authenticated"},
                    },
                    config_path=f"{tmp}/config.json",
                )
        self.assertIn("not implemented yet", str(exc.exception))

    def test_unknown_top_level_field_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                app_config_from_dict(
                    {
                        "user": {"name": "monitor_a"},
                        "sources": {"arxiv": {"enabled": True}},
                        "topics": ["protein folding"],
                        "llm": {"provider": "claude", "model": "fake-model"},
                        "email": {"recipient": "user@example.com"},
                        "unexpected": True,
                    },
                    config_path=f"{tmp}/config.json",
                )
