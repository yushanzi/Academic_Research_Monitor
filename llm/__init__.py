from .base import LLMProvider


def get_provider(config: dict) -> LLMProvider:
    """Factory: return the configured LLM provider."""
    return get_provider_from_llm_config(config.get("llm", {}))


def get_provider_from_llm_config(llm_config) -> LLMProvider:
    if isinstance(llm_config, dict):
        provider_name = llm_config.get("provider", "claude")
        model = llm_config.get("model", "")
        base_url = llm_config.get("base_url")
    else:
        provider_name = getattr(llm_config, "provider", "claude")
        model = getattr(llm_config, "model", "")
        base_url = getattr(llm_config, "base_url", None)

    if provider_name == "claude":
        from .claude_provider import ClaudeProvider

        return ClaudeProvider(model=model or "claude-sonnet-4-20250514")
    if provider_name == "openai_compatible":
        from .openai_provider import OpenAICompatibleProvider

        return OpenAICompatibleProvider(
            model=model or "gpt-4o",
            base_url=base_url,
        )

    raise ValueError(f"Unknown LLM provider: {provider_name}")
