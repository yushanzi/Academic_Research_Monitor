from __future__ import annotations

import json

from llm.base import LLMProvider
from models import InterestProfile, Paper

from .common import complete_json, parse_matched_aspects_and_reason, parse_score_value, strip_json_wrapper
from .models import AbstractRelevanceResult, CandidateGateResult, RelevanceResult
from .prompts import ABSTRACT_GATE_PROMPT, RELEVANCE_PROMPT, SYSTEM_PROMPT
from .weights import weighted_rubric_score


def gate_abstract_candidate(
    paper: Paper,
    provider: LLMProvider,
    profile: InterestProfile,
    scoring_config,
) -> CandidateGateResult:
    prompt = ABSTRACT_GATE_PROMPT.format(
        interest_summary=profile.summary or "None",
        core_topics=", ".join(profile.core_topics) if profile.core_topics else "None",
        must_have=", ".join(profile.must_have) if profile.must_have else "None",
        exclude=", ".join(profile.exclude) if profile.exclude else "None",
        title=paper.title,
        abstract=paper.abstract or "N/A",
    )
    return complete_json(
        provider,
        prompt,
        lambda raw: _parse_candidate_gate_response(raw, profile, scoring_config),
        system=SYSTEM_PROMPT,
        context=f"abstract gate for '{paper.title[:40]}'",
    )


def candidate_to_abstract_relevance(
    candidate_result: CandidateGateResult,
    scoring_config,
) -> AbstractRelevanceResult:
    is_relevant = not candidate_result.should_exclude and candidate_result.candidate_score >= scoring_config.threshold
    return AbstractRelevanceResult(
        is_relevant=is_relevant,
        relevance_score=candidate_result.candidate_score,
        topic_match=candidate_result.topic_match,
        must_have_match=candidate_result.must_have_match,
        exclude_match=candidate_result.exclude_match,
        evidence_strength=candidate_result.evidence_strength,
        focus_specificity=candidate_result.focus_specificity,
        matched_aspects=list(candidate_result.matched_aspects),
        reason=candidate_result.reason,
        method="candidate_score",
    )


def judge_relevance(
    paper: Paper,
    provider: LLMProvider,
    profile: InterestProfile,
    scoring_config,
) -> RelevanceResult:
    content = paper_evidence_text(paper)
    prompt = RELEVANCE_PROMPT.format(
        interest_summary=profile.summary or "None",
        core_topics=", ".join(profile.core_topics) if profile.core_topics else "None",
        must_have=", ".join(profile.must_have) if profile.must_have else "None",
        exclude=", ".join(profile.exclude) if profile.exclude else "None",
        title=paper.title,
        evidence_level=paper.evidence_level or "abstract_only",
        content=content,
    )
    return complete_json(
        provider,
        prompt,
        lambda raw: _parse_relevance_response_with_config(raw, profile, scoring_config),
        system=SYSTEM_PROMPT,
        context=f"relevance for '{paper.title[:40]}'",
    )


def paper_evidence_text(paper: Paper) -> str:
    return (paper.full_text or paper.abstract or "N/A")[:20000]


def relevance_field(relevance: RelevanceResult | AbstractRelevanceResult | dict | None, field: str, default):
    if isinstance(relevance, (RelevanceResult, AbstractRelevanceResult)):
        return getattr(relevance, field, default)
    if isinstance(relevance, dict):
        return relevance.get(field, default)
    return default


def _parse_candidate_gate_response(raw: str, profile: InterestProfile, scoring_config) -> CandidateGateResult:
    data = json.loads(strip_json_wrapper(raw))
    if not isinstance(data, dict):
        raise ValueError("candidate gate response must be a JSON object")

    matched_aspects, reason = parse_matched_aspects_and_reason(data, context="candidate_gate")
    topic_match = parse_score_value(data, "topic_match", allow_null=False)
    must_have_match = parse_score_value(data, "must_have_match", allow_null=not bool(profile.must_have))
    exclude_match = parse_score_value(data, "exclude_match", allow_null=not bool(profile.exclude))
    evidence_strength = parse_score_value(data, "evidence_strength", allow_null=False)
    focus_specificity = parse_score_value(data, "focus_specificity", allow_null=False)

    candidate_score = weighted_rubric_score(
        {
            "topic_match": topic_match,
            "must_have_match": must_have_match,
            "evidence_strength": evidence_strength,
            "focus_specificity": focus_specificity,
        },
        scoring_config.weights,
        exclude_match=exclude_match,
        exclude_penalty_weight=scoring_config.exclude_penalty_weight,
    )

    return CandidateGateResult(
        should_exclude=exclude_match == 2,
        candidate_score=candidate_score,
        topic_match=topic_match,
        must_have_match=must_have_match,
        exclude_match=exclude_match,
        evidence_strength=evidence_strength,
        focus_specificity=focus_specificity,
        matched_aspects=matched_aspects,
        reason=reason,
    )


def _parse_relevance_response_with_config(raw: str, profile: InterestProfile, scoring_config) -> RelevanceResult:
    data = json.loads(strip_json_wrapper(raw))
    if not isinstance(data, dict):
        raise ValueError("relevance response must be a JSON object")

    matched_aspects, reason = parse_matched_aspects_and_reason(data, context="relevance")
    topic_match = parse_score_value(data, "topic_match", allow_null=False)
    must_have_match = parse_score_value(data, "must_have_match", allow_null=not bool(profile.must_have))
    exclude_match = parse_score_value(data, "exclude_match", allow_null=not bool(profile.exclude))
    evidence_quality = parse_score_value(data, "evidence_quality", allow_null=False)
    content_alignment = parse_score_value(data, "content_alignment", allow_null=False)
    actionability = parse_score_value(data, "actionability", allow_null=False)

    relevance_score = weighted_rubric_score(
        {
            "topic_match": topic_match,
            "must_have_match": must_have_match,
            "evidence_quality": evidence_quality,
            "content_alignment": content_alignment,
            "actionability": actionability,
        },
        scoring_config.weights,
        exclude_match=exclude_match,
        exclude_penalty_weight=scoring_config.exclude_penalty_weight,
    )
    is_relevant = relevance_score >= scoring_config.threshold and topic_match >= 1 and exclude_match != 2

    return RelevanceResult(
        is_relevant=is_relevant,
        relevance_score=relevance_score,
        topic_match=topic_match,
        must_have_match=must_have_match,
        exclude_match=exclude_match,
        evidence_quality=evidence_quality,
        content_alignment=content_alignment,
        actionability=actionability,
        matched_aspects=matched_aspects,
        reason=reason,
    )
