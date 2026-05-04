# Operations Guide

## Purpose

This guide describes how to add and operate a new monitor instance in production using the single-image, multi-container model.

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

### 3. Start the new instance

```bash
docker compose -f docker-compose.multi-instance.yml up --build -d my-monitor
```

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
