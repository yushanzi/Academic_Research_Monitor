import unittest

from analyzer import (
    _parse_analysis_response,
    _parse_relevance_response,
    _parse_trend_response,
    _strip_json_wrapper,
    analyze_papers,
)
from models import InterestProfile
from sources.base import build_paper


class FakeProvider:
    def __init__(self, responses):
        self.responses = list(responses)

    def complete(self, prompt: str, system: str = "") -> str:
        if not self.responses:
            raise RuntimeError("no more fake responses")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class AnalyzerParsingTests(unittest.TestCase):
    def test_strip_json_wrapper_uses_shared_json_extraction(self):
        raw = 'prefix ```json\n{"ok": true}\n``` suffix'

        self.assertEqual(_strip_json_wrapper(raw), '{"ok": true}')

    def test_parse_analysis_response_accepts_wrapped_json(self):
        raw = """```json
        {
          \"research_direction\": \"蛋白质结构建模\",
          \"innovation_points\": [\"创新点1\", \"创新点2\"],
          \"summary\": \"这是一段摘要总结\"
        }
        ```"""

        parsed = _parse_analysis_response(raw)

        self.assertEqual(parsed["research_direction"], "蛋白质结构建模")
        self.assertEqual(parsed["innovation_points"], ["创新点1", "创新点2"])
        self.assertEqual(parsed["summary"], "这是一段摘要总结")

    def test_parse_trend_response_normalizes_suggestions(self):
        raw = """
        {
          \"trends\": \"趋势总结\",
          \"suggestions\": [\"建议1\", \"\", \" 建议2 \"]
        }
        """

        parsed = _parse_trend_response(raw)

        self.assertEqual(parsed["trends"], "趋势总结")
        self.assertEqual(parsed["suggestions"], ["建议1", "建议2"])

    def test_parse_relevance_response(self):
        result = _parse_relevance_response(
            '{"is_relevant": true, "relevance_score": 0.86, "matched_aspects": ["protein folding"], "reason": "高度相关"}'
        )
        self.assertTrue(result.is_relevant)
        self.assertAlmostEqual(result.relevance_score, 0.86)
        self.assertEqual(result.matched_aspects, ["protein folding"])

    def test_analyze_papers_falls_back_after_retries(self):
        provider = FakeProvider([
            '{"research_direction": 123, "innovation_points": [], "summary": "bad"}',
            "not json",
            RuntimeError("temporary failure"),
        ])
        paper = build_paper(
            title="Paper 1",
            authors=[],
            abstract="Abstract 1",
            date="2026-03-30",
            url="https://example.com/p1",
            source="test",
        )
        paper.evidence_level = "abstract_only"
        papers = [paper]

        analyzed = analyze_papers(papers, provider, InterestProfile(summary="关注蛋白折叠"))

        self.assertEqual(len(analyzed), 1)
        self.assertEqual(analyzed[0].analysis["research_direction"], "分析失败")
        self.assertEqual(analyzed[0].analysis["innovation_points"], [])
        self.assertEqual(analyzed[0].analysis["summary"], "Abstract 1")
