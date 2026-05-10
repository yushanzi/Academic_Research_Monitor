from __future__ import annotations

import json
import re

from llm import get_provider_from_llm_config
from llm.base import LLMProvider
from models import InterestProfile, Paper

from .common import complete_json, parse_matched_aspects_and_reason, strip_json_wrapper
from .models import AbstractRelevanceResult, JudgeVoteResult
from .prompts import ABSTRACT_VOTING_PROMPT, SYSTEM_PROMPT
from .rubric import candidate_to_abstract_relevance, gate_abstract_candidate


def judge_abstract_with_voting(
    paper: Paper,
    profile: InterestProfile,
    voting_config,
    fallback_provider: LLMProvider,
    candidate_scoring_config,
) -> AbstractRelevanceResult:
    successes: list[JudgeVoteResult] = []
    failed_judges: list[str] = []
    warning_messages: list[str] = []

    prompt = ABSTRACT_VOTING_PROMPT.format(
        interest_summary=profile.summary or "None",
        core_topics=", ".join(profile.core_topics) if profile.core_topics else "None",
        must_have=", ".join(profile.must_have) if profile.must_have else "None",
        exclude=", ".join(profile.exclude) if profile.exclude else "None",
        title=paper.title,
        abstract=paper.abstract or "N/A",
    )

    for judge in voting_config.judges:
        try:
            provider = get_provider_from_llm_config(judge)
            vote = complete_json(
                provider,
                prompt,
                lambda raw, judge_name=judge.name: _parse_judge_vote_response(raw, judge_name, profile),
                system=SYSTEM_PROMPT,
                context=f"abstract vote by '{judge.name}' for '{paper.title[:40]}'",
            )
            successes.append(vote)
        except Exception as exc:
            failed_judges.append(judge.name)
            warning_messages.append(f"{judge.name} failed: {exc}")

    if not successes:
        warning_messages.append("All voting judges failed; falling back to candidate_score.")
        try:
            candidate_result = gate_abstract_candidate(paper, fallback_provider, profile, candidate_scoring_config)
            result = candidate_to_abstract_relevance(candidate_result, candidate_scoring_config)
        except Exception as fallback_exc:
            details = "; ".join(warning_messages + [f"candidate_score fallback failed: {fallback_exc}"])
            raise RuntimeError(details) from fallback_exc
        result.method = "three_llm_voting"
        result.basis = "abstract_candidate_score_fallback"
        result.degraded = True
        result.warning_messages = warning_messages
        result.failed_judges = failed_judges
        result.fallback_trigger = "all_voting_judges_failed"
        return result

    relevant_votes = sum(1 for vote in successes if vote.is_relevant)
    successful_judges = len(successes)
    if failed_judges:
        is_relevant = relevant_votes == successful_judges
        decision_rule = "all_remaining_judges_must_pass"
    else:
        is_relevant = relevant_votes >= voting_config.required_votes
        decision_rule = "required_votes"

    matched_aspects = sorted({aspect for vote in successes for aspect in vote.matched_aspects})
    reason = (
        f"{relevant_votes}/{successful_judges} successful judges marked the abstract as relevant under degraded mode."
        if failed_judges
        else f"{relevant_votes}/{successful_judges} judges marked the abstract as relevant."
    )

    return AbstractRelevanceResult(
        is_relevant=is_relevant,
        relevance_score=(relevant_votes / successful_judges) if successful_judges else 0.0,
        topic_match=None,
        must_have_match=None,
        exclude_match=None,
        evidence_strength=None,
        focus_specificity=None,
        matched_aspects=matched_aspects,
        reason=reason,
        basis="abstract_voting",
        method="three_llm_voting",
        warning_messages=warning_messages,
        failed_judges=failed_judges,
        degraded=bool(failed_judges),
        vote_summary={
            "successful_judges": successful_judges,
            "failed_judges": len(failed_judges),
            "required_votes": voting_config.required_votes,
            "relevant_votes": relevant_votes,
            "not_relevant_votes": successful_judges - relevant_votes,
            "decision_rule": decision_rule,
        },
        judge_votes=[vote.to_dict() for vote in successes],
    )


def _parse_judge_vote_response(raw: str, judge_name: str, profile: InterestProfile) -> JudgeVoteResult:
    data = json.loads(_normalize_judge_vote_json(raw))
    if not isinstance(data, dict):
        raise ValueError("judge vote response must be a JSON object")

    is_relevant = data.get("is_relevant")
    confidence = _normalize_vote_enum(data.get("confidence"))
    topic_match = _normalize_vote_enum(data.get("topic_match"))
    must_have_match = _normalize_vote_enum(data.get("must_have_match"))
    exclude_match = _normalize_vote_enum(data.get("exclude_match"))
    matched_aspects, reason = parse_matched_aspects_and_reason(data, context="judge_vote")

    if not isinstance(is_relevant, bool):
        raise ValueError("judge_vote.is_relevant must be a boolean")
    if confidence not in {"high", "medium", "low"}:
        raise ValueError("judge_vote.confidence must be high, medium, or low")
    if topic_match not in {"yes", "partial", "no"}:
        raise ValueError("judge_vote.topic_match must be yes, partial, or no")

    if must_have_match is None:
        if profile.must_have:
            raise ValueError("judge_vote.must_have_match must be yes, partial, or no")
    elif must_have_match not in {"yes", "partial", "no"}:
        raise ValueError("judge_vote.must_have_match must be yes, partial, no, or null")

    if exclude_match is None:
        if profile.exclude:
            raise ValueError("judge_vote.exclude_match must be yes, possible, or no")
    elif exclude_match not in {"yes", "possible", "no"}:
        raise ValueError("judge_vote.exclude_match must be yes, possible, no, or null")

    if exclude_match == "yes" and is_relevant:
        raise ValueError("judge_vote must return is_relevant=false when exclude_match=yes")

    return JudgeVoteResult(
        judge_name=judge_name,
        is_relevant=is_relevant,
        confidence=confidence,
        topic_match=topic_match,
        must_have_match=must_have_match,
        exclude_match=exclude_match,
        matched_aspects=matched_aspects,
        reason=reason,
    )


def _normalize_judge_vote_json(raw: str) -> str:
    text = strip_json_wrapper(raw)
    for field in ("confidence", "topic_match", "must_have_match", "exclude_match"):
        text = _quote_relaxed_enum_value(text, field)
        text = _unquote_null_like_value(text, field)
    return text


def _quote_relaxed_enum_value(text: str, field: str) -> str:
    pattern = re.compile(rf'("{re.escape(field)}"\s*:\s*)([A-Za-z_][A-Za-z0-9_-]*)(\s*[,}}])')

    def repl(match: re.Match[str]) -> str:
        prefix, value, suffix = match.groups()
        if value in {"true", "false", "null"}:
            return match.group(0)
        return f'{prefix}"{value}"{suffix}'

    return pattern.sub(repl, text)


def _unquote_null_like_value(text: str, field: str) -> str:
    pattern = re.compile(rf'("{re.escape(field)}"\s*:\s*)"(?i:null|none|n/a|na)"')
    return pattern.sub(r"\1null", text)


def _normalize_vote_enum(value):
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip().strip('"').strip("'").lower()
        if normalized in {"", "null", "none", "n/a", "na"}:
            return None
        return normalized
    return value
