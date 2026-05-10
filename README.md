# Academic Research Monitor

Monitors configured academic sources for recent papers, builds an interest profile from user intent, expands source recall with selected synonyms, runs a configurable abstract-level selector (default: 3-LLM voting) for selection, then uses any accessible full text for enrichment analysis, generates a Chinese HTML/PDF report, and emails the result.

## Features

- Fetches papers from arXiv, bioRxiv, Nature RSS, Science RSS, and ACS RSS feeds (including JACS, JMC, and JCTC in the sample configs)
- Supports structured config with per-instance `user`, `schedule`, `sources`, `llm`, `email`, and `access`
- Uses a pre-generated, confirmed `instances/<instance>/interest_profile.json` as the single source of truth for runtime interest matching
- Uses open-access resolution metadata (`entry_url`, `download_url`, `evidence_level`, `effective_access_mode`)
- Selects papers from either 3-LLM abstract voting or candidate-score abstract scoring, then uses accessible full text for enrichment and consistency checks
- Generates HTML + PDF reports and emails them with Resend
- Supports runtime cron generation in Docker via `entrypoint.sh`
- Includes multi-instance Docker Compose examples under `instances/` and `docker-compose.multi-instance.yml`

## Requirements

- Python 3.11+
- system dependencies required by WeasyPrint
- API keys:
  - `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`
  - `RESEND_API_KEY`

## Configuration

Create one config per monitor under `instances/`, or copy `config.template.json` to `instances/<instance>/config.json` and edit it:

- `user.name`: instance name
- `schedule.cron`: cron expression
- `schedule.timezone`: defaults to `Asia/Hong_Kong`; supported values are `Asia/Hong_Kong` and `UTC`
- `schedule.run_on_start`: whether to run once at container startup
- `sources`: enable/disable data sources
  - ACS journal codes supported out of the box include `jmcmar`, `jacsat`, and `jctcce`
- `time_range_hours`: recent time window, default `24`
- `llm.provider`: `claude` or `openai_compatible`
- `llm.model`: model name
- `llm.base_url`: optional OpenAI-compatible endpoint
- `interest_profile_query.expand_synonyms`: whether to expand source queries with selected synonyms; defaults to `true`
- `interest_profile_query.max_query_synonyms`: max selected synonyms added to source queries; defaults to `3`
- `content_analysis.llm`: optional override for full-text analysis and trend-summary provider; when omitted, the system uses the first voting judge only when `abstract_selection.method=three_llm_voting`, otherwise it falls back to the top-level `llm`
- `abstract_selection.method`: abstract selector to use; defaults to `candidate_score`; set to `three_llm_voting` to opt into multi-judge voting
- `abstract_selection.three_llm_voting.required_votes`: votes needed to pass when all judges succeed; defaults to `2`
- `abstract_selection.three_llm_voting.fallback_method`: fallback selector if all voting judges fail; currently `candidate_score`
- `abstract_selection.three_llm_voting.judges`: judge list used only when `abstract_selection.method=three_llm_voting`; defaults to three clones of the main `llm` config if omitted
- `candidate_scoring.threshold`: abstract-stage candidate threshold between `0` and `1`; defaults to `0.60`
- `candidate_scoring.fail_open`: whether to continue when candidate scoring fails; defaults to `false`
- `candidate_scoring.exclude_penalty_weight`: penalty applied when `exclude` is matched; defaults to `0.30`
- `candidate_scoring.weights`: configurable rubric weights for `topic_match`, `must_have_match`, `evidence_strength`, and `focus_specificity`; defaults sum to `1.0`
- `email.recipient`: destination email address
- `email.from`: sender string
- `email.send_empty_notification`: whether to send a no-result email when no papers are selected; defaults to `true`
- `output_dir`: report/cache output directory for reports and runtime artifacts; keep this under the repo-level `output/` tree (for example `output/chem-monitor`), not under `instances/`
- `retention.days`: retention window for `/var/log/cron.log` and dated runtime artifacts in `output_dir`; defaults to `30`
- `access.mode`: must be `open_access` in the current implementation (`authenticated` not implemented yet)

Runtime interest semantics live only in the sibling `instances/<instance>/interest_profile.json` file:

- `profile.core_topics`
- `profile.synonyms`
- `profile.must_have`
- `profile.exclude`
- `profile.summary`

Do not put `topics`, `interest_description`, `must_have`, or `exclude` in `config.json`; runtime rejects those legacy fields.

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
python3 run.py --config instances/bio-monitor/config.json --dry-run
```

Before the first run, make sure onboarding has already generated a confirmed `instances/<instance>/interest_profile.json`; runtime will not generate one automatically.

## Generate config from a user document

If you want to onboard a user from a free-form interest document, use:

```bash
python3 scripts/generate_config_from_doc.py \
  --input docs/my-interest.md \
  --output instances/my-monitor/config.json \
  --user-name my-monitor \
  --email you@example.com
```

Supported input formats:

- `.txt`
- `.md`
- `.docx`

The script will:

- read the user's document
- use Poe `gemini-3-flash` to extract `interest_description`, `topics`, `must_have`, and `exclude`
- use Poe `gemini-3-flash` to generate a confirmed `instances/<instance>/interest_profile.json`
- fall back to heuristic parsing if the LLM is unavailable
- generate a runtime config based on `config.template.json`

The generated config keeps only runtime settings. The generated sibling `interest_profile.json` is the file the container will read at startup.

Recommended onboarding flow:

1. Run `generate_config_from_doc.py`
2. Review and, if needed, edit `instances/<instance>/interest_profile.json`
3. Run `python3 scripts/generate_compose_from_instances.py` if you use Docker Compose
4. Start the monitor/container

Runtime requires that `instances/<instance>/interest_profile.json` already exists and has `confirmed=true`.

Run tests:

```bash
PYTHONPYCACHEPREFIX=/tmp/pycache python3 -m unittest discover -s tests
```

## Docker

Regenerate the multi-instance Compose file from `instances/*/config.json`:

```bash
python3 scripts/generate_compose_from_instances.py
```

Then use the generated Compose file:

```bash
docker compose -f docker-compose.multi-instance.yml up -d bio-monitor
```

At container startup, each container reads its mounted `/app/instance/config.json`, generates the cron entry dynamically, optionally runs one immediate job when `schedule.run_on_start=true`, and then starts cron.

On Windows, open Docker Desktop first and run the commands from PowerShell, Windows Terminal, or a WSL shell.

### Multi-instance example

Sample per-instance configs are included in `instances/`:

- `instances/bio-monitor/config.json`
- `instances/chem-monitor/config.json`

Run both monitors in parallel:

```bash
python3 scripts/generate_compose_from_instances.py
docker compose -f docker-compose.multi-instance.yml up -d
```

To validate with just one instance first:

```bash
python3 scripts/generate_compose_from_instances.py
docker compose -f docker-compose.multi-instance.yml up -d bio-monitor
docker logs -f bio-monitor
```

Each container mounts its own instance directory to `/app/instance` and writes reports/runtime artifacts to its own subdirectory under `output/`.

For production add/change workflows, see `OPERATIONS.md`.

## Windows one-shot runtime

For Windows, the recommended deployment model is:

- Docker Desktop may stay running
- the image stays built locally
- **containers do not stay running**
- Windows Task Scheduler starts a fresh container for each scheduled run
- the container runs once and exits

Use the bundled PowerShell wrapper:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-monitor.ps1 -ConfigPath instances\bio-monitor\config.json
```

This wrapper:

- reads the target instance config file
- uses `user.name` as the one-shot container name
- ensures the configured output directory exists
- mounts the whole monitor definition directory to `/app/instance`
- mounts the repo `output/` root to `/app/output` so `output_dir` keeps the same layout inside and outside the container
- checks whether Docker is ready
- if needed, tries to start Docker Desktop and waits up to 5 minutes
- launches `docker run --rm`
- overrides the image entrypoint to run `python /app/run.py --config /app/instance/config.json`
- removes the container after the run completes

Retention note for Windows one-shot runs:

- dated files under the configured `output_dir` are still trimmed according to `retention.days`
- container-internal `/var/log/cron.log` retention does **not** apply in this mode, because the wrapper bypasses the image `entrypoint.sh` and runs `run.py` directly

If a stale container with the same `user.name` already exists, the PowerShell wrapper stops and asks you to remove it first.

This auto-start behavior is intended for Windows Task Scheduler tasks that run **while the user is logged in**.

Recommended Windows workflow:

1. Build the image once
2. Run the PowerShell wrapper manually once
3. Create one Task Scheduler job per config file
4. Let Task Scheduler trigger one-shot container runs at the desired times

Example image build:

```bash
docker build -t news-monitor:latest .
```

## Output

Generated files are written to `output/<instance>/` by default:

- `academic_report_YYYY-MM-DD.html`
- `academic_report_YYYY-MM-DD.pdf`
- `run_stats_YYYY-MM-DD.json`
- `.run.lock` while a run is active

By default, dated runtime artifacts and the container cron log are trimmed to the most recent 30 days. You can override this with `retention.days` in `config.json`.

The confirmed runtime profile lives next to the config file at `instances/<instance>/interest_profile.json`.

## Filtering pipeline

Current candidate selection is:

1. build/load `interest_profile`
2. query sources with `core_topics + selected_synonyms`
3. deduplicate fetched papers and skip entries without abstracts
4. run abstract-stage rubric scoring to produce `candidate_score` and drop excluded/below-threshold papers
5. resolve access / full text and mark open-access availability
6. analyze selected papers with the best available evidence (`full_text` or `abstract_only`) and perform consistency checks
7. build the report
