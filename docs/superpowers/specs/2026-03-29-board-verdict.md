# Board of Experts — Final Verdict on Signalstream Rebuild Design Spec

**Date:** 2026-03-29
**Spec under review:** `2026-03-29-signalstream-rebuild-design.md`
**Input:** 5 independent team reports (Alpha, Bravo, Charlie, Delta, Echo)
**Board composition:** Architecture lead, Security lead, Product lead, Data engineering lead, DX lead

---

## 1. Cross-Team Agreement Matrix

These findings were independently raised by 2+ teams. They carry the highest confidence and should be treated as ground truth.

| Finding | Teams | Confidence |
|---------|-------|------------|
| **`comments: list[str]` is a data regression.** Current code stores structured comment dicts with `comment_id`, `body`, `author`, `upvotes`, `timestamp`, `depth`, `replies`. The spec flattens this to plain strings, losing thread structure, authorship, and scores. | Alpha (ALPHA-005), Delta | **Verified against codebase.** `collector.py:568-589` proves structured comment storage. This is a real regression. |
| **Post dataclass drops `phrase_matches`, `detected_region`, `detected_language`.** These fields are used by the analyzer, thematic analyzer, and exporter throughout the current codebase. | Alpha (ALPHA-005), Delta | **Verified against codebase.** 50+ references across `collector.py`, `analyzer.py`, `thematic_analyzer.py`, `exporter.py`. |
| **WeasyPrint `url_fetcher` does not exist.** Spec section 7 describes a custom url_fetcher as if it's planned, but Team Bravo notes it doesn't exist in current code. Since we're writing a design spec for a rebuild, this is a specification gap — the spec must include the actual implementation requirement, not just mention it as "baked in." | Bravo (BRAVO-001), Alpha | **Verified.** `report_generator.py:1570` — `HTML(string=html_content, base_url=base_url)` with no `url_fetcher`. |
| **`nh3` is not installed and no HTML sanitization exists.** Spec lists it as a dependency and describes sanitization at collection time, but current code has zero references to `nh3`. | Bravo (BRAVO-002), Alpha | **Verified.** Zero `import nh3` in the codebase. |
| **Security headers do not exist.** Spec section 10 lists CSP, X-Frame-Options, nosniff as "baked into code." None exist in current code, and the spec doesn't specify where to implement them. | Bravo (BRAVO-003), Alpha (ALPHA-003) | **Verified.** Zero matches for any security header in `scripts/`. |
| **No error message catalog or taxonomy.** Errors are promised as "clear, actionable" but never specified. | Alpha (ALPHA-006), Charlie, Delta | High — three teams independently flagged this. |
| **SSRF rules block local LLM servers.** The HTTPS-only + no-raw-IPs + private-network-block rules prevent connecting to `http://localhost:1234` (LM Studio), vLLM, llama.cpp, etc. | Charlie, Alpha | High — this would break a core advertised feature. |
| **No analysis checkpointing.** A 100-post job failing at post 73 loses all work. | Delta, Alpha | High — both teams flagged pipeline fragility. |
| **Provider abstraction is too thin.** `complete(messages, model) -> str` lacks temperature, max_tokens, token counting, cost tracking. Current code already uses `temperature: 0.0`. | Delta, Alpha | **Verified.** `llm_client.py:81` — temperature is explicitly set to 0.0 in current code. The spec drops this. |
| **v0.1.0 scope is too large.** | Echo, Charlie | High — both teams concluded the scope needs cutting. |
| **No prompt specification.** Current code has detailed prompt templates; the spec replaces them with hand-waving ("analyzer parses into typed schema"). | Delta, Alpha | **Verified.** `analyzer.py:201-324` contains elaborate prompt construction. |

---

## 2. Cross-Team Conflicts

### Conflict 1: Docker-first vs pip-first quickstart

- **Charlie** says Docker should be the "hero" quickstart path, not pip install.
- **Echo** includes Docker in v0.1.0 scope but doesn't prioritize it over pip.
- The spec shows `python -m signalstream` as the primary path.

**Board decision: pip-first for README, Docker as immediate second path.** Rationale: The primary persona (indie developer) already has Python. Docker adds friction for users who don't have Docker. But the Docker path must exist in v0.1.0 because it eliminates WeasyPrint system dep pain and gives the zero-config Ollama story. Both paths appear in the quickstart section, pip first, Docker second. Neither is buried.

### Conflict 2: How aggressively to cut scope

- **Echo** recommends cutting CLI, OpenAI-compat, X/Twitter, historical dashboard, comparison view, and CSV export from v0.1.0.
- **Charlie** wants OpenAI-compat localhost exemption (implies keeping that provider).
- **Delta** focuses on pipeline robustness regardless of scope.

**Board decision: Accept Echo's cuts with one modification — keep OpenAI-compatible provider.** Rationale: Cutting OpenAI-compat removes LM Studio, vLLM, Groq, Together, and every local inference server except Ollama. That's half the "bring your own LLM" story. The implementation cost is low (it's a thin HTTP wrapper). Cut list in Section 5 below.

### Conflict 3: Severity of legal risk from Reddit public JSON scraping

- **Bravo** rates this as "medium-high legal risk."
- **Echo** treats it as acceptable with a README disclaimer.
- The spec acknowledges it with a planned disclaimer.

**Board decision: Accept with explicit mitigation.** A disclaimer alone is insufficient. The spec must include: (1) User-Agent header identifying the tool, (2) rate limiting to 1 req/sec (already specified), (3) `robots.txt` respect for the domains being hit, (4) clear user-facing notice that they are responsible for compliance with Reddit's ToS. Do not add an OAuth-only mode gate — that would destroy the zero-config story.

### Conflict 4: Port 5000 default

- **Charlie** flags macOS AirPlay Receiver conflict on port 5000 (Monterey+).
- No other team addresses this.

**Board decision: Change default to 5001.** This is a trivial change that eliminates the #1 predictable startup error on macOS. Port 5000 conflicts with AirPlay Receiver by default on every Mac running Monterey or later. Add auto-detection: if the chosen port is in use, try the next 5 ports and report which one was used.

---

## 3. Severity-Ranked Findings (Top 15)

Scoring: Impact (1-5) x Likelihood (1-5) x Inverse-effort-to-fix (1-5, where 5 = easy fix, high ROI). Higher score = fix first.

| Rank | ID | Severity | Finding | Impact | Likelihood | Effort | Score | Recommended Action |
|------|-----|----------|---------|--------|------------|--------|-------|-------------------|
| 1 | BOARD-001 | **Critical** | Post dataclass drops `phrase_matches`, `detected_region`, `detected_language`, and structured comment fields. Direct regression from working code. | 5 | 5 | 5 | 125 | Rewrite `Post` dataclass to include all fields currently in use. Add `Comment` dataclass with `id`, `body`, `author`, `score`, `timestamp`, `depth`, `replies: list[Comment]`. Change `comments` field from `list[str]` to `list[Comment]`. |
| 2 | BOARD-002 | **Critical** | WeasyPrint has no `url_fetcher`. Arbitrary file read via `file:///` in PDF templates. SSRF via external URL loading. | 5 | 4 | 5 | 100 | Add explicit `url_fetcher` implementation to `renderer.py` spec. Whitelist only `data:` URIs. Block all `file://`, `http://`, `https://` schemes. This is 15 lines of code. |
| 3 | BOARD-003 | **Critical** | No HTML sanitization anywhere. `nh3` listed as dependency but never implemented. Stored XSS pipeline: Reddit content -> SQLite -> dashboard. | 5 | 4 | 5 | 100 | Add `nh3.clean()` call in collector before storage. Add to `collectors/base.py` as a required sanitization step. Add output encoding in Jinja2 templates (Flask's `autoescape` must be on). |
| 4 | BOARD-004 | **Critical** | No prompt specification. Current code has detailed prompts with exact format instructions, retry logic, and output parsing. Spec replaces with "analyzer parses into typed schema" without defining the prompts, expected output format, or parsing strategy. | 5 | 5 | 4 | 100 | Add `analyzers/prompts.py` to project structure. Spec must include at least the system prompt template, expected output format (JSON schema), and parsing/validation rules. Port existing prompts from `analyzer.py:201-324`. |
| 5 | BOARD-005 | **Critical** | Security headers are described as "baked in" but not specified. No CSP, no X-Frame-Options, no nosniff anywhere. | 4 | 5 | 5 | 100 | Add `app/middleware/security.py` to project structure. Specify exact headers as Flask `after_request` handler. Include: `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`. |
| 6 | BOARD-006 | **Critical** | Provider abstraction `complete(messages, model) -> str` is too thin. Missing temperature, max_tokens, and structured output parsing. Current code already uses `temperature=0.0` for deterministic classification. | 4 | 5 | 4 | 80 | Expand provider interface to `complete(messages, model, temperature=0.0, max_tokens=1024) -> str`. Add `CompletionConfig` dataclass. Port temperature=0.0 default from current code. |
| 7 | BOARD-007 | **Critical** | SSRF rules block ALL local OpenAI-compatible servers. HTTPS-only + private network block prevents `http://localhost:1234`. | 4 | 5 | 4 | 80 | Add explicit localhost/loopback exemption to `safety.py`. Allow `http://` only for `127.0.0.1` and `localhost`. Maintain all other SSRF protections for non-loopback addresses. |
| 8 | BOARD-008 | **High** | No analysis checkpointing. Job failing at post N loses all completed work. | 4 | 4 | 3 | 48 | Add checkpoint-on-success after each post analysis. Store partial results in DB. On retry, resume from last checkpoint. Add to `pipeline.py` spec. |
| 9 | BOARD-009 | **High** | API keys logged in plaintext by Flask. Spec describes redaction middleware but doesn't specify implementation. | 4 | 4 | 4 | 64 | Spec must define: (1) Flask request logging filter that redacts `X-LLM-API-Key` header values, (2) custom log formatter that pattern-matches and redacts `sk-ant-*`, `sk-*` strings, (3) middleware strips keys from `request.environ` before any logging can occur. |
| 10 | BOARD-009b | **High** | CLI `--api-key` exposes secrets in process list (`ps aux`) and shell history. | 3 | 4 | 5 | 60 | Remove `--api-key` CLI flag entirely. Use only environment variables for secrets. Add note in spec explaining why. |
| 11 | BOARD-010 | **High** | Matplotlib is not thread-safe. Concurrent chart generation will crash or corrupt output. | 4 | 4 | 4 | 64 | Spec must require: (1) `matplotlib.use('Agg')` at import time, (2) object-oriented API only (no `plt.*` calls), (3) `threading.Lock` around all figure creation/rendering in `charts.py`. |
| 12 | BOARD-011 | **High** | Thematic analyzer batch summary may exceed model context windows for large collections. No chunking strategy specified. | 4 | 3 | 3 | 36 | Add chunking logic to thematic analyzer spec. For N > 50 posts, chunk into groups of 50, generate per-chunk themes, then merge themes in a final consolidation pass. Include token estimation before submission. |
| 13 | BOARD-012 | **High** | No LLM output validation. Malformed model responses pass through silently. | 4 | 4 | 3 | 48 | Add validation layer in `analyzers/schemas.py`. Each `SentimentResult` field must be validated: `sentiment` must be in `{positive, negative, neutral, mixed}`, `confidence` must be 0.0-1.0, `emotion` from defined set. Reject and retry on validation failure. |
| 14 | BOARD-013 | **High** | No CSRF protection for localhost web interface. Any website can trigger analysis jobs via `fetch('http://localhost:5001/api/analyze')`. | 3 | 3 | 4 | 36 | Add CSRF token generation and validation. Use Flask-WTF or a simple double-submit cookie pattern. All state-changing endpoints must require a valid CSRF token. |
| 15 | BOARD-014 | **Medium** | SQLite VACUUM during active server blocks all DB access. | 3 | 3 | 4 | 36 | Replace full VACUUM with `PRAGMA incremental_vacuum` after bulk deletes. Run full VACUUM only on explicit user action or when no jobs are running. |

---

## 4. Spec Amendments

These are the concrete changes to make to the design spec before implementation begins. Organized by spec section.

### Section 2 (LLM Provider System)

**Amendment 2.1:** Replace the provider base interface:
```python
# CURRENT (too thin)
complete(messages, model) -> str

# REQUIRED
@dataclass
class CompletionConfig:
    temperature: float = 0.0
    max_tokens: int = 1024

complete(messages: list[dict], model: str, config: CompletionConfig = CompletionConfig()) -> str
```

**Amendment 2.2:** Add localhost exemption to SSRF rules. Add this paragraph after the SSRF validation list:
> **Localhost exemption:** Endpoints resolving to `127.0.0.0/8` or `::1` are exempt from the HTTPS requirement and private network block. This is required to support local inference servers (LM Studio, vLLM, llama.cpp, text-generation-webui). All other SSRF protections (timeouts, response size limits, no redirects) still apply to localhost endpoints.

### Section 3 (Browser-to-Server Key Flow)

**Amendment 3.1:** Remove `--api-key` from CLI interface. Replace with:
> CLI reads credentials exclusively from environment variables. No command-line flags accept secrets. This prevents exposure in process lists and shell history.

### Section 4 (Job Management)

**Amendment 4.1:** Add subsection "Job Cancellation" after Job lifecycle:
> **Cancellation:** `cancel_job(job_id)` sets a `CancellationToken` (threading.Event). Each pipeline stage checks the token before processing the next item. The sentiment analyzer checks between posts. The collector checks between pagination requests. Cancellation is cooperative — stages complete their current item, then exit cleanly. Partial results up to the cancellation point are preserved.

**Amendment 4.2:** Add subsection "Graceful Shutdown":
> **Shutdown:** SIGTERM/SIGINT triggers orderly shutdown: (1) stop accepting new jobs, (2) set cancellation tokens on all running jobs, (3) wait up to 30 seconds for running jobs to reach a checkpoint, (4) persist partial results, (5) close database connections, (6) exit.

### Section 5 (Data Collection Layer)

**Amendment 5.1:** Replace the `Post` dataclass with an expanded version:
```python
@dataclass
class Comment:
    id: str
    body: str
    author: str           # anonymized at report time
    score: int
    timestamp: datetime
    depth: int
    replies: list['Comment']

@dataclass
class Post:
    platform: str
    id: str
    author: str
    text: str
    title: str | None
    timestamp: datetime
    url: str
    community: str
    engagement: int
    comments: list[Comment]      # structured, not list[str]
    phrase_matches: list[str]
    detected_language: str
    detected_region: str
    poster_region: str
    topic_region: str
    upvote_ratio: float | None
    flair: str | None
    is_crosspost: bool
    crosspost_source: str | None
```

**Amendment 5.2:** Add after "Content sanitization at collection time":
> **Sanitization implementation:** `collectors/base.py` provides a `sanitize_post(post: Post) -> Post` function that applies `nh3.clean()` to `post.text`, `post.title`, and all `comment.body` fields recursively. Every collector calls `sanitize_post` before returning results. This is not optional — it is enforced by the base class.

### Section 6 (Analysis Layer)

**Amendment 6.1:** Add new file `analyzers/prompts.py` to the project structure:
> **`analyzers/prompts.py`** — All LLM prompt templates. Sentiment analysis system prompt, user content formatting, expected output JSON schema, retry prompt (tighter format instructions). Prompts are version-tagged (e.g., `SENTIMENT_PROMPT_V1 = ...`) for reproducibility. Port prompt templates from current `analyzer.py:201-324`.

**Amendment 6.2:** Add after "LLM output handling":
> **Output validation:** `analyzers/schemas.py` includes validation functions for each output type. `validate_sentiment_result(raw: dict) -> SentimentResult` checks: `sentiment` is in `{positive, negative, neutral, mixed}`, `confidence` is a float in [0.0, 1.0], `emotion` is from a defined set of 8 basic emotions, `key_point` is a non-empty string under 200 characters, `sarcasm_detected` is boolean. Invalid responses trigger one retry with a tighter prompt. Second failure skips the post with a warning.

**Amendment 6.3:** Add after "Thematic analyzer":
> **Context window management:** For collections exceeding 50 posts, the thematic analyzer chunks posts into groups of 50, generates themes per chunk, then runs a consolidation pass that merges duplicate themes and recalculates percentages. Token count is estimated before each LLM call (4 chars ~= 1 token). If a single chunk exceeds 80% of the model's context window, the chunk size is halved.

**Amendment 6.4:** Add to Sentiment analyzer section:
> **Checkpointing:** After each successful post analysis, the result is written to the database immediately. If the job fails at post N, posts 1 through N-1 are preserved. Job retry resumes from post N. The progress callback reports `(completed, total, current_post_id)`.

### Section 7 (Reports & Dashboard)

**Amendment 7.1:** Replace the WeasyPrint SSRF mitigation paragraph with a concrete implementation spec:
```python
def _safe_url_fetcher(url: str, timeout=10, ssl_context=None):
    """Block all external resource loading in PDF generation."""
    if url.startswith('data:'):
        return weasyprint.default_url_fetcher(url)
    raise ValueError(f"Blocked external resource in PDF template: {url}")
```
> Pass `url_fetcher=_safe_url_fetcher` to `HTML()` constructor. No exceptions. No allowlist for local files — all assets must be inlined as data URIs or embedded in the HTML string before rendering.

**Amendment 7.2:** Add "Dashboard States" subsection:
> Every dashboard view must handle 4 states: (1) **Empty** — no analyses yet, show onboarding prompt, (2) **Loading** — skeleton/spinner while API call is in flight, (3) **Error** — specific error message with retry action, (4) **Populated** — the normal data view. Wireframes for each state to be produced before implementation.

### Section 8 (Database Layer)

**Amendment 8.1:** Replace VACUUM paragraph:
> **Space reclamation:** Use `PRAGMA auto_vacuum = INCREMENTAL` set at database creation. After bulk deletes, run `PRAGMA incremental_vacuum(N)` to reclaim N pages without blocking. Full `VACUUM` available only via explicit CLI command (`signalstream db vacuum`) when the server is stopped.

### Section 9 (First-Run Experience)

**Amendment 9.1:** Change default port from 5000 to 5001:
> Default port is `5001`. Port 5000 conflicts with macOS AirPlay Receiver (Monterey+). If the configured port is in use, the server tries the next 5 sequential ports and logs which port was actually bound.

**Amendment 9.2:** Add "Dead End Prevention" after the first-run flow:
> If no provider is available (no Ollama running, no API keys entered), the provider selector shows: (1) a one-line command to install and start Ollama, (2) a link to get a Claude API key, (3) a "Try with demo data" button that loads a cached example analysis (ships with the package). The user must never see a screen with no forward path.

**Amendment 9.3:** Add before `python -m signalstream`:
> **Prerequisites:** `pip install signalstream` (or `pip install signalstream[pdf]` for PDF reports). The zero-config startup section must begin with installation, not assume it.

### Section 10 (Repo Hygiene)

**Amendment 10.1:** Add `app/middleware/security.py` to the project structure tree. Add explicit specification:
> **`security.py`** — Flask `after_request` handler that sets security headers on every response. Headers: `Content-Security-Policy`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Permissions-Policy: camera=(), microphone=(), geolocation=()`. CSRF double-submit cookie on all POST/PUT/DELETE endpoints.

**Amendment 10.2:** Add Docker container security note:
> Dockerfile uses a non-root user. Final stage runs as `USER signalstream` with a dedicated UID. No capabilities added beyond defaults.

**Amendment 10.3:** Replace CI matrix `3.10-3.12` with `3.10-3.14`:
> The developer's local Python is 3.14. CI must cover the developer's actual version. Test matrix: 3.10, 3.12, 3.14.

### New Section: Error Handling (insert after Section 6)

**Amendment NEW-1:** Add a new section "Error Handling & Observability":
> **Error taxonomy:** All user-facing errors use structured error codes:
> - `PROVIDER_UNREACHABLE` — LLM provider not responding
> - `PROVIDER_AUTH_FAILED` — Invalid API key
> - `PROVIDER_RATE_LIMITED` — Rate limited by provider, with retry-after
> - `PROVIDER_CONTEXT_EXCEEDED` — Input too large for model
> - `COLLECTOR_RATE_LIMITED` — Reddit/X rate limit hit
> - `COLLECTOR_EMPTY` — No posts found for query
> - `COLLECTOR_BLOCKED` — Reddit/X blocking requests
> - `ANALYSIS_PARSE_FAILED` — LLM returned unparseable output
> - `ANALYSIS_PARTIAL` — Some posts failed analysis (N of M succeeded)
> - `REPORT_PDF_UNAVAILABLE` — WeasyPrint not installed
> - `DB_LOCKED` — Database write contention (retry automatically)
>
> Each code maps to a user-facing message and a suggested action. Messages defined in `app/errors.py`.
>
> **LLM call logging:** Every LLM call logs (to a debug-level structured log, not user-facing): prompt hash, response hash, model, temperature, token count (estimated), latency, success/failure. This enables debugging "why did this job produce weird results" without storing full prompt/response content in production.

### New Section: Polling & Progress (insert in Section 4)

**Amendment NEW-2:** Add "Progress Reporting" subsection to Section 4:
> **Progress transport:** The dashboard polls `GET /api/jobs/<id>/status` every 2 seconds while a job is running. Response includes: `{ stage, items_completed, items_total, message, elapsed_seconds }`. No WebSocket or SSE in v0.1.0 — XHR polling is simpler and sufficient for 1-2 concurrent jobs. The polling interval doubles to 4 seconds after 60 seconds, and to 8 seconds after 5 minutes, to reduce load on long-running jobs.

---

## 5. Scope Decision

**Verdict: Yes, reduce v0.1.0 scope. Adopt Echo's recommendation with modifications.**

### v0.1.0 — Ship This

| In | Rationale |
|----|-----------|
| Reddit collector (public JSON + optional PRAW) | Core data source. Already largely built. |
| Claude provider | Best quality, simplest integration. |
| Ollama provider | Zero-cost local option. Key differentiator. |
| OpenAI-compatible provider | Low implementation cost. Unlocks LM Studio, vLLM, Groq, Together. Cutting this guts the "bring your own LLM" story. |
| Web UI: analysis flow + results page | The "10x moment" requires this. |
| PDF report generation | Core deliverable users share. The artifact IS the product for many users. |
| JSON export | Trivial to implement alongside results API. |
| Docker + Docker Compose with Ollama sidecar | The zero-friction path. Solves WeasyPrint deps. |
| Security hardening (all amendments above) | Non-negotiable for a public repo. |

### Cut from v0.1.0

| Cut | Move to | Rationale |
|-----|---------|-----------|
| X/Twitter collector | v0.3.0 | Requires bearer token. Separate API contract. Low priority for primary persona. |
| CLI interface | v0.2.0 | Web UI is the primary interface. CLI is a power-user feature. Saves substantial work (arg parsing, output formatting, signal handling). |
| Historical dashboard | v0.2.0 | Data is still stored — the view comes later. The results page for the current job is sufficient for v0.1.0. |
| Comparison view | v0.2.0 | Depends on historical dashboard. |
| CSV export | v0.2.0 | JSON export covers programmatic access. CSV is a convenience. |
| `config.yaml` support | v0.2.0 | Zero-config is the v0.1.0 story. YAML config is a power-user feature. |

### Add to v0.1.0 (from Echo's growth recommendations)

| Add | Rationale |
|-----|-----------|
| "Powered by Signalstream" footer in PDF reports | Highest ROI growth feature. One line of HTML. |
| Demo mode with cached example data | Eliminates the dead-end state. Ships a pre-computed analysis that loads instantly. Doubles as a test fixture. |
| Cost estimation before analysis | 3 lines of math. Prevents surprise API bills. Critical for trust. |

---

## 6. Implementation Order

Build from the foundation up. Each phase produces a testable artifact.

### Phase 1: Data Foundation (Week 1)
1. `db/engine.py` — SQLite connection with WAL, write lock, incremental vacuum
2. `db/models.py` — Domain dataclasses including expanded `Post` and `Comment`
3. `db/repositories.py` — All SQL, parameterized queries
4. `db/migrations.py` — Schema versioning, auto-migrate
5. Tests for all of the above

**Rationale:** Everything depends on the database. Build and test it first. This also validates the data model decisions from BOARD-001.

### Phase 2: LLM Provider System (Week 1-2)
1. `llm/providers/base.py` — Abstract interface with `CompletionConfig`
2. `llm/providers/claude.py` — Anthropic API with temperature, max_tokens
3. `llm/providers/ollama.py` — Local auto-detection
4. `llm/providers/openai_compat.py` — Generic OpenAI-compatible
5. `llm/safety.py` — SSRF validation with localhost exemption
6. `llm/router.py` — Provider selection, pre-flight check
7. `llm/config.py` — ProviderConfig dataclass
8. Tests with mock providers

**Rationale:** Analyzers depend on the provider system. Collectors don't. Building providers before collectors lets you test the analysis layer with mock data before real scraping works.

### Phase 3: Collection Layer (Week 2)
1. `collectors/http.py` — Resilient HTTP client
2. `collectors/base.py` — Abstract interface, sanitization with `nh3`
3. `collectors/reddit.py` — Public JSON + PRAW path
4. Tests with recorded HTTP fixtures

**Rationale:** Now you can collect real data into the tested database through the tested sanitization layer.

### Phase 4: Analysis Layer (Week 2-3)
1. `analyzers/prompts.py` — All prompt templates, ported from current code
2. `analyzers/schemas.py` — Output dataclasses + validation
3. `analyzers/sentiment.py` — Per-post analysis with checkpointing
4. `analyzers/thematic.py` — Batch theme extraction with chunking
5. Tests with mock providers returning known outputs

**Rationale:** This is the most complex and error-prone layer. With providers, collectors, and DB already solid, you can focus entirely on prompt engineering and output parsing.

### Phase 5: Report Generation (Week 3)
1. `reports/charts.py` — Matplotlib with Agg backend, thread lock, OO API
2. `reports/builder.py` — Report content assembly
3. `reports/renderer.py` — WeasyPrint with `url_fetcher`, optional import
4. `reports/exports.py` — JSON export
5. `reports/pdf_templates/` — Jinja2 + CSS templates
6. Tests for chart generation, PDF rendering, export formats

### Phase 6: Pipeline Orchestration (Week 3-4)
1. `jobs/state.py` — State machine, CancellationToken, progress callbacks
2. `jobs/tasks.py` — Per-stage wrappers with error handling
3. `jobs/pipeline.py` — Stage sequencing with checkpointing
4. `jobs/manager.py` — Thread pool (max 2), submit/cancel/status
5. Integration tests: full pipeline with mock LLM

**Rationale:** Pipeline ties together all the layers above. It's the orchestrator and should be built last, once all stages are independently solid.

### Phase 7: Web Layer (Week 4-5)
1. `app/__init__.py` — App factory
2. `app/middleware/security.py` — Security headers, CSRF
3. `app/middleware/api_keys.py` — Key extraction, log redaction
4. `app/routes/settings.py` — Provider detection + validation
5. `app/routes/analysis.py` — Start jobs, poll status
6. `app/routes/dashboard.py` — Results page with all 4 states
7. `app/routes/api.py` — JSON API endpoints
8. `app/static/` — CSS, JS, Chart.js integration
9. `app/templates/` — All templates including empty/loading/error states
10. `app/errors.py` — Error code catalog

### Phase 8: Packaging & Distribution (Week 5)
1. `pyproject.toml` — Package metadata, extras, entry point
2. `Dockerfile` — Non-root user, WeasyPrint system deps
3. `docker-compose.yml` — App + Ollama sidecar
4. Demo data fixture — cached example analysis
5. README.md — Screenshot, dual quickstart (pip + Docker), provider paths
6. SECURITY.md, CONTRIBUTING.md, CHANGELOG.md
7. `.github/workflows/ci.yml` — Ruff + pytest on 3.10, 3.12, 3.14
8. Final integration tests: full pipeline via web UI

---

## 7. Final Verdict

### Overall Readiness Score: 5.8 / 10

The design spec demonstrates strong architectural thinking — the package decomposition is sound, the key management flow is well-designed, the zero-config story is compelling, and the decision to avoid an ORM is correct. The project structure is clean and the dependency boundaries are well-drawn.

However, the spec has a pattern of describing security mitigations and features that do not yet exist as if they are "baked in." Five verified instances of this pattern (WeasyPrint url_fetcher, nh3 sanitization, security headers, log redaction, SSRF rules) mean the spec cannot be implemented as-written without introducing the security vulnerabilities it claims to prevent. The Post dataclass regression is a serious oversight that would break the analyzer, thematic analyzer, and exporter. The absence of prompt specifications, output validation, and checkpointing means the most complex layer (analysis) is the least specified.

### Recommendation: CONDITIONAL GO

**Do not begin implementation until the spec amendments in Section 4 are applied.** The spec has the right shape but wrong details in critical areas. Specifically:

**Gate 1 (before any code):** Apply all amendments from Section 4. This is a documentation task, not a coding task. Estimated effort: 1 day.

**Gate 2 (before Phase 4):** Validate the expanded Post dataclass against all current code consumers (`analyzer.py`, `thematic_analyzer.py`, `exporter.py`, `report_generator.py`). Ensure no field used in current code is missing from the new dataclass.

**Gate 3 (before Phase 7):** Security audit of all middleware — verify security headers are actually set, log redaction actually works, CSRF tokens are actually validated. Automated test for each.

**Gate 4 (before Phase 8):** Pen test the WeasyPrint url_fetcher, nh3 sanitization, and SSRF validation with adversarial inputs. Include tests for `file:///etc/passwd` in PDF templates, `<script>` tags in Reddit content, and `http://169.254.169.254/latest/meta-data/` in custom endpoints.

If these gates are met, this project ships a genuinely differentiated product: free, local-first, LLM-powered sentiment analysis with beautiful reports. The competitive positioning against $800/month tools is real. The "10x moment" — type a topic, get a report in 60 seconds — is achievable within the v0.1.0 scope defined above.

The design is worth building. It just needs to be honest about what doesn't exist yet.
