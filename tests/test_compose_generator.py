from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from compose_generator import (
    discover_instance_specs,
    generate_compose_text,
    resolve_instance_config_path_by_user_name,
)


class ComposeGeneratorTests(unittest.TestCase):
    def _write_instance(self, root: Path, dir_name: str, *, user_name: str | None = None) -> Path:
        instance_dir = root / dir_name
        instance_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "user": {"name": user_name or dir_name},
            "sources": {"arxiv": {"enabled": True}},
            "llm": {"provider": "openai_compatible", "model": "gemini-3-flash", "base_url": "https://api.poe.com/v1"},
            "email": {"recipient": "user@example.com"},
            "output_dir": f"output/{dir_name}",
        }
        (instance_dir / "config.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (instance_dir / "interest_profile.json").write_text(
            json.dumps({"confirmed": True, "profile": {"core_topics": ["protein folding"], "synonyms": [], "must_have": [], "nice_to_have": [], "exclude": [], "summary": "ok"}}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return instance_dir

    def test_discover_instance_specs_reads_user_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "instances"
            self._write_instance(root, "alpha", user_name="bio-monitor")
            self._write_instance(root, "beta", user_name="chem-monitor")

            specs = discover_instance_specs(root)

        self.assertEqual([spec.user_name for spec in specs], ["bio-monitor", "chem-monitor"])
        self.assertEqual([spec.instance_dir_name for spec in specs], ["alpha", "beta"])

    def test_discover_instance_specs_rejects_duplicate_user_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "instances"
            self._write_instance(root, "alpha", user_name="duplicate")
            self._write_instance(root, "beta", user_name="duplicate")

            with self.assertRaises(ValueError) as exc:
                discover_instance_specs(root)

        self.assertIn("Duplicate user.name 'duplicate'", str(exc.exception))

    def test_discover_instance_specs_requires_interest_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "instances"
            instance_dir = self._write_instance(root, "alpha", user_name="alpha")
            (instance_dir / "interest_profile.json").unlink()

            with self.assertRaises(ValueError) as exc:
                discover_instance_specs(root)

        self.assertIn("Missing interest profile", str(exc.exception))

    def test_generate_compose_text_uses_user_name_for_service_and_container(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "instances"
            self._write_instance(root, "alpha", user_name="bio-monitor")
            specs = discover_instance_specs(root)

        compose_text = generate_compose_text(specs)
        self.assertIn("bio-monitor:", compose_text)
        self.assertIn("container_name: bio-monitor", compose_text)
        self.assertIn("./instances/alpha:/app/instance:ro", compose_text)

    def test_resolve_instance_config_path_by_user_name_returns_matching_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "instances"
            instance_dir = self._write_instance(root, "alpha", user_name="bio-monitor")

            path = resolve_instance_config_path_by_user_name("bio-monitor", root)

        self.assertEqual(path.resolve(), (instance_dir / "config.json").resolve())


if __name__ == "__main__":
    unittest.main()
