from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class RelevanceResult:
    is_relevant: bool
    relevance_score: float
    topic_match: int
    must_have_match: int | None
    exclude_match: int | None
    evidence_quality: int
    content_alignment: int
    actionability: int
    matched_aspects: list[str]
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AbstractRelevanceResult:
    is_relevant: bool
    relevance_score: float
    topic_match: int | None
    must_have_match: int | None
    exclude_match: int | None
    evidence_strength: int | None
    focus_specificity: int | None
    matched_aspects: list[str]
    reason: str
    basis: str = "abstract_only"
    report_status: str = "selected"
    method: str = "candidate_score"
    warning_messages: list[str] = field(default_factory=list)
    failed_judges: list[str] = field(default_factory=list)
    degraded: bool = False
    fallback_trigger: str | None = None
    vote_summary: dict[str, Any] = field(default_factory=dict)
    judge_votes: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CandidateGateResult:
    should_exclude: bool
    candidate_score: float
    topic_match: int | None
    must_have_match: int | None
    exclude_match: int | None
    evidence_strength: int | None
    focus_specificity: int | None
    matched_aspects: list[str]
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class JudgeVoteResult:
    judge_name: str
    is_relevant: bool
    confidence: str
    topic_match: str
    must_have_match: str | None
    exclude_match: str | None
    matched_aspects: list[str]
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)
