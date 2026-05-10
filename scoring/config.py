from __future__ import annotations

from dataclasses import dataclass, field

from .weights import (
    CANDIDATE_WEIGHT_KEYS,
    DEFAULT_CANDIDATE_THRESHOLD,
    DEFAULT_CANDIDATE_WEIGHTS,
    DEFAULT_EXCLUDE_PENALTY_WEIGHT,
    DEFAULT_RELEVANCE_THRESHOLD,
    DEFAULT_RELEVANCE_WEIGHTS,
    RELEVANCE_WEIGHT_KEYS,
)


@dataclass
class CandidateScoringConfig:
    threshold: float = DEFAULT_CANDIDATE_THRESHOLD
    fail_open: bool = False
    exclude_penalty_weight: float = DEFAULT_EXCLUDE_PENALTY_WEIGHT
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_CANDIDATE_WEIGHTS))


@dataclass
class RelevanceScoringConfig:
    threshold: float = DEFAULT_RELEVANCE_THRESHOLD
    exclude_penalty_weight: float = DEFAULT_EXCLUDE_PENALTY_WEIGHT
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_RELEVANCE_WEIGHTS))


@dataclass
class AbstractSelectionJudgeConfig:
    name: str
    provider: str
    model: str
    base_url: str | None = None


@dataclass
class ThreeLLMVotingConfig:
    required_votes: int = 2
    fallback_method: str = "candidate_score"
    judges: list[AbstractSelectionJudgeConfig] = field(default_factory=list)


@dataclass
class AbstractSelectionConfig:
    method: str = "candidate_score"
    three_llm_voting: ThreeLLMVotingConfig = field(default_factory=ThreeLLMVotingConfig)


def parse_candidate_scoring_config(raw: dict) -> CandidateScoringConfig:
    return CandidateScoringConfig(
        threshold=_parse_unit_interval(raw.get("threshold", DEFAULT_CANDIDATE_THRESHOLD), "candidate_scoring.threshold"),
        fail_open=bool(raw.get("fail_open", False)),
        exclude_penalty_weight=_parse_unit_interval(
            raw.get("exclude_penalty_weight", DEFAULT_EXCLUDE_PENALTY_WEIGHT),
            "candidate_scoring.exclude_penalty_weight",
        ),
        weights=_parse_weight_block(
            raw.get("weights"),
            defaults=DEFAULT_CANDIDATE_WEIGHTS,
            allowed_keys=CANDIDATE_WEIGHT_KEYS,
            field_name="candidate_scoring.weights",
        ),
    )


def parse_relevance_scoring_config(raw: dict) -> RelevanceScoringConfig:
    return RelevanceScoringConfig(
        threshold=_parse_unit_interval(raw.get("threshold", DEFAULT_RELEVANCE_THRESHOLD), "relevance_scoring.threshold"),
        exclude_penalty_weight=_parse_unit_interval(
            raw.get("exclude_penalty_weight", DEFAULT_EXCLUDE_PENALTY_WEIGHT),
            "relevance_scoring.exclude_penalty_weight",
        ),
        weights=_parse_weight_block(
            raw.get("weights"),
            defaults=DEFAULT_RELEVANCE_WEIGHTS,
            allowed_keys=RELEVANCE_WEIGHT_KEYS,
            field_name="relevance_scoring.weights",
        ),
    )


def parse_abstract_selection_config(raw: dict, llm_config) -> AbstractSelectionConfig:
    method = str(raw.get("method", "candidate_score")).strip() or "candidate_score"
    if method not in {"three_llm_voting", "candidate_score"}:
        raise ValueError("abstract_selection.method must be 'three_llm_voting' or 'candidate_score'")

    voting_raw = raw.get("three_llm_voting") or {}
    if not isinstance(voting_raw, dict):
        raise ValueError("abstract_selection.three_llm_voting must be an object")

    judges_raw = voting_raw.get("judges")
    if judges_raw is None:
        judges = [
            AbstractSelectionJudgeConfig(
                name=f"judge_{idx}",
                provider=getattr(llm_config, "provider", "claude"),
                model=getattr(llm_config, "model", ""),
                base_url=getattr(llm_config, "base_url", None),
            )
            for idx in range(1, 4)
        ]
    else:
        if not isinstance(judges_raw, list) or not judges_raw:
            raise ValueError("abstract_selection.three_llm_voting.judges must be a non-empty list")
        judges = []
        for index, judge_raw in enumerate(judges_raw):
            if not isinstance(judge_raw, dict):
                raise ValueError(f"abstract_selection.three_llm_voting.judges[{index}] must be an object")
            name = str(judge_raw.get("name", "")).strip()
            provider = str(judge_raw.get("provider", "")).strip()
            model = str(judge_raw.get("model", "")).strip()
            if not name:
                raise ValueError(f"abstract_selection.three_llm_voting.judges[{index}].name is required")
            if provider not in {"claude", "openai_compatible"}:
                raise ValueError(
                    f"abstract_selection.three_llm_voting.judges[{index}].provider must be 'claude' or 'openai_compatible'"
                )
            if not model:
                raise ValueError(f"abstract_selection.three_llm_voting.judges[{index}].model is required")
            base_url = judge_raw.get("base_url")
            if base_url is not None:
                base_url = str(base_url).strip() or None
            judges.append(AbstractSelectionJudgeConfig(name=name, provider=provider, model=model, base_url=base_url))

    required_votes = voting_raw.get("required_votes", 2 if len(judges) >= 2 else 1)
    if not isinstance(required_votes, int) or required_votes < 1:
        raise ValueError("abstract_selection.three_llm_voting.required_votes must be a positive integer")
    if required_votes > len(judges):
        raise ValueError("abstract_selection.three_llm_voting.required_votes must not exceed judge count")

    fallback_method = str(voting_raw.get("fallback_method", "candidate_score")).strip() or "candidate_score"
    if fallback_method != "candidate_score":
        raise ValueError("abstract_selection.three_llm_voting.fallback_method must be 'candidate_score'")

    return AbstractSelectionConfig(
        method=method,
        three_llm_voting=ThreeLLMVotingConfig(
            required_votes=required_votes,
            fallback_method=fallback_method,
            judges=judges,
        ),
    )


def _parse_unit_interval(value, field_name: str) -> float:
    if not isinstance(value, (int, float)) or not 0 <= float(value) <= 1:
        raise ValueError(f"{field_name} must be a number between 0 and 1")
    return float(value)


def _parse_weight_block(
    raw_weights,
    *,
    defaults: dict[str, float],
    allowed_keys: tuple[str, ...],
    field_name: str,
) -> dict[str, float]:
    if raw_weights is None:
        return dict(defaults)
    if not isinstance(raw_weights, dict):
        raise ValueError(f"{field_name} must be an object")

    unknown_keys = sorted(set(raw_weights) - set(allowed_keys))
    if unknown_keys:
        raise ValueError(f"Unknown {field_name} field(s): {', '.join(unknown_keys)}")

    merged = dict(defaults)
    for key in allowed_keys:
        if key in raw_weights:
            merged[key] = _parse_unit_interval(raw_weights[key], f"{field_name}.{key}")

    total = sum(merged.values())
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"{field_name} must sum to 1.0")
    return merged
