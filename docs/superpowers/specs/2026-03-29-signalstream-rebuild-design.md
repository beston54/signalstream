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
│   │   ├── api_keys.py         # Extract keys from headers, redact from logs
│   │   └── security.py         # Security headers (CSP, X-Frame-Options, etc.) + CSRF
│   ├── errors.py               # Error code catalog with user-facing messages
│   ├── routes/
│   │   ├── analysis.py         # Start jobs, job status
│   │   ├── dashboard.py        # Results page
│   │   ├── api.py              # JSON API endpoints (status, results)
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
│   └── http.py                 # Shared resilient HTTP client (retry, backoff, timeouts)
│
├── analyzers/                  # LLM-powered analysis
│   ├── base.py                 # Abstract interface with LLM dependency injection
│   ├── prompts.py              # All LLM prompt templates (version-tagged)
│   ├── sentiment.py            # Per-post sentiment/emotion analysis with checkpointing
│   ├── thematic.py             # Cross-post theme extraction with chunking
│   └── schemas.py              # Output dataclasses + validation functions
│
├── llm/                        # LLM provider system
│   ├── router.py               # Provider selection, pre-flight check, no auto-fallback
│   ├── config.py               # ProviderConfig dataclass (per-request, not singleton)
│   ├── safety.py               # SSRF validation for custom endpoints
│   └── providers/
│       ├── base.py             # Abstract: complete(messages, model, config) → str
│       ├── claude.py           # Anthropic API
│       ├── openai_compat.py    # Any OpenAI-compatible endpoint
│       └── ollama.py           # Local Ollama (auto-detected)
│
├── reports/                    # Report generation
│   ├── builder.py              # Assembles report content (what goes in)
│   ├── renderer.py             # HTML → PDF via WeasyPrint (optional dep, safe url_fetcher)
│   ├── charts.py               # Matplotlib (Agg backend, OO API, thread-locked)
│   ├── exports.py              # JSON export
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
- X/Twitter collector deferred to v0.3.0
- CLI interface deferred to v0.2.0

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

### CompletionConfig

Per-call configuration for LLM requests:

```python
@dataclass
class CompletionConfig:
    temperature: float = 0.0    # deterministic for classification tasks
    max_tokens: int = 1024
```

The provider base interface uses this:

```python
# base.py abstract method
complete(messages: list[dict], model: str, config: CompletionConfig = CompletionConfig()) -> str
```

`temperature=0.0` is the default because sentiment classification requires deterministic output. This is ported from the current codebase (`llm_client.py:81`).

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

**Localhost exemption:** Endpoints resolving to `127.0.0.0/8` or `::1` are exempt from the HTTPS requirement and private network block. This is required to support local inference servers (LM Studio, vLLM, llama.cpp, text-generation-webui). All other SSRF protections (timeouts, response size limits, no redirects) still apply to localhost endpoints.

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

### CLI uses standard env vars (v0.2.0)

CLI is deferred to v0.2.0. When implemented:

- `ANTHROPIC_API_KEY` for Claude
- `OPENAI_API_KEY` + `OPENAI_BASE_URL` for OpenAI-compatible
- `OLLAMA_HOST` for non-default Ollama address
- CLI reads credentials exclusively from environment variables. No command-line flags accept secrets. This prevents exposure in process lists (`ps aux`) and shell history.

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

### Job cancellation

`cancel_job(job_id)` sets a `CancellationToken` (`threading.Event`). Each pipeline stage checks the token before processing the next item. The sentiment analyzer checks between posts. The collector checks between pagination requests. Cancellation is cooperative — stages complete their current item, then exit cleanly. Partial results up to the cancellation point are preserved.

### Graceful shutdown

SIGTERM/SIGINT triggers orderly shutdown: (1) stop accepting new jobs, (2) set cancellation tokens on all running jobs, (3) wait up to 30 seconds for running jobs to reach a checkpoint, (4) persist partial results, (5) close database connections, (6) exit.

### Pre-flight sequence (before pipeline starts)

1. Validate `ProviderConfig` — SSRF check on custom endpoints
2. Test LLM connection — minimal API call
3. Only then submit job to thread pool

### Progress reporting

The dashboard polls `GET /api/jobs/<id>/status` every 2 seconds while a job is running. Response includes: `{ stage, items_completed, items_total, message, elapsed_seconds }`. No WebSocket or SSE in v0.1.0 — XHR polling is simpler and sufficient for 1-2 concurrent jobs. The polling interval doubles to 4 seconds after 60 seconds, and to 8 seconds after 5 minutes, to reduce load on long-running jobs.

### Key boundary

`jobs/` depends on `collectors/`, `analyzers/`, `llm/`, `reports/`. It never depends on `app/`. The CLI uses the same job pipeline without importing Flask.

---

## 5. Data Collection Layer

### Normalized data model

All collectors return `list[Post]`:

```python
@dataclass
class Comment:
    id: str
    body: str
    author: str            # anonymized at report time
    score: int
    timestamp: datetime
    depth: int
    replies: list['Comment']

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
    comments: list[Comment]       # structured comments with threading
    phrase_matches: list[str]     # which search queries matched this post
    detected_language: str        # ISO 639-1 code
    detected_region: str          # inferred region
    poster_region: str
    topic_region: str
    upvote_ratio: float | None    # Reddit-specific
    flair: str | None             # Reddit flair
    is_crosspost: bool
    crosspost_source: str | None
```

The `Comment` dataclass preserves reply nesting, authorship, and scores — required for thread-mode analysis. This matches the existing codebase's structured comment storage.

### Reddit collector

- **Default:** public JSON endpoints (`/r/{subreddit}/search.json`). No API key needed. Rate-limited to 1 req/sec with backoff.
- **Upgrade path:** if `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` env vars are set, uses PRAW automatically.
- README disclaimer about public JSON and Reddit ToS.

### X collector (v0.3.0)

Deferred to v0.3.0. Requires bearer token and separate API contract. Low priority for the primary persona.

### Shared HTTP client (`http.py`)

- Wraps `requests.Session` with: 3 retries, exponential backoff (2s base + jitter), Retry-After header parsing, configurable timeouts, response size limits
- Used by both collectors and LLM providers

### Content sanitization at collection time

- Strip HTML tags from scraped content using `nh3` before storing in SQLite
- First line of XSS defense — malicious content never reaches the database in raw form

**Sanitization implementation:** `collectors/base.py` provides a `sanitize_post(post: Post) -> Post` function that applies `nh3.clean()` to `post.text`, `post.title`, and all `comment.body` fields recursively. Every collector calls `sanitize_post` before returning results. This is not optional — it is enforced by the base class.

### Reddit ToS compliance

- User-Agent header identifies the tool (`Signalstream/0.1.0`)
- Rate-limited to 1 request/second
- Respect `robots.txt` for domains being hit
- Clear user-facing notice that users are responsible for compliance with Reddit's Terms of Service

---

## 6. Analysis Layer

### Design principle

Analyzers receive a provider instance via dependency injection. They never import the LLM router directly. This makes them testable with a mock provider.

### Prompt templates (`prompts.py`)

All LLM prompt templates live in `analyzers/prompts.py`. Prompts are version-tagged (e.g., `SENTIMENT_PROMPT_V1 = ...`) for reproducibility. Port prompt templates from current `analyzer.py:201-324`.

Contents: sentiment analysis system prompt, user content formatting (wrapped in `<user_post>...</user_post>` delimiters to mitigate prompt injection), expected output JSON schema, and retry prompt with tighter format instructions.

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

**Checkpointing:** After each successful post analysis, the result is written to the database immediately. If the job fails at post N, posts 1 through N-1 are preserved. Job retry resumes from post N. The progress callback reports `(completed, total, current_post_id)`.

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

**Context window management:** For collections exceeding 50 posts, the thematic analyzer chunks posts into groups of 50, generates themes per chunk, then runs a consolidation pass that merges duplicate themes and recalculates percentages. Token count is estimated before each LLM call (4 chars ~= 1 token). If a single chunk exceeds 80% of the model's context window, the chunk size is halved.

### LLM output handling

- Parsing lives in each analyzer, not the provider. Provider returns raw text; analyzer parses into typed schema.
- Malformed LLM output → retry once with tighter prompt → skip that post on second failure

**Output validation:** `analyzers/schemas.py` includes validation functions for each output type. `validate_sentiment_result(raw: dict) -> SentimentResult` checks: `sentiment` is in `{positive, negative, neutral, mixed}`, `confidence` is a float in [0.0, 1.0], `emotion` is from a defined set of 8 basic emotions, `key_point` is a non-empty string under 200 characters, `sarcasm_detected` is boolean. Invalid responses trigger one retry with a tighter prompt. Second failure skips the post with a warning.

---

## 7. Error Handling & Observability

### Error taxonomy

All user-facing errors use structured error codes. Each code maps to a user-facing message and a suggested action. Messages defined in `app/errors.py`.

| Code | Meaning | User Message | Action |
|------|---------|-------------|--------|
| `PROVIDER_UNREACHABLE` | LLM provider not responding | "Could not reach [provider]. Check your internet connection." | Retry / Switch Provider |
| `PROVIDER_AUTH_FAILED` | Invalid API key | "Your [provider] API key appears to be invalid or expired." | Open Settings |
| `PROVIDER_RATE_LIMITED` | Rate limited by provider | "Rate limited by [provider]. Retrying in [N] seconds..." | Auto-retry with backoff |
| `PROVIDER_CONTEXT_EXCEEDED` | Input too large for model | "Post too long for [model]. Skipping." | Auto-skip |
| `COLLECTOR_RATE_LIMITED` | Reddit rate limit hit | "Reddit is rate-limiting requests. Waiting..." | Auto-retry |
| `COLLECTOR_EMPTY` | No posts found | "No posts found for '[topic]'. Try broader search terms." | Edit topic / Retry |
| `COLLECTOR_BLOCKED` | Reddit blocking requests | "Reddit is not responding. Try again in a few minutes." | Retry later |
| `ANALYSIS_PARSE_FAILED` | LLM returned unparseable output | "Could not parse analysis for [N] posts." | Shown in results |
| `ANALYSIS_PARTIAL` | Some posts failed | "Analysis complete ([N] of [M] posts analyzed)." | Shown in results |
| `REPORT_PDF_UNAVAILABLE` | WeasyPrint not installed | "PDF export requires additional setup." | Show install instructions |
| `DB_LOCKED` | Database write contention | (invisible — auto-retry internally) | Auto-retry |

### LLM call logging

Every LLM call logs (debug-level structured log, not user-facing): prompt hash, response hash, model, temperature, token count (estimated), latency, success/failure. This enables debugging "why did this job produce weird results" without storing full prompt/response content in production.

---

## 8. Reports & Dashboard

### Reports package

- **`builder.py`** — assembles report content: which sections, which data, which charts. Produces a `ReportContent` dataclass.
- **`renderer.py`** — takes `ReportContent`, produces PDF via WeasyPrint. Owns the custom `url_fetcher` that blocks all external resource loading (SSRF mitigation). Only file that imports WeasyPrint.
- **`charts.py`** — Matplotlib chart generation as base64 PNGs. Used by the PDF renderer only. Emotion distribution, sentiment split, theme frequency, community breakdown. The web dashboard renders its own charts client-side via Chart.js from JSON API data. **Thread safety:** Must use `matplotlib.use('Agg')` at import time, object-oriented API only (no `plt.*` calls), and `threading.Lock` around all figure creation/rendering.
- **`exports.py`** — JSON export of analysis results.
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

Custom `url_fetcher` in `renderer.py` — blocks ALL external resource loading:

```python
def _safe_url_fetcher(url: str, timeout=10, ssl_context=None):
    """Block all external resource loading in PDF generation."""
    if url.startswith('data:'):
        return weasyprint.default_url_fetcher(url)
    raise ValueError(f"Blocked external resource in PDF template: {url}")
```

Pass `url_fetcher=_safe_url_fetcher` to `HTML()` constructor. No exceptions. No allowlist for local files — all assets must be inlined as data URIs or embedded in the HTML string before rendering. This prevents `file:///etc/passwd` reads and SSRF via CSS/HTML resource loading.

### Dashboard

**Results page** (after job completes):
- Sentiment breakdown with chart
- Emotion distribution chart
- Top themes with representative quotes
- Community-level breakdown
- Key metrics (post count, dominant emotion, sentiment ratio)
- Cost estimate ("This analysis used ~15,000 tokens, ~$0.05")
- "Download PDF" button + "Export JSON"
- "Powered by Signalstream" footer in PDF reports (removable via branding config)
- Data loaded from `/api/results/<job_id>` JSON endpoint

**Historical dashboard** (v0.2.0):
Deferred. Data is still stored — the view comes later. Includes: past analyses with key metrics, trend charts, side-by-side comparison, filterable by topic/date.

**Dashboard states:** Every view must handle 4 states:
1. **Empty** — no analyses yet, show onboarding prompt
2. **Loading** — skeleton/spinner while API call is in flight
3. **Error** — specific error message with retry action (using error taxonomy from Section 7)
4. **Populated** — the normal data view

**Dashboard charts are client-side** — rendered from JSON API data using Chart.js. Interactive: hover, filter. No server-round-trips for chart rendering.

---

## 9. Database Layer

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
- **Space reclamation:** Use `PRAGMA auto_vacuum = INCREMENTAL` set at database creation. After bulk deletes, run `PRAGMA incremental_vacuum(N)` to reclaim N pages without blocking concurrent operations. Full `VACUUM` available only via explicit CLI command (`signalstream db vacuum`) when the server is stopped.
- Database file, WAL, and journal in `.gitignore`.

### Post-job data minimization

After a job completes, full post text is replaced with truncated summaries. The PDF/dashboard has everything it needs from aggregated results. Limits liability of storing third-party content.

---

## 10. First-Run Experience & Configuration

### Zero-config startup

**Prerequisites:** `pip install signalstream` (or `pip install signalstream[pdf]` for PDF reports).

```bash
pip install signalstream
python -m signalstream
# → SQLite auto-created
# → Schema migrations applied
# → Browser opens to localhost:5001
# → Welcome screen with search box
```

Default port is `5001`. Port 5000 conflicts with macOS AirPlay Receiver (Monterey+). If the configured port is in use, the server tries the next 5 sequential ports and logs which port was actually bound.

### First-run flow

1. User sees search box with topic input — enters topic, clicks "Get Started"
2. No provider configured → inline provider selector appears (not a separate settings page):
   - **Ollama (free, local)** — auto-detected if running, green badge, model dropdown populated
   - **Claude (best quality)** — paste key, test connection
   - **OpenAI-compatible (flexible)** — endpoint URL + key + model
3. User picks provider, clicks "Analyze" — pipeline starts immediately
4. Provider choice persists in localStorage for next session

Settings page exists separately for changing provider later, but first-run never routes there.

### Dead end prevention

If no provider is available (no Ollama running, no API keys entered), the provider selector shows:
1. A one-line command to install and start Ollama
2. A link to get a Claude API key
3. A **"Try with demo data"** button that loads a cached example analysis (ships with the package)

The user must never see a screen with no forward path.

### Config file (v0.2.0)

`config.yaml` support is deferred to v0.2.0. In v0.1.0, all configuration happens through the web UI settings page and environment variables. This keeps the zero-config story clean.

---

## 11. Repo Hygiene & Open-Source Readiness

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
│   └── ci.yml              # ruff + pytest on Python 3.10, 3.12, 3.14
├── ISSUE_TEMPLATE/
│   ├── bug_report.yml
│   └── feature_request.yml
└── PULL_REQUEST_TEMPLATE.md
```

### Security hardening (must be implemented, not assumed)

**`app/middleware/security.py`** — Flask `after_request` handler that sets security headers on every response:
- `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'`
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: no-referrer`
- `Permissions-Policy: camera=(), microphone=(), geolocation=()`
- CSRF double-submit cookie on all POST/PUT/DELETE endpoints
- CORS same-origin only

**`app/middleware/api_keys.py`** — Header-sanitizing middleware:
- Extracts `X-LLM-API-Key` into `ProviderConfig`
- Strips key from `request.environ` before any logging can occur
- Custom `logging.Filter` that pattern-matches and redacts `sk-ant-*`, `sk-*` strings from all log messages

**Other hardening:**
- `debug=False` unless `SIGNALSTREAM_DEBUG=1` explicitly set
- Bind `127.0.0.1` by default, startup warning if overridden
- SSRF validation on custom LLM endpoints (with localhost exemption)
- WeasyPrint custom `url_fetcher` blocks external resources
- Input validation on all job parameters (subreddit names, queries, dates)
- Parameterized SQL exclusively
- Content sanitization on ingestion via `nh3`

### Docker

```bash
docker compose up
# → App at localhost:5001 with all deps (including WeasyPrint)
# → Optional Ollama sidecar for zero-key local analysis
```

Sidesteps WeasyPrint system deps and Python version issues entirely. Dockerfile uses a non-root user — final stage runs as `USER signalstream` with a dedicated UID. No capabilities added beyond defaults.

---

## Phased Roadmap

### v0.1.0 — "The Magic Moment"
Everything in this spec. Reddit + Ollama/Claude/OpenAI-compat + Web UI + PDF reports + Docker.

### v0.2.0 — "Power Users"
- CLI interface
- Historical dashboard with trends
- Side-by-side comparison view
- CSV export
- `config.yaml` support
- Reddit PRAW upgrade path docs

### v0.3.0 — "Growth & Ecosystem"
- X/Twitter collector
- Scheduled recurring analyses
- Shareable static HTML reports
- Email digest of results

---

## Out of Scope (all versions)

- User accounts or authentication (local-first tool)
- Email gating for downloads
- Server-side API key storage
- Multi-user deployment features
- Plugin/extension system for custom collectors
- Mobile-responsive UI (desktop-first for now)
