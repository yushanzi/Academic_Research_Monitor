from __future__ import annotations

from typing import Mapping

DEFAULT_CANDIDATE_THRESHOLD = 0.60
DEFAULT_RELEVANCE_THRESHOLD = 0.65
DEFAULT_EXCLUDE_PENALTY_WEIGHT = 0.30

DEFAULT_CANDIDATE_WEIGHTS: dict[str, float] = {
    "topic_match": 0.40,
    "must_have_match": 0.20,
    "evidence_strength": 0.25,
    "focus_specificity": 0.15,
}

DEFAULT_RELEVANCE_WEIGHTS: dict[str, float] = {
    "topic_match": 0.35,
    "must_have_match": 0.20,
    "evidence_quality": 0.20,
    "content_alignment": 0.15,
    "actionability": 0.10,
}

CANDIDATE_WEIGHT_KEYS = tuple(DEFAULT_CANDIDATE_WEIGHTS.keys())
RELEVANCE_WEIGHT_KEYS = tuple(DEFAULT_RELEVANCE_WEIGHTS.keys())


def clamp_score(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def weighted_rubric_score(
    rubric_values: Mapping[str, int | None],
    weights: Mapping[str, float],
    *,
    exclude_match: int | None,
    exclude_penalty_weight: float,
) -> float:
    active_weights = {name: float(weight) for name, weight in weights.items() if rubric_values.get(name) is not None}
    if not active_weights:
        return 0.0

    positive_weight_sum = sum(active_weights.values())
    if positive_weight_sum <= 0:
        return 0.0

    positive_raw = 0.0
    for name, weight in active_weights.items():
        value = rubric_values[name]
        if value is None:
            continue
        positive_raw += weight * (int(value) / 2.0)
    positive_score = positive_raw / positive_weight_sum

    penalty = 0.0
    if exclude_match is not None:
        penalty = float(exclude_penalty_weight) * (int(exclude_match) / 2.0)

    return clamp_score(positive_score - penalty)
