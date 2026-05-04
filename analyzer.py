from __future__ import annotations

import json
import logging
import time

from json_utils import extract_json_object_text
from llm.base import LLMProvider
from models import InterestProfile, Paper, RelevanceResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = "You are an academic research analyst. Always respond in valid JSON."
INTEREST_SUMMARY_PROMPT = "{summary}"  # reserved for future prompt composition

RELEVANCE_PROMPT = """Determine whether the following paper is relevant to the user's monitoring interests.

Interest profile summary:
{interest_summary}
Core topics: {core_topics}
Synonyms: {synonyms}
Must-have: {must_have}
Exclude: {exclude}

Paper title: {title}
Evidence level: {evidence_level}
Content used for judgement:
{content}

Respond in JSON with exactly these keys:
- is_relevant: boolean
- relevance_score: number between 0 and 1
- matched_aspects: array of matched aspects
- reason: concise Chinese explanation

JSON only, no markdown fences."""

ANALYSIS_PROMPT = """Analyze the following paper and provide your analysis in Chinese.

Interest profile summary:
{interest_summary}
Paper title: {title}
Evidence level: {evidence_level}
Content:
{content}

Respond in JSON with exactly these keys:
- research_direction: 简述研究领域和方向 (1-2 sentences)
- innovation_points: 2-3个核心创新点 (array of strings)
- summary: 150-220字的中文摘要总结

JSON only, no markdown fences."""

TREND_PROMPT = """Based on the following {count} selected papers, provide a trend analysis and follow-up suggestions in Chinese.

Interest profile summary:
{interest_summary}

Papers:
{paper_list}

Respond in JSON with exactly these keys:
- trends: 领域趋势总结 (2-3 paragraphs)
- suggestions: 后续关注建议 (array of 3-5 strings)

JSON only, no markdown fences."""

MAX_LLM_ATTEMPTS = 3
RETRY_BASE_DELAY_SECONDS = 2
DEFAULT_RELEVANCE_THRESHOLD = 0.70


def _strip_json_wrapper(raw: str) -> str:
    return extract_json_object_text(raw)


def _log_bad_response(context: str, raw: str, error: Exception) -> None:
    snippet = raw.strip().replace("\n", " ")
    if len(snippet) > 300:
        snippet = snippet[:300] + "..."
    logger.warning("%s: invalid LLM response (%s). Raw snippet: %s", context, error, snippet)


def _parse_analysis_response(raw: str) -> dict:
    data = json.loads(_strip_json_wrapper(raw))
    if not isinstance(data, dict):
        raise ValueError("analysis response must be a JSON object")

    research_direction = data.get("research_direction")
    innovation_points = data.get("innovation_points")
    summary = data.get("summary")

    if not isinstance(research_direction, str) or not research_direction.strip():
        raise ValueError("analysis.research_direction must be a non-empty string")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("analysis.summary must be a non-empty string")
    if not isinstance(innovation_points, list):
        raise ValueError("analysis.innovation_points must be a list")

    normalized_points = []
    for point in innovation_points:
        if isinstance(point, str) and point.strip():
            normalized_points.append(point.strip())

    return {
        "research_direction": research_direction.strip(),
        "innovation_points": normalized_points,
        "summary": summary.strip(),
    }


def _parse_trend_response(raw: str) -> dict:
    data = json.loads(_strip_json_wrapper(raw))
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


def _parse_relevance_response(raw: str) -> RelevanceResult:
    data = json.loads(_strip_json_wrapper(raw))
    if not isinstance(data, dict):
        raise ValueError("relevance response must be a JSON object")

    is_relevant = bool(data.get("is_relevant", False))
    relevance_score = float(data.get("relevance_score", 0.0))
    relevance_score = max(0.0, min(1.0, relevance_score))
    matched_aspects = data.get("matched_aspects") or []
    if not isinstance(matched_aspects, list):
        raise ValueError("relevance.matched_aspects must be a list")
    reason = str(data.get("reason", "")).strip()
    if not reason:
        raise ValueError("relevance.reason must be a non-empty string")

    return RelevanceResult(
        is_relevant=is_relevant,
        relevance_score=relevance_score,
        matched_aspects=[str(item).strip() for item in matched_aspects if str(item).strip()],
        reason=reason,
    )


def _complete_json(
    provider: LLMProvider,
    prompt: str,
    parser,
    *,
    system: str,
    context: str,
):
    last_error = None

    for attempt in range(1, MAX_LLM_ATTEMPTS + 1):
        raw = ""
        try:
            raw = provider.complete(prompt, system=system)
            return parser(raw)
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            last_error = exc
            _log_bad_response(f"{context} attempt {attempt}", raw, exc)
        except Exception as exc:
            last_error = exc
            logger.warning("%s attempt %s failed: %s", context, attempt, exc)

        if attempt < MAX_LLM_ATTEMPTS:
            delay = RETRY_BASE_DELAY_SECONDS * attempt
            logger.info("%s retrying in %ss", context, delay)
            time.sleep(delay)

    raise RuntimeError(f"{context} failed after {MAX_LLM_ATTEMPTS} attempts") from last_error


def judge_relevance(
    paper: Paper,
    provider: LLMProvider,
    profile: InterestProfile,
) -> RelevanceResult:
    content = _paper_evidence_text(paper)
    prompt = RELEVANCE_PROMPT.format(
        interest_summary=profile.summary or "无",
        core_topics="、".join(profile.core_topics) if profile.core_topics else "无",
        synonyms="、".join(profile.synonyms) if profile.synonyms else "无",
        must_have="、".join(profile.must_have) if profile.must_have else "无",
        exclude="、".join(profile.exclude) if profile.exclude else "无",
        title=paper.title,
        evidence_level=paper.evidence_level or "abstract_only",
        content=content,
    )
    return _complete_json(
        provider,
        prompt,
        _parse_relevance_response,
        system=SYSTEM_PROMPT,
        context=f"relevance for '{paper.title[:40]}'",
    )


def analyze_papers(
    papers: list[Paper],
    provider: LLMProvider,
    profile: InterestProfile | None = None,
) -> list[Paper]:
    analyzed: list[Paper] = []
    for i, paper in enumerate(papers):
        logger.info("Analyzing paper %s/%s: %s...", i + 1, len(papers), paper.title[:60])
        try:
            prompt = ANALYSIS_PROMPT.format(
                interest_summary=(profile.summary if profile else "无"),
                title=paper.title,
                evidence_level=paper.evidence_level or "abstract_only",
                content=_paper_evidence_text(paper),
            )
            paper.analysis = _complete_json(
                provider,
                prompt,
                _parse_analysis_response,
                system=SYSTEM_PROMPT,
                context=f"analysis for '{paper.title[:40]}'",
            )
        except Exception as e:
            logger.error("LLM analysis failed for '%s': %s", paper.title[:40], e)
            paper.analysis = {
                "research_direction": "分析失败",
                "innovation_points": [],
                "summary": (paper.full_text or paper.abstract or "")[:220],
            }

        analyzed.append(paper)
        if i < len(papers) - 1:
            time.sleep(1)
    return analyzed


def generate_trend_summary(
    papers: list[Paper],
    provider: LLMProvider,
    profile: InterestProfile | None = None,
) -> dict:
    if not papers:
        return {"trends": "今日未发现高相关论文。", "suggestions": []}

    paper_list = "\n".join(
        f"- {p.title or 'N/A'} | {p.source or 'unknown'} | score={_relevance_field(p.relevance, 'relevance_score', 'N/A')} | "
        f"evidence={p.evidence_level or 'abstract_only'} | reason={_relevance_field(p.relevance, 'reason', 'N/A')}"
        for p in papers
    )

    try:
        prompt = TREND_PROMPT.format(
            count=len(papers),
            interest_summary=(profile.summary if profile else "无"),
            paper_list=paper_list,
        )
        return _complete_json(
            provider,
            prompt,
            _parse_trend_response,
            system=SYSTEM_PROMPT,
            context="trend summary",
        )
    except Exception as e:
        logger.error("Failed to generate trend summary: %s", e)
        return {"trends": "趋势总结生成失败。", "suggestions": []}


def _paper_evidence_text(paper: Paper) -> str:
    return (paper.full_text or paper.abstract or "N/A")[:20000]


def _relevance_field(relevance: RelevanceResult | dict | None, field: str, default):
    if isinstance(relevance, RelevanceResult):
        return getattr(relevance, field, default)
    if isinstance(relevance, dict):
        return relevance.get(field, default)
    return default
