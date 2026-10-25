from __future__ import annotations

import argparse
import random
import subprocess
import sys
import time
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a scheduled monitor job with optional random jitter.")
    parser.add_argument("--config", required=True, help="Path to the config.json file")
    parser.add_argument("--cron-log", required=True, help="Path to the cron log file")
    parser.add_argument(
        "--jitter-window-seconds",
        type=int,
        default=0,
        help="Randomly delay the job by 0..N seconds before running",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    repo_root = Path(__file__).resolve().parents[1]

    if args.jitter_window_seconds > 0:
        delay_seconds = random.randint(0, args.jitter_window_seconds)
        print(
            f"[scheduler] Applying random delay of {delay_seconds}s within 0..{args.jitter_window_seconds}s window.",
            flush=True,
        )
        time.sleep(delay_seconds)

    retention_cmd = [
        sys.executable,
        str(repo_root / "retention.py"),
        "--config",
        args.config,
        "--cron-log",
        args.cron_log,
        "--skip-output",
    ]
    subprocess.run(retention_cmd, check=False)

    run_cmd = [sys.executable, str(repo_root / "run.py"), "--config", args.config]
    result = subprocess.run(run_cmd, check=False)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
