#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./deploy-monitor.sh <service> [--config <path>] [--follow-seconds <n>] [--no-disable-run-on-start]

Examples:
  ./deploy-monitor.sh zy-chem01
  ./deploy-monitor.sh zy-chem01 --config instances/zy-chem01/config.json --follow-seconds 240
  ./deploy-monitor.sh zy-chem01 --no-disable-run-on-start
EOF
}

log() {
  printf '[deploy-monitor] %s\n' "$*"
}

warn() {
  printf '[deploy-monitor][warn] %s\n' "$*" >&2
}

fail() {
  printf '[deploy-monitor][error] %s\n' "$*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

find_repo_root() {
  local candidate="$1"
  while [[ "$candidate" != "/" ]]; do
    if [[ -f "$candidate/docker-compose.multi-instance.yml" && -f "$candidate/compose_generator.py" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
    candidate="$(dirname "$candidate")"
  done
  return 1
}

REPO_ROOT="$(find_repo_root "$SCRIPT_DIR" || true)"
[[ -n "$REPO_ROOT" ]] || fail "Could not determine repo root from script location: $SCRIPT_DIR"
COMPOSE_FILE="$REPO_ROOT/docker-compose.multi-instance.yml"
ENV_FILE="$REPO_ROOT/.env"
FOLLOW_SECONDS=180
DISABLE_AFTER=1
SERVICE=""
CONFIG_PATH=""
ENABLED_FOR_DEPLOY=0
RESTORED=0
ORIGINAL_RUN_ON_START=""

cleanup() {
  if [[ "$ENABLED_FOR_DEPLOY" == "1" && "$DISABLE_AFTER" == "1" && "$RESTORED" == "0" ]]; then
    log "Restoring schedule.run_on_start=false in $CONFIG_PATH"
    python3 - "$CONFIG_PATH" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)
data.setdefault("schedule", {})["run_on_start"] = False
with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
    f.write("\n")
PY
  fi
}

trap cleanup EXIT

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      [[ $# -ge 2 ]] || fail "--config requires a path"
      CONFIG_PATH="$2"
      shift 2
      ;;
    --follow-seconds)
      [[ $# -ge 2 ]] || fail "--follow-seconds requires a number"
      FOLLOW_SECONDS="$2"
      shift 2
      ;;
    --no-disable-run-on-start)
      DISABLE_AFTER=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      fail "Unknown option: $1"
      ;;
    *)
      if [[ -n "$SERVICE" ]]; then
        fail "Only one service name may be provided"
      fi
      SERVICE="$1"
      shift
      ;;
  esac
done

[[ -n "$SERVICE" ]] || { usage; exit 1; }
[[ "$FOLLOW_SECONDS" =~ ^[0-9]+$ ]] || fail "--follow-seconds must be an integer"

require_cmd docker
require_cmd python3

cd "$REPO_ROOT"

[[ -f "$COMPOSE_FILE" ]] || fail "Compose file not found: $COMPOSE_FILE"
[[ -f "$ENV_FILE" ]] || fail "Missing .env file at $ENV_FILE"

if [[ -z "$CONFIG_PATH" ]]; then
  CONFIG_PATH="$(
    python3 - "$SERVICE" <<'PY'
import sys

from compose_generator import resolve_instance_config_path_by_user_name

service = sys.argv[1]
path = resolve_instance_config_path_by_user_name(service)
print(path if path is not None else "")
PY
  )"
fi
[[ -f "$CONFIG_PATH" ]] || fail "Config file not found: $CONFIG_PATH"

if ! docker compose -f "$COMPOSE_FILE" config --services | grep -Fxq "$SERVICE"; then
  fail "Compose service '$SERVICE' not found in $(basename "$COMPOSE_FILE")"
fi

CONFIG_SUMMARY="$(
python3 - "$CONFIG_PATH" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

schedule = data.get("schedule") or {}
user = data.get("user") or {}

required = {
    "user.name": str(user.get("name", "")).strip(),
    "schedule.cron": str(schedule.get("cron", "")).strip(),
    "schedule.timezone": str(schedule.get("timezone", "")).strip(),
    "output_dir": str(data.get("output_dir", "")).strip(),
}
missing = [k for k, v in required.items() if not v]
if missing:
    raise SystemExit("Missing required config field(s): " + ", ".join(missing))

time_range_hours = data.get("time_range_hours")
if not isinstance(time_range_hours, int) or time_range_hours <= 0:
    raise SystemExit("time_range_hours must be a positive integer")

run_on_start = bool(schedule.get("run_on_start", False))

print(required["user.name"])
print(required["schedule.cron"])
print(required["schedule.timezone"])
print("true" if run_on_start else "false")
print(required["output_dir"])
print(str(time_range_hours))
PY
)"

CONFIG_LINES=()
while IFS= read -r line; do
  CONFIG_LINES+=("$line")
done <<<"$CONFIG_SUMMARY"
USER_NAME="${CONFIG_LINES[0]}"
CRON_EXPR="${CONFIG_LINES[1]}"
TIMEZONE="${CONFIG_LINES[2]}"
ORIGINAL_RUN_ON_START="${CONFIG_LINES[3]}"
OUTPUT_DIR_RAW="${CONFIG_LINES[4]}"
TIME_RANGE_HOURS="${CONFIG_LINES[5]}"

if [[ "$OUTPUT_DIR_RAW" = /* ]]; then
  OUTPUT_DIR_HOST="$OUTPUT_DIR_RAW"
else
  OUTPUT_DIR_HOST="$REPO_ROOT/$OUTPUT_DIR_RAW"
fi

log "Service: $SERVICE"
log "Config: $CONFIG_PATH"
log "user.name: $USER_NAME"
log "schedule.cron: $CRON_EXPR"
log "schedule.timezone: $TIMEZONE"
log "time_range_hours: $TIME_RANGE_HOURS"
log "output_dir: $OUTPUT_DIR_HOST"

if [[ "$ORIGINAL_RUN_ON_START" == "false" ]]; then
  log "Temporarily enabling schedule.run_on_start=true for first validation"
  python3 - "$CONFIG_PATH" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)
data.setdefault("schedule", {})["run_on_start"] = True
with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
    f.write("\n")
PY
  ENABLED_FOR_DEPLOY=1
else
  log "schedule.run_on_start already true; leaving it unchanged"
fi

log "Starting service via docker compose"
docker compose -f "$COMPOSE_FILE" up --build -d "$SERVICE"

CONTAINER_ID="$(docker compose -f "$COMPOSE_FILE" ps -q "$SERVICE")"
[[ -n "$CONTAINER_ID" ]] || fail "Could not determine container id for service '$SERVICE'"
CONTAINER_NAME="$(docker inspect --format '{{.Name}}' "$CONTAINER_ID" | sed 's#^/##')"
log "Container: $CONTAINER_NAME"

if command -v timeout >/dev/null 2>&1; then
  log "Following container logs for up to ${FOLLOW_SECONDS}s"
  timeout "${FOLLOW_SECONDS}s" docker logs -f --since=1m "$CONTAINER_NAME" || true
else
  warn "'timeout' not found; showing recent logs instead of timed follow"
  docker logs --tail 200 "$CONTAINER_NAME" || true
fi

CONTAINER_STATE="$(docker inspect --format '{{.State.Status}}' "$CONTAINER_NAME")"
[[ "$CONTAINER_STATE" == "running" ]] || fail "Container is not running (state=$CONTAINER_STATE)"
log "Container state: $CONTAINER_STATE"

log "Recent container logs"
docker logs --tail 120 "$CONTAINER_NAME" || true

mkdir -p "$OUTPUT_DIR_HOST"
if [[ -f "$OUTPUT_DIR_HOST/.run.lock" ]]; then
  warn "Run lock still present at $OUTPUT_DIR_HOST/.run.lock; the startup run may still be in progress"
else
  log "No run lock present under $OUTPUT_DIR_HOST"
fi

log "Output directory contents"
ls -la "$OUTPUT_DIR_HOST" || true

log "Mounted container config"
docker exec "$CONTAINER_NAME" sh -lc 'sed -n "1,120p" /app/instance/config.json' || true

log "Installed cron entry"
docker exec "$CONTAINER_NAME" sh -lc 'crontab -l' || true

RECENT_LOGS="$(docker logs --tail 200 "$CONTAINER_NAME" 2>&1 || true)"
if grep -Fq 'ResendError:' <<<"$RECENT_LOGS"; then
  warn "Detected email delivery failure in recent logs; deployment succeeded but notifications may not send"
fi
if grep -Fq '429 Client Error' <<<"$RECENT_LOGS"; then
  warn "Detected source rate-limiting in recent logs; deployment succeeded but some sources were throttled"
fi

if [[ "$ENABLED_FOR_DEPLOY" == "1" && "$DISABLE_AFTER" == "1" ]]; then
  log "Disabling schedule.run_on_start after validation"
  python3 - "$CONFIG_PATH" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)
data.setdefault("schedule", {})["run_on_start"] = False
with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
    f.write("\n")
PY
  RESTORED=1
  log "Restarting service to apply cron-only mode"
  docker compose -f "$COMPOSE_FILE" restart "$SERVICE"
  log "Verifying cron-only config after restart"
  docker exec "$CONTAINER_NAME" sh -lc 'sed -n "1,40p" /app/instance/config.json; printf "\n--- cron ---\n"; crontab -l' || true
fi

log "Deployment flow completed for service '$SERVICE'"
