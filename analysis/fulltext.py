from __future__ import annotations

import json
import logging
import time

from models import InterestProfile, Paper
from scoring.common import complete_json, strip_json_wrapper
from scoring.prompts import SYSTEM_PROMPT

from .prompts import ANALYSIS_PROMPT

logger = logging.getLogger(__name__)


def analyze_papers(
    papers: list[Paper],
    provider,
    profile: InterestProfile | None = None,
) -> list[Paper]:
    analyzed: list[Paper] = []
    for i, paper in enumerate(papers):
        logger.info("Analyzing paper %s/%s: %s...", i + 1, len(papers), paper.title[:60])
        try:
            prompt = ANALYSIS_PROMPT.format(
                interest_summary=(profile.summary if profile else "None"),
                title=paper.title,
                evidence_level=paper.evidence_level or "abstract_only",
                content=paper_evidence_text(paper),
            )
            paper.analysis = complete_json(
                provider,
                prompt,
                _parse_analysis_response,
                system=SYSTEM_PROMPT,
                context=f"analysis for '{paper.title[:40]}'",
            )
        except Exception as e:
            logger.error("LLM analysis failed for '%s': %s", paper.title[:40], e)
            paper.analysis = {
                "research_direction": "Analysis failed",
                "innovation_points": [],
                "summary": (paper.full_text or paper.abstract or "")[:220],
                "consistency_with_abstract": "unclear",
                "consistency_reason": "Unable to compare the abstract judgement with the accessible content.",
            }

        analyzed.append(paper)
        if i < len(papers) - 1:
            time.sleep(1)
    return analyzed


def paper_evidence_text(paper: Paper) -> str:
    return (paper.full_text or paper.abstract or "N/A")[:20000]


def _parse_analysis_response(raw: str) -> dict:
    data = json.loads(strip_json_wrapper(raw))
    if not isinstance(data, dict):
        raise ValueError("analysis response must be a JSON object")

    research_direction = data.get("research_direction")
    innovation_points = data.get("innovation_points")
    summary = data.get("summary")
    consistency_with_abstract = str(data.get("consistency_with_abstract", "unclear")).strip() or "unclear"
    consistency_reason = str(data.get("consistency_reason", "")).strip()

    if not isinstance(research_direction, str) or not research_direction.strip():
        raise ValueError("analysis.research_direction must be a non-empty string")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("analysis.summary must be a non-empty string")
    if not isinstance(innovation_points, list):
        raise ValueError("analysis.innovation_points must be a list")
    if consistency_with_abstract not in {"supports_abstract", "weakens_abstract", "unclear"}:
        raise ValueError("analysis.consistency_with_abstract must be supports_abstract, weakens_abstract, or unclear")
    if not consistency_reason:
        raise ValueError("analysis.consistency_reason must be a non-empty string")

    normalized_points = []
    for point in innovation_points:
        if isinstance(point, str) and point.strip():
            normalized_points.append(point.strip())

    return {
        "research_direction": research_direction.strip(),
        "innovation_points": normalized_points,
        "summary": summary.strip(),
        "consistency_with_abstract": consistency_with_abstract,
        "consistency_reason": consistency_reason,
    }
