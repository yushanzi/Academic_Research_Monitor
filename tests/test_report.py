import importlib
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from models import RelevanceResult
from sources.base import build_paper


class _FakeTemplate:
    def render(self, **kwargs):
        paper_titles = " | ".join(paper.title for paper in kwargs["papers"])
        return f"{paper_titles}\n{kwargs['trend_summary']['trends']}\n{' '.join(kwargs['topics'])}"


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
        paper.relevance = RelevanceResult(True, 0.91, ["protein folding"], "高度相关")
        paper.analysis = {
            "research_direction": "方向",
            "innovation_points": ["创新1"],
            "summary": "总结",
        }

        config = {
            "user": {"name": "monitor-a"},
            "topics": ["protein folding"],
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
                )

            html_path = os.path.join(tmp, "academic_report_2026-03-30.html")
            self.assertEqual(pdf_path, os.path.join(tmp, "academic_report_2026-03-30.pdf"))
            self.assertTrue(os.path.exists(html_path))
            self.assertTrue(os.path.exists(pdf_path))
            with open(html_path, "r", encoding="utf-8") as f:
                html = f.read()
            self.assertIn("Paper 1", html)
            self.assertIn("protein folding", html)
