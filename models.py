from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


@dataclass
class InterestProfile:
    core_topics: list[str] = field(default_factory=list)
    synonyms: list[str] = field(default_factory=list)
    must_have: list[str] = field(default_factory=list)
    nice_to_have: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RelevanceResult:
    is_relevant: bool
    relevance_score: float
    matched_aspects: list[str]
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AccessInfo:
    landing_page_url: str = ""
    entry_url: str = ""
    download_url: str = ""
    full_text_available: bool = False
    full_text: str = ""
    open_access: bool = False
    effective_access_mode: str = "abstract_only"
    evidence_level: str = "abstract_only"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Paper:
    title: str
    authors: list[str] = field(default_factory=list)
    abstract: str = ""
    date: str = ""
    url: str = ""
    source: str = ""
    doi: str = ""
    pdf_url: str = ""
    landing_page_url: str = ""
    entry_url: str = ""
    download_url: str = ""
    full_text_available: bool = False
    full_text: str = ""
    open_access: bool = False
    effective_access_mode: str = "abstract_only"
    evidence_level: str = "abstract_only"
    matched_topics: list[str] = field(default_factory=list)
    analysis: dict[str, Any] = field(default_factory=dict)
    relevance: RelevanceResult | dict[str, Any] | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Paper":
        authors = raw.get("authors") or []
        if isinstance(authors, str):
            authors = [authors]
        matched_topics = raw.get("matched_topics") or []
        if isinstance(matched_topics, str):
            matched_topics = [matched_topics]
        return cls(
            title=str(raw.get("title", "")),
            authors=[str(author) for author in authors],
            abstract=str(raw.get("abstract", "")),
            date=str(raw.get("date", "")),
            url=str(raw.get("url", "")),
            source=str(raw.get("source", "")),
            doi=str(raw.get("doi", "")),
            pdf_url=str(raw.get("pdf_url", "")),
            landing_page_url=str(raw.get("landing_page_url", "")),
            entry_url=str(raw.get("entry_url", "")),
            download_url=str(raw.get("download_url", "")),
            full_text_available=bool(raw.get("full_text_available", False)),
            full_text=str(raw.get("full_text", "")),
            open_access=bool(raw.get("open_access", False)),
            effective_access_mode=str(raw.get("effective_access_mode", "abstract_only")),
            evidence_level=str(raw.get("evidence_level", "abstract_only")),
            matched_topics=[str(topic) for topic in matched_topics],
            analysis=dict(raw.get("analysis") or {}),
            relevance=raw.get("relevance"),
        )

    def apply_access_info(self, access_info: AccessInfo) -> None:
        self.landing_page_url = access_info.landing_page_url
        self.entry_url = access_info.entry_url
        self.download_url = access_info.download_url
        self.full_text_available = access_info.full_text_available
        self.full_text = access_info.full_text
        self.open_access = access_info.open_access
        self.effective_access_mode = access_info.effective_access_mode
        self.evidence_level = access_info.evidence_level


def ensure_paper(raw: Paper | Mapping[str, Any]) -> Paper:
    if isinstance(raw, Paper):
        return raw
    return Paper.from_dict(raw)
