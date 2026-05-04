from .base import LLMProvider


def get_provider(config: dict) -> LLMProvider:
    """Factory: return the configured LLM provider."""
    llm_config = config.get("llm", {})
    provider_name = llm_config.get("provider", "claude")

    if provider_name == "claude":
        from .claude_provider import ClaudeProvider

        return ClaudeProvider(model=llm_config.get("model", "claude-sonnet-4-20250514"))
    if provider_name == "openai_compatible":
        from .openai_provider import OpenAICompatibleProvider

        return OpenAICompatibleProvider(
            model=llm_config.get("model", "gpt-4o"),
            base_url=llm_config.get("base_url"),
        )

    raise ValueError(f"Unknown LLM provider: {provider_name}")
