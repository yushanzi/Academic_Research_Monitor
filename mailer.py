import os
import base64
import logging

import resend

from config_schema import DEFAULT_EMAIL_FROM

logger = logging.getLogger(__name__)


def _response_id(response) -> str:
    if isinstance(response, dict):
        return str(response.get("id", "unknown"))

    value = getattr(response, "id", None)
    if value:
        return str(value)

    data = getattr(response, "data", None)
    if isinstance(data, dict):
        return str(data.get("id", "unknown"))

    return "unknown"


def send_report(
    pdf_path: str,
    paper_count: int,
    config: dict,
    date_str: str,
) -> None:
    api_key = os.environ.get("RESEND_API_KEY", "")
    if not api_key:
        raise ValueError("RESEND_API_KEY environment variable is required")

    resend.api_key = api_key

    email_cfg = config.get("email", {})
    recipient = email_cfg.get("recipient", "")
    if not recipient:
        raise ValueError("No email recipient configured")

    sender = email_cfg.get("from", DEFAULT_EMAIL_FROM)
    monitor_name = config.get("user", {}).get("name", "academic-monitor")
    topics = config.get("topics", [])
    topics_str = "、".join(topics) if topics else "未配置 topics"

    with open(pdf_path, "rb") as f:
        pdf_data = f.read()

    filename = os.path.basename(pdf_path)
    encoded_pdf = base64.b64encode(pdf_data).decode("ascii")

    params = {
        "from": sender,
        "to": [recipient],
        "subject": f"[{monitor_name}] 学术研究监控报告 - {date_str}",
        "html": (
            f"<p>您好，</p>"
            f"<p><strong>{monitor_name}</strong> 本轮学术研究监控已完成。</p>"
            f"<p><strong>监控主题：</strong>{topics_str}</p>"
            f"<p><strong>高相关论文数量：</strong>{paper_count}</p>"
            f"<p>详细分析请见附件 PDF 报告。</p>"
            f"<p>—— 学术研究监控系统</p>"
        ),
        "attachments": [
            {
                "filename": filename,
                "content": encoded_pdf,
            }
        ],
    }

    response = resend.Emails.send(params)
    logger.info("Email sent successfully, id: %s", _response_id(response))


def send_empty_notification(config: dict, date_str: str, *, reason: str = "no_candidates") -> None:
    api_key = os.environ.get("RESEND_API_KEY", "")
    if not api_key:
        logger.warning("No RESEND_API_KEY, skipping empty notification")
        return

    resend.api_key = api_key
    email_cfg = config.get("email", {})
    recipient = email_cfg.get("recipient", "")
    if not recipient:
        return

    sender = email_cfg.get("from", DEFAULT_EMAIL_FROM)
    monitor_name = config.get("user", {}).get("name", "academic-monitor")
    topics_str = "、".join(config.get("topics", []))

    if reason == "no_relevant":
        message = "今日发现候选论文，但没有通过高相关性筛选。"
        suffix = "(无高相关论文)"
    else:
        message = "今日未发现进入候选集的新论文。"
        suffix = "(无新论文)"

    params = {
        "from": sender,
        "to": [recipient],
        "subject": f"[{monitor_name}] 学术研究监控报告 - {date_str} {suffix}",
        "html": (
            f"<p>您好，</p>"
            f"<p>{message}</p>"
            f"<p><strong>监控主题：</strong>{topics_str}</p>"
            f"<p>—— 学术研究监控系统</p>"
        ),
    }

    response = resend.Emails.send(params)
    logger.info("Empty notification sent, id: %s", _response_id(response))
