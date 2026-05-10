from __future__ import annotations

import copy
import logging
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from interest_profile import build_interest_profile_payload, generate_interest_profile, write_interest_profile
from json_utils import parse_json_object
from llm import get_provider_from_llm_config

from .loader import app_config_from_dict, resolve_interest_profile_path

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = "You generate editable monitoring configs. Always respond in valid JSON."
PROMPT = """You are helping turn a free-form research-interest document into an editable monitoring config draft.

Read the user document and extract the core monitoring intent. Output JSON with exactly these fields:
- interest_description: a concise 1-3 sentence summary in English
- topics: an array of 3-10 topic keywords or short phrases
- must_have: an array of conditions the user explicitly wants to prioritize or require; use [] if none
- exclude: an array of conditions the user explicitly wants to exclude; use [] if none

Requirements:
1. Do not invent hard constraints the user did not express.
2. Keep topics specific and useful for search.
3. If the document is broad, still provide a concise English interest_description.
4. Output JSON only, with no markdown.

User document:
{document}
"""

ONBOARDING_LLM_CONFIG = {
    "provider": "openai_compatible",
    "model": "gemini-3-flash",
    "base_url": "https://api.poe.com/v1",
}

SECTION_ALIASES = {
    "topics": {"topic", "topics", "主题", "方向", "兴趣方向", "研究方向", "关注主题"},
    "must_have": {"must have", "must-have", "must_have", "必须", "必须有", "必备", "重点关注", "优先关注", "必须包含"},
    "exclude": {"exclude", "excludes", "排除", "不看", "忽略", "不要", "排除项"},
}


def load_document_text(path: str) -> str:
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    if suffix == ".docx":
        return _load_docx_text(file_path)
    return file_path.read_text(encoding="utf-8").strip()


def build_config_from_document(
    *,
    template: dict,
    document_text: str,
    config_path: str,
    user_name: str | None = None,
    email_recipient: str | None = None,
    provider=None,
) -> dict:
    config = copy.deepcopy(template)
    _apply_identity_defaults(config, user_name=user_name, email_recipient=email_recipient)
    config.pop("interest_profile_confirmed", None)

    resolved_provider = provider or _resolve_provider()
    intent = interpret_user_document(document_text, provider=resolved_provider)
    validated = app_config_from_dict(config, config_path=config_path)
    generated_profile = generate_interest_profile(
        interest_description=intent["interest_description"],
        topics=intent["topics"],
        must_have=intent["must_have"],
        exclude=intent["exclude"],
        provider=resolved_provider,
    )
    profile_payload = build_interest_profile_payload(generated_profile, confirmed=True, source="generated_from_document")

    profile_path = resolve_interest_profile_path(config_path=config_path)
    write_interest_profile(profile_path, profile_payload)
    return validated.to_dict()


def interpret_user_document(document_text: str, *, provider=None) -> dict:
    cleaned = document_text.strip()
    if not cleaned:
        raise ValueError("Input document is empty")

    provider = provider or _resolve_provider()

    if provider is not None:
        try:
            raw = provider.complete(PROMPT.format(document=cleaned), system=SYSTEM_PROMPT)
            return _normalize_intent_payload(parse_json_object(raw), fallback_text=cleaned)
        except Exception as exc:
            logger.warning("Failed to parse user document with LLM, falling back to heuristic parsing: %s", exc)

    return _heuristic_intent_from_document(cleaned)


def _resolve_provider():
    try:
        return get_provider_from_llm_config(ONBOARDING_LLM_CONFIG)
    except Exception as exc:
        logger.warning("Failed to initialize onboarding LLM provider, falling back to heuristic parsing: %s", exc)
        return None


def _apply_identity_defaults(config: dict, *, user_name: str | None, email_recipient: str | None) -> None:
    config.setdefault("user", {})
    config.setdefault("email", {})

    actual_user_name = _normalize_user_name(user_name or config["user"].get("name") or "my-monitor")
    config["user"]["name"] = actual_user_name
    if email_recipient:
        config["email"]["recipient"] = email_recipient

    output_dir = str(config.get("output_dir") or "").strip()
    if not output_dir or output_dir == "output/my-monitor":
        config["output_dir"] = f"output/{actual_user_name}"


def _normalize_user_name(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip()).strip("-")
    return normalized or "my-monitor"


def _normalize_intent_payload(payload: dict, *, fallback_text: str) -> dict:
    def normalize_list(name: str) -> list[str]:
        value = payload.get(name) or []
        if not isinstance(value, list):
            return []
        items = []
        for item in value:
            text = str(item).strip()
            if text and text not in items:
                items.append(text)
        return items

    interest_description = str(payload.get("interest_description", "")).strip()
    if not interest_description:
        interest_description = _build_summary_from_text(fallback_text)

    topics = normalize_list("topics")
    must_have = normalize_list("must_have")
    exclude = normalize_list("exclude")

    return {
        "interest_description": interest_description,
        "topics": topics,
        "must_have": must_have,
        "exclude": exclude,
    }


def _heuristic_intent_from_document(document_text: str) -> dict:
    sections = {"topics": [], "must_have": [], "exclude": []}
    freeform_lines: list[str] = []
    active_section: str | None = None

    for raw_line in document_text.splitlines():
        line = raw_line.strip()
        if not line:
            active_section = None
            continue

        section_name, inline_value = _match_section_line(line)
        if section_name:
            active_section = section_name
            if inline_value:
                sections[section_name].extend(_split_items(inline_value))
            continue

        item_value = _strip_list_marker(line)
        if active_section and item_value:
            sections[active_section].extend(_split_items(item_value))
            continue

        freeform_lines.append(line)

    inferred = _infer_constraints_from_freeform_lines(freeform_lines)
    topics = _dedupe_preserve_order(sections["topics"])
    must_have = _dedupe_preserve_order(sections["must_have"] + inferred["must_have"])
    exclude = _dedupe_preserve_order(sections["exclude"] + inferred["exclude"])

    return {
        "interest_description": _build_heuristic_summary(
            freeform_lines=freeform_lines,
            topics=topics,
            must_have=must_have,
            exclude=exclude,
            original_text=document_text,
        ),
        "topics": topics,
        "must_have": must_have,
        "exclude": exclude,
    }


def _match_section_line(line: str) -> tuple[str | None, str]:
    stripped = _strip_list_marker(line)
    normalized = stripped.lower().replace("：", ":")
    if ":" in normalized:
        label, _inline_value = normalized.split(":", 1)
        original_inline_value = stripped.split("：", 1)[1] if "：" in stripped else stripped.split(":", 1)[1]
    else:
        label = normalized
        original_inline_value = ""

    label = label.strip()
    for section_name, aliases in SECTION_ALIASES.items():
        if label in aliases:
            return section_name, original_inline_value.strip()
    return None, ""


def _split_items(raw: str) -> list[str]:
    parts = re.split(r"[、,;；]\s*", raw.strip())
    return [part for part in (item.strip() for item in parts) if part]


def _strip_list_marker(line: str) -> str:
    return re.sub(r"^[-*•\d.)\s]+", "", line).strip()


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _infer_constraints_from_freeform_lines(lines: list[str]) -> dict[str, list[str]]:
    text = "\n".join(lines).lower()
    must_have: list[str] = []
    exclude: list[str] = []

    if "实验验证" in text or "experimental validation" in text or "wet lab" in text:
        must_have.append("experimental validation")
    if "in vivo" in text:
        must_have.append("in vivo evidence")
    if "review" in text:
        exclude.append("review article")
    if "dataset" in text:
        exclude.append("dataset paper")

    return {"must_have": must_have, "exclude": exclude}


def _build_summary_from_text(text: str) -> str:
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return first_line[:120] if first_line else "User-provided research interest document."


def _build_heuristic_summary(
    *,
    freeform_lines: list[str],
    topics: list[str],
    must_have: list[str],
    exclude: list[str],
    original_text: str,
) -> str:
    parts: list[str] = []
    if freeform_lines:
        parts.append(" ".join(freeform_lines)[:120])
    elif topics:
        parts.append("Focus topics: " + ", ".join(topics[:5]))
    elif original_text.strip():
        parts.append(original_text.strip()[:120])
    if must_have:
        parts.append("Prioritize: " + ", ".join(must_have))
    if exclude:
        parts.append("Exclude: " + ", ".join(exclude))
    return "; ".join(parts)


def _load_docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        xml_data = archive.read("word/document.xml")
    root = ET.fromstring(xml_data)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", ns):
        texts = [node.text or "" for node in paragraph.findall(".//w:t", ns)]
        joined = "".join(texts).strip()
        if joined:
            paragraphs.append(joined)
    return "\n".join(paragraphs).strip()
