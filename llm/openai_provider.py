from __future__ import annotations

import os
import logging

from openai import OpenAI

from .base import LLMProvider

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider(LLMProvider):
    """Works with OpenAI, Poe, and any OpenAI-compatible API endpoint."""

    def __init__(self, model: str = "gpt-4o", base_url: str | None = None):
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required")

        kwargs = {"api_key": api_key}
        actual_base_url = base_url or os.environ.get("OPENAI_BASE_URL")
        if actual_base_url:
            kwargs["base_url"] = actual_base_url

        self.client = OpenAI(**kwargs)
        self.model = model

    def complete(self, prompt: str, system: str = "") -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=2048,
        )
        return response.choices[0].message.content
