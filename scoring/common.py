from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable

from json_utils import extract_json_object_text
from llm.base import LLMProvider

logger = logging.getLogger(__name__)

MAX_LLM_ATTEMPTS = 3
RETRY_BASE_DELAY_SECONDS = 2


def strip_json_wrapper(raw: str) -> str:
    return extract_json_object_text(raw)


def log_bad_response(context: str, raw: str, error: Exception) -> None:
    snippet = raw.strip().replace("\n", " ")
    if len(snippet) > 300:
        snippet = snippet[:300] + "..."
    logger.warning("%s: invalid LLM response (%s). Raw snippet: %s", context, error, snippet)


def complete_json(
    provider: LLMProvider,
    prompt: str,
    parser: Callable[[str], Any],
    *,
    system: str,
    context: str,
):
    last_error = None

    for attempt in range(1, MAX_LLM_ATTEMPTS + 1):
        raw = ""
        try:
            raw = provider.complete(prompt, system=system)
            return parser(raw)
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            last_error = exc
            log_bad_response(f"{context} attempt {attempt}", raw, exc)
        except Exception as exc:
            last_error = exc
            logger.warning("%s attempt %s failed: %s", context, attempt, exc)

        if attempt < MAX_LLM_ATTEMPTS:
            delay = RETRY_BASE_DELAY_SECONDS * attempt
            logger.info("%s retrying in %ss", context, delay)
            time.sleep(delay)

    raise RuntimeError(f"{context} failed after {MAX_LLM_ATTEMPTS} attempts") from last_error


def parse_score_value(data: dict[str, Any], field_name: str, *, allow_null: bool) -> int | None:
    value = data.get(field_name)
    if value is None:
        if allow_null:
            return None
        raise ValueError(f"{field_name} must be 0, 1, or 2")
    if isinstance(value, bool) or not isinstance(value, int) or value not in {0, 1, 2}:
        raise ValueError(f"{field_name} must be 0, 1, or 2")
    return value


def parse_matched_aspects_and_reason(data: dict[str, Any], *, context: str) -> tuple[list[str], str]:
    matched_aspects = data.get("matched_aspects") or []
    if not isinstance(matched_aspects, list):
        raise ValueError(f"{context}.matched_aspects must be a list")
    reason = str(data.get("reason", "")).strip()
    if not reason:
        raise ValueError(f"{context}.reason must be a non-empty string")
    normalized_aspects = [str(item).strip() for item in matched_aspects if str(item).strip()]
    return normalized_aspects, reason
