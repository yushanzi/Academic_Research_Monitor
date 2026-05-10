from __future__ import annotations

from llm import get_provider_from_llm_config
from llm.base import LLMProvider


def resolve_content_analysis_provider(config, root_provider: LLMProvider) -> LLMProvider:
    if getattr(config, "content_analysis", None) and getattr(config.content_analysis, "llm", None):
        return get_provider_from_llm_config(config.content_analysis.llm)
    if config.abstract_selection.method == "three_llm_voting":
        judges = config.abstract_selection.three_llm_voting.judges
        if judges:
            return get_provider_from_llm_config(judges[0])
    return root_provider
