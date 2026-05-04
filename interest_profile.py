from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

from config_schema import AppConfig
from json_utils import parse_json_object
from llm.base import LLMProvider
from models import InterestProfile

logger = logging.getLogger(__name__)

PROMPT_VERSION = "interest-profile-v1"
SCHEMA_VERSION = "interest-profile-schema-v1"
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
- must_have: array of high-signal requirements
- nice_to_have: array of positive but optional traits
- exclude: array of phrases or concepts to avoid
- summary: concise Chinese summary

JSON only, no markdown fences."""


def load_or_create_interest_profile(config: AppConfig, provider: LLMProvider | None = None) -> InterestProfile:
    os.makedirs(config.output_dir, exist_ok=True)
    cache_path = Path(config.output_dir) / "interest_profile.json"
    fingerprint = build_profile_fingerprint(config)

    if cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if cached.get("fingerprint") == fingerprint:
                return parse_interest_profile(cached.get("profile", {}))
        except Exception as exc:
            logger.warning("Failed to load cached interest profile: %s", exc)

    profile = generate_interest_profile(config, provider)
    payload = {
        "fingerprint": fingerprint,
        "versions": {
            "prompt_version": PROMPT_VERSION,
            "schema_version": SCHEMA_VERSION,
            "parser_version": PARSER_VERSION,
        },
        "profile": profile.to_dict(),
    }
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return profile


def build_profile_fingerprint(config: AppConfig) -> str:
    material = {
        "interest_description": config.interest_description,
        "topics": config.topics,
        "llm_provider": config.llm.provider,
        "llm_model": config.llm.model,
        "llm_base_url": config.llm.base_url,
        "prompt_version": PROMPT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "parser_version": PARSER_VERSION,
    }
    raw = json.dumps(material, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_interest_profile(config: AppConfig, provider: LLMProvider | None = None) -> InterestProfile:
    if provider and config.interest_description:
        try:
            raw = provider.complete(
                PROMPT.format(
                    interest_description=config.interest_description,
                    topics="、".join(config.topics) if config.topics else "无",
                ),
                system=SYSTEM_PROMPT,
            )
            return parse_interest_profile(_extract_json(raw))
        except Exception as exc:
            logger.warning("Falling back to heuristic interest profile: %s", exc)
    return build_simple_interest_profile(config)


def build_simple_interest_profile(config: AppConfig) -> InterestProfile:
    core_topics = list(dict.fromkeys(config.topics))
    summary_parts = []
    if config.interest_description:
        summary_parts.append(config.interest_description.strip())
    if core_topics:
        summary_parts.append("关注主题：" + "、".join(core_topics))
    return InterestProfile(
        core_topics=core_topics,
        synonyms=[],
        must_have=core_topics[:3],
        nice_to_have=[],
        exclude=[],
        summary="；".join(summary_parts) if summary_parts else "基于 topics 生成的简化兴趣画像。",
    )


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
