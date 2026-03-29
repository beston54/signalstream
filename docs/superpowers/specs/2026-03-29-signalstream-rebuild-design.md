# Signalstream Rebuild — Design Spec

**Date:** 2026-03-29
**Scope:** Major refactor of the existing Signalstream codebase for public GitHub release
**Goal:** Clean, modular, open-source-ready sentiment analysis tool with bring-your-own-LLM support

---

## 1. Project Structure

Flat domain packages under `signalstream/`. No `core/` grab-bag — each package has a clear owner and boundary.

```
signalstream/
├── app/                        # Flask web layer
│   ├── __init__.py             # App factory
│   ├── middleware/
│   │   └── api_keys.py         # Extract keys from headers, redact from logs
│   ├── routes/
│   │   ├── analysis.py         # Start jobs, job status
│   │   ├── dashboard.py        # Results page, historical dashboard
│   │   ├── api.py              # JSON API endpoints (status, trends, results, compare)
│   │   └── settings.py         # Provider detection + key validation endpoint
│   ├── static/                 # CSS, JS
│   └── templates/
│       ├── layouts/            # Base templates
│       ├── pages/              # Page templates
│       └── components/         # Reusable partials (charts, cards)
│
├── collectors/                 # Data collection from social platforms
│   ├── base.py                 # Abstract interface + normalized Post dataclass
│   ├── reddit.py               # Public JSON (default) + optional PRAW
│   ├── x.py                    # X/Twitter API v2 (optional, requires bearer token)
│   └── http.py                 # Shared resilient HTTP client (retry, backoff, timeouts)
│
├── analyzers/                  # LLM-powered analysis
│   ├── base.py                 # Abstract interface with LLM dependency injection
│   ├── sentiment.py            # Per-post sentiment/emotion analysis
│   ├── thematic.py             # Cross-post theme extraction
│   └── schemas.py              # Output dataclasses (SentimentResult, Theme)
│
├── llm/                        # LLM provider system
│   ├── router.py               # Provider selection, pre-flight check, no auto-fallback
│   ├── config.py               # ProviderConfig dataclass (per-request, not singleton)
│   ├── safety.py               # SSRF validation for custom endpoints
│   └── providers/
│       ├── base.py             # Abstract: complete(messages, model) → str
│       ├── claude.py           # Anthropic API
│       ├── openai_compat.py    # Any OpenAI-compatible endpoint
│       └── ollama.py           # Local Ollama (auto-detected)
│
├── reports/                    # Report generation
│   ├── builder.py              # Assembles report content (what goes in)
│   ├── renderer.py             # HTML → PDF via WeasyPrint (optional dep)
│   ├── charts.py               # Matplotlib chart generation (base64 PNGs)
│   ├── exports.py              # JSON, CSV export
│   └── pdf_templates/          # Jinja2 + CSS for PDF cards (separate from Flask templates)
│       ├── report.html
│       └── styles.css
│
├── jobs/                       # Pipeline orchestration + job lifecycle
│   ├── manager.py              # Thread pool (max 2), submit/cancel/status
│   ├── pipeline.py             # Stage sequencing: collect → analyze → themes → report
│   ├── state.py                # Job state enum, transitions, progress callbacks
│   └── tasks.py                # Per-stage wrappers with error handling + user messages
│
├── db/                         # Database layer
│   ├── engine.py               # Connection management, WAL mode, write lock
│   ├── models.py               # Domain dataclasses (not ORM)
│   ├── repositories.py         # All SQL here (parameterized queries only)
│   └── migrations.py           # Schema versioning, auto-migrate on startup
│
├── cli/                        # CLI entry point
│   └── main.py                 # Argument parsing, env var keys, output formatting
│
├── dev/                        # Internal dev tools (not user-facing)
│   └── orchestrator.py         # Multi-agent review framework
│
└── tests/                      # Mirrors package structure
    ├── conftest.py             # Shared fixtures, mock LLM provider, test DB
    ├── test_collectors/
    ├── test_analyzers/
    ├── test_llm/
    ├── test_reports/
    ├── test_jobs/
    └── test_app/
```

### Key structural changes from current codebase

- `app.py` (1,384 lines) → app factory + route blueprints + middleware
- `collector.py` (2,653 lines) → `collectors/reddit.py` + `collectors/x.py` + `collectors/http.py`
- `report_generator.py` (2,210 lines) → `reports/builder.py` + `reports/renderer.py` + `reports/charts.py`
- `llm_client.py` (397 lines) → `llm/` package with provider system + router + SSRF safety
- Pipeline orchestration extracted from `app.py` into `jobs/` package
- `orchestrator.py` moved to `dev/` (contributor tool, not user-facing)

---

## 2. LLM Provider System

### Architecture

Providers are **stateless**. Each job creates a provider instance with credentials from the request. No singletons, no module-level state.

### Provider types

**Claude (`claude.py`):**
- Anthropic API with system/user message separation (prompt injection defense)
- Key format validation: starts with `sk-ant-`

**OpenAI-compatible (`openai_compat.py`):**
- Works with OpenAI, Groq, Together, LM Studio, local vLLM, etc.
- User provides: endpoint URL + API key + model name
- Endpoint URL validated through `safety.py` before any request

**Ollama (`ollama.py`):**
- Local instance, no API key needed
- Auto-detected: settings page pings `localhost:11434/api/tags` on load
- Model dropdown populated from available models

### ProviderConfig

Per-request dataclass, never a singleton:

```python
@dataclass
class ProviderConfig:
    provider: str          # "claude" | "openai-compat" | "ollama"
    api_key: str | None
    model: str
    endpoint: str | None   # only for openai-compat
```

Built from request headers by middleware. Passed into the job as a parameter. Discarded when the job completes.

### Router behavior

- User picks their provider explicitly in the UI
- No auto-fallback between providers (current Claude → Ollama fallback is removed)
- Pre-flight check before pipeline starts: minimal test call to confirm provider is reachable and key is valid
- Fails fast with a clear, actionable error message

### SSRF validation (`safety.py`)

For user-configurable OpenAI-compatible endpoints:

- HTTPS only (reject http, file, ftp, gopher)
- Reject raw IP addresses — require hostnames
- Resolve hostname and check all A/AAAA records against blocked networks:
  - `127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16` (private)
  - `169.254.0.0/16` (link-local / cloud metadata)
  - IPv6 equivalents (`::1/128`, `fc00::/7`, `fe80::/10`)
- No redirect following (prevents 302 to internal addresses)
- DNS resolution pinning (resolve once, use the resolved IP for the actual request)
- Enforce timeouts (30s connect, 120s read) and response size limits (10MB)

---

## 3. Browser-to-Server Key Flow

### Browser side (localStorage)

```json
{
  "provider": "claude",
  "claude_key": "sk-ant-...",
  "claude_model": "claude-sonnet-4-20250514",
  "openai_key": "sk-...",
  "openai_endpoint": "https://api.openai.com/v1",
  "openai_model": "gpt-4o",
  "ollama_model": "llama3.1:8b"
}
```

### Per-request flow

1. User clicks "Analyze" — JS reads active provider config from localStorage, attaches as HTTP headers
2. Flask middleware (`app/middleware/api_keys.py`) extracts headers into `ProviderConfig`, strips keys from request before any logging
3. Config passed to job manager as a parameter — not stored in database, not written to disk
4. Job holds config in memory for its duration, passes to LLM provider
5. Job completes → config discarded with the thread

### HTTP headers (never query params, never URLs)

```
X-LLM-Provider: claude
X-LLM-API-Key: sk-ant-...
X-LLM-Model: claude-sonnet-4-20250514
X-LLM-Endpoint: https://api.openai.com/v1  (only for openai-compat)
```

### CLI uses standard env vars

- `ANTHROPIC_API_KEY` for Claude
- `OPENAI_API_KEY` + `OPENAI_BASE_URL` for OpenAI-compatible
- `OLLAMA_HOST` for non-default Ollama address
- CLI also accepts `--api-key` as an override

CLI never touches localStorage or HTTP headers.

---

## 4. Job Management System

### Package structure

- **`manager.py`** — thread pool (max 2 concurrent workers). `submit_job()`, `cancel_job()`, `get_status()`. Accepts `ProviderConfig` per job. Persists job metadata to database, never credentials.
- **`pipeline.py`** — sequences four stages. Each stage updates progress via callback. Records which stage failed and why on error.
- **`state.py`** — state machine and progress reporting. Each stage reports: stage name, items processed, items total, current message.
- **`tasks.py`** — per-stage wrappers with error handling. Translates provider errors, rate limits, empty results into user-facing messages.

### Job lifecycle

```
PENDING → COLLECTING → ANALYZING → THEMING → REPORTING → COMPLETED
                                                        → FAILED (from any stage)
```

### Pre-flight sequence (before pipeline starts)

1. Validate `ProviderConfig` — SSRF check on custom endpoints
2. Test LLM connection — minimal API call
3. Only then submit job to thread pool

### Key boundary

`jobs/` depends on `collectors/`, `analyzers/`, `llm/`, `reports/`. It never depends on `app/`. The CLI uses the same job pipeline without importing Flask.

---

## 5. Data Collection Layer

### Normalized Post dataclass

All collectors return `list[Post]`:

```python
@dataclass
class Post:
    platform: str          # "reddit" | "x"
    id: str
    author: str            # anonymized at report time, not collection
    text: str
    title: str | None      # Reddit has titles, X doesn't
    timestamp: datetime
    url: str
    community: str         # subreddit name or X search context
    engagement: int        # upvotes / likes
    comments: list[str]    # top N comment texts
```

### Reddit collector

- **Default:** public JSON endpoints (`/r/{subreddit}/search.json`). No API key needed. Rate-limited to 1 req/sec with backoff.
- **Upgrade path:** if `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` env vars are set, uses PRAW automatically.
- README disclaimer about public JSON and Reddit ToS.

### X collector

- Requires bearer token via `X-Twitter-Bearer` header (browser) or `X_API_BEARER_TOKEN` env var (CLI)
- Optional — skipped with a note if no token configured

### Shared HTTP client (`http.py`)

- Wraps `requests.Session` with: 3 retries, exponential backoff (2s base + jitter), Retry-After header parsing, configurable timeouts, response size limits
- Used by both collectors and LLM providers

### Content sanitization at collection time

- Strip HTML tags from scraped content using `nh3` before storing in SQLite
- First line of XSS defense — malicious content never reaches the database in raw form

---

## 6. Analysis Layer

### Design principle

Analyzers receive a provider instance via dependency injection. They never import the LLM router directly. This makes them testable with a mock provider.

### Sentiment analyzer

- Input: `list[Post]` + provider instance
- Output: `list[AnalyzedPost]` (post enriched with `SentimentResult`)

```python
@dataclass
class SentimentResult:
    sentiment: str         # positive | negative | neutral | mixed
    emotion: str           # joy, anger, fear, surprise, etc.
    confidence: float      # 0.0–1.0
    key_point: str         # one-sentence summary
    sarcasm_detected: bool
```

- Partial failure handling: if 5/37 posts fail (rate limits, malformed LLM output), returns the 32 that succeeded with a count of skipped posts
- Progress callback after each post for UI updates

### Thematic analyzer

- Input: `list[AnalyzedPost]` (output of sentiment analysis)
- Sends batch summary to LLM (not each post individually)
- Output: `list[Theme]` sorted by prevalence

```python
@dataclass
class Theme:
    name: str
    description: str
    percentage: float      # share of posts touching this theme
    post_count: int
    sentiment_skew: str    # positive | negative | neutral
    representative_quotes: list[str]
```

### LLM output handling

- Parsing lives in each analyzer, not the provider. Provider returns raw text; analyzer parses into typed schema.
- Malformed LLM output → retry once with tighter prompt → skip that post on second failure

---

## 7. Reports & Dashboard

### Reports package

- **`builder.py`** — assembles report content: which sections, which data, which charts. Produces a `ReportContent` dataclass.
- **`renderer.py`** — takes `ReportContent`, produces PDF via WeasyPrint. Owns the custom `url_fetcher` that blocks all external resource loading (SSRF mitigation). Only file that imports WeasyPrint.
- **`charts.py`** — Matplotlib chart generation as base64 PNGs. Used by the PDF renderer only. Emotion distribution, sentiment split, theme frequency, community breakdown. The web dashboard renders its own charts client-side via Chart.js from JSON API data.
- **`exports.py`** — JSON and CSV export of analysis results.
- **`pdf_templates/`** — Jinja2 + CSS for PDF report cards. Separate Jinja2 environment from Flask templates.

### WeasyPrint is optional

```python
try:
    import weasyprint
    PDF_AVAILABLE = True
except (ImportError, OSError):
    PDF_AVAILABLE = False
```

- If not installed: "Download PDF" button shows platform-detected install instructions
- Fallback: "Print / Save as PDF" via `window.print()` with print stylesheet
- All dashboard and analysis features work without WeasyPrint
- Install via `pip install signalstream[pdf]`

### WeasyPrint SSRF mitigation

Custom `url_fetcher` in `renderer.py`:
- Only allows `data:` URIs and pre-approved local static files
- Blocks all external URLs and `file://` URIs
- Prevents CSS/HTML resource loading attacks during PDF rendering

### Dashboard

**Results page** (after job completes):
- Sentiment breakdown with chart
- Emotion distribution chart
- Top themes with representative quotes
- Community-level breakdown
- Key metrics (post count, dominant emotion, sentiment ratio)
- "Download PDF" button + "Export JSON/CSV"
- Data loaded from `/api/results/<job_id>` JSON endpoint

**Historical dashboard** (separate page):
- Past analyses with key metrics
- Trend charts: sentiment for a topic over multiple runs
- Side-by-side comparison of two analyses
- Filterable by topic, date range
- Data from `/api/trends` and `/api/compare` endpoints

**Dashboard charts are client-side** — rendered from JSON API data using a lightweight charting library (Chart.js). Interactive: hover, filter, drill-down. No server-round-trips for chart rendering.

---

## 8. Database Layer

### Design decisions

- **Raw SQLite, no ORM.** Schema is straightforward. SQLAlchemy adds complexity without payoff.
- **All SQL in `repositories.py`.** Single file to audit for injection. No raw queries elsewhere.
- **Parameterized queries exclusively.** No f-strings or string formatting with user input.
- **WAL mode** for concurrent reads. Write serialization through a threading lock.
- **Auto-migration on startup.** `migrations.py` checks `schema_version` pragma, applies migrations sequentially. New databases created fresh. Zero manual setup.
- **Legacy migration:** auto-imports from `data/job_history.json` if it exists and database doesn't.

### What's stored vs what's not

**Stored:** job metadata (topic, status, timestamps), analysis results (sentiment, themes, stats), chart data for trends, job progress/error state.

**Never stored:** API keys, raw request headers, provider credentials.

### Data retention

- Configurable auto-delete, default 90 days. Runs on app startup.
- "Delete all data" endpoint in the UI.
- `VACUUM` after bulk deletes to reclaim space and ensure data is removed from the file.
- Database file, WAL, and journal in `.gitignore`.

### Post-job data minimization

After a job completes, full post text is replaced with truncated summaries. The PDF/dashboard has everything it needs from aggregated results. Limits liability of storing third-party content.

---

## 9. First-Run Experience & Configuration

### Zero-config startup

```bash
python -m signalstream
# → SQLite auto-created
# → Schema migrations applied
# → Browser opens to localhost:5000
# → Welcome screen with search box
```

### First-run flow

1. User sees search box with topic input — enters topic, clicks "Get Started"
2. No provider configured → inline provider selector appears (not a separate settings page):
   - **Ollama (free, local)** — auto-detected if running, green badge, model dropdown populated
   - **Claude (best quality)** — paste key, test connection
   - **OpenAI-compatible (flexible)** — endpoint URL + key + model
3. User picks provider, clicks "Analyze" — pipeline starts immediately
4. Provider choice persists in localStorage for next session

Settings page exists separately for changing provider later, but first-run never routes there.

### Config file is entirely optional

`config.yaml` overrides defaults. Everything commented out by default. The file is documentation, not a prerequisite.

```yaml
# search:
#   max_posts: 50              # default: 25
#   time_filter: month         # default: week
#   subreddits: [technology]   # default: auto from topic

# branding:
#   company_name: "My Company"
#   accent_color: "#2563eb"

# server:
#   host: 127.0.0.1            # default, never 0.0.0.0
#   port: 5000

# data:
#   retention_days: 90         # default: 90
```

### CLI mirrors zero-config

```bash
# Ollama auto-detected
python -m signalstream analyze "remote work"

# Cloud provider via env var
ANTHROPIC_API_KEY=sk-ant-... python -m signalstream analyze "remote work"

# Full control
python -m signalstream analyze "remote work" \
  --subreddits technology,cscareer \
  --max-posts 100 \
  --format pdf,html,json \
  --open
```

---

## 10. Repo Hygiene & Open-Source Readiness

### Root-level files

```
pyproject.toml              # Package metadata, deps, extras, CLI entry point
LICENSE                     # MIT
README.md                   # Screenshot, quickstart, provider paths, architecture
CONTRIBUTING.md             # Setup, code style, PR process
SECURITY.md                 # Disclosure policy, API key handling docs
CHANGELOG.md                # Start at 0.1.0
Dockerfile                  # Full env including WeasyPrint system deps
docker-compose.yml          # App + optional Ollama sidecar
.gitignore                  # db, logs, reports, .env, __pycache__, config.yaml
config.example.yaml         # Commented-out defaults
```

### pyproject.toml

```toml
[project]
name = "signalstream"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "flask>=3.0",
    "requests>=2.31",
    "matplotlib>=3.8",
    "jinja2>=3.1",
    "nh3>=0.2",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
pdf = ["weasyprint>=60"]
reddit-api = ["praw>=7.7"]
dev = ["pytest", "ruff", "mypy", "pre-commit"]

[project.scripts]
signalstream = "signalstream.cli.main:main"
```

### GitHub configuration

```
.github/
├── workflows/
│   └── ci.yml              # ruff + pytest on Python 3.10–3.12
├── ISSUE_TEMPLATE/
│   ├── bug_report.yml
│   └── feature_request.yml
└── PULL_REQUEST_TEMPLATE.md
```

### Security hardening (baked into code)

- CSP headers on all responses (`script-src 'self'`, no inline scripts)
- CORS same-origin only
- `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`
- Header-sanitizing middleware redacts API keys from all logs
- `debug=False` unless `SIGNALSTREAM_DEBUG=1` explicitly set
- Bind `127.0.0.1` by default, startup warning if overridden
- SSRF validation on custom LLM endpoints
- WeasyPrint custom `url_fetcher` blocks external resources
- Input validation on all job parameters (subreddit names, queries, dates)
- Parameterized SQL exclusively
- Content sanitization on ingestion via `nh3`

### Docker

```bash
docker compose up
# → App at localhost:5000 with all deps (including WeasyPrint)
# → Optional Ollama sidecar for zero-key local analysis
```

Sidesteps WeasyPrint system deps and Python version issues entirely.

---

## Out of Scope

These are explicitly not part of this rebuild:

- User accounts or authentication (local-first tool)
- Email gating for downloads
- Server-side API key storage
- Multi-user deployment features
- Plugin/extension system for custom collectors
- Mobile-responsive UI (desktop-first for now)
