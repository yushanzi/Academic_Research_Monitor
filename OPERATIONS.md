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
- One JSON config per monitor instance under `configs/`

## Add a New Monitor Instance

### 1. Create a config file

Copy one of the example configs and adjust:

```bash
cp configs/bio-monitor.json configs/my-monitor.json
```

Update at minimum:

- `user.name`
- `schedule.cron`
- `topics`
- `interest_description`
- `email.recipient`
- `output_dir`
- source enablement under `sources`

Rules:

- `schedule.timezone` must be `UTC` in the current implementation
- `output_dir` should be unique per instance, e.g. `output/my-monitor`
- `user.name` should be unique per instance
- keep secrets out of instance config files
- in Windows one-shot mode, `schedule.cron` and `schedule.run_on_start` are informational only; Task Scheduler is the actual schedule source

### 2. Add a service to Compose

Example service block:

```yaml
  my-monitor:
    build: .
    container_name: academic-monitor-my-monitor
    env_file:
      - .env
    environment:
      CONFIG_PATH: /app/config.json
    volumes:
      - ./output:/app/output
      - ./configs/my-monitor.json:/app/config.json:ro
    restart: unless-stopped
```

You can add this block to `docker-compose.multi-instance.yml` or maintain a site-specific compose file.

### 2b. Windows one-shot runtime (recommended on Windows)

Build the image once:

```bash
docker build -t news-monitor:latest .
```

Then run a single instance manually:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-monitor.ps1 -ConfigPath configs\my-monitor.json
```

This starts a transient container with `docker run --rm`, mounts the selected config as `/app/config.json`, mounts the configured output directory to `/app/output`, runs the monitor once, and removes the container on completion.

The script first checks Docker readiness. If Docker Desktop is not ready, it attempts to start Docker Desktop and waits for the engine to become ready for up to 5 minutes before running the container.

### 3. Start the new instance

```bash
docker compose -f docker-compose.multi-instance.yml up --build -d my-monitor
```

For Windows one-shot scheduling, instead of a long-running Compose service, create a Task Scheduler job that runs:

```powershell
powershell -ExecutionPolicy Bypass -File C:\path\to\repo\scripts\run-monitor.ps1 -RepoRoot C:\path\to\repo -ConfigPath configs\my-monitor.json
```

Recommended Task Scheduler setting: run the task only when the user is logged in, so Docker Desktop can be started interactively if needed.

### 4. Verify startup

Check logs:

```bash
docker logs -f academic-monitor-my-monitor
```

Expected startup flow:

- config is loaded
- runtime cron file is generated
- optional startup run happens if `schedule.run_on_start=true`
- cron starts and tails `/var/log/cron.log`
- `/var/log/cron.log` should be rotated by the container platform or host log pipeline for long-running deployments

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
  interest_profile.json
  academic_report_YYYY-MM-DD.html
  academic_report_YYYY-MM-DD.pdf
```

### Check schedule behavior

- confirm the cron expression in config
- confirm the instance logs mention the expected query topics and report date
- confirm no `.run.lock` file is stuck after a normal run

### Check email delivery

- verify report emails arrive at `email.recipient`
- verify sender matches `email.from`
- if no papers are selected, verify the empty-notification variant is sent

## Common Failure Modes

### Container exits immediately

Likely causes:

- config file missing
- invalid `schedule.cron`
- invalid `schedule.timezone`
- invalid email or missing required config field
- output directory not writable

### Container runs but no report is produced

Check:

- source enablement in config
- whether the topic/interest profile is too restrictive
- whether all candidate papers were filtered out at relevance stage
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

- interest profile cache is fingerprinted on config + internal prompt/schema/parser versions
- changing model, topics, or interest description triggers cache refresh on next run
- in Windows one-shot mode, if you change only the config file, the next scheduled Task Scheduler run picks it up automatically; no always-on container restart is needed

## Recommended Naming Convention

- config file: `configs/<instance>.json`
- container name: `academic-monitor-<instance>`
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
