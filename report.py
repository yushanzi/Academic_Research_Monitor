from __future__ import annotations

import os
import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML

from models import Paper

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"


def generate_report(
    papers: list[Paper],
    trend_summary: dict,
    config: dict,
    date_str: str,
    output_dir: str = "output",
) -> str:
    os.makedirs(output_dir, exist_ok=True)

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("report.html")

    sources_used = sorted({p.source for p in papers}) if papers else []
    configured_topics = config.get("topics", [])
    profile = config.get("interest_profile", {}) or {}
    monitor_name = config.get("user", {}).get("name", "academic-monitor")
    schedule = config.get("schedule", {}) or {}

    papers_by_topic = []
    grouping_topics = configured_topics or profile.get("core_topics", [])
    for topic in grouping_topics:
        topic_papers = [paper for paper in papers if topic in paper.matched_topics]
        papers_by_topic.append({
            "topic": topic,
            "papers": topic_papers,
            "count": len(topic_papers),
        })

    html_content = template.render(
        date=date_str,
        monitor_name=monitor_name,
        topics=configured_topics,
        profile=profile,
        sources_used=sources_used,
        time_range_hours=config.get("time_range_hours", 24),
        papers=papers,
        papers_by_topic=papers_by_topic,
        trend_summary=trend_summary,
        schedule=schedule,
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
