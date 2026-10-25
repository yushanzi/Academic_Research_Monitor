from __future__ import annotations


def parse_fixed_daily_cron(expr: str) -> tuple[int, int] | None:
    parts = str(expr or "").strip().split()
    if len(parts) != 5:
        return None

    minute, hour, day_of_month, month, day_of_week = parts
    if day_of_month != "*" or month != "*" or day_of_week != "*":
        return None
    if not minute.isdigit() or not hour.isdigit():
        return None

    minute_value = int(minute)
    hour_value = int(hour)
    if not (0 <= minute_value <= 59 and 0 <= hour_value <= 23):
        return None
    return hour_value, minute_value


def build_cron_with_jitter(expr: str, random_jitter_minutes: int) -> tuple[str, int]:
    if random_jitter_minutes < 0:
        raise ValueError("schedule.random_jitter_minutes must be a non-negative integer")
    if random_jitter_minutes == 0:
        return expr, 0

    parsed = parse_fixed_daily_cron(expr)
    if parsed is None:
        raise ValueError(
            "schedule.random_jitter_minutes requires schedule.cron to be a fixed daily time like '0 8 * * *'"
        )

    hour_value, minute_value = parsed
    base_minutes = hour_value * 60 + minute_value
    earliest_minutes = base_minutes - random_jitter_minutes
    latest_minutes = base_minutes + random_jitter_minutes
    if earliest_minutes < 0 or latest_minutes > (24 * 60 - 1):
        raise ValueError(
            "schedule.random_jitter_minutes must keep the randomized window within the same calendar day"
        )

    start_hour, start_minute = divmod(earliest_minutes, 60)
    effective_cron = f"{start_minute} {start_hour} * * *"
    jitter_window_seconds = (latest_minutes - earliest_minutes) * 60
    return effective_cron, jitter_window_seconds


def format_schedule_display(schedule: dict) -> str:
    cron = str((schedule or {}).get("cron", "")).strip()
    timezone = str((schedule or {}).get("timezone", "UTC")).strip() or "UTC"
    random_jitter_minutes = int((schedule or {}).get("random_jitter_minutes", 0) or 0)
    jitter_suffix = f"，随机 ±{random_jitter_minutes} 分钟" if random_jitter_minutes > 0 else ""

    if not cron:
        return f"N/A（{timezone}{jitter_suffix}）"

    parsed = parse_fixed_daily_cron(cron)
    if parsed is not None:
        hour_24, minute_value = parsed
        suffix = "AM" if hour_24 < 12 else "PM"
        hour_12 = hour_24 % 12 or 12
        return f"每天 {hour_12}:{minute_value:02d} {suffix}（{timezone}{jitter_suffix}）"

    if random_jitter_minutes > 0:
        return f"{cron} ({timezone}, random +/- {random_jitter_minutes} min)"
    return f"{cron} ({timezone})"
