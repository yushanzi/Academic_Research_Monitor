import os
import tempfile
import unittest
from datetime import date

from retention import prune_output_artifacts, trim_log_file


class RetentionTests(unittest.TestCase):
    def test_prune_output_artifacts_removes_only_dated_runtime_files_older_than_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_files = [
                "academic_report_2026-04-01.html",
                "academic_report_2026-04-01.pdf",
                "run_stats_2026-04-01.json",
            ]
            keep_files = [
                "academic_report_2026-05-10.html",
                "academic_report_2026-05-10.pdf",
                "run_stats_2026-05-10.json",
                "interest_profile.json",
                ".run.lock",
                "custom_note.txt",
            ]
            for name in old_files + keep_files:
                with open(os.path.join(tmp, name), "w", encoding="utf-8") as f:
                    f.write(name)

            removed = prune_output_artifacts(tmp, today=date(2026, 5, 11), retention_days=30)

            self.assertEqual(
                sorted(os.path.basename(path) for path in removed),
                sorted(old_files),
            )
            for name in old_files:
                self.assertFalse(os.path.exists(os.path.join(tmp, name)))
            for name in keep_files:
                self.assertTrue(os.path.exists(os.path.join(tmp, name)))

    def test_prune_output_artifacts_keeps_boundary_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            keep_name = "run_stats_2026-04-12.json"
            with open(os.path.join(tmp, keep_name), "w", encoding="utf-8") as f:
                f.write("boundary")

            removed = prune_output_artifacts(tmp, today=date(2026, 5, 11), retention_days=30)

            self.assertEqual(removed, [])
            self.assertTrue(os.path.exists(os.path.join(tmp, keep_name)))

    def test_trim_log_file_keeps_recent_dated_blocks_and_preamble(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = os.path.join(tmp, "cron.log")
            with open(log_path, "w", encoding="utf-8") as f:
                f.write("startup line without date\n")
                f.write("2026-04-01 09:00:00 [INFO] old entry\n")
                f.write("Traceback continuation old\n")
                f.write("2026-05-10 08:00:00 [INFO] recent entry\n")
                f.write("recent continuation\n")

            changed = trim_log_file(log_path, today=date(2026, 5, 11), retention_days=30)

            self.assertTrue(changed)
            with open(log_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("startup line without date", content)
            self.assertNotIn("old entry", content)
            self.assertNotIn("Traceback continuation old", content)
            self.assertIn("recent entry", content)
            self.assertIn("recent continuation", content)

    def test_trim_log_file_is_noop_when_everything_is_within_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = os.path.join(tmp, "cron.log")
            with open(log_path, "w", encoding="utf-8") as f:
                f.write("2026-05-10 08:00:00 [INFO] recent entry\n")

            changed = trim_log_file(log_path, today=date(2026, 5, 11), retention_days=30)

            self.assertFalse(changed)
