from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_EMAIL_FROM = "Academic Monitor <onboarding@resend.dev>"
ALLOWED_TOP_LEVEL_KEYS = {
    "user",
    "schedule",
    "sources",
    "interest_description",
    "topics",
    "time_range_hours",
    "llm",
    "email",
    "output_dir",
    "access",
}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SIMPLE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass
class UserConfig:
    name: str


@dataclass
class ScheduleConfig:
    cron: str = "0 8 * * *"
    timezone: str = "UTC"
    run_on_start: bool = False


@dataclass
class LLMConfig:
    provider: str = "claude"
    model: str = ""
    base_url: str | None = None


@dataclass
class EmailConfig:
    recipient: str = ""
    from_address: str = DEFAULT_EMAIL_FROM


@dataclass
class AccessConfig:
    mode: str = "open_access"
    auth_profile: str | None = None


@dataclass
class AppConfig:
    user: UserConfig
    schedule: ScheduleConfig
    sources: dict[str, dict]
    interest_description: str | None = None
    topics: list[str] = field(default_factory=list)
    time_range_hours: int = 24
    llm: LLMConfig = field(default_factory=LLMConfig)
    email: EmailConfig = field(default_factory=EmailConfig)
    output_dir: str = ""
    access: AccessConfig = field(default_factory=AccessConfig)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["email"]["from"] = data["email"].pop("from_address")
        return data


def load_app_config(path: str) -> AppConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return app_config_from_dict(raw, config_path=path)


def app_config_from_dict(raw: dict, *, config_path: str = "config.json") -> AppConfig:
    if not isinstance(raw, dict):
        raise ValueError("Config root must be an object")

    unknown_top_level = sorted(set(raw) - ALLOWED_TOP_LEVEL_KEYS)
    if unknown_top_level:
        raise ValueError(f"Unknown top-level config field(s): {', '.join(unknown_top_level)}")

    user_raw = raw.get("user") or {}
    schedule_raw = raw.get("schedule") or {}
    llm_raw = raw.get("llm") or {}
    email_raw = raw.get("email") or {}
    access_raw = raw.get("access") or {}
    sources_raw = raw.get("sources") or {}

    user_name = str(user_raw.get("name", "")).strip()
    if not user_name:
        raise ValueError("user.name is required")
    if not SIMPLE_NAME_RE.match(user_name):
        raise ValueError("user.name may only contain letters, digits, '-' and '_'")

    cron = str(schedule_raw.get("cron", "0 8 * * *")).strip()
    _validate_cron(cron)

    timezone = str(schedule_raw.get("timezone", "UTC")).strip() or "UTC"
    if timezone != "UTC":
        raise ValueError("schedule.timezone must be 'UTC' in v1")

    run_on_start = bool(schedule_raw.get("run_on_start", False))

    interest_description = raw.get("interest_description")
    if interest_description is not None:
        interest_description = str(interest_description).strip() or None

    topics = raw.get("topics") or []
    if not isinstance(topics, list):
        raise ValueError("topics must be a list of strings")
    topics = [str(topic).strip() for topic in topics if str(topic).strip()]

    if not topics and not interest_description:
        raise ValueError("At least one of topics or interest_description must be provided")

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

    if not isinstance(sources_raw, dict):
        raise ValueError("sources must be an object")
    normalized_sources = {}
    for source_name, source_cfg in sources_raw.items():
        if not isinstance(source_cfg, dict):
            raise ValueError(f"sources.{source_name} must be an object")
        normalized_sources[source_name] = source_cfg

    return AppConfig(
        user=UserConfig(name=user_name),
        schedule=ScheduleConfig(cron=cron, timezone=timezone, run_on_start=run_on_start),
        sources=normalized_sources,
        interest_description=interest_description,
        topics=topics,
        time_range_hours=time_range_hours,
        llm=LLMConfig(provider=provider, model=model, base_url=base_url),
        email=EmailConfig(recipient=recipient, from_address=from_address),
        output_dir=output_dir,
        access=AccessConfig(mode=access_mode, auth_profile=auth_profile),
    )


def _validate_cron(expr: str) -> None:
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError("schedule.cron must contain exactly 5 fields")
    allowed = re.compile(r"^[0-9*/,\-]+$")
    for part in parts:
        if not allowed.match(part):
            raise ValueError(f"schedule.cron contains invalid field: {part}")


def _validate_output_dir(output_dir: str, *, config_path: str) -> None:
    config_base = Path(config_path).resolve().parent
    path = Path(output_dir)
    if not path.is_absolute():
        path = config_base / path
    parent = path if path.exists() and path.is_dir() else path.parent
    if not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)
    if not os.access(parent, os.W_OK):
        raise ValueError(f"output_dir parent is not writable: {parent}")
