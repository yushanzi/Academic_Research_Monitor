import os
import unittest

from config_schema import load_app_config


class ExampleConfigTests(unittest.TestCase):
    def test_multi_instance_example_configs_load(self):
        for path in ("configs/bio-monitor.json", "configs/chem-monitor.json"):
            with self.subTest(path=path):
                config = load_app_config(path)
                self.assertTrue(config.user.name)
                self.assertEqual(config.schedule.timezone, "UTC")
                self.assertTrue(config.output_dir)

    def test_multi_instance_compose_mentions_both_configs(self):
        with open("docker-compose.multi-instance.yml", "r", encoding="utf-8") as f:
            compose_text = f.read()
        self.assertIn("configs/bio-monitor.json", compose_text)
        self.assertIn("configs/chem-monitor.json", compose_text)
        self.assertIn("bio-monitor:", compose_text)
        self.assertIn("chem-monitor:", compose_text)
