# Academic Research Monitor Deployment Checklist

## 1. Pre-deployment checks

### 1.1 Environment

Make sure the target machine has:

- Docker Desktop (WSL2 backend recommended on Windows)
- Docker Compose
- outbound network access to external APIs
- a writable directory for the `output/` volume mount
- an editor that will not convert shell scripts to CRLF

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

Make sure each `configs/<instance>.json` includes at least:

- `user.name`
- `schedule.cron`
- `schedule.timezone = UTC`
- `schedule.run_on_start`
- `topics` or `interest_description`
- `llm.provider`
- `llm.model`
- `email.recipient`
- `output_dir`
- `access.mode = open_access`

### 1.4 Output layout

Plan the output directories in advance, for example:

```text
output/
  bio-monitor/
  chem-monitor/
```

Each instance should write to its own directory.

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
python3 run.py --config configs/bio-monitor.json --dry-run
```

Expected checks:

- no config validation errors
- papers can be fetched and analyzed
- reports are generated successfully
- generated files include:
  - `output/<instance>/interest_profile.json`
  - `output/<instance>/academic_report_YYYY-MM-DD.html`
  - `output/<instance>/academic_report_YYYY-MM-DD.pdf`

---

### Step 3: Build and start with Docker

```bash
docker compose -f docker-compose.multi-instance.yml up --build -d
```

Expected checks:

- containers start successfully
- containers do not exit immediately because of config errors
- `entrypoint.sh` generates cron successfully
- if `run_on_start=true`, the instance performs one immediate run at startup

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
- `Using query topics`
- `Found X papers`
- `Total relevant papers`
- `Report saved`

If a Windows container cannot read mounted directories, first check Docker Desktop file sharing / path access settings.

---

### Step 5: Verify output files

For example:

```bash
ls -la output/bio-monitor
```

Confirm that the directory contains:

- `interest_profile.json`
- `.html`
- `.pdf`

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

- `configs/bio-monitor.json`
- `configs/chem-monitor.json`

Confirm for each instance:

- `user.name` is unique
- `output_dir` is unique
- recipient email is correct
- cron schedule is reasonable

### Step 2: Start one instance first

```bash
docker compose -f docker-compose.multi-instance.yml up --build -d bio-monitor
docker logs -f academic-monitor-bio
```

For the first verification, it is recommended to temporarily set `schedule.run_on_start = true` for the target instance so it runs immediately after container startup.

### Step 3: Start both instances after the first one passes

```bash
docker compose -f docker-compose.multi-instance.yml up --build -d
```

### Step 4: Check container status

```bash
docker compose -f docker-compose.multi-instance.yml ps
```

Expected result:

- all instances are running

### Step 5: Check logs per instance

```bash
docker logs -f academic-monitor-bio
docker logs -f academic-monitor-chem
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
- avoid overly broad topics at first
- set `time_range_hours` to 12 or 24 initially
- verify email delivery and PDF quality before enabling all instances

After the first successful run, if you want cron-only scheduling:

- change `schedule.run_on_start` back to `false`
- restart the container

---

## 5. Common failure checks

### 5.1 Container exits immediately

Check:

- config file path is mounted correctly
- `schedule.timezone` is `UTC`
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
python3 run.py --config configs/bio-monitor.json --dry-run
docker compose -f docker-compose.multi-instance.yml up --build -d bio-monitor
docker logs -f academic-monitor-bio
docker compose -f docker-compose.multi-instance.yml logs -f
docker compose -f docker-compose.multi-instance.yml up --build -d
docker compose -f docker-compose.multi-instance.yml ps
docker logs -f academic-monitor-chem
```

---

## 7. Deployment acceptance criteria

A successful first deployment should satisfy at least:

- config loads successfully
- containers start successfully
- `interest_profile.json` is generated
- HTML and PDF reports are generated
- email delivery works
- multi-instance outputs do not interfere with each other
- no obvious lock or overlapping-run issues occur
