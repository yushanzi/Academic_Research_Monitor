import io
import json
import os
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from unittest.mock import MagicMock, patch

import run
from analysis.providers import resolve_content_analysis_provider
from config_schema import app_config_from_dict
from models import AccessInfo, InterestProfile
from scoring.models import AbstractRelevanceResult, CandidateGateResult
from sources.base import build_paper


@contextmanager
def unlocked(*args, **kwargs):
    yield


class RunModuleTests(unittest.TestCase):
    def test_resolve_content_analysis_provider_defaults_to_root_provider_for_candidate_score(self):
        config = app_config_from_dict(
            {
                "user": {"name": "monitor_a"},
                "sources": {"fake": {"enabled": True}},
                "llm": {"provider": "claude", "model": "root-model"},
                "email": {"recipient": "test@example.com"},
                "abstract_selection": {
                    "three_llm_voting": {
                        "judges": [
                            {"name": "j1", "provider": "claude", "model": "judge-1"},
                            {"name": "j2", "provider": "claude", "model": "judge-2"},
                            {"name": "j3", "provider": "claude", "model": "judge-3"},
                        ]
                    }
                },
            }
        )
        root_provider = object()

        with patch("analysis.providers.get_provider_from_llm_config", return_value="judge-provider") as provider_mock:
            provider = resolve_content_analysis_provider(config, root_provider)

        self.assertIs(provider, root_provider)
        provider_mock.assert_not_called()

    def test_resolve_content_analysis_provider_uses_first_voting_judge_when_voting_enabled(self):
        config = app_config_from_dict(
            {
                "user": {"name": "monitor_a"},
                "sources": {"fake": {"enabled": True}},
                "llm": {"provider": "claude", "model": "root-model"},
                "email": {"recipient": "test@example.com"},
                "abstract_selection": {
                    "method": "three_llm_voting",
                    "three_llm_voting": {
                        "judges": [
                            {"name": "j1", "provider": "claude", "model": "judge-1"},
                            {"name": "j2", "provider": "claude", "model": "judge-2"},
                            {"name": "j3", "provider": "claude", "model": "judge-3"},
                        ]
                    }
                },
            }
        )
        root_provider = object()

        with patch("analysis.providers.get_provider_from_llm_config", return_value="judge-provider") as provider_mock:
            provider = resolve_content_analysis_provider(config, root_provider)

        self.assertEqual(provider, "judge-provider")
        provider_mock.assert_called_once_with(config.abstract_selection.three_llm_voting.judges[0])

    def test_resolve_content_analysis_provider_prefers_explicit_override(self):
        config = app_config_from_dict(
            {
                "user": {"name": "monitor_a"},
                "sources": {"fake": {"enabled": True}},
                "llm": {"provider": "claude", "model": "root-model"},
                "email": {"recipient": "test@example.com"},
                "content_analysis": {
                    "llm": {"provider": "openai_compatible", "model": "analysis-model", "base_url": "https://example.test/v1"}
                },
            }
        )
        root_provider = object()

        with patch("analysis.providers.get_provider_from_llm_config", return_value="analysis-provider") as provider_mock:
            provider = resolve_content_analysis_provider(config, root_provider)

        self.assertEqual(provider, "analysis-provider")
        provider_mock.assert_called_once_with(config.content_analysis.llm)

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
                "time_range_hours": 24,
                "output_dir": "output/test-run",
                "llm": {"provider": "claude", "model": "fake-model"},
                "abstract_selection": {"method": "candidate_score"},
                "email": {"recipient": "test@example.com"},
                "access": {"mode": "open_access", "auth_profile": None},
            }
        )

        fake_provider = object()
        analyzed_paper = fake_source.fetch_papers.return_value[0]
        analyzed_paper.relevance = AbstractRelevanceResult(
            is_relevant=True,
            relevance_score=0.8,
            topic_match=2,
            must_have_match=1,
            exclude_match=None,
            evidence_strength=2,
            focus_specificity=1,
            matched_aspects=["protein folding dynamics"],
            reason="Strong abstract match",
        )
        analyzed_paper.analysis = {
            "research_direction": "Direction",
            "innovation_points": ["Innovation"],
            "summary": "Summary",
            "consistency_with_abstract": "unclear",
            "consistency_reason": "No full text available.",
        }
        analyzed_papers = [analyzed_paper]
        trend_summary = {"trends": "Trend", "suggestions": ["Suggestion"]}

        with patch("sys.argv", ["run.py", "--config", "instances/bio-monitor/config.json", "--dry-run"]):
            with patch.object(run, "load_app_config", return_value=config):
                with patch.object(run, "run_lock", return_value=unlocked()):
                    with patch.object(run, "get_enabled_sources", return_value=[fake_source]):
                        with patch.object(run, "get_provider", return_value=fake_provider):
                            with patch.object(
                                run,
                                "load_or_create_interest_profile",
                                return_value=InterestProfile(
                                    core_topics=["protein folding dynamics"],
                                    must_have=["protein folding dynamics"],
                                    summary="Monitor protein folding",
                                ),
                            ):
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
                                    with patch.object(run, "select_abstract_relevance", return_value=analyzed_paper.relevance):
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
                "time_range_hours": 24,
                "output_dir": "output/test-run",
                "llm": {"provider": "claude", "model": "fake-model"},
                "email": {"recipient": "test@example.com"},
                "access": {"mode": "open_access", "auth_profile": None},
            }
        )

        with patch("sys.argv", ["run.py", "--config", "instances/bio-monitor/config.json"]):
            with patch.object(run, "load_app_config", return_value=config):
                with patch.object(run, "run_lock", return_value=unlocked()):
                    with patch.object(run, "get_provider", return_value=object()):
                        with patch.object(
                            run,
                            "load_or_create_interest_profile",
                            return_value=InterestProfile(core_topics=["protein folding dynamics"], summary="Monitor protein folding"),
                        ):
                            with patch.object(run, "get_enabled_sources", return_value=[fake_source]):
                                fake_send_empty_notification = MagicMock()
                                with patch.object(run, "send_empty_notification", fake_send_empty_notification):
                                    run.main()

        fake_send_empty_notification.assert_called_once()
        _, kwargs = fake_send_empty_notification.call_args
        self.assertEqual(kwargs["reason"], "no_candidates")

    def test_run_pipeline_writes_run_stats_and_passes_display_to_report(self):
        fake_source = MagicMock()
        fake_source.name = "FakeSource"
        fake_source.fetch_papers.return_value = [
            build_paper(
                title="Paper 1",
                authors=["Author A"],
                abstract="Abstract 1",
                date="2026-03-23",
                url="https://example.com/p1",
                source="FakeSource",
                doi="10.1000/test1",
            ),
            build_paper(
                title="Paper 2",
                authors=["Author B"],
                abstract="Abstract 2",
                date="2026-03-23",
                url="https://example.com/p2",
                source="FakeSource",
                doi="10.1000/test2",
            ),
        ]
        config = app_config_from_dict(
            {
                "user": {"name": "monitor_a"},
                "sources": {"fake": {"enabled": True}},
                "llm": {"provider": "claude", "model": "fake-model"},
                "abstract_selection": {"method": "candidate_score"},
                "email": {"recipient": "test@example.com"},
            }
        )
        logger = MagicMock()
        selected_paper = fake_source.fetch_papers.return_value[0]
        selected_paper.relevance = AbstractRelevanceResult(
            is_relevant=True,
            relevance_score=0.8,
            topic_match=2,
            must_have_match=None,
            exclude_match=None,
            evidence_strength=1,
            focus_specificity=2,
            matched_aspects=["protein folding dynamics"],
            reason="Strong abstract match",
        )
        selected_paper.analysis = {
            "research_direction": "Direction",
            "innovation_points": [],
            "summary": "Summary",
            "consistency_with_abstract": "unclear",
            "consistency_reason": "No full text available.",
        }
        rejected_relevance = AbstractRelevanceResult(
            is_relevant=False,
            relevance_score=0.2,
            topic_match=0,
            must_have_match=None,
            exclude_match=None,
            evidence_strength=0,
            focus_specificity=0,
            matched_aspects=[],
            reason="Weak match",
        )

        with tempfile.TemporaryDirectory() as tmp:
            config.output_dir = tmp
            with patch.object(run, "get_provider", return_value=object()):
                with patch.object(
                    run,
                    "load_or_create_interest_profile",
                    return_value=InterestProfile(core_topics=["protein folding dynamics"]),
                ):
                    with patch.object(run, "get_enabled_sources", return_value=[fake_source]):
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
                            with patch.object(
                                run,
                                "select_abstract_relevance",
                                side_effect=[selected_paper.relevance, rejected_relevance],
                            ):
                                with patch.object(run, "analyze_papers", return_value=[selected_paper]):
                                    with patch.object(run, "generate_trend_summary", return_value={"trends": "Trend", "suggestions": []}):
                                        fake_generate_report = MagicMock(return_value=os.path.join(tmp, "report.pdf"))
                                        with patch.object(run, "generate_report", fake_generate_report):
                                            result = run._run_pipeline(
                                                config,
                                                config.to_dict(),
                                                "2026-05-05",
                                                True,
                                                logger,
                                                tmp,
                                                "instances/bio-monitor/config.json",
                                            )

            self.assertEqual(result, 0)
            stats_path = os.path.join(tmp, "run_stats_2026-05-05.json")
            self.assertTrue(os.path.exists(stats_path))
            with open(stats_path, "r", encoding="utf-8") as f:
                stats = json.load(f)
            self.assertEqual(stats["instance_name"], "monitor_a")
            self.assertEqual(stats["raw_fetched_count"], 2)
            self.assertEqual(stats["raw_fetched_by_source"], {"FakeSource": 2})
            self.assertEqual(stats["deduplicated_candidate_count"], 2)
            self.assertEqual(stats["abstract_scored_count"], 2)
            self.assertEqual(stats["selected_unique_count"], 1)
            self.assertEqual(stats["report_count_display"], "1/2")
            self.assertEqual(fake_generate_report.call_args.args[5]["report_count_display"], "1/2")

    def test_run_pipeline_writes_run_stats_for_empty_selection(self):
        fake_source = MagicMock()
        fake_source.name = "FakeSource"
        fake_source.fetch_papers.return_value = [
            build_paper(
                title="Paper 1",
                authors=["Author A"],
                abstract="Abstract 1",
                date="2026-03-23",
                url="https://example.com/p1",
                source="FakeSource",
                doi="10.1000/test1",
            )
        ]
        config = app_config_from_dict(
            {
                "user": {"name": "monitor_a"},
                "sources": {"fake": {"enabled": True}},
                "llm": {"provider": "claude", "model": "fake-model"},
                "abstract_selection": {"method": "candidate_score"},
                "email": {"recipient": "test@example.com"},
            }
        )
        logger = MagicMock()
        rejected_relevance = AbstractRelevanceResult(
            is_relevant=False,
            relevance_score=0.2,
            topic_match=0,
            must_have_match=None,
            exclude_match=None,
            evidence_strength=0,
            focus_specificity=0,
            matched_aspects=[],
            reason="Weak match",
        )

        with tempfile.TemporaryDirectory() as tmp:
            config.output_dir = tmp
            with patch.object(run, "get_provider", return_value=object()):
                with patch.object(
                    run,
                    "load_or_create_interest_profile",
                    return_value=InterestProfile(core_topics=["protein folding dynamics"]),
                ):
                    with patch.object(run, "get_enabled_sources", return_value=[fake_source]):
                        with patch.object(run, "select_abstract_relevance", return_value=rejected_relevance):
                            result = run._run_pipeline(
                                config,
                                config.to_dict(),
                                "2026-05-05",
                                True,
                                logger,
                                tmp,
                                "instances/bio-monitor/config.json",
                            )

            self.assertEqual(result, 0)
            stats_path = os.path.join(tmp, "run_stats_2026-05-05.json")
            self.assertTrue(os.path.exists(stats_path))
            with open(stats_path, "r", encoding="utf-8") as f:
                stats = json.load(f)
            self.assertEqual(stats["raw_fetched_count"], 1)
            self.assertEqual(stats["selected_unique_count"], 0)
            self.assertEqual(stats["report_count_display"], "0/1")

    def test_run_pipeline_prunes_old_runtime_artifacts_only(self):
        fake_source = MagicMock()
        fake_source.name = "FakeSource"
        fake_source.fetch_papers.return_value = []
        config = app_config_from_dict(
            {
                "user": {"name": "monitor_a"},
                "sources": {"fake": {"enabled": True}},
                "llm": {"provider": "claude", "model": "fake-model"},
                "email": {"recipient": "test@example.com"},
            }
        )
        logger = MagicMock()

        with tempfile.TemporaryDirectory() as tmp:
            config.output_dir = tmp
            old_report = os.path.join(tmp, "academic_report_2026-04-01.html")
            old_stats = os.path.join(tmp, "run_stats_2026-04-01.json")
            keep_profile = os.path.join(tmp, "interest_profile.json")
            for path in (old_report, old_stats, keep_profile):
                with open(path, "w", encoding="utf-8") as f:
                    f.write("x")

            prune_calls = []

            def _fake_prune(output_dir, retention_days):
                prune_calls.append((output_dir, retention_days))
                os.remove(old_report)
                os.remove(old_stats)
                return [old_report, old_stats]

            with patch.object(run, "get_provider", return_value=object()):
                with patch.object(
                    run,
                    "load_or_create_interest_profile",
                    return_value=InterestProfile(core_topics=["protein folding dynamics"]),
                ):
                    with patch.object(run, "get_enabled_sources", return_value=[fake_source]):
                        with patch.object(run, "prune_output_artifacts", side_effect=_fake_prune):
                            result = run._run_pipeline(
                                config,
                                config.to_dict(),
                                "2026-05-05",
                                True,
                                logger,
                                tmp,
                                "instances/bio-monitor/config.json",
                            )

            self.assertEqual(result, 0)
            self.assertEqual(prune_calls, [(tmp, 30)])
            self.assertFalse(os.path.exists(old_report))
            self.assertFalse(os.path.exists(old_stats))
            self.assertTrue(os.path.exists(keep_profile))

    def test_main_no_candidates_skips_empty_notification_when_disabled(self):
        fake_source = MagicMock()
        fake_source.name = "FakeSource"
        fake_source.fetch_papers.return_value = []

        config = app_config_from_dict(
            {
                "user": {"name": "monitor_a"},
                "schedule": {"cron": "0 8 * * *", "timezone": "UTC", "run_on_start": False},
                "sources": {"fake": {"enabled": True}},
                "time_range_hours": 24,
                "output_dir": "output/test-run",
                "llm": {"provider": "claude", "model": "fake-model"},
                "email": {"recipient": "test@example.com", "send_empty_notification": False},
                "access": {"mode": "open_access", "auth_profile": None},
            }
        )

        with patch("sys.argv", ["run.py", "--config", "instances/bio-monitor/config.json"]):
            with patch.object(run, "load_app_config", return_value=config):
                with patch.object(run, "run_lock", return_value=unlocked()):
                    with patch.object(run, "get_provider", return_value=object()):
                        with patch.object(
                            run,
                            "load_or_create_interest_profile",
                            return_value=InterestProfile(core_topics=["protein folding dynamics"], summary="Monitor protein folding"),
                        ):
                            with patch.object(run, "get_enabled_sources", return_value=[fake_source]):
                                fake_send_empty_notification = MagicMock()
                                with patch.object(run, "send_empty_notification", fake_send_empty_notification):
                                    run.main()

        fake_send_empty_notification.assert_not_called()

    def test_run_pipeline_uses_selected_synonyms_in_query_topics(self):
        fake_source = MagicMock()
        fake_source.name = "FakeSource"
        fake_source.fetch_papers.return_value = []
        config = app_config_from_dict(
            {
                "user": {"name": "monitor_a"},
                "sources": {"fake": {"enabled": True}},
                "llm": {"provider": "claude", "model": "fake-model"},
                "email": {"recipient": "test@example.com"},
                "output_dir": "output/test-run",
                "interest_profile_query": {"expand_synonyms": True, "max_query_synonyms": 2},
            }
        )
        profile = InterestProfile(
            core_topics=["protein structure prediction"],
            synonyms=["protein folding", "structure modeling", "folding"],
            summary="Monitor protein structure prediction",
        )

        logger = MagicMock()
        with patch.object(run, "get_provider", return_value=object()):
            with patch.object(run, "load_or_create_interest_profile", return_value=profile):
                with patch.object(run, "get_enabled_sources", return_value=[fake_source]):
                    run._run_pipeline(config, config.to_dict(), "2026-05-05", True, logger, config.output_dir, "instances/bio-monitor/config.json")

        fake_source.fetch_papers.assert_called_once_with(
            ["protein structure prediction", "protein folding", "structure modeling"],
            24,
        )

    def test_run_pipeline_candidate_scoring_failure_is_fatal_by_default(self):
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
                "sources": {"fake": {"enabled": True}},
                "llm": {"provider": "claude", "model": "fake-model"},
                "abstract_selection": {"method": "candidate_score"},
                "email": {"recipient": "test@example.com"},
                "output_dir": "output/test-run",
            }
        )
        logger = MagicMock()

        with patch.object(run, "get_provider", return_value=object()):
            with patch.object(run, "load_or_create_interest_profile", return_value=InterestProfile(core_topics=["protein folding dynamics"])):
                with patch.object(run, "get_enabled_sources", return_value=[fake_source]):
                    with patch.object(run, "select_abstract_relevance", side_effect=RuntimeError("llm down")):
                        with self.assertRaises(RuntimeError):
                            run._run_pipeline(config, config.to_dict(), "2026-05-05", False, logger, config.output_dir, "instances/bio-monitor/config.json")

    def test_run_pipeline_keeps_abstract_selected_paper_without_full_text(self):
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
                "sources": {"fake": {"enabled": True}},
                "llm": {"provider": "claude", "model": "fake-model"},
                "abstract_selection": {"method": "candidate_score"},
                "email": {"recipient": "test@example.com"},
                "output_dir": "output/test-run",
            }
        )
        logger = MagicMock()
        analyzed_paper = fake_source.fetch_papers.return_value[0]
        analyzed_paper.relevance = AbstractRelevanceResult(
            is_relevant=True,
            relevance_score=0.8,
            topic_match=2,
            must_have_match=None,
            exclude_match=None,
            evidence_strength=1,
            focus_specificity=2,
            matched_aspects=["protein folding dynamics"],
            reason="Strong abstract match",
        )
        analyzed_paper.analysis = {
            "research_direction": "Direction",
            "innovation_points": [],
            "summary": "Summary",
            "consistency_with_abstract": "unclear",
            "consistency_reason": "No full text available.",
        }

        with patch.object(run, "get_provider", return_value=object()):
            with patch.object(run, "load_or_create_interest_profile", return_value=InterestProfile(core_topics=["protein folding dynamics"])):
                with patch.object(run, "get_enabled_sources", return_value=[fake_source]):
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
                        with patch.object(run, "select_abstract_relevance", return_value=analyzed_paper.relevance):
                            with patch.object(run, "analyze_papers", return_value=[analyzed_paper]):
                                with patch.object(run, "generate_trend_summary", return_value={"trends": "Trend", "suggestions": []}):
                                    with patch.object(run, "generate_report", return_value="output/report.pdf"):
                                        result = run._run_pipeline(config, config.to_dict(), "2026-05-05", True, logger, config.output_dir, "instances/bio-monitor/config.json")

        self.assertEqual(result, 0)

    def test_run_pipeline_keeps_topic_match_zero_paper_when_score_meets_threshold(self):
        fake_source = MagicMock()
        fake_source.name = "FakeSource"
        fake_source.fetch_papers.return_value = [
            build_paper(
                title="Paper 1",
                authors=["Author A"],
                abstract="This paper studies a tightly scoped method with strong results.",
                date="2026-03-23",
                url="https://example.com/p1",
                source="FakeSource",
                doi="10.1000/test1",
            )
        ]
        config = app_config_from_dict(
            {
                "user": {"name": "monitor_a"},
                "sources": {"fake": {"enabled": True}},
                "llm": {"provider": "claude", "model": "fake-model"},
                "abstract_selection": {"method": "candidate_score"},
                "email": {"recipient": "test@example.com"},
                "output_dir": "output/test-run",
            }
        )
        logger = MagicMock()
        analyzed_paper = fake_source.fetch_papers.return_value[0]
        analyzed_paper.relevance = AbstractRelevanceResult(
            is_relevant=True,
            relevance_score=0.6,
            topic_match=0,
            must_have_match=2,
            exclude_match=0,
            evidence_strength=2,
            focus_specificity=2,
            matched_aspects=["strong results"],
            reason="Selected by abstract score.",
        )
        analyzed_paper.analysis = {
            "research_direction": "Direction",
            "innovation_points": [],
            "summary": "Summary",
            "consistency_with_abstract": "unclear",
            "consistency_reason": "No full text available.",
        }

        with patch.object(run, "get_provider", return_value=object()):
            with patch.object(
                run,
                "load_or_create_interest_profile",
                return_value=InterestProfile(core_topics=["protein folding dynamics"], must_have=["strong results"]),
            ):
                with patch.object(run, "get_enabled_sources", return_value=[fake_source]):
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
                        with patch.object(run, "select_abstract_relevance", return_value=analyzed_paper.relevance):
                            with patch.object(run, "analyze_papers", return_value=[analyzed_paper]):
                                with patch.object(run, "generate_trend_summary", return_value={"trends": "Trend", "suggestions": []}):
                                    with patch.object(run, "generate_report", return_value="output/report.pdf"):
                                        result = run._run_pipeline(config, config.to_dict(), "2026-05-05", True, logger, config.output_dir, "instances/bio-monitor/config.json")

        self.assertEqual(result, 0)

    def test_run_pipeline_uses_three_llm_voting_when_explicitly_configured(self):
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
                "sources": {"fake": {"enabled": True}},
                "llm": {"provider": "claude", "model": "fake-model"},
                "email": {"recipient": "test@example.com"},
                "output_dir": "output/test-run",
                "abstract_selection": {"method": "three_llm_voting"},
            }
        )
        logger = MagicMock()
        analyzed_paper = fake_source.fetch_papers.return_value[0]
        analyzed_paper.relevance = AbstractRelevanceResult(
            is_relevant=True,
            relevance_score=2 / 3,
            topic_match=None,
            must_have_match=None,
            exclude_match=None,
            evidence_strength=None,
            focus_specificity=None,
            matched_aspects=["protein folding dynamics"],
            reason="2/3 judges marked the abstract as relevant.",
            basis="abstract_voting",
            method="three_llm_voting",
            vote_summary={"successful_judges": 3, "relevant_votes": 2, "decision_rule": "required_votes"},
        )
        analyzed_paper.analysis = {
            "research_direction": "Direction",
            "innovation_points": [],
            "summary": "Summary",
            "consistency_with_abstract": "unclear",
            "consistency_reason": "No full text available.",
        }

        with patch.object(run, "get_provider", return_value=object()):
            with patch.object(run, "load_or_create_interest_profile", return_value=InterestProfile(core_topics=["protein folding dynamics"])):
                with patch.object(run, "get_enabled_sources", return_value=[fake_source]):
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
                        with patch.object(run, "select_abstract_relevance", return_value=analyzed_paper.relevance) as voting_mock:
                            with patch.object(run, "resolve_content_analysis_provider", return_value=object()):
                                with patch.object(run, "analyze_papers", return_value=[analyzed_paper]):
                                    with patch.object(run, "generate_trend_summary", return_value={"trends": "Trend", "suggestions": []}):
                                        with patch.object(run, "generate_report", return_value="output/report.pdf"):
                                            result = run._run_pipeline(config, config.to_dict(), "2026-05-05", True, logger, config.output_dir, "instances/bio-monitor/config.json")

        self.assertEqual(result, 0)
        voting_mock.assert_called_once()
