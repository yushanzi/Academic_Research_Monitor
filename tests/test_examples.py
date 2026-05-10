import os
import json
import re
import unittest

from compose_generator import discover_instance_specs, generate_compose_text
from config_schema import load_app_config


class ExampleConfigTests(unittest.TestCase):
    def test_single_template_file_is_used(self):
        self.assertTrue(os.path.exists("config.template.json"))
        self.assertFalse(os.path.exists("config.example.json"))

    def test_template_uses_expected_default_llms_and_sender(self):
        with open("config.template.json", "r", encoding="utf-8") as f:
            template = json.load(f)
        self.assertEqual(template["llm"]["provider"], "openai_compatible")
        self.assertEqual(template["llm"]["model"], "gemini-3-flash")
        self.assertEqual(template["llm"]["base_url"], "https://api.poe.com/v1")
        self.assertEqual(template["email"]["from"], "Academic Monitor <noreply@innoscreen.ai>")
        self.assertEqual(template["retention"]["days"], 30)
        self.assertEqual(template["abstract_selection"]["method"], "candidate_score")
        self.assertEqual(
            [judge["model"] for judge in template["abstract_selection"]["three_llm_voting"]["judges"]],
            ["gemini-3-flash", "gpt-4o", "claude-haiku-4.5"],
        )
        self.assertNotIn("topics", template)
        self.assertNotIn("interest_description", template)
        self.assertNotIn("must_have", template)
        self.assertNotIn("exclude", template)
        self.assertNotIn("relevance_scoring", template)

    def test_onboarding_interest_documents_exist(self):
        self.assertTrue(os.path.exists("instances/bio-monitor.txt"))
        self.assertTrue(os.path.exists("instances/chem-monitor.txt"))

    def test_runtime_instance_configs_load_if_present(self):
        specs = discover_instance_specs("instances")
        for spec in specs:
            with self.subTest(path=str(spec.config_path)):
                config = load_app_config(str(spec.config_path))
                self.assertEqual(config.user.name, spec.user_name)
                self.assertTrue(config.output_dir.startswith("output/"))
                self.assertEqual(config.abstract_selection.method, "candidate_score")
                self.assertTrue(os.path.exists(spec.interest_profile_path))

    def test_instance_interest_profile_summaries_default_to_english(self):
        specs = discover_instance_specs("instances")
        cjk_re = re.compile(r"[\u4e00-\u9fff]")
        for spec in specs:
            with self.subTest(path=str(spec.interest_profile_path)):
                with open(spec.interest_profile_path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                summary = payload["profile"]["summary"]
                self.assertFalse(cjk_re.search(summary), summary)

    def test_multi_instance_compose_uses_shared_output_root_and_both_configs(self):
        with open("docker-compose.multi-instance.yml", "r", encoding="utf-8") as f:
            compose_text = f.read()
        specs = discover_instance_specs("instances")
        for spec in specs:
            self.assertIn(f"./instances/{spec.instance_dir_name}:/app/instance:ro", compose_text)
            self.assertIn(f"{spec.user_name}:", compose_text)
            self.assertIn(f"container_name: {spec.user_name}", compose_text)
        self.assertEqual(compose_text.count("./output:/app/output"), len(specs))
        self.assertEqual(compose_text.count("CONFIG_PATH: /app/instance/config.json"), len(specs))
        self.assertNotIn("academic-monitor-", compose_text)

    def test_compose_file_matches_generated_instances(self):
        specs = discover_instance_specs("instances")
        generated = generate_compose_text(specs)
        with open("docker-compose.multi-instance.yml", "r", encoding="utf-8") as f:
            existing = f.read()
        self.assertEqual(existing, generated)

    def test_windows_run_script_mounts_shared_output_root(self):
        with open("scripts/run-monitor.ps1", "r", encoding="utf-8") as f:
            script_text = f.read()
        self.assertIn('Join-Path $repoRootAbs "output"', script_text)
        self.assertIn('-v "${outputRootAbs}:/app/output"', script_text)
        self.assertNotIn('-v "${outputAbs}:/app/output"', script_text)
        self.assertIn('Split-Path -Parent $configAbs', script_text)
        self.assertIn('-v "${instanceDirAbs}:/app/instance:ro"', script_text)
        self.assertIn('--name "$containerName"', script_text)
        self.assertIn('--entrypoint python', script_text)
        self.assertIn('"$Image" /app/run.py --config /app/instance/config.json', script_text)
