import importlib
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from scoring.models import AbstractRelevanceResult
from sources.base import build_paper


class _FakeTemplate:
    def render(self, **kwargs):
        paper_titles = " | ".join(paper.title for paper in kwargs["papers"])
        summary_labels = " | ".join(kwargs["summary_label"](paper) for paper in kwargs["papers"])
        return (
            f"{paper_titles}\n"
            f"{kwargs['trend_summary']['trends']}\n"
            f"{' '.join(kwargs['topics'])}\n"
            f"{kwargs['schedule_display']}\n"
            f"{kwargs['run_stats']['report_count_display']}\n"
            f"{summary_labels}"
        )


class _FakeEnvironment:
    def __init__(self, *args, **kwargs):
        pass

    def get_template(self, name):
        return _FakeTemplate()


class _FakeHTML:
    def __init__(self, string, base_url=None):
        self.string = string
        self.base_url = base_url

    def write_pdf(self, path, stylesheets=None):
        with open(path, "wb") as f:
            f.write(b"%PDF-1.4 fake")


class ReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.modules.setdefault(
            "jinja2",
            types.SimpleNamespace(
                Environment=_FakeEnvironment,
                FileSystemLoader=lambda path: path,
                select_autoescape=lambda _: None,
            ),
        )
        sys.modules.setdefault("weasyprint", types.SimpleNamespace(HTML=_FakeHTML))
        cls.report = importlib.import_module("report")

    def test_generate_report_writes_html_and_pdf(self):
        paper = build_paper(
            title="Paper 1",
            authors=["Author A"],
            abstract="Abstract text",
            date="2026-03-30",
            url="https://example.com/p1",
            source="arXiv",
        )
        paper.matched_topics = ["protein folding"]
        paper.relevance = AbstractRelevanceResult(
            is_relevant=True,
            relevance_score=0.91,
            topic_match=2,
            must_have_match=None,
            exclude_match=None,
            evidence_strength=2,
            focus_specificity=2,
            matched_aspects=["protein folding"],
            reason="Highly relevant",
        )
        paper.analysis = {
            "research_direction": "方向",
            "innovation_points": ["创新1"],
            "summary": "总结",
            "consistency_with_abstract": "supports_abstract",
            "consistency_reason": "全文支持摘要判断。",
        }

        config = {
            "user": {"name": "monitor-a"},
            "interest_profile": {"summary": "关注蛋白折叠", "core_topics": ["protein folding"]},
            "time_range_hours": 24,
            "schedule": {"cron": "0 8 * * *", "timezone": "UTC"},
        }

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(self.report, "HTML", _FakeHTML):
                pdf_path = self.report.generate_report(
                    [paper],
                    {"trends": "趋势总结", "suggestions": ["建议1"]},
                    config,
                    "2026-03-30",
                    tmp,
                    {"report_count_display": "1/3"},
                )

            html_path = os.path.join(tmp, "academic_report_2026-03-30.html")
            self.assertEqual(pdf_path, os.path.join(tmp, "academic_report_2026-03-30.pdf"))
            self.assertTrue(os.path.exists(html_path))
            self.assertTrue(os.path.exists(pdf_path))
            with open(html_path, "r", encoding="utf-8") as f:
                html = f.read()
            self.assertIn("Paper 1", html)
            self.assertIn("protein folding", html)
            self.assertIn("每天 8:00 AM（UTC）", html)
            self.assertIn("1/3", html)

    def test_report_template_omits_redundant_metadata_labels(self):
        template_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "templates",
            "report.html",
        )
        with open(template_path, "r", encoding="utf-8") as f:
            template = f.read()

        removed_labels = [
            "命中关注点",
            "入选依据",
            "内容审阅",
            "报告状态",
            "全文复核",
            "复核说明",
            "判断依据",
            "访问方式",
            "Open Access",
        ]
        for label in removed_labels:
            self.assertNotIn(f"<strong>{label}：</strong>", template)

        self.assertNotIn(">核心关注点<", template)
        self.assertIn("<strong>纳入原因：</strong>", template)
        self.assertIn("<strong>访问入口：</strong>", template)
        self.assertIn("<strong>下载地址：</strong>", template)
        self.assertIn("{{ schedule_display }}", template)

    def test_generate_report_labels_summary_as_full_text_when_true_full_text_is_available(self):
        paper = build_paper(
            title="Paper full-text",
            authors=["Author A"],
            abstract="Abstract text",
            date="2026-03-30",
            url="https://example.com/p1",
            source="bioRxiv",
        )
        paper.full_text_available = True
        paper.evidence_level = "full_text"
        paper.relevance = AbstractRelevanceResult(
            is_relevant=True,
            relevance_score=0.91,
            topic_match=2,
            must_have_match=None,
            exclude_match=None,
            evidence_strength=2,
            focus_specificity=2,
            matched_aspects=["protein folding"],
            reason="Highly relevant",
        )
        paper.analysis = {
            "research_direction": "方向",
            "innovation_points": ["创新1"],
            "summary": "基于全文的总结",
            "consistency_with_abstract": "supports_abstract",
            "consistency_reason": "全文支持摘要判断。",
        }
        config = {
            "user": {"name": "monitor-a"},
            "interest_profile": {"summary": "关注蛋白折叠", "core_topics": ["protein folding"]},
            "time_range_hours": 24,
            "schedule": {"cron": "0 8 * * *", "timezone": "UTC"},
        }

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(self.report, "HTML", _FakeHTML):
                self.report.generate_report(
                    [paper],
                    {"trends": "趋势总结", "suggestions": ["建议1"]},
                    config,
                    "2026-03-30",
                    tmp,
                    {"report_count_display": "1/1"},
                )

            html_path = os.path.join(tmp, "academic_report_2026-03-30.html")
            with open(html_path, "r", encoding="utf-8") as f:
                html = f.read()
            self.assertIn("全文总结", html)
            self.assertNotIn("摘要总结", html)

    def test_generate_report_keeps_summary_label_as_abstract_when_full_text_not_available(self):
        paper = build_paper(
            title="Paper abstract-only",
            authors=["Author A"],
            abstract="Abstract text",
            date="2026-03-30",
            url="https://example.com/p1",
            source="bioRxiv",
        )
        paper.full_text_available = False
        paper.evidence_level = "abstract_only"
        paper.relevance = AbstractRelevanceResult(
            is_relevant=True,
            relevance_score=0.91,
            topic_match=2,
            must_have_match=None,
            exclude_match=None,
            evidence_strength=2,
            focus_specificity=2,
            matched_aspects=["protein folding"],
            reason="Highly relevant",
        )
        paper.analysis = {
            "research_direction": "方向",
            "innovation_points": ["创新1"],
            "summary": "基于摘要的总结",
            "consistency_with_abstract": "supports_abstract",
            "consistency_reason": "摘要支持摘要判断。",
        }
        config = {
            "user": {"name": "monitor-a"},
            "interest_profile": {"summary": "关注蛋白折叠", "core_topics": ["protein folding"]},
            "time_range_hours": 24,
            "schedule": {"cron": "0 8 * * *", "timezone": "UTC"},
        }

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(self.report, "HTML", _FakeHTML):
                self.report.generate_report(
                    [paper],
                    {"trends": "趋势总结", "suggestions": ["建议1"]},
                    config,
                    "2026-03-30",
                    tmp,
                    {"report_count_display": "1/1"},
                )

            html_path = os.path.join(tmp, "academic_report_2026-03-30.html")
            with open(html_path, "r", encoding="utf-8") as f:
                html = f.read()
            self.assertIn("摘要总结", html)

    def test_summary_label_uses_full_text_only_when_actual_full_text_was_extracted(self):
        paper = build_paper(
            title="Paper",
            authors=["Author A"],
            abstract="Abstract text",
            date="2026-03-30",
            url="https://example.com/p1",
            source="bioRxiv",
        )
        paper.full_text_available = True
        paper.evidence_level = "full_text"
        self.assertEqual(self.report._summary_label(paper), "全文总结")

        paper.full_text_available = False
        paper.evidence_level = "abstract_only"
        self.assertEqual(self.report._summary_label(paper), "摘要总结")

    def test_report_css_uses_finer_grained_pagination_controls(self):
        css_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "templates",
            "report.css",
        )
        with open(css_path, "r", encoding="utf-8") as f:
            css = f.read()

        self.assertIn(".paper {\n  margin: 0;\n}", css)
        self.assertIn("page-break-after: avoid;", css)
        self.assertIn("break-after: avoid-page;", css)
        self.assertIn(".paper .meta {", css)
        self.assertIn(".analysis {", css)
        self.assertNotIn(".paper {\n  margin: 1em 0;\n  page-break-inside: avoid;\n}", css)

    def test_report_css_sets_two_line_spacing_for_paper_section(self):
        css_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "templates",
            "report.css",
        )
        with open(css_path, "r", encoding="utf-8") as f:
            css = f.read()

        self.assertIn(".papers h2 {\n  margin-bottom: 3.2em;\n}", css)
        self.assertIn("hr {\n  border: none;\n  border-top: 1px solid #ddd;\n  margin: 1.6em 0;\n}", css)

    def test_format_schedule_display_daily_morning(self):
        result = self.report._format_schedule_display({"cron": "0 8 * * *", "timezone": "Asia/Hong_Kong"})
        self.assertEqual(result, "每天 8:00 AM（Asia/Hong_Kong）")

    def test_format_schedule_display_daily_evening_with_minutes(self):
        result = self.report._format_schedule_display({"cron": "30 20 * * *", "timezone": "UTC"})
        self.assertEqual(result, "每天 8:30 PM（UTC）")

    def test_format_schedule_display_falls_back_for_non_daily_cron(self):
        result = self.report._format_schedule_display({"cron": "0 8 * * 1", "timezone": "Asia/Hong_Kong"})
        self.assertEqual(result, "0 8 * * 1 (Asia/Hong_Kong)")

    def test_topics_match_ignores_case_and_simple_pluralization(self):
        self.assertTrue(self.report._topics_match("protein language model", "Protein Language Models"))
        self.assertTrue(self.report._topics_match("AI for drug discovery", "AI for Drug Discovery"))
        self.assertFalse(self.report._topics_match("protein structure prediction", "computational chemistry"))

    def test_group_papers_by_topic_matches_variant_topic_labels(self):
        paper = build_paper(
            title="Paper 1",
            authors=["Author A"],
            abstract="Abstract text",
            date="2026-03-30",
            url="https://example.com/p1",
            source="arXiv",
        )
        paper.matched_topics = ["Protein Language Models", "AI for Drug Discovery"]

        papers_by_topic, ungrouped_papers = self.report._group_papers_by_topic(
            [paper],
            ["protein language model", "AI for drug discovery"],
        )

        self.assertEqual(papers_by_topic[0]["count"], 1)
        self.assertEqual(papers_by_topic[1]["count"], 1)
        self.assertEqual(ungrouped_papers, [])

    def test_group_papers_by_topic_keeps_unmatched_selected_papers_visible(self):
        paper = build_paper(
            title="Paper 2",
            authors=["Author B"],
            abstract="Abstract text",
            date="2026-03-30",
            url="https://example.com/p2",
            source="bioRxiv",
        )
        paper.matched_topics = ["Structure-Based Drug Design"]

        papers_by_topic, ungrouped_papers = self.report._group_papers_by_topic(
            [paper],
            ["protein language model"],
        )

        self.assertEqual(papers_by_topic[0]["count"], 0)
        self.assertEqual([item.title for item in ungrouped_papers], ["Paper 2"])
