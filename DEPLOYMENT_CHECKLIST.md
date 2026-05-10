# Academic Research Monitor Deployment Checklist

## 1. Pre-deployment checks

### 1.1 Environment

Make sure the target machine has:

- Docker Desktop (WSL2 backend recommended on Windows)
- Docker Compose
- outbound network access to external APIs
- a writable directory for the `output/` volume mount
- an editor that will not convert shell scripts to CRLF
- if using Windows Task Scheduler, permission to run Docker Desktop / Docker CLI from the scheduled account
- for auto-start behavior, configure the task to run when the user is logged in

### 1.2 Credentials

Prepare a `.env` file with at least:

```bash
RESEND_API_KEY=...
ANTHROPIC_API_KEY=...
```

or:

```bash
RESEND_API_KEY=...
OPENAI_API_KEY=...
OPENAI_BASE_URL=...
```

Optional:

```bash
NEWS_MONITOR_IMAGE=news-monitor:latest
```

### 1.3 Config validation

Make sure each `instances/<instance>/config.json` includes at least:

- `user.name`
- `schedule.cron`
- `schedule.timezone = Asia/Hong_Kong` (or `UTC` if explicitly desired)
- `schedule.run_on_start`
- `llm.provider`
- `llm.model`
- `interest_profile_query.expand_synonyms`
- `interest_profile_query.max_query_synonyms`
- `candidate_scoring.threshold` / `relevance_scoring.threshold`
- `email.recipient`
- `email.send_empty_notification`
- `output_dir` (under repo-level `output/`, not `instances/`)
- `access.mode = open_access`

And make sure `instances/<instance>/interest_profile.json` exists, is confirmed, and contains the runtime interest semantics (`core_topics`, `synonyms`, `must_have`, `exclude`, `summary`).

Note for Windows one-shot deployment:

- `schedule.cron` and `schedule.run_on_start` remain in the config for compatibility, but the real execution schedule comes from Windows Task Scheduler

### 1.4 Output layout

Plan the output directories in advance, for example:

```text
output/
  bio-monitor/
  chem-monitor/
```

Each instance should write to its own directory.

Before the first container start, make sure onboarding has already created:

```text
instances/<instance>/interest_profile.json
```

Runtime will not generate this file automatically.

---

## 2. First deployment sequence

### Step 1: Run tests locally

From the project directory:

```bash
PYTHONPYCACHEPREFIX=/tmp/pycache python3 -m unittest discover -s tests -v
```

Expected result:

- all tests pass

---

### Step 2: Run a local dry-run

Before sending real emails, validate the full pipeline:

```bash
python3 run.py --config instances/bio-monitor/config.json --dry-run
```

Expected checks:

- no config validation errors
- `instances/<instance>/interest_profile.json` already exists before the run
- papers can be fetched and analyzed
- reports are generated successfully
- generated files include:
  - `output/<instance>/academic_report_YYYY-MM-DD.html`
  - `output/<instance>/academic_report_YYYY-MM-DD.pdf`

---

### Step 3: Build and start with Docker

Regenerate the compose file first:

```bash
python3 scripts/generate_compose_from_instances.py
```

Then start the service(s):

```bash
docker compose -f docker-compose.multi-instance.yml up -d bio-monitor
```

Expected checks:

- containers start successfully
- containers do not exit immediately because of config errors
- `entrypoint.sh` generates cron successfully
- if `run_on_start=true`, the instance performs one immediate run at startup

For Windows one-shot deployment, build the image once instead:

```bash
docker build -t news-monitor:latest .
```

---

### Step 4: Check container logs

```bash
docker logs -f <container_name>
```

Or:

```bash
docker compose -f docker-compose.multi-instance.yml logs -f
```

Look for logs such as:

- `Starting academic research monitor`
- `Primary query topics`
- `Selected query synonyms`
- `Using query topics`
- `Found X papers`
- `Total abstract-gate-selected papers`
- `Total relevant papers`
- `Report saved`

If a Windows container cannot read mounted directories, first check Docker Desktop file sharing / path access settings.

For Windows one-shot deployment, manually run one instance first:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-monitor.ps1 -ConfigPath instances\bio-monitor\config.json
```

Expected checks:

- a fresh container is created
- Docker Desktop starts automatically if it was not already ready
- the run completes once
- the container is removed automatically
- output files are written successfully
- old dated files in `output/<instance>/` are trimmed according to `retention.days`
- `/var/log/cron.log` retention is not part of this one-shot check because the PowerShell wrapper bypasses `entrypoint.sh`

---

### Step 5: Verify output files

For example:

```bash
ls -la output/bio-monitor
```

Confirm that the directory contains:

- `.html`
- `.pdf`

And confirm the monitor definition directory contains:

- `instances/<instance>/config.json`
- `instances/<instance>/interest_profile.json`

---

### Step 6: Verify email delivery

Run without `--dry-run` and confirm:

- the report email arrives
- the sender is correct
- the PDF attachment opens
- report fields are complete

---

## 3. Multi-instance rollout sequence

### Step 1: Prepare instance configs

For example:

- `instances/bio-monitor/config.json`
- `instances/chem-monitor/config.json`

Confirm for each instance:

- `user.name` is unique
- `output_dir` is unique
- recipient email is correct
- any `must_have` / `exclude` constraints in `interest_profile.json` are intentional
- synonym expansion settings are intentional
- cron schedule is reasonable

### Step 2: Start one instance first

```bash
python3 scripts/generate_compose_from_instances.py
docker compose -f docker-compose.multi-instance.yml up -d bio-monitor
docker logs -f bio-monitor
```

For the first verification, it is recommended to temporarily set `schedule.run_on_start = true` for the target instance so it runs immediately after container startup.

For Windows one-shot deployment, the preferred equivalent is:

- manually run `scripts/run-monitor.ps1` once for `bio-monitor`
- after validation, create one Task Scheduler job per config file

### Step 3: Start both instances after the first one passes

```bash
python3 scripts/generate_compose_from_instances.py
docker compose -f docker-compose.multi-instance.yml up -d chem-monitor
```

For Windows one-shot deployment, create separate Task Scheduler tasks such as:

- `AcademicResearchMonitor-Bio`
- `AcademicResearchMonitor-Chem`

### Step 4: Check container status

```bash
docker compose -f docker-compose.multi-instance.yml ps
```

Expected result:

- all instances are running

### Step 5: Check logs per instance

```bash
docker logs -f bio-monitor
docker logs -f chem-monitor
```

### Step 6: Verify output isolation

Confirm:

- `output/bio-monitor/` is used only by the bio instance
- `output/chem-monitor/` is used only by the chem instance

---

## 4. Recommended first-live settings

For a smoother first validation:

- set `schedule.run_on_start = true`
- start with one instance only
- avoid overly broad `interest_profile.core_topics` at first
- set `time_range_hours` to 24 initially unless you have a specific reason to narrow the window
- verify email delivery and PDF quality before enabling all instances

After the first successful run, if you want cron-only scheduling:

- change `schedule.run_on_start` back to `false`
- restart the container

---

## 5. Common failure checks

### 5.1 Container exits immediately

Check:

- config file path is mounted correctly
- `schedule.timezone` is one of the supported values (`Asia/Hong_Kong` or `UTC`)
- `schedule.cron` is valid
- `email.recipient` is not empty
- `output_dir` is writable

### 5.2 No report is generated

Check:

- there are candidate papers to process
- all candidates were not filtered out at the relevance stage
- external APIs are reachable
- the LLM key is valid

### 5.3 Email is not delivered

Check:

- `RESEND_API_KEY`
- recipient email address
- `email.from`
- Resend sending-domain or sandbox restrictions

### 5.4 Run lock appears to be stuck

Check whether the output directory still contains:

```bash
ls output/<instance>/.run.lock
```

If there is no active process using it, remove it:

```bash
rm output/<instance>/.run.lock
```

---

## 6. Recommended command sequence

```bash
PYTHONPYCACHEPREFIX=/tmp/pycache python3 -m unittest discover -s tests -v
python3 scripts/generate_compose_from_instances.py
python3 run.py --config instances/bio-monitor/config.json --dry-run
docker compose -f docker-compose.multi-instance.yml up -d bio-monitor
docker logs -f bio-monitor
docker compose -f docker-compose.multi-instance.yml logs -f
docker compose -f docker-compose.multi-instance.yml up -d chem-monitor
docker compose -f docker-compose.multi-instance.yml ps
docker logs -f chem-monitor
```

Recommended Windows one-shot sequence:

```powershell
docker build -t news-monitor:latest .
powershell -ExecutionPolicy Bypass -File .\scripts\run-monitor.ps1 -ConfigPath instances\bio-monitor\config.json
# after validation, create one Task Scheduler task per monitor instance
```

---

## 7. Mac Docker Desktop pre-commit test plan

Use this release-gate on a Mac before committing changes that will be validated with Docker Desktop. The current target is the two-container setup:

- `bio-monitor`
- `chem-monitor`

### 7.1 Preflight

Run:

```bash
docker info
git ls-files --eol | egrep 'entrypoint.sh|scripts/run-monitor.ps1|Dockerfile|docker-compose.multi-instance.yml'
sh -n entrypoint.sh
PYTHONPYCACHEPREFIX=/tmp/pycache python3 -m unittest discover -s tests -v
```

Pass criteria:

- Docker Desktop daemon is running
- deployment-sensitive files remain LF
- `entrypoint.sh` shell syntax is valid
- the test suite passes

### 7.2 Build the image on Mac Docker Desktop

If you want a Windows-parity image for a later Windows host handoff, build for `linux/amd64` on the Mac. Otherwise, omit `--platform` and build for the local Docker Desktop default.

```bash
docker build --platform linux/amd64 --pull --no-cache -t news-monitor:precommit .
```

Pass criteria:

- image build succeeds
- runtime dependencies install successfully
- `/app/entrypoint.sh` remains executable in the image

### 7.3 Run one-shot dry-runs for each config

Prepare output directories:

```bash
mkdir -p output/bio-monitor output/chem-monitor
```

Run:

```bash
docker run --rm --platform linux/amd64 \
  --env-file .env \
  --name bio-monitor \
  -v "$PWD/instances/bio-monitor:/app/instance:ro" \
  -v "$PWD/output:/app/output" \
  --entrypoint python \
  news-monitor:precommit /app/run.py --config /app/instance/config.json --dry-run
```

```bash
docker run --rm --platform linux/amd64 \
  --env-file .env \
  --name chem-monitor \
  -v "$PWD/instances/chem-monitor:/app/instance:ro" \
  -v "$PWD/output:/app/output" \
  --entrypoint python \
  news-monitor:precommit /app/run.py --config /app/instance/config.json --dry-run
```

Pass criteria for each config:

- exit code is `0`
- no config validation or mount errors occur
- output files are generated successfully under the configured subdirectory only
- daily stats JSON is generated successfully under the configured subdirectory only

### 7.4 Verify generated artifacts

Confirm each instance output directory contains:

- `academic_report_YYYY-MM-DD.html`
- `academic_report_YYYY-MM-DD.pdf`
- `run_stats_YYYY-MM-DD.json`

Confirm each instance definition directory contains:

- `instances/bio-monitor/interest_profile.json`
- `instances/chem-monitor/interest_profile.json`

Also confirm there is no accidental nested path such as:

- `output/bio-monitor/bio-monitor/`
- `output/chem-monitor/chem-monitor/`

Also confirm:

- PDF overview shows `入选论文数（入选/抓取）` in `x/y` format
- `run_stats_YYYY-MM-DD.json` contains:
  - `raw_fetched_count`
  - `raw_fetched_by_source`
  - `deduplicated_candidate_count`
  - `abstract_scored_count`
  - `selected_unique_count`
  - `report_count_display`
- the PDF `x` value matches the actual number of unique papers in the report
- the PDF `y` value matches `run_stats_YYYY-MM-DD.json.raw_fetched_count`

### 7.5 Check Compose / cron startup sanity

Even if production later uses one-shot runs, verify the Compose / cron path still starts cleanly with both services:

```bash
NEWS_MONITOR_IMAGE=news-monitor:precommit docker compose -f docker-compose.multi-instance.yml up -d
docker compose -f docker-compose.multi-instance.yml ps
docker logs bio-monitor --tail 100
docker logs chem-monitor --tail 100
docker exec bio-monitor python - <<'PY'
import json
with open('/app/instance/config.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
print(data['user']['name'])
print(data['output_dir'])
PY
docker exec chem-monitor python - <<'PY'
import json
with open('/app/instance/config.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
print(data['user']['name'])
print(data['output_dir'])
PY
docker exec bio-monitor crontab -l
docker exec chem-monitor crontab -l
docker compose -f docker-compose.multi-instance.yml down --remove-orphans
```

Pass criteria:

- both containers stay up
- there are no immediate config / cron / timezone failures
- `bio-monitor` reports `bio-monitor` and `output/bio-monitor`
- `chem-monitor` reports `chem-monitor` and `output/chem-monitor`
- each container has the expected crontab entry for `run.py --config /app/instance/config.json`

### 7.6 Release gate

Do not commit for Windows deployment unless all of the following are true:

- unit tests pass
- the selected image build passes
- both one-shot dry-runs pass
- expected output artifacts are produced
- daily stats JSON artifacts are produced
- `bio-monitor` and `chem-monitor` write only to their own output directories
- the Compose / cron startup path is healthy
- no CRLF regression is introduced in Docker or shell files

### 7.7 Final Windows host smoke test

Mac validation is necessary but not sufficient. After copying the repo to Windows, run at least one final smoke test there:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-monitor.ps1 -ConfigPath instances\bio-monitor\config.json
```

Repeat for other configs that will be deployed.

Pass criteria:

- Docker Desktop starts or is already ready
- the transient container runs once and exits cleanly
- expected outputs are written to the configured output directory

---

## 8. Deployment acceptance criteria

A successful first deployment should satisfy at least:

- config loads successfully
- containers start successfully
- `instances/<instance>/interest_profile.json` exists before runtime and is readable by the container
- HTML and PDF reports are generated
- email delivery works
- multi-instance outputs do not interfere with each other
- no obvious lock or overlapping-run issues occur
