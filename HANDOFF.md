# Fintech Change Radar — developer handoff

## Purpose

Fintech Change Radar monitors public product and technology updates relevant to a Russian retail bank. It collects RSS/Atom publications, groups evidence into events, and prepares Russian-language analysis cards with facts, interpretation, hypotheses, limitations, research questions, and source links.

## Current design

- Python application with PostgreSQL, a Telegram bot, a web feed, and a background worker.
- Ten configured RSS feeds and a prioritized company watchlist are in `config/radar.json`.
- The worker collects every six hours and prepares a daily digest for 09:00 Moscow time.
- Model spending is limited to $1 per database per Moscow calendar day. Unknown model pricing pauses paid analysis while collection can continue.
- Publications, events, evidence, spending, digests, and per-recipient delivery state are stored separately.
- Database initialization and migrations preserve legacy findings, materials, and subscribers. Do not replace a database or volume without a verified backup and an explicit migration plan.
- Telegram credentials and the OpenRouter key belong in protected environment variables only. Never commit secrets or paste them into issues, logs, or chat.

## Local development

- Install dependencies with `pip install -r requirements.txt`.
- Copy the variable names and safe defaults from `.env.example` into a local environment file. Local secret files and database exports are ignored by Git.
- `compose.local.yaml` runs an isolated local PostgreSQL database, worker, bot, and feed. Keep it stopped unless local Telegram use has been explicitly arranged; one Telegram polling bot should have only one active instance.
- `compose.test.yml` provides a disposable PostgreSQL database for `scripts/run_checks.py`.
- Run the test suite with `python scripts/run_checks.py`; run Ruff with `ruff check .`.

## Recent verification snapshot

As of 2026-11-02, 33 tests passed on Python 3.14 and 27 passed in the Python 3.12 Docker image. Ten public feeds were checked, and a repeated collection added no duplicates. The live OpenRouter model and Telegram delivery were not exercised in that local verification. Collected publications are source material, not finished AI cards.

## Deployment principles

- Deploy Radar as its own application with its own database or persistent volume, secrets, schedule, and Telegram endpoint.
- Do not replace or reconfigure another running application as part of a Radar deployment.
- Before deploying, inspect the target configuration, make and verify a database backup, and record a rollback path.
- After deployment, check the worker, `/health`, the feed, `/start`, `/status`, Telegram delivery, the daily digest, and persistence after restart.
- See `DEPLOY_COOLIFY.md` for the deployment checklist and rollback notes; verify it against the actual target before use.

## Project references

- `README.md` — architecture and setup.
- `VERIFICATION.md` and `reports/` — recorded checks and their limits.
- `LOCAL_RUN.md` — local-only operating instructions.
- `config/radar.json` — sources, schedule, watchlist, and analysis limits.
- `db/` — schema and migrations.
