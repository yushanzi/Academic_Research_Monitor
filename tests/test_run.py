import io
import unittest
from contextlib import contextmanager, redirect_stdout
from unittest.mock import MagicMock, patch

import run
from config_schema import app_config_from_dict
from models import AccessInfo, InterestProfile, RelevanceResult
from sources.base import build_paper


@contextmanager
def unlocked(*args, **kwargs):
    yield


class RunModuleTests(unittest.TestCase):
    def test_get_enabled_sources_passes_supported_kwargs_and_ignores_unknown(self):
        class FakeSource:
            def __init__(self, journals=None):
                self.journals = journals

        config = {
            "sources": {
                "fake": {
                    "enabled": True,
                    "journals": ["a", "b"],
                    "unexpected": "ignored",
                }
            }
        }

        with patch.dict(run.ALL_SOURCES, {"fake": ("fake.module", "FakeSource")}, clear=True):
            with patch.object(run, "get_source_class", return_value=FakeSource):
                with self.assertLogs("main", level="WARNING") as logs:
                    instances = run.get_enabled_sources(config)

        self.assertEqual(len(instances), 1)
        self.assertEqual(instances[0].journals, ["a", "b"])
        self.assertTrue(any("unsupported config key 'unexpected'" in msg for msg in logs.output))

    def test_main_dry_run_executes_pipeline_without_email(self):
        fake_source = MagicMock()
        fake_source.name = "FakeSource"
        fake_source.fetch_papers.return_value = [
            build_paper(
                title="Paper 1",
                authors=["Author A"],
                abstract="This paper studies protein folding dynamics in detail.",
                date="2026-03-23",
                url="https://example.com/p1",
                source="FakeSource",
                doi="10.1000/test1",
            )
        ]

        config = app_config_from_dict(
            {
                "user": {"name": "monitor_a"},
                "schedule": {"cron": "0 8 * * *", "timezone": "UTC", "run_on_start": False},
                "sources": {"fake": {"enabled": True}},
                "topics": ["protein folding dynamics"],
                "interest_description": "关注 protein folding dynamics",
                "time_range_hours": 24,
                "output_dir": "output/test-run",
                "llm": {"provider": "claude", "model": "fake-model"},
                "email": {"recipient": "test@example.com"},
                "access": {"mode": "open_access", "auth_profile": None},
            }
        )

        fake_provider = object()
        analyzed_paper = fake_source.fetch_papers.return_value[0]
        analyzed_paper.relevance = {
            "is_relevant": True,
            "relevance_score": 0.9,
            "matched_aspects": ["protein folding dynamics"],
            "reason": "高度相关",
        }
        analyzed_paper.analysis = {
            "research_direction": "方向",
            "innovation_points": ["创新"],
            "summary": "总结",
        }
        analyzed_papers = [analyzed_paper]
        trend_summary = {"trends": "趋势", "suggestions": ["建议"]}

        with patch("sys.argv", ["run.py", "--config", "configs/bio-monitor.json", "--dry-run"]):
            with patch.object(run, "load_app_config", return_value=config):
                with patch.object(run, "run_lock", return_value=unlocked()):
                    with patch.object(run, "get_enabled_sources", return_value=[fake_source]):
                        with patch.object(run, "get_provider", return_value=fake_provider):
                            with patch.object(run, "load_or_create_interest_profile", return_value=InterestProfile(core_topics=["protein folding dynamics"], must_have=["protein folding dynamics"], summary="关注蛋白折叠")):
                                with patch.object(run, "get_access_provider") as get_access_provider:
                                    get_access_provider.return_value.resolve.side_effect = lambda paper: AccessInfo(
                                        entry_url=paper.url,
                                        download_url="",
                                        landing_page_url=paper.url,
                                        full_text_available=False,
                                        full_text="",
                                        open_access=False,
                                        effective_access_mode="abstract_only",
                                        evidence_level="abstract_only",
                                    )
                                    with patch.object(run, "judge_relevance", return_value=RelevanceResult(True, 0.9, ["protein folding dynamics"], "高度相关")):
                                        with patch.object(run, "analyze_papers", return_value=analyzed_papers):
                                            with patch.object(run, "generate_trend_summary", return_value=trend_summary):
                                                fake_generate_report = MagicMock(return_value="output/report.pdf")
                                                with patch.object(run, "generate_report", fake_generate_report):
                                                    stdout = io.StringIO()
                                                    with redirect_stdout(stdout):
                                                        run.main()

        fake_source.fetch_papers.assert_called_once()
        fake_generate_report.assert_called_once()

    def test_main_no_candidates_sends_empty_notification(self):
        fake_source = MagicMock()
        fake_source.name = "FakeSource"
        fake_source.fetch_papers.return_value = []

        config = app_config_from_dict(
            {
                "user": {"name": "monitor_a"},
                "schedule": {"cron": "0 8 * * *", "timezone": "UTC", "run_on_start": False},
                "sources": {"fake": {"enabled": True}},
                "topics": ["protein folding dynamics"],
                "interest_description": "关注 protein folding dynamics",
                "time_range_hours": 24,
                "output_dir": "output/test-run",
                "llm": {"provider": "claude", "model": "fake-model"},
                "email": {"recipient": "test@example.com"},
                "access": {"mode": "open_access", "auth_profile": None},
            }
        )

        with patch("sys.argv", ["run.py", "--config", "configs/bio-monitor.json"]):
            with patch.object(run, "load_app_config", return_value=config):
                with patch.object(run, "run_lock", return_value=unlocked()):
                    with patch.object(run, "get_provider", return_value=object()):
                        with patch.object(run, "load_or_create_interest_profile", return_value=InterestProfile(core_topics=["protein folding dynamics"], summary="关注蛋白折叠")):
                            with patch.object(run, "get_enabled_sources", return_value=[fake_source]):
                                fake_send_empty_notification = MagicMock()
                                with patch.object(run, "send_empty_notification", fake_send_empty_notification):
                                    run.main()

        fake_send_empty_notification.assert_called_once()
        _, kwargs = fake_send_empty_notification.call_args
        self.assertEqual(kwargs["reason"], "no_candidates")
