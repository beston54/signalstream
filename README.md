# Signalstream — Social Intelligence, Distilled

Scans public social discussions (Reddit, X), analyzes sentiment and emotion with AI, and generates professional report cards ready to share.

## Quick Start (Web UI)

```bash
# 1. Install dependencies (first time only)
brew install cairo pango gdk-pixbuf libffi
pip install -r requirements.txt

# 2. Start the web UI
python app.py
```

Open **http://localhost:5000** in your browser. Enter a topic, pick a time range, and click "Run Analysis."

No API keys are needed for the default setup (uses Reddit's public endpoints). For higher limits, see [Advanced Configuration](#advanced-configuration) below.

## What You Get

A set of 7 report cards (PDF) covering:

1. Executive snapshot with key metrics
2. Emotional landscape distribution
3. Sentiment split analysis
4. Key themes identified
5. Community lens (per-community breakdown)
6. Messaging playbook
7. Methodology and data scope

## Prerequisites

- **Python 3.10+**
- **macOS** (tested) or Linux
- **Ollama** with a model installed (optional — can use Claude API instead)

### Setting Up an LLM Provider

Choose one:

**Option A: Claude API (recommended)**
```bash
export ANTHROPIC_API_KEY="your-key-here"
```

**Option B: Local Ollama**
```bash
brew install ollama
ollama pull gemma2:9b
ollama serve
```

The system auto-detects which is available. Set `analysis.provider` in config to force one.

## Advanced Configuration

Copy the example config and customize:

```bash
cp config.example.yaml config.yaml
```

Key settings in `config.yaml`:

```yaml
search:
  key_phrases:
    - "your topic"
  time_range: "week"          # week, month, year, all
  max_posts_per_phrase: 100   # higher = more robust analysis

analysis:
  provider: "auto"            # auto, claude, or ollama

sources:
  reddit: true
  x: false                    # requires X API v2 bearer token
```

Environment variables (preferred over config file for secrets):

```bash
export ANTHROPIC_API_KEY="..."       # Claude API
export FLASK_SECRET_KEY="..."        # Session security (auto-generated if unset)
export X_API_BEARER_TOKEN="..."      # X API v2 (optional)
export UNSPLASH_ACCESS_KEY="..."     # Cover photos (optional)
export PEXELS_API_KEY="..."          # Cover photos (optional)
```

## CLI Usage (Advanced)

For scripting or automation, use the CLI directly:

```bash
# Full pipeline run
python scripts/main.py

# Dry run (10 posts)
python scripts/main.py --dry-run

# Report only (reuse existing data)
python scripts/main.py --only-report

# See all options
python scripts/main.py --help
```

## Project Structure

```
Sentiment Analysis/
├── app.py                     # Web UI (Flask)
├── config.example.yaml        # Starter config (copy to config.yaml)
├── requirements.txt           # Python dependencies
├── scripts/
│   ├── main.py                # CLI orchestration
│   ├── collector.py           # Reddit data collection
│   ├── x_collector.py         # X collection (optional)
│   ├── analyzer.py            # Per-post sentiment analysis
│   ├── thematic_analyzer.py   # Theme extraction
│   ├── llm_client.py          # Shared LLM provider interface
│   ├── config_utils.py        # Config normalization
│   ├── query_expander.py      # Search phrase expansion
│   └── report_generator.py    # PDF generation
├── templates/
│   ├── web/                   # Web UI templates
│   ├── report_template.html   # PDF report template
│   └── report_styles.css      # PDF report styling
├── static/                    # Web UI assets (CSS, JS)
├── data/                      # Pipeline data (gitignored)
├── reports/                   # Generated PDFs
└── logs/                      # Log files
```

## Troubleshooting

**"Ollama is not running"** — Start it: `ollama serve`

**No posts collected** — Try broader search phrases, reduce `min_upvotes`, or check network.

**WeasyPrint errors on macOS** — Reinstall dependencies:
```bash
brew install cairo pango gdk-pixbuf libffi
pip install --force-reinstall weasyprint
```

**Detailed logs** — Check `logs/reddit_intelligence.log` or run with `--verbose`.
