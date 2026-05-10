from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

from json_utils import parse_json_object
from llm.base import LLMProvider
from models import InterestProfile
from app_config.loader import resolve_interest_profile_path

logger = logging.getLogger(__name__)

PROMPT_VERSION = "interest-profile-v4"
SCHEMA_VERSION = "interest-profile-schema-v3"
PARSER_VERSION = "interest-profile-parser-v1"
SYSTEM_PROMPT = "You are an academic research assistant. Always respond in valid JSON."
PROMPT = """Build a compact research-interest profile from the following user intent.

Interest description:
{interest_description}

Topic hints:
{topics}

Respond in JSON with exactly these keys:
- core_topics: array of 3-8 key topics
- synonyms: array of related keywords or phrases
- summary: concise English summary

JSON only, no markdown fences."""


def load_or_create_interest_profile(
    config,
    provider: LLMProvider | None = None,
    *,
    config_path: str | None = None,
) -> InterestProfile:
    del provider  # runtime no longer generates profiles; the file must already exist

    profile_path = _resolve_runtime_profile_path(config, config_path=config_path)
    if not profile_path.exists():
        raise RuntimeError(
            f"Missing required interest profile file: {profile_path}. "
            "Generate it from a user interest document before running this instance."
        )

    with open(profile_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    if not isinstance(payload, dict):
        raise RuntimeError(f"Invalid interest profile file: {profile_path}")
    if payload.get("confirmed") is not True:
        raise RuntimeError(
            f"Interest profile is not confirmed for this instance: {profile_path}. "
            "Confirm the profile before starting the container."
        )
    if not isinstance(payload.get("profile"), dict):
        raise RuntimeError(f"Invalid interest profile payload in {profile_path}: missing profile object")

    try:
        return parse_interest_profile(payload["profile"])
    except Exception as exc:
        raise RuntimeError(f"Invalid interest profile payload in {profile_path}: {exc}") from exc


def build_profile_fingerprint(profile: InterestProfile | dict) -> str:
    if isinstance(profile, InterestProfile):
        material = profile.to_dict()
    elif isinstance(profile, dict) and "profile" in profile:
        material = profile["profile"]
    else:
        material = profile
    raw = json.dumps(material, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_interest_profile_payload(
    profile: InterestProfile,
    *,
    confirmed: bool = True,
    source: str = "generated_from_document",
) -> dict:
    return {
        "confirmed": confirmed,
        "source": source,
        "fingerprint": build_profile_fingerprint(profile),
        "versions": {
            "prompt_version": PROMPT_VERSION,
            "schema_version": SCHEMA_VERSION,
            "parser_version": PARSER_VERSION,
        },
        "profile": profile.to_dict(),
    }


def write_interest_profile(profile_path: str | Path, payload: dict) -> None:
    path = Path(profile_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def generate_interest_profile(
    *,
    interest_description: str | None,
    topics: list[str],
    must_have: list[str] | None = None,
    exclude: list[str] | None = None,
    provider: LLMProvider | None = None,
) -> InterestProfile:
    must_have = list(must_have or [])
    exclude = list(exclude or [])
    if provider and interest_description:
        try:
            raw = provider.complete(
                PROMPT.format(
                    interest_description=interest_description,
                    topics=", ".join(topics) if topics else "None",
                ),
                system=SYSTEM_PROMPT,
            )
            generated = parse_interest_profile(_extract_json(raw))
            generated.must_have = must_have
            generated.exclude = exclude
            return generated
        except Exception as exc:
            logger.warning("Falling back to heuristic interest profile: %s", exc)
    return build_simple_interest_profile(
        interest_description=interest_description,
        topics=topics,
        must_have=must_have,
        exclude=exclude,
    )


def build_simple_interest_profile(
    *,
    interest_description: str | None,
    topics: list[str],
    must_have: list[str] | None = None,
    exclude: list[str] | None = None,
) -> InterestProfile:
    core_topics = list(dict.fromkeys(topics))
    summary_parts = []
    if interest_description:
        summary_parts.append(interest_description.strip())
    if core_topics:
        summary_parts.append("Focus topics: " + ", ".join(core_topics))
    return InterestProfile(
        core_topics=core_topics,
        synonyms=[],
        must_have=list(must_have or []),
        nice_to_have=[],
        exclude=list(exclude or []),
        summary="; ".join(summary_parts) if summary_parts else "Simplified interest profile generated from topics.",
    )


def select_query_synonyms(
    profile: InterestProfile,
    *,
    existing_topics: list[str] | None = None,
    limit: int = 3,
) -> list[str]:
    if limit <= 0:
        return []

    seen = {
        _normalize_topic_for_query(item)
        for item in (profile.core_topics + (existing_topics or []))
        if _normalize_topic_for_query(item)
    }
    selected: list[str] = []
    for synonym in profile.synonyms:
        normalized = _normalize_topic_for_query(synonym)
        if not normalized or normalized in seen:
            continue
        words = normalized.split()
        if len(words) < 2:
            continue
        if len(normalized) < 10:
            continue
        selected.append(synonym.strip())
        seen.add(normalized)
        if len(selected) >= limit:
            break
    return selected


def parse_interest_profile(raw: dict | str) -> InterestProfile:
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, dict):
        raise ValueError("interest profile must be a JSON object")

    def normalize_list(name: str) -> list[str]:
        value = raw.get(name, [])
        if not isinstance(value, list):
            raise ValueError(f"interest profile field '{name}' must be a list")
        return [str(item).strip() for item in value if str(item).strip()]

    summary = str(raw.get("summary", "")).strip()
    return InterestProfile(
        core_topics=normalize_list("core_topics"),
        synonyms=normalize_list("synonyms"),
        must_have=normalize_list("must_have"),
        nice_to_have=normalize_list("nice_to_have"),
        exclude=normalize_list("exclude"),
        summary=summary,
    )


def _extract_json(raw: str) -> dict:
    return parse_json_object(raw)


def _normalize_topic_for_query(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()


def _resolve_runtime_profile_path(config: AppConfig, *, config_path: str | None) -> Path:
    config_path = config_path or getattr(config, "config_path", None)
    if config_path:
        return resolve_interest_profile_path(config_path=config_path)
    return Path(config.output_dir) / "interest_profile.json"
