#!/usr/bin/env python3
"""Academic Research Monitor — main orchestrator."""

from __future__ import annotations

import argparse
import inspect
import logging
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Callable

from access import get_access_provider
from analyzer import DEFAULT_RELEVANCE_THRESHOLD, analyze_papers, generate_trend_summary, judge_relevance
from config_schema import AppConfig, load_app_config
from interest_profile import load_or_create_interest_profile
from llm import get_provider
from models import Paper
from sources import ALL_SOURCES, get_source_class
from sources.base import deduplicate_papers, matches_interest_profile

REPORT_IMPORT_ERROR: Exception | None = None
MAILER_IMPORT_ERROR: Exception | None = None
generate_report: Callable | None = None
send_empty_notification: Callable | None = None
send_report: Callable | None = None

try:
    from report import generate_report
except Exception as exc:
    REPORT_IMPORT_ERROR = exc

try:
    from mailer import send_empty_notification, send_report
except Exception as exc:
    MAILER_IMPORT_ERROR = exc


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def get_enabled_sources(config: dict | AppConfig) -> list:
    sources_config = config.sources if isinstance(config, AppConfig) else config.get("sources", {})
    instances = []

    for name in ALL_SOURCES:
        src_cfg = sources_config.get(name, {})
        if not src_cfg.get("enabled", False):
            continue

        cls = get_source_class(name)
        instances.append(_build_source_instance(name, cls, src_cfg))

    return instances


def _build_source_instance(name: str, cls, src_cfg: dict):
    init_params = inspect.signature(cls.__init__).parameters
    supported_kwargs = {}

    for key, value in src_cfg.items():
        if key == "enabled":
            continue
        if key in init_params:
            supported_kwargs[key] = value
        else:
            logging.getLogger("main").warning(
                "Ignoring unsupported config key '%s' for source '%s'",
                key,
                name,
            )

    return cls(**supported_kwargs)


@contextmanager
def run_lock(output_dir: str):
    os.makedirs(output_dir, exist_ok=True)
    lock_path = os.path.join(output_dir, ".run.lock")
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as lock_file:
            lock_file.write(str(os.getpid()))
    except FileExistsError:
        raise RuntimeError(f"Another run is already in progress for output_dir={output_dir}")

    try:
        yield
    finally:
        try:
            os.remove(lock_path)
        except FileNotFoundError:
            pass


def main():
    parser = argparse.ArgumentParser(description="Academic Research Monitor")
    parser.add_argument(
        "--config",
        required=True,
        help="Path to config file, e.g. configs/bio-monitor.json",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch, analyze, generate PDF but do not send email",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Override report label date (YYYY-MM-DD); does not change fetch time window",
    )
    args = parser.parse_args()

    setup_logging()
    logger = logging.getLogger("main")

    config_path = args.config
    if not os.path.isabs(config_path):
        config_path = os.path.join(os.path.dirname(__file__), config_path)
    config = load_app_config(config_path)
    config_dict = config.to_dict()

    if args.date:
        try:
            datetime.strptime(args.date, "%Y-%m-%d")
        except ValueError as exc:
            raise SystemExit(f"Invalid --date value: {args.date}. Expected YYYY-MM-DD") from exc

    date_str = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    output_dir = config.output_dir
    if not os.path.isabs(output_dir):
        output_dir = os.path.join(os.path.dirname(__file__), output_dir)
        config.output_dir = output_dir
        config_dict["output_dir"] = output_dir

    try:
        with run_lock(output_dir):
            return _run_pipeline(config, config_dict, date_str, args.dry_run, logger, output_dir)
    except RuntimeError as exc:
        logger.warning("Skipping run: %s", exc)
        return 0


def _run_pipeline(
    config: AppConfig, config_dict: dict, date_str: str, dry_run: bool, logger, output_dir: str
) -> int:
    topics = config.topics
    hours = config.time_range_hours

    logger.info("Starting academic research monitor for report date %s", date_str)
    logger.info("Topics: %s", topics)
    logger.info("Time range: past %s hours", hours)

    provider = get_provider(config_dict)
    interest_profile = load_or_create_interest_profile(config, provider)
    config_dict["interest_profile"] = interest_profile.to_dict()

    query_topics = list(dict.fromkeys(interest_profile.core_topics + topics)) or topics
    logger.info("Using query topics: %s", query_topics)

    all_papers: list[Paper] = []
    source_instances = get_enabled_sources(config)
    for source in source_instances:
        try:
            papers = source.fetch_papers(query_topics, hours)
            all_papers.extend(papers)
            logger.info("[%s] Found %s papers", source.name, len(papers))
        except Exception as e:
            logger.error("[%s] Error: %s", source.name, e)

    filtered_papers: list[Paper] = []
    for paper in all_papers:
        paper_text = f"{paper.title}\n{paper.abstract}"
        matched, matched_topics = matches_interest_profile(paper_text, interest_profile)
        if not matched:
            continue
        paper.matched_topics = sorted(set(paper.matched_topics) | set(matched_topics))
        filtered_papers.append(paper)

    logger.info("Total interest-matched papers before deduplication: %s", len(filtered_papers))
    candidate_papers = deduplicate_papers(filtered_papers)
    logger.info("Total unique candidate papers: %s", len(candidate_papers))

    if not candidate_papers:
        logger.info("No candidate papers found matching criteria")
        if not dry_run:
            _require_mailer("send_empty_notification")(config_dict, date_str, reason="no_candidates")
        return 0

    access_provider = get_access_provider(config.access.mode)
    selected_papers: list[Paper] = []
    for paper in candidate_papers:
        access_info = access_provider.resolve(paper)
        paper.apply_access_info(access_info)
        if not paper.abstract and not paper.full_text_available:
            logger.info("Skipping paper without abstract/full text: %s", paper.title)
            continue

        try:
            relevance = judge_relevance(paper, provider, interest_profile)
        except Exception as exc:
            logger.error("Relevance judgement failed for '%s': %s", paper.title[:40], exc)
            continue

        paper.relevance = relevance
        if relevance.is_relevant and relevance.relevance_score >= DEFAULT_RELEVANCE_THRESHOLD:
            selected_papers.append(paper)

    logger.info("Total relevant papers: %s", len(selected_papers))
    if not selected_papers:
        if not dry_run:
            _require_mailer("send_empty_notification")(config_dict, date_str, reason="no_relevant")
        return 0

    analyzed_papers = analyze_papers(selected_papers, provider, interest_profile)
    trend_summary = generate_trend_summary(analyzed_papers, provider, interest_profile)

    pdf_path = _require_generate_report()(
        analyzed_papers,
        trend_summary,
        config_dict,
        date_str,
        output_dir,
    )
    logger.info("Report saved: %s", pdf_path)

    if dry_run:
        logger.info("Dry run mode — skipping email delivery")
        return 0

    _require_mailer("send_report")(pdf_path, len(analyzed_papers), config_dict, date_str)
    logger.info("Done!")
    return 0


def _require_generate_report() -> Callable:
    if generate_report is None:
        raise RuntimeError("report module is unavailable") from REPORT_IMPORT_ERROR
    return generate_report


def _require_mailer(name: str) -> Callable:
    func = {"send_empty_notification": send_empty_notification, "send_report": send_report}[name]
    if func is None:
        raise RuntimeError("mailer module is unavailable") from MAILER_IMPORT_ERROR
    return func


if __name__ == "__main__":
    raise SystemExit(main())
