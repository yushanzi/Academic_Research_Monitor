from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Abstract interface for LLM providers."""

    @abstractmethod
    def complete(self, prompt: str, system: str = "") -> str:
        """Send a prompt and return the text response."""
        raise NotImplementedError
