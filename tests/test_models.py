import unittest

from models import Paper, ensure_paper
from scoring.models import AbstractRelevanceResult, RelevanceResult
from sources.base import build_paper


class PaperModelTests(unittest.TestCase):
    def test_build_paper_returns_typed_paper(self):
        paper = build_paper(
            title="Paper 1",
            authors=["Author A"],
            abstract="Abstract",
            date="2026-03-30",
            url="https://example.com/paper-1",
            source="Example",
            doi="10.1000/example",
        )

        self.assertIsInstance(paper, Paper)
        self.assertEqual(paper.title, "Paper 1")
        self.assertEqual(paper.source, "Example")

    def test_ensure_paper_converts_dict(self):
        paper = ensure_paper(
            {
                "title": "Paper 2",
                "authors": ["Author B"],
                "abstract": "Abstract",
                "date": "2026-03-30",
                "url": "https://example.com/paper-2",
                "source": "Example",
                "relevance": {"relevance_score": 0.8},
            }
        )

        self.assertIsInstance(paper, Paper)
        self.assertEqual(paper.relevance["relevance_score"], 0.8)

    def test_paper_to_dict_serializes_nested_relevance(self):
        paper = build_paper(
            title="Paper 3",
            authors=[],
            abstract="Abstract",
            date="2026-03-30",
            url="https://example.com/paper-3",
            source="Example",
        )
        paper.relevance = RelevanceResult(
            is_relevant=True,
            relevance_score=0.9,
            topic_match=2,
            must_have_match=None,
            exclude_match=None,
            evidence_quality=2,
            content_alignment=2,
            actionability=1,
            matched_aspects=["aspect"],
            reason="reason",
        )

        payload = paper.to_dict()

        self.assertEqual(payload["relevance"]["relevance_score"], 0.9)

    def test_paper_to_dict_serializes_abstract_relevance(self):
        paper = build_paper(
            title="Paper 4",
            authors=[],
            abstract="Abstract",
            date="2026-03-30",
            url="https://example.com/paper-4",
            source="Example",
        )
        paper.relevance = AbstractRelevanceResult(
            is_relevant=True,
            relevance_score=0.8,
            topic_match=2,
            must_have_match=None,
            exclude_match=None,
            evidence_strength=1,
            focus_specificity=2,
            matched_aspects=["aspect"],
            reason="abstract reason",
        )

        payload = paper.to_dict()

        self.assertEqual(payload["relevance"]["basis"], "abstract_only")
