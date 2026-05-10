# Operations Guide

## Purpose

This guide describes how to add and operate a new monitor instance in production using the single-image, multi-container model.

For Windows, the preferred operational model is **host-scheduled one-shot runs**:

- Docker Desktop can remain running
- the image is built once and reused
- Task Scheduler starts a transient container for each run
- the container exits after the monitor finishes
- if Docker Desktop is not ready, the PowerShell runner can try to start it and wait up to 5 minutes

## Prerequisites

- Docker and Docker Compose available on the host
- A `.env` file with valid:
  - `RESEND_API_KEY`
  - `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`
- Writable host `output/` directory
- One JSON config per monitor instance under `instances/`

## Add a New Monitor Instance

### 1. Create a config file and interest profile

Either copy the template manually:

```bash
mkdir -p instances/my-monitor
cp instances/bio-monitor/config.json instances/my-monitor/config.json
cp instances/bio-monitor/interest_profile.json instances/my-monitor/interest_profile.json
```

Or, preferably, generate both the instance config and the required profile file from a user interest document:

```bash
python3 scripts/generate_config_from_doc.py \
  --input docs/my-interest.md \
  --output instances/my-monitor/config.json \
  --user-name my-monitor \
  --email you@example.com
```

Update at minimum:

- `user.name`
- `schedule.cron`
- `email.recipient`
- `email.send_empty_notification`
- `output_dir`
- `retention.days`
- source enablement under `sources`
- `instances/<instance>/interest_profile.json`

Rules:

- `schedule.timezone` should normally be `Asia/Hong_Kong` (supported values: `Asia/Hong_Kong`, `UTC`)
- `output_dir` should be unique per instance and stay under the repo-level `output/` tree, e.g. `output/my-monitor` (do not point it into `instances/`)
- `user.name` should be unique per instance
- `instances/<instance>/interest_profile.json` must exist and be confirmed before runtime starts
- `config.json` must not contain `topics`, `interest_description`, `must_have`, or `exclude`
- keep secrets out of instance config files
- in Windows one-shot mode, `schedule.cron` and `schedule.run_on_start` are informational only; Task Scheduler is the actual schedule source

### 2. Regenerate the Compose file

Regenerate the Compose file from all instance configs:

```bash
python3 scripts/generate_compose_from_instances.py
```

The generated `docker-compose.multi-instance.yml` uses:

- `service name = user.name`
- `container_name = user.name`

Do not hand-edit service blocks; treat the compose file as generated output.

### 2b. Windows one-shot runtime (recommended on Windows)

Build the image once:

```bash
docker build -t news-monitor:latest .
```

Then run a single instance manually:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-monitor.ps1 -ConfigPath instances\my-monitor\config.json
```

This starts a transient container with `docker run --rm`, mounts the selected instance directory as `/app/instance`, mounts the configured output directory to `/app/output`, runs the monitor once, and removes the container on completion.

Because this wrapper runs `python /app/run.py` directly, Windows one-shot runs still apply `retention.days` to dated files in `output_dir`, but they do not exercise the container-internal `/var/log/cron.log` trimming path from `entrypoint.sh`.

The script first checks Docker readiness. If Docker Desktop is not ready, it attempts to start Docker Desktop and waits for the engine to become ready for up to 5 minutes before running the container.

The one-shot container name is also taken from `user.name`. If a stale container with that name already exists, the script stops and asks you to remove it first.

### 3. Start the new instance

```bash
python3 scripts/generate_compose_from_instances.py
docker compose -f docker-compose.multi-instance.yml up -d my-monitor
```

For Windows one-shot scheduling, instead of a long-running Compose service, create a Task Scheduler job that runs:

```powershell
powershell -ExecutionPolicy Bypass -File C:\path\to\repo\scripts\run-monitor.ps1 -RepoRoot C:\path\to\repo -ConfigPath instances\my-monitor\config.json
```

Recommended Task Scheduler setting: run the task only when the user is logged in, so Docker Desktop can be started interactively if needed.

### 4. Verify startup

Check logs:

```bash
docker logs -f my-monitor
```

Expected startup flow:

- config is loaded
- runtime cron file is generated
- optional startup run happens if `schedule.run_on_start=true`
- cron starts and tails `/var/log/cron.log`
- `/var/log/cron.log` is trimmed automatically to the configured retention window (`retention.days`, default 30)

For Windows one-shot mode, verify instead:

- the Task Scheduler job starts successfully
- Docker Desktop starts automatically if it was not already ready
- the transient container appears and exits
- output files are written to the configured output directory
- email delivery works when not using `--dry-run`

## Operational Checks

### Check generated outputs

Each instance should write only to its own directory, for example:

```text
output/my-monitor/
  academic_report_YYYY-MM-DD.html
  academic_report_YYYY-MM-DD.pdf
  run_stats_YYYY-MM-DD.json
```

The monitor definition files stay under:

```text
instances/my-monitor/
  config.json
  interest_profile.json
```

### Check schedule behavior

- confirm the cron expression in config
- confirm the instance logs mention the expected query topics and report date
- confirm no `.run.lock` file is stuck after a normal run

### Check email delivery

- verify report emails arrive at `email.recipient`
- verify sender matches `email.from`
- if no papers are selected, verify the empty-notification variant is sent only when `email.send_empty_notification=true`

## Common Failure Modes

### Container exits immediately

Likely causes:

- config file missing
- `interest_profile.json` missing or not confirmed
- invalid `schedule.cron`
- invalid `schedule.timezone`
- invalid email or missing required config field
- output directory not writable

### Container runs but no report is produced

Check:

- source enablement in config
- whether the topic/interest profile is too restrictive
- whether selected synonym expansion, profile-level `must_have` / `exclude`, or candidate threshold needs tuning
- whether all candidate papers were filtered out at abstract-gate or relevance stage
- whether external APIs are failing

### Repeated skipping due to lock

If logs repeatedly say another run is in progress:

- inspect whether the previous run is actually still executing
- if the container crashed mid-run, remove the stale lock from the instance output directory:

```bash
rm output/my-monitor/.run.lock
```

Only do this after confirming no active process is using that directory.

## Safe Rollout Pattern

For a new production instance:

1. set `schedule.run_on_start=true`
2. start only that one container
3. verify one successful end-to-end run
4. switch `schedule.run_on_start=false` if you only want cron-driven runs
5. restart the container

## Updating an Existing Instance

When changing config:

1. edit the instance JSON file
2. restart the target container:

```bash
docker compose -f docker-compose.multi-instance.yml restart my-monitor
```

Notes:

- `interest_profile.json` is the runtime source of truth for interest matching
- if you change user interests, regenerate or edit `instances/<instance>/interest_profile.json` before the next run
- source recall uses `core_topics + selected_synonyms`
- exclude decisions are made by the abstract-level LLM gate, not a local hard exclude filter
- in Windows one-shot mode, if you change only the config file, the next scheduled Task Scheduler run picks it up automatically; no always-on container restart is needed

## Recommended Naming Convention

- config file: `instances/<instance>/config.json`
- container/service name: `user.name`
- output dir: `output/<instance>`
- `user.name`: `<instance>`

## Minimal Production Checklist

- config validated locally
- unique `user.name`
- unique `output_dir`
- correct recipient email
- sources enabled intentionally
- `.env` present on host
- first run observed in logs
- output files generated
- email received
