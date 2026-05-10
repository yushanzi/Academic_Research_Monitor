from __future__ import annotations

from dataclasses import asdict, dataclass, field

from analysis.config import ContentAnalysisConfig
from scoring.config import (
    AbstractSelectionConfig,
    CandidateScoringConfig,
)

DEFAULT_EMAIL_FROM = "Academic Monitor <noreply@innoscreen.ai>"


@dataclass
class UserConfig:
    name: str


@dataclass
class ScheduleConfig:
    cron: str = "0 8 * * *"
    timezone: str = "Asia/Hong_Kong"
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
    send_empty_notification: bool = True


@dataclass
class AccessConfig:
    mode: str = "open_access"
    auth_profile: str | None = None


@dataclass
class InterestProfileQueryConfig:
    expand_synonyms: bool = True
    max_query_synonyms: int = 3


@dataclass
class RetentionConfig:
    days: int = 30


@dataclass
class AppConfig:
    user: UserConfig
    schedule: ScheduleConfig
    sources: dict[str, dict]
    time_range_hours: int = 24
    llm: LLMConfig = field(default_factory=LLMConfig)
    email: EmailConfig = field(default_factory=EmailConfig)
    output_dir: str = ""
    access: AccessConfig = field(default_factory=AccessConfig)
    interest_profile_query: InterestProfileQueryConfig = field(default_factory=InterestProfileQueryConfig)
    retention: RetentionConfig = field(default_factory=RetentionConfig)
    content_analysis: ContentAnalysisConfig = field(default_factory=ContentAnalysisConfig)
    abstract_selection: AbstractSelectionConfig = field(default_factory=AbstractSelectionConfig)
    candidate_scoring: CandidateScoringConfig = field(default_factory=CandidateScoringConfig)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["email"]["from"] = data["email"].pop("from_address")
        return data
