# macOS Validation Summary — news-monitor

Date: 2026-05-03

## Objective

The goal of this work was to validate this repository on macOS first, before promoting it to a Windows Docker Desktop deployment for daily use.

## What Was Tested

The macOS validation covered the following phases:

1. repository and Markdown documentation review
2. deployment/test planning for macOS first, Windows later
3. creation of a dedicated macOS test config and Docker Compose file
4. unit test execution
5. source test fix for stale date-based fixtures in `tests/test_sources.py`
6. local dry-run validation
7. investigation of relevance filtering and broadening of the test config
8. local WeasyPrint/native dependency troubleshooting on macOS
9. Homebrew installation and native library setup
10. creation of `.venv-mac-test` with Homebrew Python 3.11
11. successful local report/PDF generation
12. Docker build troubleshooting
13. Dockerfile package fix for Debian base image compatibility
14. successful Docker dry-run validation
15. successful real Docker-triggered run with report generation and email sending
16. cleanup of test-only artifacts

## Problems Found and Fixes Applied

### 1. Unit tests failed because source fixtures used stale dates
Two tests failed because they used hardcoded paper dates that had aged outside the fetch window.

**Fix:**
- updated `tests/test_sources.py`
- changed fixture dates to dynamic current UTC time so the tests do not go stale again

### 2. Local dry-run initially failed because the `openai` package was missing
The environment running `python3 run.py` did not yet have the Python dependencies installed.

**Fix:**
- installed the project requirements

### 3. Local dry-run in sandbox could not reach external APIs
Initial local runs inside the sandbox could not reach source APIs or the model endpoint.

**Fix:**
- reran the dry-run outside the sandbox with the `.env` values loaded into the shell

### 4. Local report generation failed because WeasyPrint native libraries were missing on macOS
The local Python environment had `weasyprint` installed but could not load required native libraries.

**Fix:**
- installed Homebrew
- installed native libraries via Homebrew:
  - `cairo`
  - `pango`
  - `gdk-pixbuf`
  - `libffi`
- installed Homebrew Python 3.11
- created `.venv-mac-test`
- installed repo dependencies inside `.venv-mac-test`
- reran the local dry-run successfully with PDF generation

### 5. Docker build failed because the Debian package name was outdated
The original `Dockerfile` used `libgdk-pixbuf2.0-0`, which was not available in the current Debian base image.

**Fix:**
- updated `Dockerfile`
- replaced `libgdk-pixbuf2.0-0` with `libgdk-pixbuf-2.0-0`
- added `shared-mime-info`

### 6. Docker startup test initially skipped because of a stale `.run.lock`
A stale lock file caused the first startup-triggered run to skip.

**Fix:**
- verified no active process still owned the lock
- removed the stale lock file
- reran the application inside the running container

## Final Validated Outcomes

The macOS validation ended with all major milestones succeeding.

### Successful outcomes
- unit tests passed after the fixture fix
- local dry-run completed successfully
- local HTML/PDF report generation succeeded
- Docker image built successfully
- Dockerized dry-run completed successfully
- real Dockerized end-to-end run generated the report successfully
- real email delivery succeeded

### Final successful email evidence
- email send succeeded with ID: `8380accc-5fa7-4fbb-b604-6cb7a77f91b1`

## Important Configuration Decisions Used in Testing

The successful test path used these settings:

- LLM provider: `openai_compatible`
- model: `gpt-4o`
- broader topics:
  - `protein`
  - `drug discovery`
  - `medicinal chemistry`
  - `structure-based design`
- `time_range_hours = 168`
- all major sources enabled:
  - arXiv
  - bioRxiv
  - Nature
  - Science
  - ACS
- `access.mode = open_access`
- Docker image name: `news-monitor-v1.0`

## Current Readiness Conclusion

This repository has now been successfully validated on macOS for:

- Docker build
- Docker runtime
- cron-style entrypoint behavior
- source fetching
- relevance filtering
- LLM analysis
- report generation
- PDF output
- real email delivery

Conclusion:

> The repository is substantially ready for Windows Docker Desktop deployment, pending final default config alignment and Windows-side secrets/config setup.

## Cleanup Performed

After the macOS validation succeeded, the following test-only artifacts were removed:

- `configs/mac-test-monitor.json`
- `docker-compose.mac-test.yml`
- `.venv-mac-test`
- `output/mac-test-monitor/`
- `AI_POST_TEST_CLEANUP_PLAN_macOS_2026-05-03.md`
- Docker image `news-monitor-v1.0:latest`

Reusable repo files were intentionally kept, including:

- `.env`
- `docker-compose.yml`
- `Dockerfile`
- source code
- tests
- reusable example configs

## Validated Test Scenarios

The following scenarios were explicitly validated:

1. unit tests pass after fixing stale fixtures
2. local dry-run reaches report generation successfully
3. Docker image builds successfully after Dockerfile fix
4. Dockerized dry-run generates the report successfully
5. real end-to-end email sending works successfully
