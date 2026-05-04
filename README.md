# Academic Research Monitor

Monitors configured academic sources for recent papers, builds an interest profile from user intent, judges relevance with an LLM, generates a Chinese HTML/PDF report, and emails the result.

## Features

- Fetches papers from arXiv, bioRxiv, Nature RSS, Science RSS, and ACS RSS feeds
- Supports structured config with per-instance `user`, `schedule`, `sources`, `topics`, `interest_description`, `llm`, `email`, and `access`
- Builds and caches an `interest_profile` from long-form user intent
- Uses open-access resolution metadata (`entry_url`, `download_url`, `evidence_level`, `effective_access_mode`)
- Runs relevance judgement before detailed paper analysis
- Generates HTML + PDF reports and emails them with Resend
- Supports runtime cron generation in Docker via `entrypoint.sh`
- Includes multi-instance Docker Compose examples under `configs/` and `docker-compose.multi-instance.yml`

## Requirements

- Python 3.11+
- system dependencies required by WeasyPrint
- API keys:
  - `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`
  - `RESEND_API_KEY`

## Configuration

Create one config per monitor under `configs/`, or copy `config.example.json` to `configs/<instance>.json` and edit it:

- `user.name`: instance name
- `schedule.cron`: cron expression
- `schedule.timezone`: currently `UTC`
- `schedule.run_on_start`: whether to run once at container startup
- `sources`: enable/disable data sources
- `interest_description`: long-form monitoring intent
- `topics`: keyword hints / backward-compatible topic list
- `time_range_hours`: recent time window
- `llm.provider`: `claude` or `openai_compatible`
- `llm.model`: model name
- `llm.base_url`: optional OpenAI-compatible endpoint
- `email.recipient`: destination email address
- `email.from`: sender string
- `output_dir`: report/cache output directory
- `access.mode`: must be `open_access` in the current implementation (`authenticated` not implemented yet)

## Environment

Copy `.env.example` to `.env` and set your keys.

Optional:

- `NEWS_MONITOR_IMAGE`: override the Docker image tag used by Compose

## First Git setup

If this is the first time you are putting the project under Git:

```bash
git init -b main
git add .
git commit -m "Initial commit"
```

Then add your remote and push:

```bash
git remote add origin <your-remote-url>
git push -u origin main
```

The repo is configured to keep `.env`, `output/`, and `logs/` out of Git.

## Windows deployment notes

For Windows, prefer **Docker Desktop + WSL2 backend**.

- make sure Docker Desktop is running
- make sure the repo path is writable by Docker Desktop
- keep shell scripts and Docker-related files in **LF** line endings
- if you use an editor on Windows, avoid converting `entrypoint.sh` to CRLF

## Local run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 run.py --config configs/bio-monitor.json --dry-run
```

Before the first run, make sure the selected config contains at least one of `topics` or `interest_description`; otherwise config validation will fail.

Run tests:

```bash
PYTHONPYCACHEPREFIX=/tmp/pycache python3 -m unittest discover -s tests
```

## Docker

Use the multi-instance Compose file:

```bash
docker compose -f docker-compose.multi-instance.yml up --build -d
```

At container startup, each container reads its mounted `/app/config.json`, generates the cron entry dynamically, optionally runs one immediate job when `schedule.run_on_start=true`, and then starts cron.

On Windows, open Docker Desktop first and run the commands from PowerShell, Windows Terminal, or a WSL shell.

### Multi-instance example

Sample per-instance configs are included in `configs/`:

- `configs/bio-monitor.json`
- `configs/chem-monitor.json`

Run both monitors in parallel:

```bash
docker compose -f docker-compose.multi-instance.yml up --build -d
```

To validate with just one instance first:

```bash
docker compose -f docker-compose.multi-instance.yml up --build -d bio-monitor
docker logs -f academic-monitor-bio
```

Each container mounts its own config to `/app/config.json` and writes to its own subdirectory under `output/`.

For production add/change workflows, see `OPERATIONS.md`.

## Output

Generated files are written to `output/<instance>/` by default:

- `interest_profile.json`
- `academic_report_YYYY-MM-DD.html`
- `academic_report_YYYY-MM-DD.pdf`
