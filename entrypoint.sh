#!/bin/sh
set -eu

CONFIG_PATH="${CONFIG_PATH:-/app/instance/config.json}"
CRON_FILE="/etc/cron.d/academic-monitor"
CRON_ENV_FILE="${CRON_ENV_FILE:-/tmp/academic-monitor.env}"
LOG_FILE="/var/log/cron.log"
export CONFIG_PATH CRON_FILE CRON_ENV_FILE

if [ ! -f "$CONFIG_PATH" ]; then
  echo "Config file not found: $CONFIG_PATH" >&2
  exit 1
fi

python3 - <<'PY'
import json
import os
import shlex

config_path = os.environ.get("CONFIG_PATH", "/app/instance/config.json")
cron_file = os.environ.get("CRON_FILE", "/etc/cron.d/academic-monitor")
cron_env_file = os.environ.get("CRON_ENV_FILE", "/tmp/academic-monitor.env")

with open(config_path, "r", encoding="utf-8") as f:
    config = json.load(f)

schedule = config.get("schedule") or {}
cron = str(schedule.get("cron", "0 8 * * *")).strip()
timezone = str(schedule.get("timezone", "Asia/Hong_Kong")).strip() or "Asia/Hong_Kong"
run_on_start = bool(schedule.get("run_on_start", False))

parts = cron.split()
if len(parts) != 5:
    raise SystemExit("Invalid schedule.cron: expected 5 fields")
if timezone not in {"Asia/Hong_Kong", "UTC"}:
    raise SystemExit("Invalid schedule.timezone: supported values are Asia/Hong_Kong and UTC")

with open(cron_file, "w", encoding="utf-8") as f:
    f.write(f"CRON_TZ={timezone}\n")
    retention_cmd = (
        f"/usr/local/bin/python /app/retention.py --config {shlex.quote(config_path)} "
        f"--cron-log /var/log/cron.log --skip-output"
    )
    run_cmd = f"/usr/local/bin/python run.py --config {shlex.quote(config_path)}"
    f.write(
        f"{cron} . {shlex.quote(cron_env_file)}; cd /app && ({retention_cmd} >> /var/log/cron.log 2>&1 || true) && "
        f"{run_cmd} >> /var/log/cron.log 2>&1\n"
    )
PY

RUN_ON_START=$(python3 - <<'PY'
import json
import os

config_path = os.environ.get("CONFIG_PATH", "/app/instance/config.json")
with open(config_path, "r", encoding="utf-8") as f:
    config = json.load(f)
print("true" if (config.get("schedule") or {}).get("run_on_start", False) else "false")
PY
)

chmod 0644 "$CRON_FILE"
crontab "$CRON_FILE"
touch "$LOG_FILE"
/usr/local/bin/python /app/retention.py --config "$CONFIG_PATH" --cron-log "$LOG_FILE" --skip-output >> "$LOG_FILE" 2>&1 || true
python3 - <<'PY'
import os
import shlex

env_file = os.environ.get("CRON_ENV_FILE", "/tmp/academic-monitor.env")
allowed_keys = [
    "CONFIG_PATH",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "RESEND_API_KEY",
]

with open(env_file, "w", encoding="utf-8") as f:
    for key in allowed_keys:
        value = os.environ.get(key)
        if value:
            f.write(f"export {key}={shlex.quote(value)}\n")

os.chmod(env_file, 0o600)
PY

if [ "$RUN_ON_START" = "true" ]; then
  echo "Running initial job before starting cron..."
  /usr/local/bin/python /app/retention.py --config "$CONFIG_PATH" --cron-log "$LOG_FILE" --skip-output >> "$LOG_FILE" 2>&1 || true
  /usr/local/bin/python /app/run.py --config "$CONFIG_PATH" >> "$LOG_FILE" 2>&1 || true
fi

cron
exec tail -f "$LOG_FILE"
