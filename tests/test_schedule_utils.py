import unittest

from schedule_utils import build_cron_with_jitter, format_schedule_display, parse_fixed_daily_cron


class ScheduleUtilsTests(unittest.TestCase):
    def test_parse_fixed_daily_cron(self):
        self.assertEqual(parse_fixed_daily_cron("0 8 * * *"), (8, 0))
        self.assertIsNone(parse_fixed_daily_cron("0 8 * * 1"))

    def test_build_cron_with_jitter_keeps_window_inside_same_day(self):
        effective_cron, jitter_window_seconds = build_cron_with_jitter("0 8 * * *", 60)
        self.assertEqual(effective_cron, "0 7 * * *")
        self.assertEqual(jitter_window_seconds, 7200)

    def test_build_cron_with_jitter_rejects_non_daily_cron(self):
        with self.assertRaises(ValueError):
            build_cron_with_jitter("0 8 * * 1", 60)

    def test_build_cron_with_jitter_rejects_cross_day_window(self):
        with self.assertRaises(ValueError):
            build_cron_with_jitter("15 0 * * *", 60)

    def test_format_schedule_display_for_non_daily_cron_with_jitter(self):
        result = format_schedule_display(
            {"cron": "0 8 * * 1", "timezone": "Asia/Hong_Kong", "random_jitter_minutes": 30}
        )
        self.assertEqual(result, "0 8 * * 1 (Asia/Hong_Kong, random +/- 30 min)")
