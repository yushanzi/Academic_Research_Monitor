# Academic Research Monitor — Deployment Plan

## Context

The user has an `academic-research-monitor.skill` file that defines a workflow to monitor academic journals for new papers, analyze abstracts with an LLM, generate a Chinese PDF report, and email it daily. The project directory is currently empty (no code). We need to build the entire system from scratch and package it as a Docker container for deployment on a remote Windows machine running Docker Desktop.

**Target**: A fully automated, containerized service that runs daily, scrapes 5 academic sources, uses an LLM to analyze abstracts, generates a PDF report in Chinese, and emails it via Resend.

---

## Architecture Decisions

| Component | Choice | Rationale |
|---|---|---|
| Language | Python 3.11 | bs4/requests for scraping, stdlib email/xml, rich ecosystem |
| Data fetching | RSS feeds (primary) + REST APIs (arXiv, bioRxiv) + HTML scraping (fallback for full abstracts) | Feeds are stable and structured |
| LLM analysis | **Flexible adapter** — ships with Claude API default, swappable to OpenAI-compatible endpoints (including Poe) | User wants flexibility |
| PDF generation | WeasyPrint + Jinja2 HTML template | Best for structured text + Chinese typography |
| Email | **Resend API** (free tier, 100 emails/day) | Simple HTTP call, no SMTP config, reliable from Docker |
| Scheduling | cron inside Docker (via `supercrond` or `crond`) | Self-contained, no host-level config needed |
| Configuration | `config.json` + environment variables for secrets | Secrets via `.env` file passed to Docker |

---

## Project Structure

```
news-monitor/
  config.json                  # User-configurable settings (topics, sources, schedule)
  requirements.txt             # Python dependencies
  run.py                       # Main orchestrator (CLI entry point)
  sources/
    __init__.py
    base.py                    # PaperSource base class + keyword matching utility
    arxiv_source.py            # arXiv Atom API
    biorxiv_source.py          # bioRxiv REST JSON API
    nature_source.py           # Nature RSS + abstract scraping
    science_source.py          # Science RSS + abstract scraping
    acs_source.py              # ACS Pubs RSS + abstract scraping
  llm/
    __init__.py
    base.py                    # LLMProvider abstract interface
    claude_provider.py         # Anthropic Claude API (default)
    openai_provider.py         # OpenAI-compatible API (covers Poe, local, etc.)
  analyzer.py                  # Orchestrates LLM calls for abstract analysis
  report.py                    # Jinja2 rendering + WeasyPrint PDF conversion
  mailer.py                    # Resend API email with PDF attachment
  templates/
    report.html                # Jinja2 HTML template for PDF
    report.css                 # CSS (Chinese fonts, A4 layout)
  .env.example                 # Template for secrets
  Dockerfile                   # Primary deployment artifact
  docker-compose.yml           # Docker Compose with cron schedule
  crontab                      # Cron schedule file for in-container cron
  setup.sh                     # Optional: local dev setup
```

---

## Data Acquisition Strategy (per source)

| Source | Method | Keyword filtering | Abstract |
|---|---|---|---|
| **arXiv** | Atom API (`export.arxiv.org/api/query`) | Server-side (query param) | In API response |
| **bioRxiv** | REST API (`api.biorxiv.org/details/biorxiv/{date}/{date}`) | Client-side (title+abstract match) | In API response |
| **Nature** | RSS feed (`nature.com/nature.rss`) | Client-side | Scrape article page (`<meta name="dc.description">`) |
| **Science** | RSS feed (`science.org/action/showFeed?...`) | Client-side | Scrape article page (`<meta name="citation_abstract">`) |
| **ACS Pubs** | RSS feed (per-journal, e.g. J. Med. Chem.) | Client-side | Scrape article page (`<meta name="dc.Description">`) |

- Deduplication by DOI (fallback: normalized title similarity)
- Each source wrapped in try/except — partial failures don't kill the run

---

## Implementation Steps

### Step 1: Project skeleton & config
- Create `config.json` with defaults (sources, topics, time_range, LLM provider, email)
- Create `requirements.txt`: `requests`, `beautifulsoup4`, `anthropic`, `openai`, `weasyprint`, `Jinja2`, `feedparser`, `resend`
- Create `.env.example` with placeholder keys

### Step 2: Source scrapers
- `sources/base.py` — `PaperSource` ABC with `fetch_papers(topics, hours) -> list[dict]` + keyword matching utility
- `sources/arxiv_source.py` — Atom API, parse with `xml.etree`, 3s delay between requests
- `sources/biorxiv_source.py` — REST JSON API, paginated fetch, client-side keyword filter
- `sources/nature_source.py` — RSS via `feedparser`, scrape abstract from article page via `<meta>` tags
- `sources/science_source.py` — same pattern as Nature
- `sources/acs_source.py` — same pattern, use `curl_cffi` if blocked by Cloudflare

Paper dict schema: `{title, authors, abstract, date, url, source, doi}`

### Step 3: LLM adapter layer
- `llm/base.py` — `LLMProvider` ABC with `analyze(prompt) -> str`
- `llm/claude_provider.py` — uses `anthropic` SDK, model `claude-sonnet-4-20250514`
- `llm/openai_provider.py` — uses `openai` SDK with configurable `base_url` (covers OpenAI, Poe, any compatible endpoint)
- Provider selection via `config.json` field `"llm_provider": "claude"` or `"openai_compatible"`

### Step 4: Analyzer
- `analyzer.py` — iterates papers, sends each abstract to the LLM with a structured prompt requesting JSON output: `{research_direction, innovation_points[], summary}` in Chinese
- Retry with backoff (max 3), skip on failure
- After all papers: one final LLM call for trend summary

### Step 5: PDF report
- `templates/report.html` — Jinja2 template matching the report structure from SKILL.md
- `templates/report.css` — A4 page, Chinese font stack (`Noto Sans CJK SC`), clean academic styling
- `report.py` — renders template, calls `weasyprint.HTML(...).write_pdf(...)`

### Step 6: Email via Resend
- `mailer.py` — single function: POST to `https://api.resend.com/emails` with PDF attachment (base64), subject `学术研究监控报告 - {date}`
- Requires `RESEND_API_KEY` in `.env`

### Step 7: Orchestrator
- `run.py` — ties it all together: load config -> fetch papers -> deduplicate -> analyze -> generate PDF -> email
- CLI flags: `--dry-run` (no email), `--config PATH`, `--date YYYY-MM-DD`
- Logging to stdout (Docker captures it) + `output/` dir for generated PDFs

### Step 8: Docker deployment
- `Dockerfile` — `python:3.11-slim`, install `fonts-noto-cjk` + WeasyPrint system deps (`libpango`, `libpangocairo`), pip install requirements, copy code
- `crontab` — `0 8 * * * cd /app && python run.py >> /var/log/cron.log 2>&1` (8 AM UTC, adjustable)
- `docker-compose.yml` — mounts `.env`, optionally mounts `output/` volume for PDF persistence
- Container runs `crond` in foreground as the main process

---

## Configuration File (`config.json`)

```json
{
  "sources": {
    "arxiv": {"enabled": true},
    "biorxiv": {"enabled": true},
    "nature": {"enabled": true, "journals": ["nature"]},
    "science": {"enabled": true},
    "acs": {"enabled": true, "journals": ["jmcmar", "jacsat"]}
  },
  "topics": [
    "protein folding dynamics",
    "small molecule drug discovery and design"
  ],
  "time_range_hours": 24,
  "language": "Chinese",
  "llm": {
    "provider": "claude",
    "model": "claude-sonnet-4-20250514",
    "base_url": null
  },
  "email": {
    "recipient": "you@example.com"
  },
  "schedule_cron": "0 8 * * *"
}
```

Secrets in `.env`:
```
ANTHROPIC_API_KEY=sk-...
RESEND_API_KEY=re_...
# For OpenAI-compatible provider:
# OPENAI_API_KEY=...
# OPENAI_BASE_URL=...
```

---

## Verification Plan

1. **Unit test each source** — run `python -m sources.arxiv_source` with a test topic, verify paper dicts returned
2. **Test LLM analysis** — `python run.py --dry-run` with 1-2 papers, inspect Chinese analysis output
3. **Test PDF generation** — verify `output/academic_report_{date}.pdf` opens correctly with Chinese text
4. **Test email** — run full pipeline, check `you@example.com` inbox
5. **Docker test** — `docker-compose up`, verify cron fires and report arrives
6. **Failure test** — disable one source in config, verify the rest still work

---

## Key Files to Create (in order)

1. `/Users/yushanzi/Documents/news-monitor/config.json`
2. `/Users/yushanzi/Documents/news-monitor/requirements.txt`
3. `/Users/yushanzi/Documents/news-monitor/.env.example`
4. `/Users/yushanzi/Documents/news-monitor/sources/__init__.py`
5. `/Users/yushanzi/Documents/news-monitor/sources/base.py`
6. `/Users/yushanzi/Documents/news-monitor/sources/arxiv_source.py`
7. `/Users/yushanzi/Documents/news-monitor/sources/biorxiv_source.py`
8. `/Users/yushanzi/Documents/news-monitor/sources/nature_source.py`
9. `/Users/yushanzi/Documents/news-monitor/sources/science_source.py`
10. `/Users/yushanzi/Documents/news-monitor/sources/acs_source.py`
11. `/Users/yushanzi/Documents/news-monitor/llm/__init__.py`
12. `/Users/yushanzi/Documents/news-monitor/llm/base.py`
13. `/Users/yushanzi/Documents/news-monitor/llm/claude_provider.py`
14. `/Users/yushanzi/Documents/news-monitor/llm/openai_provider.py`
15. `/Users/yushanzi/Documents/news-monitor/analyzer.py`
16. `/Users/yushanzi/Documents/news-monitor/templates/report.html`
17. `/Users/yushanzi/Documents/news-monitor/templates/report.css`
18. `/Users/yushanzi/Documents/news-monitor/report.py`
19. `/Users/yushanzi/Documents/news-monitor/mailer.py`
20. `/Users/yushanzi/Documents/news-monitor/run.py`
21. `/Users/yushanzi/Documents/news-monitor/crontab`
22. `/Users/yushanzi/Documents/news-monitor/Dockerfile`
23. `/Users/yushanzi/Documents/news-monitor/docker-compose.yml`
