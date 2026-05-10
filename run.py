#!/usr/bin/env python3
"""Academic Research Monitor — main orchestrator."""

from __future__ import annotations

import argparse
import inspect
import json
import logging
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Callable

from analysis import analyze_papers, generate_trend_summary, resolve_content_analysis_provider
from access import get_access_provider
from app_config.loader import resolve_output_dir_path
from config_schema import AppConfig, load_app_config
from interest_profile import load_or_create_interest_profile, select_query_synonyms
from llm import get_provider
from models import Paper
from retention import prune_output_artifacts
from scoring.selector import select_abstract_relevance
from sources import ALL_SOURCES, get_source_class
from sources.base import deduplicate_papers

REPORT_IMPORT_ERROR: Exception | None = None
MAILER_IMPORT_ERROR: Exception | None = None
generate_report: Callable | None = None
send_empty_notification: Callable | None = None
send_report: Callable | None = None


class RunAlreadyInProgressError(RuntimeError):
    pass

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
        raise RunAlreadyInProgressError(f"Another run is already in progress for output_dir={output_dir}")

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
        help="Path to config file, e.g. instances/bio-monitor/config.json",
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
    output_dir = str(resolve_output_dir_path(config.output_dir, config_path=config_path))
    config.output_dir = output_dir
    config_dict["output_dir"] = output_dir

    try:
        with run_lock(output_dir):
            return _run_pipeline(config, config_dict, date_str, args.dry_run, logger, output_dir, config_path)
    except RunAlreadyInProgressError as exc:
        logger.warning("Skipping run: %s", exc)
        return 0


def _run_pipeline(
    config: AppConfig, config_dict: dict, date_str: str, dry_run: bool, logger, output_dir: str, config_path: str
) -> int:
    hours = config.time_range_hours

    prune_output_artifacts(output_dir, retention_days=config.retention.days)

    logger.info("Starting academic research monitor for report date %s", date_str)
    logger.info("Time range: past %s hours", hours)

    provider = get_provider(config_dict)
    interest_profile = load_or_create_interest_profile(config, provider, config_path=config_path)
    config_dict["interest_profile"] = interest_profile.to_dict()

    primary_query_topics = list(dict.fromkeys(interest_profile.core_topics))
    query_synonyms = []
    if config.interest_profile_query.expand_synonyms:
        query_synonyms = select_query_synonyms(
            interest_profile,
            existing_topics=primary_query_topics,
            limit=config.interest_profile_query.max_query_synonyms,
        )
    query_topics = list(dict.fromkeys(primary_query_topics + query_synonyms))
    if not query_topics:
        raise RuntimeError("Interest profile must define at least one core topic or selectable synonym")
    logger.info("Interest profile core topics: %s", interest_profile.core_topics)
    logger.info("Primary query topics: %s", primary_query_topics)
    logger.info("Selected query synonyms: %s", query_synonyms)
    logger.info("Using query topics: %s", query_topics)

    all_papers: list[Paper] = []
    raw_fetched_by_source: dict[str, int] = {}
    source_instances = get_enabled_sources(config)
    for source in source_instances:
        try:
            papers = source.fetch_papers(query_topics, hours)
            all_papers.extend(papers)
            raw_fetched_by_source[source.name] = raw_fetched_by_source.get(source.name, 0) + len(papers)
            logger.info("[%s] Found %s papers", source.name, len(papers))
        except Exception as e:
            logger.error("[%s] Error: %s", source.name, e)

    raw_fetched_count = len(all_papers)
    candidate_papers = deduplicate_papers(all_papers)
    logger.info("Total unique fetched candidate papers: %s", len(candidate_papers))

    abstract_selected_papers: list[Paper] = []
    abstract_scored_count = 0
    for paper in candidate_papers:
        if not _has_abstract_content(paper):
            logger.info("Skipping paper without abstract for abstract gate: %s", paper.title)
            continue

        abstract_scored_count += 1
        try:
            paper.relevance = select_abstract_relevance(paper, provider, interest_profile, config)
        except Exception:
            logger.exception("Abstract selection failed for paper: %s", paper.title)
            raise
        paper.matched_topics = sorted(set(paper.matched_topics) | set(paper.relevance.matched_aspects))
        for warning in getattr(paper.relevance, "warning_messages", []):
            logger.warning("Abstract selection warning for '%s': %s", paper.title, warning)
        if not paper.relevance.is_relevant:
            logger.info("Abstract selection (%s) did not pass for paper: %s", config.abstract_selection.method, paper.title)
            continue
        abstract_selected_papers.append(paper)

    logger.info("Total abstract-gate-selected papers: %s", len(abstract_selected_papers))
    logger.info(
        "Run stats summary: selected/fetched=%s/%s, unique_candidates=%s, abstract_scored=%s, per_source=%s",
        len(abstract_selected_papers),
        raw_fetched_count,
        len(candidate_papers),
        abstract_scored_count,
        raw_fetched_by_source,
    )

    run_stats = _build_run_stats(
        date_str=date_str,
        instance_name=config.user.name,
        raw_fetched_count=raw_fetched_count,
        raw_fetched_by_source=raw_fetched_by_source,
        deduplicated_candidate_count=len(candidate_papers),
        abstract_scored_count=abstract_scored_count,
        selected_unique_count=len(abstract_selected_papers),
    )

    if not abstract_selected_papers:
        logger.info("No candidate papers found matching criteria")
        _write_run_stats(run_stats, output_dir)
        if not dry_run and config.email.send_empty_notification:
            reason = "no_relevant" if raw_fetched_count > 0 else "no_candidates"
            _require_mailer("send_empty_notification")(config_dict, date_str, reason=reason)
        elif not dry_run:
            logger.info("Skipping empty notification email because email.send_empty_notification=false")
        return 0

    selected_papers: list[Paper] = list(abstract_selected_papers)

    access_provider = get_access_provider(config.access.mode)
    for paper in selected_papers:
        access_info = access_provider.resolve(paper)
        paper.apply_access_info(access_info)
        if not paper.abstract and not paper.full_text_available:
            logger.info("Skipping paper without abstract/full text after access resolution: %s", paper.title)
            paper.analysis = {
                "research_direction": "Abstract-only selection",
                "innovation_points": [],
                "summary": (paper.abstract or "")[:220],
                "consistency_with_abstract": "unclear",
                "consistency_reason": "No full text or abstract remained available after access resolution.",
            }

    logger.info("Total relevant papers: %s", len(selected_papers))

    analysis_provider = resolve_content_analysis_provider(config, provider)
    analyzed_papers = analyze_papers(selected_papers, analysis_provider, interest_profile)
    for paper in analyzed_papers:
        analysis = paper.analysis or {}
        if analysis.get("consistency_with_abstract") == "weakens_abstract":
            paper.relevance.report_status = "downgraded"
    trend_summary = generate_trend_summary(analyzed_papers, analysis_provider, interest_profile)

    run_stats = _build_run_stats(
        date_str=date_str,
        instance_name=config.user.name,
        raw_fetched_count=raw_fetched_count,
        raw_fetched_by_source=raw_fetched_by_source,
        deduplicated_candidate_count=len(candidate_papers),
        abstract_scored_count=abstract_scored_count,
        selected_unique_count=len(analyzed_papers),
    )
    _write_run_stats(run_stats, output_dir)

    pdf_path = _require_generate_report()(
        analyzed_papers,
        trend_summary,
        config_dict,
        date_str,
        output_dir,
        run_stats,
    )
    logger.info("Report saved: %s", pdf_path)

    if dry_run:
        logger.info("Dry run mode — skipping email delivery")
        return 0

    _require_mailer("send_report")(pdf_path, len(analyzed_papers), config_dict, date_str)
    logger.info("Done!")
    return 0


def _has_abstract_content(paper: Paper) -> bool:
    return bool((paper.abstract or "").strip())


def _build_run_stats(
    *,
    date_str: str,
    instance_name: str,
    raw_fetched_count: int,
    raw_fetched_by_source: dict[str, int],
    deduplicated_candidate_count: int,
    abstract_scored_count: int,
    selected_unique_count: int,
) -> dict:
    return {
        "date": date_str,
        "instance_name": instance_name,
        "raw_fetched_count": raw_fetched_count,
        "raw_fetched_by_source": dict(sorted(raw_fetched_by_source.items())),
        "deduplicated_candidate_count": deduplicated_candidate_count,
        "abstract_scored_count": abstract_scored_count,
        "selected_unique_count": selected_unique_count,
        "report_count_display": f"{selected_unique_count}/{raw_fetched_count}",
    }


def _run_stats_path(output_dir: str, date_str: str) -> str:
    return os.path.join(output_dir, f"run_stats_{date_str}.json")


def _write_run_stats(run_stats: dict, output_dir: str) -> str:
    os.makedirs(output_dir, exist_ok=True)
    path = _run_stats_path(output_dir, run_stats["date"])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(run_stats, f, ensure_ascii=False, indent=2)
        f.write("\n")
    logging.getLogger("main").info("Run stats saved: %s", path)
    return path


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
