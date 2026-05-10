from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ContentAnalysisLLMConfig:
    provider: str
    model: str
    base_url: str | None = None


@dataclass
class ContentAnalysisConfig:
    llm: ContentAnalysisLLMConfig | None = None


def parse_content_analysis_config(raw: dict) -> ContentAnalysisConfig:
    if not raw:
        return ContentAnalysisConfig()
    if not isinstance(raw, dict):
        raise ValueError("content_analysis must be an object")

    llm_raw = raw.get("llm")
    if llm_raw is None:
        return ContentAnalysisConfig()
    if not isinstance(llm_raw, dict):
        raise ValueError("content_analysis.llm must be an object")

    provider = str(llm_raw.get("provider", "")).strip()
    model = str(llm_raw.get("model", "")).strip()
    if provider not in {"claude", "openai_compatible"}:
        raise ValueError("content_analysis.llm.provider must be 'claude' or 'openai_compatible'")
    if not model:
        raise ValueError("content_analysis.llm.model is required")
    base_url = llm_raw.get("base_url")
    if base_url is not None:
        base_url = str(base_url).strip() or None

    return ContentAnalysisConfig(llm=ContentAnalysisLLMConfig(provider=provider, model=model, base_url=base_url))
