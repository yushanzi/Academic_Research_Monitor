from __future__ import annotations

import json
import logging

from models import InterestProfile, Paper
from scoring.common import complete_json, strip_json_wrapper
from scoring.prompts import SYSTEM_PROMPT
from scoring.rubric import relevance_field

from .prompts import TREND_PROMPT

logger = logging.getLogger(__name__)


def generate_trend_summary(
    papers: list[Paper],
    provider,
    profile: InterestProfile | None = None,
) -> dict:
    if not papers:
        return {"trends": "No highly relevant papers were found today.", "suggestions": []}

    paper_list = "\n".join(
        f"- {p.title or 'N/A'} | {p.source or 'unknown'} | score={relevance_field(p.relevance, 'relevance_score', 'N/A')} | "
        f"evidence={p.evidence_level or 'abstract_only'} | reason={relevance_field(p.relevance, 'reason', 'N/A')}"
        for p in papers
    )

    try:
        prompt = TREND_PROMPT.format(
            count=len(papers),
            interest_summary=(profile.summary if profile else "None"),
            paper_list=paper_list,
        )
        return complete_json(
            provider,
            prompt,
            _parse_trend_response,
            system=SYSTEM_PROMPT,
            context="trend summary",
        )
    except Exception as e:
        logger.error("Failed to generate trend summary: %s", e)
        return {"trends": "Trend summary generation failed.", "suggestions": []}


def _parse_trend_response(raw: str) -> dict:
    data = json.loads(strip_json_wrapper(raw))
    if not isinstance(data, dict):
        raise ValueError("trend response must be a JSON object")

    trends = data.get("trends")
    suggestions = data.get("suggestions")

    if not isinstance(trends, str) or not trends.strip():
        raise ValueError("trend.trends must be a non-empty string")
    if not isinstance(suggestions, list):
        raise ValueError("trend.suggestions must be a list")

    normalized_suggestions = []
    for item in suggestions:
        if isinstance(item, str) and item.strip():
            normalized_suggestions.append(item.strip())

    return {
        "trends": trends.strip(),
        "suggestions": normalized_suggestions,
    }
