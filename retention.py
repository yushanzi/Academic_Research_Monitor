from __future__ import annotations

import argparse
import logging
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from config_schema import load_app_config

logger = logging.getLogger(__name__)

REPORT_HTML_RE = re.compile(r"^academic_report_(\d{4}-\d{2}-\d{2})\.html$")
REPORT_PDF_RE = re.compile(r"^academic_report_(\d{4}-\d{2}-\d{2})\.pdf$")
RUN_STATS_RE = re.compile(r"^run_stats_(\d{4}-\d{2}-\d{2})\.json$")
LOG_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\b")


def cutoff_date(*, today: date | None = None, retention_days: int = 30) -> date:
    if retention_days <= 0:
        raise ValueError("retention_days must be positive")
    today = today or datetime.now().date()
    return today - timedelta(days=retention_days - 1)


def prune_output_artifacts(output_dir: str, *, today: date | None = None, retention_days: int = 30) -> list[str]:
    path = Path(output_dir)
    if not path.exists() or not path.is_dir():
        return []

    keep_from = cutoff_date(today=today, retention_days=retention_days)
    removed: list[str] = []
    for entry in path.iterdir():
        if not entry.is_file():
            continue
        artifact_date = _artifact_date_from_name(entry.name)
        if artifact_date is None or artifact_date >= keep_from:
            continue
        entry.unlink()
        removed.append(str(entry))
    return sorted(removed)


def trim_log_file(log_path: str, *, today: date | None = None, retention_days: int = 30) -> bool:
    path = Path(log_path)
    if not path.exists() or not path.is_file():
        return False

    keep_from = cutoff_date(today=today, retention_days=retention_days)
    original = path.read_text(encoding="utf-8", errors="replace")
    if not original:
        return False

    preamble: list[str] = []
    blocks: list[tuple[date, list[str]]] = []
    current_block: tuple[date, list[str]] | None = None

    for line in original.splitlines(keepends=True):
        line_date = _parse_log_line_date(line)
        if line_date is not None:
            current_block = (line_date, [line])
            blocks.append(current_block)
            continue
        if current_block is None:
            preamble.append(line)
        else:
            current_block[1].append(line)

    kept = list(preamble)
    for block_date, lines in blocks:
        if block_date >= keep_from:
            kept.extend(lines)

    rewritten = "".join(kept)
    if rewritten == original:
        return False

    path.write_text(rewritten, encoding="utf-8")
    return True


def _artifact_date_from_name(name: str) -> date | None:
    for pattern in (REPORT_HTML_RE, REPORT_PDF_RE, RUN_STATS_RE):
        match = pattern.match(name)
        if match:
            return datetime.strptime(match.group(1), "%Y-%m-%d").date()
    return None


def _parse_log_line_date(line: str) -> date | None:
    match = LOG_DATE_RE.match(line)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y-%m-%d").date()
    except ValueError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply retention policy to cron log and output artifacts.")
    parser.add_argument("--config", required=True, help="Path to config file")
    parser.add_argument("--cron-log", help="Path to cron log file")
    parser.add_argument("--skip-output", action="store_true", help="Skip pruning output artifacts")
    args = parser.parse_args()

    config = load_app_config(args.config)
    retention_days = config.retention.days

    if not args.skip_output:
        removed = prune_output_artifacts(config.output_dir, retention_days=retention_days)
        if removed:
            logger.info("Pruned %s old output artifact(s) from %s", len(removed), config.output_dir)

    if args.cron_log:
        changed = trim_log_file(args.cron_log, retention_days=retention_days)
        if changed:
            logger.info("Trimmed cron log to last %s day(s): %s", retention_days, args.cron_log)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
