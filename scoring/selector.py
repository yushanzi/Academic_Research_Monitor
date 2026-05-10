from __future__ import annotations

from llm.base import LLMProvider
from models import InterestProfile, Paper

from .models import AbstractRelevanceResult, CandidateGateResult
from .rubric import candidate_to_abstract_relevance, gate_abstract_candidate
from .voting import judge_abstract_with_voting


def select_abstract_relevance(
    paper: Paper,
    provider: LLMProvider,
    profile: InterestProfile,
    config,
) -> AbstractRelevanceResult:
    method = config.abstract_selection.method
    if method == "three_llm_voting":
        return judge_abstract_with_voting(
            paper,
            profile,
            config.abstract_selection.three_llm_voting,
            provider,
            config.candidate_scoring,
        )

    try:
        candidate_result = gate_abstract_candidate(paper, provider, profile, config.candidate_scoring)
        return candidate_to_abstract_relevance(candidate_result, config.candidate_scoring)
    except Exception:
        if config.candidate_scoring.fail_open:
            result = candidate_to_abstract_relevance(
                CandidateGateResult(
                    should_exclude=False,
                    candidate_score=0.0,
                    topic_match=None,
                    must_have_match=None,
                    exclude_match=None,
                    evidence_strength=None,
                    focus_specificity=None,
                    matched_aspects=list(paper.matched_topics),
                    reason="Abstract scoring failed; included because fail_open=true.",
                ),
                config.candidate_scoring,
            )
            result.is_relevant = True
            return result
        raise
