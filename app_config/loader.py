from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from analysis.config import parse_content_analysis_config
from scoring.config import (
    parse_abstract_selection_config,
    parse_candidate_scoring_config,
)

from .schema import (
    DEFAULT_EMAIL_FROM,
    AccessConfig,
    AppConfig,
    EmailConfig,
    InterestProfileQueryConfig,
    LLMConfig,
    RetentionConfig,
    ScheduleConfig,
    UserConfig,
)

logger = logging.getLogger(__name__)

ALLOWED_TOP_LEVEL_KEYS = {
    "user",
    "schedule",
    "sources",
    "time_range_hours",
    "llm",
    "email",
    "output_dir",
    "access",
    "interest_profile_query",
    "retention",
    "content_analysis",
    "abstract_selection",
    "candidate_scoring",
}
LEGACY_INTEREST_FIELDS = {"interest_description", "topics", "must_have", "exclude"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SIMPLE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def load_app_config(path: str) -> AppConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return app_config_from_dict(raw, config_path=path)


def app_config_from_dict(raw: dict, *, config_path: str = "config.json") -> AppConfig:
    if not isinstance(raw, dict):
        raise ValueError("Config root must be an object")

    raw = dict(raw)
    if "relevance_scoring" in raw:
        logger.warning("Ignoring deprecated config field 'relevance_scoring'; it is no longer used by the runtime.")
        raw.pop("relevance_scoring", None)

    legacy_interest_fields = sorted(set(raw) & LEGACY_INTEREST_FIELDS)
    if legacy_interest_fields:
        raise ValueError(
            "Interest fields must be stored in instances/<instance>/interest_profile.json, "
            f"not config.json: {', '.join(legacy_interest_fields)}"
        )

    unknown_top_level = sorted(set(raw) - ALLOWED_TOP_LEVEL_KEYS)
    if unknown_top_level:
        raise ValueError(f"Unknown top-level config field(s): {', '.join(unknown_top_level)}")

    user_raw = raw.get("user") or {}
    schedule_raw = raw.get("schedule") or {}
    llm_raw = raw.get("llm") or {}
    email_raw = raw.get("email") or {}
    access_raw = raw.get("access") or {}
    sources_raw = raw.get("sources") or {}
    interest_profile_query_raw = raw.get("interest_profile_query") or {}
    retention_raw = raw.get("retention") or {}
    content_analysis_raw = raw.get("content_analysis") or {}
    abstract_selection_raw = raw.get("abstract_selection") or {}
    candidate_scoring_raw = raw.get("candidate_scoring") or {}

    user_name = str(user_raw.get("name", "")).strip()
    if not user_name:
        raise ValueError("user.name is required")
    if not SIMPLE_NAME_RE.match(user_name):
        raise ValueError("user.name may only contain letters, digits, '-' and '_'")

    cron = str(schedule_raw.get("cron", "0 8 * * *")).strip()
    _validate_cron(cron)

    timezone = str(schedule_raw.get("timezone", "Asia/Hong_Kong")).strip() or "Asia/Hong_Kong"
    if timezone not in {"Asia/Hong_Kong", "UTC"}:
        raise ValueError("schedule.timezone must be 'Asia/Hong_Kong' or 'UTC'")

    run_on_start = bool(schedule_raw.get("run_on_start", False))

    time_range_hours = raw.get("time_range_hours", 24)
    if not isinstance(time_range_hours, int) or time_range_hours <= 0:
        raise ValueError("time_range_hours must be a positive integer")

    provider = str(llm_raw.get("provider", "claude")).strip() or "claude"
    if provider not in {"claude", "openai_compatible"}:
        raise ValueError("llm.provider must be 'claude' or 'openai_compatible'")

    model = str(llm_raw.get("model", "")).strip()
    if not model:
        raise ValueError("llm.model is required")

    base_url = llm_raw.get("base_url")
    if base_url is not None:
        base_url = str(base_url).strip() or None

    recipient = str(email_raw.get("recipient", "")).strip()
    if not recipient or not EMAIL_RE.match(recipient):
        raise ValueError("email.recipient must be a valid email address")

    from_address = str(email_raw.get("from", DEFAULT_EMAIL_FROM)).strip()
    if not from_address or "@" not in from_address:
        raise ValueError("email.from must be a valid sender string")

    send_empty_notification = bool(email_raw.get("send_empty_notification", True))

    output_dir = str(raw.get("output_dir") or f"output/{user_name}").strip()
    if not output_dir:
        raise ValueError("output_dir must not be empty")
    _validate_output_dir(output_dir, config_path=config_path)

    access_mode = str(access_raw.get("mode", "open_access")).strip() or "open_access"
    if access_mode == "authenticated":
        raise ValueError("access.mode='authenticated' is not implemented yet; use 'open_access'")
    if access_mode != "open_access":
        raise ValueError("access.mode must be 'open_access'")
    auth_profile = access_raw.get("auth_profile")
    if auth_profile is not None:
        auth_profile = str(auth_profile).strip() or None

    if not isinstance(interest_profile_query_raw, dict):
        raise ValueError("interest_profile_query must be an object")
    expand_synonyms = bool(interest_profile_query_raw.get("expand_synonyms", True))
    max_query_synonyms = interest_profile_query_raw.get("max_query_synonyms", 3)
    if not isinstance(max_query_synonyms, int) or max_query_synonyms < 0:
        raise ValueError("interest_profile_query.max_query_synonyms must be a non-negative integer")

    if not isinstance(retention_raw, dict):
        raise ValueError("retention must be an object")
    retention_days = retention_raw.get("days", 30)
    if not isinstance(retention_days, int) or retention_days <= 0:
        raise ValueError("retention.days must be a positive integer")

    if not isinstance(candidate_scoring_raw, dict):
        raise ValueError("candidate_scoring must be an object")
    if not isinstance(abstract_selection_raw, dict):
        raise ValueError("abstract_selection must be an object")

    candidate_scoring = parse_candidate_scoring_config(candidate_scoring_raw)
    llm_config = LLMConfig(provider=provider, model=model, base_url=base_url)
    abstract_selection = parse_abstract_selection_config(abstract_selection_raw, llm_config)
    content_analysis = parse_content_analysis_config(content_analysis_raw)

    if not isinstance(sources_raw, dict):
        raise ValueError("sources must be an object")
    normalized_sources = {}
    for source_name, source_cfg in sources_raw.items():
        if not isinstance(source_cfg, dict):
            raise ValueError(f"sources.{source_name} must be an object")
        normalized_sources[source_name] = source_cfg

    config = AppConfig(
        user=UserConfig(name=user_name),
        schedule=ScheduleConfig(cron=cron, timezone=timezone, run_on_start=run_on_start),
        sources=normalized_sources,
        time_range_hours=time_range_hours,
        llm=llm_config,
        email=EmailConfig(
            recipient=recipient,
            from_address=from_address,
            send_empty_notification=send_empty_notification,
        ),
        output_dir=output_dir,
        access=AccessConfig(mode=access_mode, auth_profile=auth_profile),
        interest_profile_query=InterestProfileQueryConfig(
            expand_synonyms=expand_synonyms,
            max_query_synonyms=max_query_synonyms,
        ),
        retention=RetentionConfig(days=retention_days),
        content_analysis=content_analysis,
        abstract_selection=abstract_selection,
        candidate_scoring=candidate_scoring,
    )
    setattr(config, "config_path", str(Path(config_path).resolve()))
    return config


def _validate_cron(expr: str) -> None:
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError("schedule.cron must contain exactly 5 fields")
    allowed = re.compile(r"^[0-9*/,\-]+$")
    for part in parts:
        if not allowed.match(part):
            raise ValueError(f"schedule.cron contains invalid field: {part}")


def _validate_output_dir(output_dir: str, *, config_path: str) -> None:
    path = resolve_output_dir_path(output_dir, config_path=config_path)
    _validate_output_dir_location(path, config_path=config_path)
    parent = path if path.exists() and path.is_dir() else path.parent
    if not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)
    if not os.access(parent, os.W_OK):
        raise ValueError(f"output_dir parent is not writable: {parent}")


def resolve_output_dir_path(output_dir: str, *, config_path: str) -> Path:
    path = Path(output_dir)
    if path.is_absolute():
        return path

    config_base = Path(config_path).resolve().parent
    if config_base.name == "instance":
        return config_base.parent / path
    instances_root = _find_instances_root(config_base)
    project_base = instances_root.parent if instances_root is not None else config_base
    return project_base / path


def resolve_interest_profile_path(*, config_path: str) -> Path:
    return Path(config_path).resolve().parent / "interest_profile.json"


def _find_instances_root(path: Path) -> Path | None:
    for candidate in [path, *path.parents]:
        if candidate.name == "instances":
            return candidate
    return None


def _validate_output_dir_location(path: Path, *, config_path: str) -> None:
    path = path.resolve()
    config_base = Path(config_path).resolve().parent

    protected_roots: list[Path] = []
    if config_base.name == "instance":
        protected_roots.append(config_base)

    instances_root = _find_instances_root(config_base)
    if instances_root is not None:
        protected_roots.append(instances_root)

    for root in protected_roots:
        try:
            path.relative_to(root)
        except ValueError:
            continue
        raise ValueError(
            f"output_dir must resolve outside the instance definition tree ({root}); use output/<name>"
        )
