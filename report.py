from __future__ import annotations

import os
import logging
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML

from models import Paper

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"


def _normalize_topic_tokens(topic: str) -> tuple[str, ...]:
    normalized = re.sub(r"[^a-z0-9]+", " ", (topic or "").lower()).strip()
    tokens = []
    for token in normalized.split():
        if token.endswith("ies") and len(token) > 4:
            token = token[:-3] + "y"
        elif token.endswith("s") and len(token) > 3 and not token.endswith("ss"):
            token = token[:-1]
        tokens.append(token)
    return tuple(tokens)


def _topics_match(group_topic: str, matched_topic: str) -> bool:
    if not group_topic or not matched_topic:
        return False
    if group_topic.strip().lower() == matched_topic.strip().lower():
        return True
    return _normalize_topic_tokens(group_topic) == _normalize_topic_tokens(matched_topic)


def _group_papers_by_topic(papers: list[Paper], grouping_topics: list[str]) -> tuple[list[dict], list[Paper]]:
    papers_by_topic = []
    matched_paper_ids: set[int] = set()

    for topic in grouping_topics:
        topic_papers = [
            paper
            for paper in papers
            if any(_topics_match(topic, matched_topic) for matched_topic in paper.matched_topics)
        ]
        matched_paper_ids.update(id(paper) for paper in topic_papers)
        papers_by_topic.append({
            "topic": topic,
            "papers": topic_papers,
            "count": len(topic_papers),
        })

    ungrouped_papers = [paper for paper in papers if id(paper) not in matched_paper_ids]
    return papers_by_topic, ungrouped_papers


def _format_schedule_display(schedule: dict) -> str:
    cron = str((schedule or {}).get("cron", "")).strip()
    timezone = str((schedule or {}).get("timezone", "UTC")).strip() or "UTC"
    if not cron:
        return f"N/A（{timezone}）"

    parts = cron.split()
    if len(parts) == 5:
        minute, hour, day_of_month, month, day_of_week = parts
        if day_of_month == "*" and month == "*" and day_of_week == "*" and minute.isdigit() and hour.isdigit():
            hour_24 = int(hour)
            minute_value = int(minute)
            if 0 <= hour_24 <= 23 and 0 <= minute_value <= 59:
                suffix = "AM" if hour_24 < 12 else "PM"
                hour_12 = hour_24 % 12 or 12
                return f"每天 {hour_12}:{minute_value:02d} {suffix}（{timezone}）"

    return f"{cron} ({timezone})"


def _summary_label(paper: Paper) -> str:
    return "全文总结" if paper.evidence_level == "full_text" or paper.full_text_available else "摘要总结"


def generate_report(
    papers: list[Paper],
    trend_summary: dict,
    config: dict,
    date_str: str,
    output_dir: str = "output",
    run_stats: dict | None = None,
) -> str:
    os.makedirs(output_dir, exist_ok=True)

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("report.html")

    sources_used = sorted({p.source for p in papers}) if papers else []
    profile = config.get("interest_profile", {}) or {}
    monitor_name = config.get("user", {}).get("name", "academic-monitor")
    schedule = config.get("schedule", {}) or {}

    profile_topics = profile.get("core_topics", [])
    grouping_topics = profile_topics
    papers_by_topic, ungrouped_papers = _group_papers_by_topic(papers, grouping_topics)
    schedule_display = _format_schedule_display(schedule)

    html_content = template.render(
        date=date_str,
        monitor_name=monitor_name,
        topics=profile_topics,
        profile=profile,
        sources_used=sources_used,
        time_range_hours=config.get("time_range_hours", 24),
        papers=papers,
        papers_by_topic=papers_by_topic,
        ungrouped_papers=ungrouped_papers,
        trend_summary=trend_summary,
        schedule=schedule,
        schedule_display=schedule_display,
        summary_label=_summary_label,
        run_stats=run_stats or {},
    )

    html_path = os.path.join(output_dir, f"academic_report_{date_str}.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    pdf_path = os.path.join(output_dir, f"academic_report_{date_str}.pdf")
    css_path = TEMPLATE_DIR / "report.css"

    HTML(string=html_content, base_url=str(TEMPLATE_DIR)).write_pdf(
        pdf_path,
        stylesheets=[str(css_path)],
    )

    logger.info("PDF report generated: %s", pdf_path)
    return pdf_path
