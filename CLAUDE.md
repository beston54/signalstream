# Signalstream

LLM-powered sentiment analysis tool. Scrapes Reddit/X, analyzes with Claude/OpenAI/Ollama, generates PDF reports and interactive dashboards.

## Status

Active rebuild on branch `rebuild/v0.1.0`. Migrating from monolithic `scripts/` + `app.py` to modular `signalstream/` package.

- Design spec: `docs/superpowers/specs/2026-03-29-signalstream-rebuild-design.md`
- Board review verdict: `docs/superpowers/specs/2026-03-29-board-verdict.md`
- Implementation plans: `docs/superpowers/plans/2026-03-29-plan-{1,2,3}-*.md`
- Plan 1 (Foundation): Tasks 0-2 complete, Task 3+ pending
- Plan 2 (Pipeline): Not started
- Plan 3 (Web): Not started

## Architecture

```
signalstream/           # New modular package (being built)
├── db/                 # SQLite with WAL, write lock, incremental vacuum
├── llm/                # Provider system (Claude, Ollama, OpenAI-compat)
├── collectors/         # Reddit (public JSON + PRAW), X deferred to v0.3.0
├── analyzers/          # Sentiment + thematic with checkpointing
├── jobs/               # Pipeline orchestration, thread pool (max 2)
├── reports/            # PDF (WeasyPrint optional), charts (Matplotlib), JSON export
├── app/                # Flask web UI with middleware
└── tests/              # Mirrors package structure

scripts/                # Legacy code (reference only, do not modify)
app.py                  # Legacy Flask app (reference only)
```

## Key Decisions

- **API keys**: Browser localStorage, sent via `X-LLM-*` headers per-request, never stored server-side
- **No auth**: Local-first tool, binds 127.0.0.1 by default
- **WeasyPrint optional**: `pip install signalstream[pdf]`, graceful fallback
- **Port 5001**: Avoids macOS AirPlay conflict on 5000
- **CLI deferred** to v0.2.0, X/Twitter to v0.3.0

## Commands

```bash
pip install -e ".[dev]"                    # Install with dev deps
pip install -e ".[dev,pdf,claude]"         # Full install
python -m pytest signalstream/tests/ -v    # Run tests
python -m pytest signalstream/tests/ -x -q # Fast fail
ruff check signalstream/                   # Lint
```

## Build Rules

- Python 3.10+. Use `from __future__ import annotations` in all files.
- TDD: write failing test first, then implement, then commit.
- All SQL in `db/repositories.py` only. Parameterized queries exclusively. No f-strings with user input.
- LLM providers are stateless. Per-request `ProviderConfig`, no singletons.
- `temperature=0.0` for all classification calls (deterministic output).
- Matplotlib: Agg backend, OO API only (no `plt.*`), thread lock around figure creation.
- `nh3.clean()` all scraped content before storage. Enforced in base collector.
- WeasyPrint: always pass `url_fetcher=_safe_url_fetcher` that blocks all non-`data:` URIs.
- SSRF validation on custom LLM endpoints. Localhost exempt from HTTPS requirement.
- Security headers (CSP, X-Frame-Options, nosniff) in `app/middleware/security.py`.
- Commit messages: `feat(scope):`, `fix(scope):`, `test(scope):` format.

## Don't

- Don't modify files in `scripts/` or the root `app.py` — those are legacy reference.
- Don't store secrets in config files, database, or server-side storage.
- Don't use `plt.*` pyplot API — use Figure/Axes OO API.
- Don't use `|safe` or `Markup()` on user-influenced content in Jinja2 templates.
- Don't put user data in `<script>` blocks.
- Don't follow redirects on user-provided endpoint URLs.
- Don't log request headers without redacting `X-LLM-*` keys.
