# Plan 2: Pipeline & Reports — Orchestration, Charts, PDF, Job Management

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the report generation pipeline and job orchestration that connects the foundation layer to the web interface.

**Architecture:** Reports are built by a builder (content assembly) and rendered by pluggable renderers (PDF via WeasyPrint, JSON export). The job manager runs pipelines in a thread pool with cooperative cancellation, checkpointing, and structured error reporting.

**Tech Stack:** Python 3.10+, matplotlib (Agg backend), WeasyPrint (optional), Jinja2, threading

**Depends on:** Plan 1 (Foundation) must be complete.

---

## Key Interfaces From Plan 1 (Assumed Complete)

These modules exist and are tested. Plan 2 imports from them but never modifies them.

```python
# From db/repositories.py
def save_job(job: dict) -> None
def get_job(job_id: str) -> dict | None
def update_job_status(job_id: str, status: str, **kwargs) -> None
def save_job_statistics(job_id: str, stats: dict) -> None
def save_analyzed_post(job_id: str, post_id: str, result: dict) -> None
def get_analyzed_posts(job_id: str) -> list[dict]

# From llm/router.py
def create_provider(config: ProviderConfig) -> BaseProvider
def preflight_check(provider: BaseProvider) -> bool

# From llm/config.py
@dataclass ProviderConfig(provider, api_key, model, endpoint)
@dataclass CompletionConfig(temperature=0.0, max_tokens=1024)

# From collectors/reddit.py
def collect_reddit_posts(phrases: list[str], time_range: str, max_posts: int, ...) -> list[Post]

# From analyzers/sentiment.py
def analyze_posts(posts: list[Post], provider: BaseProvider, progress_callback, cancellation_token) -> tuple[list[AnalyzedPost], int]

# From analyzers/thematic.py
def extract_themes(posts: list[AnalyzedPost], provider: BaseProvider, phrase: str) -> ThematicResult

# From analyzers/schemas.py
@dataclass SentimentResult(sentiment, emotion, confidence, key_point, sarcasm_detected, ...)
@dataclass Theme(name, description, percentage, post_count, sentiment_skew, representative_quotes)
@dataclass AnalyzedPost(post: Post, analysis: SentimentResult)

# From db/models.py
@dataclass Post(...), Comment(...), etc.
```

---

## Task 1: Chart Generation — `signalstream/reports/charts.py`

**Files:**
- Create: `signalstream/reports/__init__.py`
- Create: `signalstream/reports/charts.py`
- Create: `signalstream/tests/test_reports/__init__.py`
- Create: `signalstream/tests/test_reports/test_charts.py`

**Why:** Charts are the visual foundation of the PDF report. Thread-safe matplotlib with OO API is required by BOARD-010. Building charts first lets us validate the base64 PNG pipeline before tackling PDF rendering.

**Key constraints (BOARD-010):**
- `matplotlib.use('Agg')` at import time, before any other matplotlib imports
- Object-oriented API only (Figure/Axes) — never use `plt.subplots()`, `plt.show()`, or any `plt.*` state calls
- `threading.Lock` around all figure creation and rendering
- All chart functions return base64-encoded PNG data URIs

### Steps

- [ ] **Step 1.1** — Write test for emotion distribution bar chart (2 min)

```bash
# Test command (expect FAIL — module does not exist yet)
cd "/Users/eston/Desktop/Sentiment Analysis" && python -m pytest signalstream/tests/test_reports/test_charts.py::test_emotion_distribution_chart -x 2>&1 | tail -5
```

```python
# signalstream/tests/test_reports/__init__.py
# (empty)

# signalstream/tests/test_reports/test_charts.py
"""Tests for thread-safe matplotlib chart generation."""

import base64
import threading

import pytest


def test_emotion_distribution_chart():
    """Emotion bar chart returns a valid base64 PNG data URI."""
    from signalstream.reports.charts import generate_emotion_chart

    emotions = {
        "joy": 15,
        "anger": 8,
        "fear": 5,
        "surprise": 3,
        "sadness": 2,
    }
    result = generate_emotion_chart(emotions)

    assert result.startswith("data:image/png;base64,")
    # Verify the base64 payload is decodable
    b64_data = result.split(",", 1)[1]
    decoded = base64.b64decode(b64_data)
    # PNG magic bytes
    assert decoded[:4] == b"\x89PNG"


def test_emotion_chart_empty_input():
    """Empty emotion dict returns empty string, no crash."""
    from signalstream.reports.charts import generate_emotion_chart

    result = generate_emotion_chart({})
    assert result == ""


def test_emotion_chart_filters_zeros():
    """Zero-count emotions are excluded from the chart."""
    from signalstream.reports.charts import generate_emotion_chart

    emotions = {"joy": 10, "anger": 0, "fear": 0}
    result = generate_emotion_chart(emotions)
    assert result.startswith("data:image/png;base64,")
```

- [ ] **Step 1.2** — Write test for sentiment split pie/donut chart (2 min)

```python
# Append to signalstream/tests/test_reports/test_charts.py

def test_sentiment_split_chart():
    """Sentiment donut chart returns valid PNG data URI."""
    from signalstream.reports.charts import generate_sentiment_chart

    sentiments = {"positive": 20, "negative": 8, "neutral": 12, "mixed": 3}
    result = generate_sentiment_chart(sentiments)

    assert result.startswith("data:image/png;base64,")
    b64_data = result.split(",", 1)[1]
    decoded = base64.b64decode(b64_data)
    assert decoded[:4] == b"\x89PNG"


def test_sentiment_chart_empty():
    """Empty sentiment dict returns empty string."""
    from signalstream.reports.charts import generate_sentiment_chart

    assert generate_sentiment_chart({}) == ""
```

- [ ] **Step 1.3** — Write test for theme frequency horizontal bar chart (2 min)

```python
# Append to signalstream/tests/test_reports/test_charts.py

def test_theme_frequency_chart():
    """Theme frequency horizontal bar returns valid PNG."""
    from signalstream.reports.charts import generate_theme_chart

    themes = [
        {"name": "Product Quality", "percentage": 45.0, "post_count": 18},
        {"name": "Customer Service", "percentage": 30.0, "post_count": 12},
        {"name": "Pricing Concerns", "percentage": 15.0, "post_count": 6},
        {"name": "Feature Requests", "percentage": 10.0, "post_count": 4},
    ]
    result = generate_theme_chart(themes)

    assert result.startswith("data:image/png;base64,")
    b64_data = result.split(",", 1)[1]
    decoded = base64.b64decode(b64_data)
    assert decoded[:4] == b"\x89PNG"


def test_theme_chart_empty():
    """Empty themes list returns empty string."""
    from signalstream.reports.charts import generate_theme_chart

    assert generate_theme_chart([]) == ""
```

- [ ] **Step 1.4** — Write test for community breakdown grouped bar chart (2 min)

```python
# Append to signalstream/tests/test_reports/test_charts.py

def test_community_breakdown_chart():
    """Community breakdown grouped bar returns valid PNG."""
    from signalstream.reports.charts import generate_community_chart

    communities = {
        "r/python": {"positive": 10, "negative": 3, "neutral": 5},
        "r/programming": {"positive": 8, "negative": 6, "neutral": 4},
        "r/learnpython": {"positive": 12, "negative": 1, "neutral": 7},
    }
    result = generate_community_chart(communities)

    assert result.startswith("data:image/png;base64,")
    b64_data = result.split(",", 1)[1]
    decoded = base64.b64decode(b64_data)
    assert decoded[:4] == b"\x89PNG"


def test_community_chart_empty():
    """Empty community dict returns empty string."""
    from signalstream.reports.charts import generate_community_chart

    assert generate_community_chart({}) == ""
```

- [ ] **Step 1.5** — Write thread-safety test (3 min)

```python
# Append to signalstream/tests/test_reports/test_charts.py

def test_concurrent_chart_generation():
    """Multiple threads generating charts simultaneously must not crash or corrupt."""
    from signalstream.reports.charts import (
        generate_emotion_chart,
        generate_sentiment_chart,
        generate_theme_chart,
        generate_community_chart,
    )

    errors: list[Exception] = []

    def gen_emotion():
        try:
            r = generate_emotion_chart({"joy": 10, "anger": 5, "fear": 3})
            assert r.startswith("data:image/png;base64,")
        except Exception as e:
            errors.append(e)

    def gen_sentiment():
        try:
            r = generate_sentiment_chart({"positive": 15, "negative": 5, "neutral": 10})
            assert r.startswith("data:image/png;base64,")
        except Exception as e:
            errors.append(e)

    def gen_themes():
        try:
            r = generate_theme_chart([
                {"name": "Topic A", "percentage": 40.0, "post_count": 8},
                {"name": "Topic B", "percentage": 30.0, "post_count": 6},
            ])
            assert r.startswith("data:image/png;base64,")
        except Exception as e:
            errors.append(e)

    def gen_community():
        try:
            r = generate_community_chart({
                "r/test": {"positive": 5, "negative": 2, "neutral": 3},
            })
            assert r.startswith("data:image/png;base64,")
        except Exception as e:
            errors.append(e)

    threads = []
    # Run 3 rounds of all 4 chart types concurrently (12 threads)
    for _ in range(3):
        for fn in [gen_emotion, gen_sentiment, gen_themes, gen_community]:
            t = threading.Thread(target=fn)
            threads.append(t)

    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert errors == [], f"Thread-safety errors: {errors}"
```

- [ ] **Step 1.6** — Write test for `generate_all_charts` convenience function (2 min)

```python
# Append to signalstream/tests/test_reports/test_charts.py

def test_generate_all_charts():
    """Convenience function returns dict of all chart data URIs."""
    from signalstream.reports.charts import generate_all_charts

    statistics = {
        "sentiment_distribution": {"positive": 20, "negative": 8, "neutral": 12},
        "emotion_distribution": {"joy": 15, "anger": 5, "surprise": 3},
        "community_breakdown": {
            "r/python": {"positive": 10, "negative": 3, "neutral": 5},
        },
    }
    themes = [
        {"name": "Quality", "percentage": 45.0, "post_count": 18},
        {"name": "Support", "percentage": 30.0, "post_count": 12},
    ]

    result = generate_all_charts(statistics, themes)

    assert isinstance(result, dict)
    assert "sentiment" in result
    assert "emotion" in result
    assert "themes" in result
    assert "community" in result
    for key, uri in result.items():
        assert uri.startswith("data:image/png;base64,"), f"{key} is not a valid data URI"


def test_generate_all_charts_partial_data():
    """Missing sections produce partial results, not crashes."""
    from signalstream.reports.charts import generate_all_charts

    statistics = {
        "sentiment_distribution": {"positive": 10, "negative": 5},
        # No emotion or community data
    }
    themes = []

    result = generate_all_charts(statistics, themes)
    assert isinstance(result, dict)
    assert "sentiment" in result
    # Missing sections should be absent, not empty strings
    assert "emotion" not in result or result.get("emotion") == ""
```

- [ ] **Step 1.7** — Run tests, confirm all FAIL (1 min)

```bash
cd "/Users/eston/Desktop/Sentiment Analysis" && python -m pytest signalstream/tests/test_reports/test_charts.py -x 2>&1 | tail -10
```

- [ ] **Step 1.8** — Implement `signalstream/reports/__init__.py` and `charts.py` (5 min)

```python
# signalstream/reports/__init__.py
"""Report generation: charts, content assembly, PDF rendering, JSON export."""
```

```python
# signalstream/reports/charts.py
"""
Thread-safe matplotlib chart generation for PDF reports.

BOARD-010 compliance:
- matplotlib.use('Agg') at import time (non-interactive backend)
- Object-oriented API only (Figure/Axes, never plt.*)
- threading.Lock around all figure creation/rendering
- Returns base64 PNG data URIs for embedding
"""

from __future__ import annotations

import base64
import io
import logging
import threading
from typing import Any

import matplotlib
matplotlib.use("Agg")  # MUST be before any other matplotlib import
from matplotlib.figure import Figure

logger = logging.getLogger(__name__)

# Global lock for all matplotlib operations (BOARD-010)
_chart_lock = threading.Lock()

# -- Color palettes ----------------------------------------------------------

SENTIMENT_COLORS = {
    "positive": "#34D399",
    "negative": "#FB7185",
    "neutral": "#94A3B8",
    "mixed": "#FBBF24",
}

EMOTION_COLORS = {
    "joy": "#34D399",
    "anger": "#EF4444",
    "fear": "#A78BFA",
    "surprise": "#FBBF24",
    "sadness": "#60A5FA",
    "disgust": "#F97316",
    "anticipation": "#2DD4BF",
    "trust": "#818CF8",
}

CHART_PALETTE = [
    "#6366F1", "#8B5CF6", "#A78BFA", "#C4B5FD",
    "#34D399", "#2DD4BF", "#FBBF24", "#FB923C",
]

# -- Internal helpers ---------------------------------------------------------


def _fig_to_data_uri(fig: Figure, dpi: int = 150) -> str:
    """Convert a matplotlib Figure to a base64 PNG data URI.

    The figure is closed after rendering. Caller must hold _chart_lock.
    """
    buf = io.BytesIO()
    fig.savefig(
        buf,
        format="png",
        dpi=dpi,
        bbox_inches="tight",
        facecolor="white",
        edgecolor="none",
    )
    # Close the figure to free memory — we already rendered to buffer
    matplotlib.pyplot.close(fig)
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode("utf-8")
    return f"data:image/png;base64,{b64}"


def _get_color(name: str, palette: dict[str, str], fallback_palette: list[str], idx: int = 0) -> str:
    """Look up a named color or fall back to the rotating palette."""
    return palette.get(name.lower(), fallback_palette[idx % len(fallback_palette)])


# -- Public chart generators --------------------------------------------------


def generate_emotion_chart(emotions: dict[str, int], dpi: int = 150) -> str:
    """Horizontal bar chart of emotion distribution.

    Args:
        emotions: Mapping of emotion name to post count (e.g. {"joy": 15, "anger": 8}).
        dpi: Resolution for the output PNG.

    Returns:
        Base64 data URI string, or "" if input is empty / all zeros.
    """
    filtered = {k: v for k, v in emotions.items() if v > 0}
    if not filtered:
        return ""

    sorted_items = sorted(filtered.items(), key=lambda x: x[1], reverse=True)
    labels = [item[0].capitalize() for item in sorted_items]
    values = [item[1] for item in sorted_items]
    colors = [_get_color(item[0], EMOTION_COLORS, CHART_PALETTE, i) for i, item in enumerate(sorted_items)]
    total = sum(values)

    with _chart_lock:
        fig = Figure(figsize=(7, max(2.5, len(sorted_items) * 0.5 + 1)))
        ax = fig.add_subplot(111)

        bars = ax.barh(labels, values, color=colors, height=0.55, edgecolor="none", alpha=0.92)

        for bar, val in zip(bars, values):
            pct = (val / total * 100) if total > 0 else 0
            ax.text(
                bar.get_width() + 0.3,
                bar.get_y() + bar.get_height() / 2,
                f"{val} ({pct:.0f}%)",
                va="center",
                fontsize=9,
                fontweight="bold",
            )

        ax.set_title("Emotional Tone Distribution", fontweight="bold", fontsize=14)
        ax.invert_yaxis()
        ax.set_xlabel("Number of Posts")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.annotate(
            f"n={total}", xy=(1.0, -0.08), xycoords="axes fraction",
            ha="right", va="top", fontsize=8, fontstyle="italic", color="#6B7280",
        )

        return _fig_to_data_uri(fig, dpi)


def generate_sentiment_chart(sentiments: dict[str, int], dpi: int = 150) -> str:
    """Donut chart of sentiment split (positive / negative / neutral / mixed).

    Args:
        sentiments: Mapping of sentiment label to count.
        dpi: Resolution for the output PNG.

    Returns:
        Base64 data URI string, or "" if input is empty.
    """
    filtered = {k: v for k, v in sentiments.items() if v > 0}
    if not filtered:
        return ""

    labels = [k.capitalize() for k in filtered]
    values = list(filtered.values())
    colors = [SENTIMENT_COLORS.get(k.lower(), "#94A3B8") for k in filtered]
    total = sum(values)

    with _chart_lock:
        fig = Figure(figsize=(6, 5))
        ax = fig.add_subplot(111)

        wedges, texts, autotexts = ax.pie(
            values,
            labels=labels,
            colors=colors,
            autopct=lambda pct: f"{pct:.1f}%\n({int(round(pct / 100 * total))})",
            startangle=90,
            pctdistance=0.75,
            wedgeprops={"width": 0.4, "edgecolor": "white", "linewidth": 2},
        )
        for autotext in autotexts:
            autotext.set_fontsize(9)
            autotext.set_fontweight("bold")
        for text in texts:
            text.set_fontsize(10)

        ax.set_title("Sentiment Split", fontweight="bold", fontsize=14)
        ax.annotate(
            f"n={total}", xy=(0.5, -0.05), xycoords="axes fraction",
            ha="center", va="top", fontsize=8, fontstyle="italic", color="#6B7280",
        )

        return _fig_to_data_uri(fig, dpi)


def generate_theme_chart(themes: list[dict[str, Any]], dpi: int = 150) -> str:
    """Horizontal bar chart of theme frequency by percentage.

    Args:
        themes: List of theme dicts, each with "name", "percentage", "post_count".
        dpi: Resolution for the output PNG.

    Returns:
        Base64 data URI string, or "" if input is empty.
    """
    if not themes:
        return ""

    # Take top 8, sorted by percentage descending
    sorted_themes = sorted(themes, key=lambda t: t.get("percentage", 0), reverse=True)[:8]
    labels = [t["name"][:25] for t in sorted_themes]
    values = [t["percentage"] for t in sorted_themes]
    counts = [t.get("post_count", 0) for t in sorted_themes]
    colors = [CHART_PALETTE[i % len(CHART_PALETTE)] for i in range(len(sorted_themes))]

    with _chart_lock:
        fig = Figure(figsize=(7, max(2.5, len(sorted_themes) * 0.5 + 1)))
        ax = fig.add_subplot(111)

        bars = ax.barh(labels, values, color=colors, height=0.55, edgecolor="none", alpha=0.92)

        for bar, pct, count in zip(bars, values, counts):
            ax.text(
                bar.get_width() + 0.5,
                bar.get_y() + bar.get_height() / 2,
                f"{pct:.0f}% ({count} posts)",
                va="center",
                fontsize=9,
                fontweight="bold",
            )

        ax.set_title("Key Themes", fontweight="bold", fontsize=14)
        ax.invert_yaxis()
        ax.set_xlabel("Prevalence (%)")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        return _fig_to_data_uri(fig, dpi)


def generate_community_chart(communities: dict[str, dict[str, int]], dpi: int = 150) -> str:
    """Grouped bar chart of sentiment by community.

    Args:
        communities: Mapping of community name to sentiment counts.
            e.g. {"r/python": {"positive": 10, "negative": 3, "neutral": 5}}
        dpi: Resolution for the output PNG.

    Returns:
        Base64 data URI string, or "" if input is empty.
    """
    if not communities:
        return ""

    import numpy as np

    # Take top 8 communities by total post count
    sorted_comms = sorted(
        communities.items(),
        key=lambda x: sum(x[1].values()),
        reverse=True,
    )[:8]

    comm_labels = [name[:18] for name, _ in sorted_comms]
    sentiment_keys = ["positive", "negative", "neutral", "mixed"]
    present_keys = [
        k for k in sentiment_keys
        if any(data.get(k, 0) > 0 for _, data in sorted_comms)
    ]

    x = np.arange(len(comm_labels))
    width = 0.8 / max(len(present_keys), 1)

    with _chart_lock:
        fig = Figure(figsize=(max(7, len(comm_labels) * 1.2), 5))
        ax = fig.add_subplot(111)

        for i, key in enumerate(present_keys):
            vals = [data.get(key, 0) for _, data in sorted_comms]
            offset = (i - len(present_keys) / 2 + 0.5) * width
            bars = ax.bar(
                x + offset,
                vals,
                width=width,
                label=key.capitalize(),
                color=SENTIMENT_COLORS.get(key, "#94A3B8"),
                edgecolor="none",
                alpha=0.9,
            )

        ax.set_title("Community Breakdown", fontweight="bold", fontsize=14)
        ax.set_ylabel("Number of Posts")
        ax.set_xticks(x)
        ax.set_xticklabels(comm_labels, rotation=35, ha="right", fontsize=9)
        ax.legend(fontsize=9, frameon=False)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        total = sum(sum(d.values()) for _, d in sorted_comms)
        ax.annotate(
            f"n={total}", xy=(1.0, 1.0), xycoords="axes fraction",
            ha="right", va="top", fontsize=8, fontstyle="italic", color="#6B7280",
        )

        return _fig_to_data_uri(fig, dpi)


def generate_all_charts(
    statistics: dict[str, Any],
    themes: list[dict[str, Any]],
    dpi: int = 150,
) -> dict[str, str]:
    """Generate all report charts, returning a dict of chart name to data URI.

    Skips charts for which data is missing or empty. Never raises — logs errors
    and returns partial results.

    Args:
        statistics: Dict with keys "sentiment_distribution", "emotion_distribution",
            "community_breakdown" mapping to their respective data shapes.
        themes: List of theme dicts (from ThematicResult).
        dpi: Resolution for output PNGs.

    Returns:
        Dict like {"sentiment": "data:image/png;base64,...", "emotion": "...", ...}
    """
    charts: dict[str, str] = {}

    generators = [
        ("sentiment", lambda: generate_sentiment_chart(
            statistics.get("sentiment_distribution", {}), dpi)),
        ("emotion", lambda: generate_emotion_chart(
            statistics.get("emotion_distribution", {}), dpi)),
        ("themes", lambda: generate_theme_chart(themes, dpi)),
        ("community", lambda: generate_community_chart(
            statistics.get("community_breakdown", {}), dpi)),
    ]

    for name, gen in generators:
        try:
            result = gen()
            if result:
                charts[name] = result
        except Exception:
            logger.exception("Failed to generate %s chart", name)

    return charts
```

- [ ] **Step 1.9** — Run tests, confirm all PASS (2 min)

```bash
cd "/Users/eston/Desktop/Sentiment Analysis" && python -m pytest signalstream/tests/test_reports/test_charts.py -v 2>&1 | tail -20
```

- [ ] **Step 1.10** — Commit (1 min)

```bash
cd "/Users/eston/Desktop/Sentiment Analysis" && git add signalstream/reports/__init__.py signalstream/reports/charts.py signalstream/tests/test_reports/__init__.py signalstream/tests/test_reports/test_charts.py && git commit -m "feat(reports): add thread-safe matplotlib chart generation (BOARD-010)"
```

---

## Task 2: Report Content Builder — `signalstream/reports/builder.py`

**Files:**
- Create: `signalstream/reports/builder.py`
- Create: `signalstream/tests/test_reports/test_builder.py`

**Why:** The builder assembles a `ReportContent` dataclass from raw analysis results. It computes statistics, generates chart data URIs, and structures everything the renderer needs. This is the "what goes in the report" layer, decoupled from "how it is rendered."

### Steps

- [ ] **Step 2.1** — Write test for ReportContent dataclass and statistics computation (3 min)

```bash
# Test command (expect FAIL)
cd "/Users/eston/Desktop/Sentiment Analysis" && python -m pytest signalstream/tests/test_reports/test_builder.py -x 2>&1 | tail -5
```

```python
# signalstream/tests/test_reports/test_builder.py
"""Tests for report content assembly."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest


def _make_analyzed_post(
    post_id: str,
    sentiment: str = "positive",
    emotion: str = "joy",
    confidence: float = 0.85,
    community: str = "r/python",
    key_point: str = "Great discussion.",
    sarcasm_detected: bool = False,
) -> dict:
    """Helper to build a minimal analyzed post dict for testing."""
    return {
        "post": {
            "platform": "reddit",
            "id": post_id,
            "author": "test_user",
            "text": "Sample post text.",
            "title": "Sample Title",
            "timestamp": datetime(2026, 3, 15, tzinfo=timezone.utc).isoformat(),
            "url": f"https://reddit.com/r/python/comments/{post_id}",
            "community": community,
            "engagement": 42,
            "comments": [],
            "phrase_matches": ["python"],
        },
        "analysis": {
            "sentiment": sentiment,
            "emotion": emotion,
            "confidence": confidence,
            "key_point": key_point,
            "sarcasm_detected": sarcasm_detected,
        },
    }


def test_build_report_content_basic():
    """Builder produces a ReportContent with correct top-level fields."""
    from signalstream.reports.builder import build_report_content, ReportContent

    posts = [
        _make_analyzed_post("1", "positive", "joy", community="r/python"),
        _make_analyzed_post("2", "negative", "anger", community="r/python"),
        _make_analyzed_post("3", "positive", "surprise", community="r/programming"),
        _make_analyzed_post("4", "neutral", "trust", community="r/programming"),
    ]
    themes = [
        {"name": "Code Quality", "description": "Focus on code standards", "percentage": 50.0,
         "post_count": 2, "sentiment_skew": "positive", "representative_quotes": ["quote1"]},
        {"name": "Tooling", "description": "IDE and tool discussions", "percentage": 25.0,
         "post_count": 1, "sentiment_skew": "neutral", "representative_quotes": ["quote2"]},
    ]

    content = build_report_content(
        job_id="job-001",
        topic="Python sentiment",
        phrases=["python", "coding"],
        analyzed_posts=posts,
        themes=themes,
        skipped_count=1,
    )

    assert isinstance(content, ReportContent)
    assert content.job_id == "job-001"
    assert content.topic == "Python sentiment"
    assert content.total_posts == 4
    assert content.skipped_count == 1


def test_statistics_computation():
    """Statistics dict has correct sentiment and emotion distributions."""
    from signalstream.reports.builder import build_report_content

    posts = [
        _make_analyzed_post("1", "positive", "joy", community="r/python"),
        _make_analyzed_post("2", "positive", "joy", community="r/python"),
        _make_analyzed_post("3", "negative", "anger", community="r/python"),
        _make_analyzed_post("4", "neutral", "trust", community="r/learnpython"),
    ]

    content = build_report_content(
        job_id="job-002",
        topic="test",
        phrases=["test"],
        analyzed_posts=posts,
        themes=[],
    )

    stats = content.statistics
    assert stats["sentiment_distribution"]["positive"] == 2
    assert stats["sentiment_distribution"]["negative"] == 1
    assert stats["sentiment_distribution"]["neutral"] == 1
    assert stats["emotion_distribution"]["joy"] == 2
    assert stats["emotion_distribution"]["anger"] == 1
    assert stats["emotion_distribution"]["trust"] == 1
    assert "r/python" in stats["community_breakdown"]
    assert "r/learnpython" in stats["community_breakdown"]


def test_community_breakdown_sentiment_split():
    """Community breakdown includes per-community sentiment counts."""
    from signalstream.reports.builder import build_report_content

    posts = [
        _make_analyzed_post("1", "positive", "joy", community="r/python"),
        _make_analyzed_post("2", "negative", "anger", community="r/python"),
        _make_analyzed_post("3", "positive", "joy", community="r/rust"),
    ]

    content = build_report_content(
        job_id="job-003", topic="test", phrases=["test"],
        analyzed_posts=posts, themes=[],
    )

    python_breakdown = content.statistics["community_breakdown"]["r/python"]
    assert python_breakdown["positive"] == 1
    assert python_breakdown["negative"] == 1


def test_charts_are_generated():
    """ReportContent includes chart data URIs when data is present."""
    from signalstream.reports.builder import build_report_content

    posts = [
        _make_analyzed_post("1", "positive", "joy"),
        _make_analyzed_post("2", "negative", "anger"),
    ]

    content = build_report_content(
        job_id="job-004", topic="test", phrases=["test"],
        analyzed_posts=posts, themes=[
            {"name": "Theme A", "description": "Desc", "percentage": 60.0,
             "post_count": 1, "sentiment_skew": "positive", "representative_quotes": []},
        ],
    )

    assert content.charts.get("sentiment", "").startswith("data:image/png;base64,")
    assert content.charts.get("emotion", "").startswith("data:image/png;base64,")


def test_executive_snapshot():
    """Executive snapshot card data is computed correctly."""
    from signalstream.reports.builder import build_report_content

    posts = [
        _make_analyzed_post("1", "positive", "joy", confidence=0.9),
        _make_analyzed_post("2", "positive", "joy", confidence=0.8),
        _make_analyzed_post("3", "negative", "anger", confidence=0.7),
    ]

    content = build_report_content(
        job_id="job-005", topic="test", phrases=["test"],
        analyzed_posts=posts, themes=[],
    )

    snap = content.executive_snapshot
    assert snap["dominant_sentiment"] == "positive"
    assert snap["dominant_emotion"] == "joy"
    assert snap["total_posts"] == 3
    assert 0.0 <= snap["avg_confidence"] <= 1.0


def test_empty_posts_produces_empty_report():
    """Zero posts produces valid but empty ReportContent."""
    from signalstream.reports.builder import build_report_content

    content = build_report_content(
        job_id="job-006", topic="empty", phrases=["nothing"],
        analyzed_posts=[], themes=[],
    )

    assert content.total_posts == 0
    assert content.statistics["sentiment_distribution"] == {}
```

- [ ] **Step 2.2** — Run tests, confirm FAIL (1 min)

```bash
cd "/Users/eston/Desktop/Sentiment Analysis" && python -m pytest signalstream/tests/test_reports/test_builder.py -x 2>&1 | tail -5
```

- [ ] **Step 2.3** — Implement `builder.py` (5 min)

```python
# signalstream/reports/builder.py
"""
Report content assembly.

Computes statistics, generates charts, and structures all data needed by
the renderer. This is the "what goes in the report" layer — decoupled from
"how it is rendered" (PDF, JSON, etc.).
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from signalstream.reports.charts import generate_all_charts

logger = logging.getLogger(__name__)


@dataclass
class ReportContent:
    """All data needed to render a report in any format."""

    job_id: str
    topic: str
    phrases: list[str]
    generated_at: str
    total_posts: int
    skipped_count: int
    statistics: dict[str, Any]
    executive_snapshot: dict[str, Any]
    themes: list[dict[str, Any]]
    charts: dict[str, str]  # chart name -> base64 data URI
    analyzed_posts: list[dict[str, Any]]
    branding_footer: bool = True  # "Powered by Signalstream"


def _compute_statistics(posts: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive distribution statistics from analyzed posts.

    Returns dict with keys: sentiment_distribution, emotion_distribution,
    community_breakdown.
    """
    if not posts:
        return {
            "sentiment_distribution": {},
            "emotion_distribution": {},
            "community_breakdown": {},
        }

    sentiment_counter: Counter[str] = Counter()
    emotion_counter: Counter[str] = Counter()
    community_sentiments: dict[str, Counter[str]] = {}

    for post_data in posts:
        analysis = post_data.get("analysis", {})
        post = post_data.get("post", {})

        sentiment = analysis.get("sentiment", "neutral")
        emotion = analysis.get("emotion", "unknown")
        community = post.get("community", "unknown")

        sentiment_counter[sentiment] += 1
        emotion_counter[emotion] += 1

        if community not in community_sentiments:
            community_sentiments[community] = Counter()
        community_sentiments[community][sentiment] += 1

    # Convert community counters to plain dicts
    community_breakdown = {
        comm: dict(counter) for comm, counter in community_sentiments.items()
    }

    return {
        "sentiment_distribution": dict(sentiment_counter),
        "emotion_distribution": dict(emotion_counter),
        "community_breakdown": community_breakdown,
    }


def _compute_executive_snapshot(
    posts: list[dict[str, Any]],
    statistics: dict[str, Any],
    themes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute top-level metrics for the executive snapshot card."""
    if not posts:
        return {
            "total_posts": 0,
            "dominant_sentiment": "n/a",
            "dominant_emotion": "n/a",
            "avg_confidence": 0.0,
            "top_theme": "n/a",
            "sentiment_ratio": "n/a",
        }

    sent_dist = statistics.get("sentiment_distribution", {})
    emo_dist = statistics.get("emotion_distribution", {})

    dominant_sentiment = max(sent_dist, key=sent_dist.get) if sent_dist else "n/a"
    dominant_emotion = max(emo_dist, key=emo_dist.get) if emo_dist else "n/a"

    confidences = [
        p.get("analysis", {}).get("confidence", 0.0) for p in posts
    ]
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

    top_theme = themes[0]["name"] if themes else "n/a"

    positive = sent_dist.get("positive", 0)
    negative = sent_dist.get("negative", 0)
    total_pn = positive + negative
    sentiment_ratio = (
        f"{positive}:{negative}"
        if total_pn > 0
        else "n/a"
    )

    return {
        "total_posts": len(posts),
        "dominant_sentiment": dominant_sentiment,
        "dominant_emotion": dominant_emotion,
        "avg_confidence": round(avg_confidence, 3),
        "top_theme": top_theme,
        "sentiment_ratio": sentiment_ratio,
    }


def build_report_content(
    job_id: str,
    topic: str,
    phrases: list[str],
    analyzed_posts: list[dict[str, Any]],
    themes: list[dict[str, Any]],
    skipped_count: int = 0,
    branding_footer: bool = True,
) -> ReportContent:
    """Assemble all report content from analysis results.

    This is the single entry point for report data preparation. It computes
    statistics, generates charts (thread-safe), and structures the executive
    snapshot. The returned ReportContent is renderer-agnostic.

    Args:
        job_id: Unique job identifier.
        topic: The analysis topic / query.
        phrases: Search phrases used for collection.
        analyzed_posts: List of post dicts, each with "post" and "analysis" keys.
        themes: List of theme dicts from thematic analysis.
        skipped_count: Number of posts that failed analysis.
        branding_footer: Whether to include "Powered by Signalstream" in output.

    Returns:
        ReportContent dataclass ready for any renderer.
    """
    statistics = _compute_statistics(analyzed_posts)
    executive_snapshot = _compute_executive_snapshot(analyzed_posts, statistics, themes)

    charts = generate_all_charts(statistics, themes)

    return ReportContent(
        job_id=job_id,
        topic=topic,
        phrases=phrases,
        generated_at=datetime.now(timezone.utc).isoformat(),
        total_posts=len(analyzed_posts),
        skipped_count=skipped_count,
        statistics=statistics,
        executive_snapshot=executive_snapshot,
        themes=themes,
        charts=charts,
        analyzed_posts=analyzed_posts,
        branding_footer=branding_footer,
    )
```

- [ ] **Step 2.4** — Run tests, confirm all PASS (2 min)

```bash
cd "/Users/eston/Desktop/Sentiment Analysis" && python -m pytest signalstream/tests/test_reports/test_builder.py -v 2>&1 | tail -15
```

- [ ] **Step 2.5** — Commit (1 min)

```bash
cd "/Users/eston/Desktop/Sentiment Analysis" && git add signalstream/reports/builder.py signalstream/tests/test_reports/test_builder.py && git commit -m "feat(reports): add report content builder with statistics and chart assembly"
```

---

## Task 3: PDF Templates — `signalstream/reports/pdf_templates/`

**Files:**
- Create: `signalstream/reports/pdf_templates/report.html`
- Create: `signalstream/reports/pdf_templates/styles.css`

**Why:** The PDF report is the primary shareable artifact. The template uses Jinja2 for content and inline CSS for styling. All assets (charts) are embedded as data URIs — no external resource loading (BOARD-002).

**Structure (7 cards):**
1. Executive snapshot with key metrics
2. Emotional landscape distribution
3. Sentiment split analysis
4. Key themes identified
5. Community lens (per-community breakdown)
6. Messaging playbook
7. Methodology and data scope

### Steps

- [ ] **Step 3.1** — Create `styles.css` for the PDF report (4 min)

```css
/* signalstream/reports/pdf_templates/styles.css */
/*
 * PDF Report Stylesheet — Signalstream
 *
 * Designed for WeasyPrint rendering. All assets must be inline
 * (data URIs). No external resource loading (BOARD-002).
 *
 * Page size: A4 portrait.
 */

@page {
    size: A4;
    margin: 20mm 18mm 25mm 18mm;

    @bottom-center {
        content: counter(page) " of " counter(pages);
        font-size: 9px;
        color: #6B7280;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
}

* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    font-size: 11px;
    line-height: 1.5;
    color: #1F2937;
    background: #FFFFFF;
}

/* -- Cover / Header -------------------------------------------------------- */

.report-header {
    text-align: center;
    padding: 30px 0 20px 0;
    border-bottom: 3px solid #6366F1;
    margin-bottom: 25px;
}

.report-header h1 {
    font-size: 26px;
    font-weight: 700;
    color: #111827;
    margin-bottom: 6px;
}

.report-header .subtitle {
    font-size: 14px;
    color: #6B7280;
    margin-bottom: 4px;
}

.report-header .meta {
    font-size: 10px;
    color: #9CA3AF;
}

/* -- Card system ----------------------------------------------------------- */

.card {
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 8px;
    padding: 20px 24px;
    margin-bottom: 20px;
    page-break-inside: avoid;
}

.card h2 {
    font-size: 16px;
    font-weight: 700;
    color: #111827;
    margin-bottom: 12px;
    padding-bottom: 8px;
    border-bottom: 2px solid #6366F1;
}

.card h3 {
    font-size: 13px;
    font-weight: 600;
    color: #374151;
    margin-bottom: 8px;
}

.card p {
    margin-bottom: 8px;
    color: #4B5563;
}

/* -- Executive snapshot ---------------------------------------------------- */

.snapshot-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    margin-top: 10px;
}

.snapshot-metric {
    flex: 1 1 30%;
    background: #F9FAFB;
    border: 1px solid #E5E7EB;
    border-radius: 6px;
    padding: 12px 16px;
    text-align: center;
}

.snapshot-metric .value {
    font-size: 22px;
    font-weight: 700;
    color: #6366F1;
}

.snapshot-metric .label {
    font-size: 10px;
    color: #6B7280;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-top: 2px;
}

/* -- Charts ---------------------------------------------------------------- */

.chart-container {
    text-align: center;
    margin: 15px 0;
}

.chart-container img {
    max-width: 100%;
    height: auto;
}

/* -- Themes ---------------------------------------------------------------- */

.theme-item {
    margin-bottom: 14px;
    padding: 12px 16px;
    background: #F9FAFB;
    border-left: 4px solid #6366F1;
    border-radius: 0 6px 6px 0;
}

.theme-item .theme-name {
    font-weight: 700;
    font-size: 13px;
    color: #111827;
}

.theme-item .theme-stats {
    font-size: 10px;
    color: #6B7280;
    margin-top: 2px;
}

.theme-item .theme-desc {
    font-size: 11px;
    color: #4B5563;
    margin-top: 4px;
}

.theme-item blockquote {
    margin-top: 6px;
    padding-left: 10px;
    border-left: 2px solid #D1D5DB;
    font-style: italic;
    font-size: 10px;
    color: #6B7280;
}

/* -- Community lens -------------------------------------------------------- */

.community-table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 10px;
    font-size: 10px;
}

.community-table th {
    background: #F3F4F6;
    padding: 8px 10px;
    text-align: left;
    font-weight: 600;
    color: #374151;
    border-bottom: 2px solid #E5E7EB;
}

.community-table td {
    padding: 6px 10px;
    border-bottom: 1px solid #F3F4F6;
    color: #4B5563;
}

.community-table tr:nth-child(even) {
    background: #F9FAFB;
}

/* -- Playbook -------------------------------------------------------------- */

.playbook-item {
    margin-bottom: 10px;
    padding: 10px 14px;
    background: #EEF2FF;
    border-radius: 6px;
}

.playbook-item .playbook-label {
    font-weight: 700;
    font-size: 11px;
    color: #4338CA;
}

.playbook-item .playbook-text {
    font-size: 11px;
    color: #4B5563;
    margin-top: 2px;
}

/* -- Methodology ----------------------------------------------------------- */

.methodology {
    font-size: 10px;
    color: #6B7280;
    line-height: 1.6;
}

.methodology dt {
    font-weight: 600;
    color: #374151;
    margin-top: 6px;
}

.methodology dd {
    margin-left: 0;
    margin-bottom: 4px;
}

/* -- Footer ---------------------------------------------------------------- */

.report-footer {
    text-align: center;
    padding-top: 20px;
    margin-top: 30px;
    border-top: 1px solid #E5E7EB;
    font-size: 10px;
    color: #9CA3AF;
}

.report-footer .branding {
    font-weight: 600;
    color: #6366F1;
}
```

- [ ] **Step 3.2** — Create `report.html` Jinja2 template with 7 cards (5 min)

```html
{# signalstream/reports/pdf_templates/report.html #}
{#
    PDF Report Template — Signalstream

    Rendered by WeasyPrint via renderer.py.
    All chart images are inline base64 data URIs (BOARD-002).

    Context variables:
      - content: ReportContent dataclass
      - css: inline CSS string (from styles.css)
#}
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <style>{{ css }}</style>
</head>
<body>

{# -- Report Header -------------------------------------------------------- #}
<div class="report-header">
    <h1>Sentiment Analysis Report</h1>
    <p class="subtitle">{{ content.topic }}</p>
    <p class="meta">
        Generated {{ content.generated_at[:10] }}
        &middot; {{ content.total_posts }} posts analyzed
        {% if content.skipped_count > 0 %}
        &middot; {{ content.skipped_count }} skipped
        {% endif %}
        &middot; Search: {{ content.phrases | join(", ") }}
    </p>
</div>

{# -- Card 1: Executive Snapshot ------------------------------------------- #}
<div class="card">
    <h2>Executive Snapshot</h2>
    <div class="snapshot-grid">
        <div class="snapshot-metric">
            <div class="value">{{ content.executive_snapshot.total_posts }}</div>
            <div class="label">Posts Analyzed</div>
        </div>
        <div class="snapshot-metric">
            <div class="value">{{ content.executive_snapshot.dominant_sentiment | capitalize }}</div>
            <div class="label">Dominant Sentiment</div>
        </div>
        <div class="snapshot-metric">
            <div class="value">{{ content.executive_snapshot.dominant_emotion | capitalize }}</div>
            <div class="label">Dominant Emotion</div>
        </div>
        <div class="snapshot-metric">
            <div class="value">{{ "%.0f" | format(content.executive_snapshot.avg_confidence * 100) }}%</div>
            <div class="label">Avg Confidence</div>
        </div>
        <div class="snapshot-metric">
            <div class="value">{{ content.executive_snapshot.sentiment_ratio }}</div>
            <div class="label">Positive : Negative</div>
        </div>
        <div class="snapshot-metric">
            <div class="value">{{ content.executive_snapshot.top_theme }}</div>
            <div class="label">Top Theme</div>
        </div>
    </div>
</div>

{# -- Card 2: Emotional Landscape ----------------------------------------- #}
{% if content.charts.get("emotion") %}
<div class="card">
    <h2>Emotional Landscape</h2>
    <p>Distribution of detected emotions across all analyzed posts.</p>
    <div class="chart-container">
        <img src="{{ content.charts.emotion }}" alt="Emotion distribution chart">
    </div>
</div>
{% endif %}

{# -- Card 3: Sentiment Split ---------------------------------------------- #}
{% if content.charts.get("sentiment") %}
<div class="card">
    <h2>Sentiment Split</h2>
    <p>Overall sentiment breakdown across the dataset.</p>
    <div class="chart-container">
        <img src="{{ content.charts.sentiment }}" alt="Sentiment split chart">
    </div>
</div>
{% endif %}

{# -- Card 4: Key Themes --------------------------------------------------- #}
{% if content.themes %}
<div class="card">
    <h2>Key Themes</h2>
    {% if content.charts.get("themes") %}
    <div class="chart-container">
        <img src="{{ content.charts.themes }}" alt="Theme frequency chart">
    </div>
    {% endif %}

    {% for theme in content.themes %}
    <div class="theme-item">
        <div class="theme-name">{{ theme.name }}</div>
        <div class="theme-stats">
            {{ "%.0f" | format(theme.percentage) }}% of posts
            ({{ theme.post_count }} posts)
            &middot; Sentiment skew: {{ theme.sentiment_skew }}
        </div>
        <div class="theme-desc">{{ theme.description }}</div>
        {% for quote in theme.get("representative_quotes", [])[:2] %}
        <blockquote>&ldquo;{{ quote }}&rdquo;</blockquote>
        {% endfor %}
    </div>
    {% endfor %}
</div>
{% endif %}

{# -- Card 5: Community Lens ----------------------------------------------- #}
{% if content.statistics.community_breakdown %}
<div class="card">
    <h2>Community Lens</h2>
    <p>Sentiment distribution across online communities.</p>

    {% if content.charts.get("community") %}
    <div class="chart-container">
        <img src="{{ content.charts.community }}" alt="Community breakdown chart">
    </div>
    {% endif %}

    <table class="community-table">
        <thead>
            <tr>
                <th>Community</th>
                <th>Positive</th>
                <th>Negative</th>
                <th>Neutral</th>
                <th>Mixed</th>
                <th>Total</th>
            </tr>
        </thead>
        <tbody>
            {% for comm_name, comm_data in content.statistics.community_breakdown.items() %}
            <tr>
                <td>{{ comm_name }}</td>
                <td>{{ comm_data.get("positive", 0) }}</td>
                <td>{{ comm_data.get("negative", 0) }}</td>
                <td>{{ comm_data.get("neutral", 0) }}</td>
                <td>{{ comm_data.get("mixed", 0) }}</td>
                <td>{{ comm_data.values() | sum }}</td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% endif %}

{# -- Card 6: Messaging Playbook ------------------------------------------ #}
{% if content.themes %}
<div class="card">
    <h2>Messaging Playbook</h2>
    <p>Actionable takeaways based on the dominant themes and sentiment patterns.</p>

    {% for theme in content.themes[:5] %}
    <div class="playbook-item">
        <div class="playbook-label">
            {% if theme.sentiment_skew == "positive" %}
                Amplify: {{ theme.name }}
            {% elif theme.sentiment_skew == "negative" %}
                Address: {{ theme.name }}
            {% else %}
                Monitor: {{ theme.name }}
            {% endif %}
        </div>
        <div class="playbook-text">
            {{ theme.description }}
            ({{ "%.0f" | format(theme.percentage) }}% of conversation,
            {{ theme.sentiment_skew }} sentiment)
        </div>
    </div>
    {% endfor %}
</div>
{% endif %}

{# -- Card 7: Methodology & Data Scope ------------------------------------ #}
<div class="card">
    <h2>Methodology &amp; Data Scope</h2>
    <dl class="methodology">
        <dt>Data Source</dt>
        <dd>Reddit public posts and comments</dd>

        <dt>Search Phrases</dt>
        <dd>{{ content.phrases | join(", ") }}</dd>

        <dt>Posts Collected</dt>
        <dd>{{ content.total_posts }}{% if content.skipped_count > 0 %} ({{ content.skipped_count }} could not be analyzed){% endif %}</dd>

        <dt>Analysis Method</dt>
        <dd>Per-post LLM-based sentiment classification, emotion detection, sarcasm detection, and key-point extraction. Cross-post thematic analysis with consolidation.</dd>

        <dt>Confidence</dt>
        <dd>Average model confidence: {{ "%.0f" | format(content.executive_snapshot.avg_confidence * 100) }}%</dd>

        <dt>Limitations</dt>
        <dd>Results reflect publicly visible content only. Sentiment classification accuracy depends on the LLM model used. Sarcasm and nuance may be misclassified. This report is for informational purposes and should not be the sole basis for decisions.</dd>
    </dl>
</div>

{# -- Footer --------------------------------------------------------------- #}
{% if content.branding_footer %}
<div class="report-footer">
    <span class="branding">Powered by Signalstream</span>
    &middot; Open-source sentiment analysis
</div>
{% endif %}

</body>
</html>
```

- [ ] **Step 3.3** — Commit (1 min)

```bash
cd "/Users/eston/Desktop/Sentiment Analysis" && git add signalstream/reports/pdf_templates/report.html signalstream/reports/pdf_templates/styles.css && git commit -m "feat(reports): add PDF report Jinja2 template and CSS (7-card layout)"
```

---

## Task 4: PDF Renderer — `signalstream/reports/renderer.py`

**Files:**
- Create: `signalstream/reports/renderer.py`
- Create: `signalstream/tests/test_reports/test_renderer.py`

**Why:** The renderer converts ReportContent into a PDF via WeasyPrint. WeasyPrint is optional (BOARD-002) — the app must work without it. The custom `url_fetcher` blocks all external resource loading to prevent SSRF.

### Steps

- [ ] **Step 4.1** — Write tests for PDF rendering and SSRF protection (4 min)

```python
# signalstream/tests/test_reports/test_renderer.py
"""Tests for PDF renderer with SSRF protection (BOARD-002)."""

from __future__ import annotations
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

import pytest


def _make_report_content():
    """Build a minimal ReportContent for renderer tests."""
    from signalstream.reports.builder import ReportContent

    return ReportContent(
        job_id="test-001",
        topic="Test Topic",
        phrases=["test"],
        generated_at=datetime.now(timezone.utc).isoformat(),
        total_posts=5,
        skipped_count=0,
        statistics={
            "sentiment_distribution": {"positive": 3, "negative": 2},
            "emotion_distribution": {"joy": 3, "anger": 2},
            "community_breakdown": {
                "r/test": {"positive": 3, "negative": 2},
            },
        },
        executive_snapshot={
            "total_posts": 5,
            "dominant_sentiment": "positive",
            "dominant_emotion": "joy",
            "avg_confidence": 0.85,
            "top_theme": "n/a",
            "sentiment_ratio": "3:2",
        },
        themes=[],
        charts={},
        analyzed_posts=[],
        branding_footer=True,
    )


def test_pdf_available_flag():
    """PDF_AVAILABLE is a boolean reflecting whether weasyprint is importable."""
    from signalstream.reports.renderer import PDF_AVAILABLE

    assert isinstance(PDF_AVAILABLE, bool)


def test_render_html_string():
    """render_html() returns an HTML string regardless of WeasyPrint availability."""
    from signalstream.reports.renderer import render_html

    content = _make_report_content()
    html = render_html(content)

    assert isinstance(html, str)
    assert "Test Topic" in html
    assert "Sentiment Analysis Report" in html
    assert "Powered by Signalstream" in html


def test_render_html_no_branding():
    """Branding footer is omitted when branding_footer=False."""
    from signalstream.reports.renderer import render_html

    content = _make_report_content()
    content.branding_footer = False
    html = render_html(content)

    assert "Powered by Signalstream" not in html


def test_safe_url_fetcher_allows_data_uris():
    """data: URIs are passed through by the safe url_fetcher."""
    from signalstream.reports.renderer import _safe_url_fetcher

    data_uri = "data:image/png;base64,iVBORw0KGgo="
    # Should not raise
    result = _safe_url_fetcher(data_uri)
    # Result should be a dict with at least 'string' or 'file_obj'
    assert isinstance(result, dict)


def test_safe_url_fetcher_blocks_http():
    """HTTP URLs are blocked by the safe url_fetcher (SSRF prevention)."""
    from signalstream.reports.renderer import _safe_url_fetcher

    with pytest.raises(ValueError, match="Blocked external resource"):
        _safe_url_fetcher("http://example.com/evil.css")


def test_safe_url_fetcher_blocks_https():
    """HTTPS URLs are blocked — no external resources in PDF templates."""
    from signalstream.reports.renderer import _safe_url_fetcher

    with pytest.raises(ValueError, match="Blocked external resource"):
        _safe_url_fetcher("https://cdn.example.com/styles.css")


def test_safe_url_fetcher_blocks_file():
    """file:// URLs are blocked (prevents /etc/passwd reads)."""
    from signalstream.reports.renderer import _safe_url_fetcher

    with pytest.raises(ValueError, match="Blocked external resource"):
        _safe_url_fetcher("file:///etc/passwd")


def test_safe_url_fetcher_blocks_ftp():
    """ftp:// URLs are blocked."""
    from signalstream.reports.renderer import _safe_url_fetcher

    with pytest.raises(ValueError, match="Blocked external resource"):
        _safe_url_fetcher("ftp://internal.server/data")


def test_render_pdf_when_available():
    """render_pdf() returns bytes when WeasyPrint is installed."""
    from signalstream.reports import renderer

    if not renderer.PDF_AVAILABLE:
        pytest.skip("WeasyPrint not installed")

    content = _make_report_content()
    pdf_bytes = renderer.render_pdf(content)

    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes[:5] == b"%PDF-"


def test_render_pdf_when_unavailable():
    """render_pdf() raises RuntimeError with install instructions when WeasyPrint missing."""
    from signalstream.reports.renderer import render_pdf

    with patch("signalstream.reports.renderer.PDF_AVAILABLE", False):
        with pytest.raises(RuntimeError, match="WeasyPrint"):
            render_pdf(_make_report_content())
```

- [ ] **Step 4.2** — Run tests, confirm FAIL (1 min)

```bash
cd "/Users/eston/Desktop/Sentiment Analysis" && python -m pytest signalstream/tests/test_reports/test_renderer.py -x 2>&1 | tail -5
```

- [ ] **Step 4.3** — Implement `renderer.py` (5 min)

```python
# signalstream/reports/renderer.py
"""
PDF and HTML rendering for reports.

WeasyPrint is an optional dependency (BOARD-002). If not installed,
render_html() still works (for print-to-PDF fallback) and render_pdf()
raises RuntimeError with install instructions.

SSRF mitigation: custom url_fetcher blocks ALL external resource loading.
Only data: URIs are permitted. This prevents file:///etc/passwd reads
and SSRF via CSS/HTML resource loading.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)

# -- WeasyPrint optional import (BOARD-002) -----------------------------------

try:
    import weasyprint

    PDF_AVAILABLE = True
except (ImportError, OSError):
    weasyprint = None  # type: ignore[assignment]
    PDF_AVAILABLE = False

# -- Template setup -----------------------------------------------------------

_TEMPLATE_DIR = Path(__file__).parent / "pdf_templates"

_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)


def _load_css() -> str:
    """Read the PDF stylesheet as a string for inline embedding."""
    css_path = _TEMPLATE_DIR / "styles.css"
    return css_path.read_text(encoding="utf-8")


# -- SSRF-safe URL fetcher (BOARD-002) ----------------------------------------


def _safe_url_fetcher(url: str, timeout: int = 10, ssl_context: Any = None) -> dict:
    """Block all external resource loading in PDF generation.

    Only data: URIs are permitted. Everything else — http, https, file, ftp,
    gopher, or any other scheme — is blocked with a ValueError.

    This is the sole url_fetcher passed to WeasyPrint's HTML() constructor.
    There are no exceptions, no allowlists, no local file access.
    """
    if url.startswith("data:"):
        # Delegate data URI parsing to WeasyPrint's built-in handler
        return weasyprint.default_url_fetcher(url)
    raise ValueError(f"Blocked external resource in PDF template: {url}")


# -- Public API ---------------------------------------------------------------


def render_html(content: Any) -> str:
    """Render a ReportContent into an HTML string.

    Works regardless of WeasyPrint availability. This HTML is used for:
    1. PDF rendering (via WeasyPrint)
    2. Print-to-PDF fallback (via window.print() in browser)
    3. HTML export (future)

    Args:
        content: ReportContent dataclass from builder.py.

    Returns:
        Complete HTML document as a string.
    """
    template = _jinja_env.get_template("report.html")
    css = _load_css()
    return template.render(content=content, css=css)


def render_pdf(content: Any) -> bytes:
    """Render a ReportContent into a PDF document.

    Requires WeasyPrint to be installed. Raises RuntimeError with
    platform-specific install instructions if it is not.

    Args:
        content: ReportContent dataclass from builder.py.

    Returns:
        PDF file contents as bytes.

    Raises:
        RuntimeError: If WeasyPrint is not installed.
    """
    if not PDF_AVAILABLE:
        raise RuntimeError(
            "PDF export requires WeasyPrint. Install it with:\n"
            "  pip install signalstream[pdf]\n"
            "\n"
            "On macOS, you may also need:\n"
            "  brew install cairo pango gdk-pixbuf libffi\n"
            "\n"
            "Or use Docker, which includes all dependencies:\n"
            "  docker compose up"
        )

    html_string = render_html(content)

    html_doc = weasyprint.HTML(
        string=html_string,
        url_fetcher=_safe_url_fetcher,
    )
    return html_doc.write_pdf()
```

- [ ] **Step 4.4** — Run tests, confirm all PASS (2 min)

```bash
cd "/Users/eston/Desktop/Sentiment Analysis" && python -m pytest signalstream/tests/test_reports/test_renderer.py -v 2>&1 | tail -15
```

- [ ] **Step 4.5** — Commit (1 min)

```bash
cd "/Users/eston/Desktop/Sentiment Analysis" && git add signalstream/reports/renderer.py signalstream/tests/test_reports/test_renderer.py && git commit -m "feat(reports): add PDF renderer with SSRF-safe url_fetcher (BOARD-002)"
```

---

## Task 5: JSON Export — `signalstream/reports/exports.py`

**Files:**
- Create: `signalstream/reports/exports.py`
- Create: `signalstream/tests/test_reports/test_exports.py`

**Why:** JSON export is the programmatic access path. It serializes the ReportContent for API consumers, downstream tools, and the frontend Chart.js rendering.

### Steps

- [ ] **Step 5.1** — Write tests for JSON export (3 min)

```python
# signalstream/tests/test_reports/test_exports.py
"""Tests for JSON export."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest


def _make_report_content():
    from signalstream.reports.builder import ReportContent

    return ReportContent(
        job_id="export-001",
        topic="Export Test",
        phrases=["test"],
        generated_at=datetime.now(timezone.utc).isoformat(),
        total_posts=3,
        skipped_count=0,
        statistics={
            "sentiment_distribution": {"positive": 2, "negative": 1},
            "emotion_distribution": {"joy": 2, "anger": 1},
            "community_breakdown": {
                "r/test": {"positive": 2, "negative": 1},
            },
        },
        executive_snapshot={
            "total_posts": 3,
            "dominant_sentiment": "positive",
            "dominant_emotion": "joy",
            "avg_confidence": 0.82,
            "top_theme": "n/a",
            "sentiment_ratio": "2:1",
        },
        themes=[
            {"name": "Theme A", "description": "Desc A", "percentage": 60.0,
             "post_count": 2, "sentiment_skew": "positive",
             "representative_quotes": ["quote 1"]},
        ],
        charts={"sentiment": "data:image/png;base64,fakedata"},
        analyzed_posts=[
            {
                "post": {"id": "p1", "text": "Great stuff", "community": "r/test"},
                "analysis": {"sentiment": "positive", "emotion": "joy"},
            },
        ],
        branding_footer=True,
    )


def test_export_json_string():
    """export_json() returns a valid JSON string."""
    from signalstream.reports.exports import export_json

    content = _make_report_content()
    result = export_json(content)

    assert isinstance(result, str)
    parsed = json.loads(result)
    assert parsed["job_id"] == "export-001"
    assert parsed["topic"] == "Export Test"


def test_export_json_excludes_charts_by_default():
    """Charts (large base64 blobs) are excluded from JSON export by default."""
    from signalstream.reports.exports import export_json

    content = _make_report_content()
    result = export_json(content)
    parsed = json.loads(result)

    assert "charts" not in parsed


def test_export_json_includes_charts_when_requested():
    """Charts are included when include_charts=True."""
    from signalstream.reports.exports import export_json

    content = _make_report_content()
    result = export_json(content, include_charts=True)
    parsed = json.loads(result)

    assert "charts" in parsed
    assert "sentiment" in parsed["charts"]


def test_export_json_includes_statistics():
    """Statistics and themes are always present in JSON export."""
    from signalstream.reports.exports import export_json

    content = _make_report_content()
    parsed = json.loads(export_json(content))

    assert "statistics" in parsed
    assert "themes" in parsed
    assert "executive_snapshot" in parsed
    assert parsed["statistics"]["sentiment_distribution"]["positive"] == 2


def test_export_dict():
    """export_dict() returns a plain Python dict (for API responses)."""
    from signalstream.reports.exports import export_dict

    content = _make_report_content()
    result = export_dict(content)

    assert isinstance(result, dict)
    assert result["job_id"] == "export-001"
    assert "charts" not in result


def test_export_json_post_text_truncated():
    """Post text is truncated in export to limit file size and liability."""
    from signalstream.reports.exports import export_json
    from signalstream.reports.builder import ReportContent

    content = _make_report_content()
    # Add a post with very long text
    content.analyzed_posts = [
        {
            "post": {"id": "p1", "text": "x" * 5000, "community": "r/test"},
            "analysis": {"sentiment": "positive"},
        },
    ]

    parsed = json.loads(export_json(content))
    exported_text = parsed["analyzed_posts"][0]["post"]["text"]
    assert len(exported_text) <= 500
```

- [ ] **Step 5.2** — Run tests, confirm FAIL (1 min)

```bash
cd "/Users/eston/Desktop/Sentiment Analysis" && python -m pytest signalstream/tests/test_reports/test_exports.py -x 2>&1 | tail -5
```

- [ ] **Step 5.3** — Implement `exports.py` (3 min)

```python
# signalstream/reports/exports.py
"""
JSON export for analysis results.

Serializes ReportContent into JSON for API responses, file download,
and downstream analysis tools. Charts (large base64 blobs) are excluded
by default. Post text is truncated for data minimization.
"""

from __future__ import annotations

import copy
import json
import logging
from dataclasses import asdict
from typing import Any

logger = logging.getLogger(__name__)

_MAX_POST_TEXT_LENGTH = 500


def _prepare_export_dict(
    content: Any,
    include_charts: bool = False,
) -> dict[str, Any]:
    """Convert ReportContent to an export-ready dict.

    - Excludes charts unless explicitly requested (they are large base64 blobs).
    - Truncates post text to _MAX_POST_TEXT_LENGTH characters.
    """
    data = asdict(content)

    # Remove charts by default — they are large base64 blobs
    if not include_charts:
        data.pop("charts", None)

    # Truncate post text for data minimization
    for post_data in data.get("analyzed_posts", []):
        post = post_data.get("post", {})
        text = post.get("text", "")
        if len(text) > _MAX_POST_TEXT_LENGTH:
            post["text"] = text[:_MAX_POST_TEXT_LENGTH]

    return data


def export_dict(content: Any, include_charts: bool = False) -> dict[str, Any]:
    """Convert ReportContent to a plain dict for API JSON responses.

    Args:
        content: ReportContent dataclass from builder.py.
        include_charts: If True, include chart data URIs. Defaults to False.

    Returns:
        Dict suitable for json.dumps() or Flask jsonify().
    """
    return _prepare_export_dict(content, include_charts=include_charts)


def export_json(
    content: Any,
    include_charts: bool = False,
    indent: int = 2,
) -> str:
    """Serialize ReportContent to a formatted JSON string.

    Args:
        content: ReportContent dataclass from builder.py.
        include_charts: If True, include chart data URIs. Defaults to False.
        indent: JSON indentation level. Defaults to 2.

    Returns:
        JSON string.
    """
    data = _prepare_export_dict(content, include_charts=include_charts)
    return json.dumps(data, indent=indent, ensure_ascii=False, default=str)
```

- [ ] **Step 5.4** — Run tests, confirm all PASS (1 min)

```bash
cd "/Users/eston/Desktop/Sentiment Analysis" && python -m pytest signalstream/tests/test_reports/test_exports.py -v 2>&1 | tail -15
```

- [ ] **Step 5.5** — Commit (1 min)

```bash
cd "/Users/eston/Desktop/Sentiment Analysis" && git add signalstream/reports/exports.py signalstream/tests/test_reports/test_exports.py && git commit -m "feat(reports): add JSON export with text truncation and optional chart inclusion"
```

---

## Task 6: Job State Machine — `signalstream/jobs/state.py`

**Files:**
- Create: `signalstream/jobs/__init__.py`
- Create: `signalstream/jobs/state.py`
- Create: `signalstream/tests/test_jobs/__init__.py`
- Create: `signalstream/tests/test_jobs/test_state.py`

**Why:** The state machine defines valid job transitions, the CancellationToken for cooperative cancellation (BOARD / ALPHA-002), and progress reporting. Everything in the pipeline depends on this.

### Steps

- [ ] **Step 6.1** — Write tests for JobState enum and valid transitions (3 min)

```python
# signalstream/tests/test_jobs/__init__.py
# (empty)

# signalstream/tests/test_jobs/test_state.py
"""Tests for job state machine, cancellation, and progress reporting."""

from __future__ import annotations

import threading
import time

import pytest


def test_job_state_enum():
    """JobState has all required states."""
    from signalstream.jobs.state import JobState

    assert hasattr(JobState, "PENDING")
    assert hasattr(JobState, "COLLECTING")
    assert hasattr(JobState, "ANALYZING")
    assert hasattr(JobState, "THEMING")
    assert hasattr(JobState, "REPORTING")
    assert hasattr(JobState, "COMPLETED")
    assert hasattr(JobState, "FAILED")
    assert hasattr(JobState, "CANCELLED")


def test_valid_transitions():
    """State transitions follow the defined state machine."""
    from signalstream.jobs.state import JobState, is_valid_transition

    # Happy path
    assert is_valid_transition(JobState.PENDING, JobState.COLLECTING)
    assert is_valid_transition(JobState.COLLECTING, JobState.ANALYZING)
    assert is_valid_transition(JobState.ANALYZING, JobState.THEMING)
    assert is_valid_transition(JobState.THEMING, JobState.REPORTING)
    assert is_valid_transition(JobState.REPORTING, JobState.COMPLETED)

    # Any state can fail
    for state in [JobState.COLLECTING, JobState.ANALYZING, JobState.THEMING, JobState.REPORTING]:
        assert is_valid_transition(state, JobState.FAILED)

    # Any running state can be cancelled
    for state in [JobState.COLLECTING, JobState.ANALYZING, JobState.THEMING, JobState.REPORTING]:
        assert is_valid_transition(state, JobState.CANCELLED)


def test_invalid_transitions():
    """Invalid state transitions are rejected."""
    from signalstream.jobs.state import JobState, is_valid_transition

    # Cannot go backwards
    assert not is_valid_transition(JobState.ANALYZING, JobState.COLLECTING)
    # Cannot transition from terminal states
    assert not is_valid_transition(JobState.COMPLETED, JobState.COLLECTING)
    assert not is_valid_transition(JobState.FAILED, JobState.COLLECTING)
    # Cannot skip states
    assert not is_valid_transition(JobState.PENDING, JobState.ANALYZING)


def test_cancellation_token_starts_unset():
    """CancellationToken starts in non-cancelled state."""
    from signalstream.jobs.state import CancellationToken

    token = CancellationToken()
    assert not token.is_cancelled


def test_cancellation_token_cancel():
    """Calling cancel() makes is_cancelled return True."""
    from signalstream.jobs.state import CancellationToken

    token = CancellationToken()
    token.cancel()
    assert token.is_cancelled


def test_cancellation_token_check_raises():
    """check() raises CancelledError when token is cancelled."""
    from signalstream.jobs.state import CancellationToken, CancelledError

    token = CancellationToken()
    token.check()  # Should not raise

    token.cancel()
    with pytest.raises(CancelledError):
        token.check()


def test_cancellation_token_thread_safe():
    """CancellationToken works across threads."""
    from signalstream.jobs.state import CancellationToken

    token = CancellationToken()
    saw_cancellation = threading.Event()

    def worker():
        while not token.is_cancelled:
            time.sleep(0.01)
        saw_cancellation.set()

    t = threading.Thread(target=worker)
    t.start()
    time.sleep(0.05)
    token.cancel()
    t.join(timeout=2)

    assert saw_cancellation.is_set()


def test_job_progress():
    """JobProgress tracks stage, counts, and message."""
    from signalstream.jobs.state import JobProgress

    progress = JobProgress()
    assert progress.stage == ""
    assert progress.items_completed == 0
    assert progress.items_total == 0

    progress.update(stage="ANALYZING", items_completed=5, items_total=20, message="Analyzing post 5/20")
    assert progress.stage == "ANALYZING"
    assert progress.items_completed == 5
    assert progress.items_total == 20
    assert progress.message == "Analyzing post 5/20"


def test_job_progress_elapsed():
    """JobProgress reports elapsed seconds since creation."""
    from signalstream.jobs.state import JobProgress

    progress = JobProgress()
    time.sleep(0.05)
    assert progress.elapsed_seconds >= 0.04


def test_job_progress_to_dict():
    """JobProgress serializes to a status dict for API responses."""
    from signalstream.jobs.state import JobProgress

    progress = JobProgress()
    progress.update(stage="COLLECTING", items_completed=3, items_total=10, message="Collecting...")

    d = progress.to_dict()
    assert d["stage"] == "COLLECTING"
    assert d["items_completed"] == 3
    assert d["items_total"] == 10
    assert d["message"] == "Collecting..."
    assert "elapsed_seconds" in d
```

- [ ] **Step 6.2** — Run tests, confirm FAIL (1 min)

```bash
cd "/Users/eston/Desktop/Sentiment Analysis" && python -m pytest signalstream/tests/test_jobs/test_state.py -x 2>&1 | tail -5
```

- [ ] **Step 6.3** — Implement `state.py` (4 min)

```python
# signalstream/jobs/__init__.py
"""Job pipeline orchestration and lifecycle management."""

# signalstream/jobs/state.py
"""
Job state machine, cancellation tokens, and progress reporting.

State machine:
    PENDING -> COLLECTING -> ANALYZING -> THEMING -> REPORTING -> COMPLETED
                                                               -> FAILED (from any running state)
                                                               -> CANCELLED (from any running state)
"""

from __future__ import annotations

import enum
import threading
import time
from typing import Any


class JobState(str, enum.Enum):
    """Pipeline job states."""

    PENDING = "PENDING"
    COLLECTING = "COLLECTING"
    ANALYZING = "ANALYZING"
    THEMING = "THEMING"
    REPORTING = "REPORTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


# Valid transitions: from_state -> set of allowed to_states
_TRANSITIONS: dict[JobState, set[JobState]] = {
    JobState.PENDING: {JobState.COLLECTING, JobState.FAILED},
    JobState.COLLECTING: {JobState.ANALYZING, JobState.FAILED, JobState.CANCELLED},
    JobState.ANALYZING: {JobState.THEMING, JobState.FAILED, JobState.CANCELLED},
    JobState.THEMING: {JobState.REPORTING, JobState.FAILED, JobState.CANCELLED},
    JobState.REPORTING: {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED},
    # Terminal states — no transitions out
    JobState.COMPLETED: set(),
    JobState.FAILED: set(),
    JobState.CANCELLED: set(),
}


def is_valid_transition(from_state: JobState, to_state: JobState) -> bool:
    """Check whether a state transition is allowed."""
    return to_state in _TRANSITIONS.get(from_state, set())


class CancelledError(Exception):
    """Raised by CancellationToken.check() when the job has been cancelled."""

    pass


class CancellationToken:
    """Cooperative cancellation via threading.Event.

    Pipeline stages check this token between items. When cancelled,
    stages complete their current item and exit cleanly.
    """

    def __init__(self) -> None:
        self._event = threading.Event()

    @property
    def is_cancelled(self) -> bool:
        """Check cancellation state without raising."""
        return self._event.is_set()

    def cancel(self) -> None:
        """Signal cancellation. Thread-safe."""
        self._event.set()

    def check(self) -> None:
        """Raise CancelledError if cancelled.

        Call this between items in a processing loop:

            for post in posts:
                token.check()
                process(post)
        """
        if self._event.is_set():
            raise CancelledError("Job cancelled")


class JobProgress:
    """Thread-safe progress tracker for a running job.

    Updated by pipeline stages. Read by the status API endpoint.
    Polling at GET /api/jobs/<id>/status returns this as a dict.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stage: str = ""
        self._items_completed: int = 0
        self._items_total: int = 0
        self._message: str = ""
        self._start_time: float = time.monotonic()

    @property
    def stage(self) -> str:
        with self._lock:
            return self._stage

    @property
    def items_completed(self) -> int:
        with self._lock:
            return self._items_completed

    @property
    def items_total(self) -> int:
        with self._lock:
            return self._items_total

    @property
    def message(self) -> str:
        with self._lock:
            return self._message

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self._start_time

    def update(
        self,
        stage: str | None = None,
        items_completed: int | None = None,
        items_total: int | None = None,
        message: str | None = None,
    ) -> None:
        """Update progress fields. Only provided fields are changed."""
        with self._lock:
            if stage is not None:
                self._stage = stage
            if items_completed is not None:
                self._items_completed = items_completed
            if items_total is not None:
                self._items_total = items_total
            if message is not None:
                self._message = message

    def to_dict(self) -> dict[str, Any]:
        """Serialize for the status API response."""
        with self._lock:
            return {
                "stage": self._stage,
                "items_completed": self._items_completed,
                "items_total": self._items_total,
                "message": self._message,
                "elapsed_seconds": round(self.elapsed_seconds, 1),
            }
```

- [ ] **Step 6.4** — Run tests, confirm all PASS (1 min)

```bash
cd "/Users/eston/Desktop/Sentiment Analysis" && python -m pytest signalstream/tests/test_jobs/test_state.py -v 2>&1 | tail -15
```

- [ ] **Step 6.5** — Commit (1 min)

```bash
cd "/Users/eston/Desktop/Sentiment Analysis" && git add signalstream/jobs/__init__.py signalstream/jobs/state.py signalstream/tests/test_jobs/__init__.py signalstream/tests/test_jobs/test_state.py && git commit -m "feat(jobs): add job state machine, CancellationToken, and progress tracking"
```

---

## Task 7: Pipeline Stage Tasks — `signalstream/jobs/tasks.py`

**Files:**
- Create: `signalstream/jobs/tasks.py`
- Create: `signalstream/tests/test_jobs/test_tasks.py`

**Why:** Each pipeline stage needs a wrapper that handles errors, translates them to user-facing messages (using the error taxonomy from spec Section 7), reports progress, and respects cancellation. These are the building blocks that `pipeline.py` sequences.

### Steps

- [ ] **Step 7.1** — Write tests for stage task wrappers (5 min)

```python
# signalstream/tests/test_jobs/test_tasks.py
"""Tests for pipeline stage task wrappers with error handling."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from signalstream.jobs.state import CancellationToken, JobProgress, CancelledError


def test_collect_task_returns_posts():
    """collect_task calls the collector and returns posts."""
    from signalstream.jobs.tasks import collect_task

    mock_collector = MagicMock(return_value=[{"id": "1"}, {"id": "2"}])
    progress = JobProgress()
    token = CancellationToken()

    result = collect_task(
        collector_fn=mock_collector,
        phrases=["test"],
        time_range="week",
        max_posts=50,
        progress=progress,
        cancellation_token=token,
    )

    assert len(result) == 2
    mock_collector.assert_called_once()


def test_collect_task_empty_raises():
    """collect_task raises TaskError with COLLECTOR_EMPTY when no posts found."""
    from signalstream.jobs.tasks import collect_task, TaskError

    mock_collector = MagicMock(return_value=[])
    progress = JobProgress()
    token = CancellationToken()

    with pytest.raises(TaskError) as exc_info:
        collect_task(
            collector_fn=mock_collector,
            phrases=["obscure-topic"],
            time_range="week",
            max_posts=50,
            progress=progress,
            cancellation_token=token,
        )
    assert exc_info.value.error_code == "COLLECTOR_EMPTY"


def test_collect_task_cancelled():
    """collect_task respects cancellation token."""
    from signalstream.jobs.tasks import collect_task

    mock_collector = MagicMock(return_value=[{"id": "1"}])
    progress = JobProgress()
    token = CancellationToken()
    token.cancel()

    with pytest.raises(CancelledError):
        collect_task(
            collector_fn=mock_collector,
            phrases=["test"],
            time_range="week",
            max_posts=50,
            progress=progress,
            cancellation_token=token,
        )


def test_analyze_task_returns_results():
    """analyze_task calls the analyzer and returns results."""
    from signalstream.jobs.tasks import analyze_task

    posts = [MagicMock(), MagicMock(), MagicMock()]
    analyzed = [MagicMock(), MagicMock()]
    mock_analyzer = MagicMock(return_value=(analyzed, 1))  # 1 skipped

    progress = JobProgress()
    token = CancellationToken()
    mock_provider = MagicMock()

    result_posts, skipped = analyze_task(
        analyzer_fn=mock_analyzer,
        posts=posts,
        provider=mock_provider,
        progress=progress,
        cancellation_token=token,
    )

    assert len(result_posts) == 2
    assert skipped == 1


def test_analyze_task_provider_error():
    """analyze_task wraps provider errors into TaskError."""
    from signalstream.jobs.tasks import analyze_task, TaskError

    mock_analyzer = MagicMock(side_effect=ConnectionError("refused"))
    progress = JobProgress()
    token = CancellationToken()

    with pytest.raises(TaskError) as exc_info:
        analyze_task(
            analyzer_fn=mock_analyzer,
            posts=[MagicMock()],
            provider=MagicMock(),
            progress=progress,
            cancellation_token=token,
        )
    assert exc_info.value.error_code == "PROVIDER_UNREACHABLE"


def test_theme_task_returns_themes():
    """theme_task calls the thematic analyzer and returns themes."""
    from signalstream.jobs.tasks import theme_task

    mock_thematic = MagicMock(return_value={"themes": [{"name": "Quality"}]})
    progress = JobProgress()
    token = CancellationToken()

    result = theme_task(
        thematic_fn=mock_thematic,
        analyzed_posts=[MagicMock()],
        provider=MagicMock(),
        phrase="test query",
        progress=progress,
        cancellation_token=token,
    )

    assert "themes" in result
    mock_thematic.assert_called_once()


def test_report_task_returns_content():
    """report_task assembles report content via the builder."""
    from signalstream.jobs.tasks import report_task
    from signalstream.reports.builder import ReportContent

    progress = JobProgress()
    token = CancellationToken()

    result = report_task(
        job_id="task-test-001",
        topic="test",
        phrases=["test"],
        analyzed_posts=[
            {
                "post": {"id": "1", "community": "r/test", "engagement": 5},
                "analysis": {"sentiment": "positive", "emotion": "joy", "confidence": 0.9,
                             "key_point": "Good", "sarcasm_detected": False},
            },
        ],
        themes=[],
        skipped_count=0,
        progress=progress,
        cancellation_token=token,
    )

    assert isinstance(result, ReportContent)
    assert result.job_id == "task-test-001"


def test_task_error_has_user_message():
    """TaskError includes both an error_code and a user-facing message."""
    from signalstream.jobs.tasks import TaskError

    err = TaskError(
        error_code="PROVIDER_AUTH_FAILED",
        message="Your Claude API key appears to be invalid or expired.",
    )
    assert err.error_code == "PROVIDER_AUTH_FAILED"
    assert "invalid or expired" in str(err)
```

- [ ] **Step 7.2** — Run tests, confirm FAIL (1 min)

```bash
cd "/Users/eston/Desktop/Sentiment Analysis" && python -m pytest signalstream/tests/test_jobs/test_tasks.py -x 2>&1 | tail -5
```

- [ ] **Step 7.3** — Implement `tasks.py` (5 min)

```python
# signalstream/jobs/tasks.py
"""
Per-stage task wrappers with error handling and progress reporting.

Each task wraps a pipeline stage (collection, analysis, theming, reporting)
with:
- Cancellation token checks
- Error translation to user-facing messages (error taxonomy, spec Section 7)
- Progress updates

These are the building blocks that pipeline.py sequences.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from signalstream.jobs.state import CancellationToken, CancelledError, JobProgress
from signalstream.reports.builder import ReportContent, build_report_content

logger = logging.getLogger(__name__)


class TaskError(Exception):
    """Structured error from a pipeline stage.

    Carries an error_code (from the error taxonomy) and a user-facing message.
    """

    def __init__(self, error_code: str, message: str) -> None:
        self.error_code = error_code
        super().__init__(message)


# -- Error classification helpers ---------------------------------------------

_CONNECTION_ERRORS = (ConnectionError, ConnectionRefusedError, ConnectionResetError, TimeoutError, OSError)


def _classify_provider_error(exc: Exception) -> tuple[str, str]:
    """Map a provider exception to (error_code, user_message)."""
    msg = str(exc).lower()

    if isinstance(exc, _CONNECTION_ERRORS) or "refused" in msg or "unreachable" in msg:
        return ("PROVIDER_UNREACHABLE", "Could not reach the LLM provider. Check your internet connection.")

    if "401" in msg or "403" in msg or "auth" in msg or "invalid" in msg or "expired" in msg:
        return ("PROVIDER_AUTH_FAILED", "Your API key appears to be invalid or expired.")

    if "429" in msg or "rate" in msg:
        return ("PROVIDER_RATE_LIMITED", "Rate limited by the LLM provider. Retrying...")

    if "context" in msg or "token" in msg and "too" in msg:
        return ("PROVIDER_CONTEXT_EXCEEDED", "Content too large for the model. Try fewer posts.")

    return ("PROVIDER_UNREACHABLE", f"LLM provider error: {exc}")


def _classify_collector_error(exc: Exception) -> tuple[str, str]:
    """Map a collector exception to (error_code, user_message)."""
    msg = str(exc).lower()

    if "429" in msg or "rate" in msg:
        return ("COLLECTOR_RATE_LIMITED", "Reddit is rate-limiting requests. Waiting...")

    if "403" in msg or "blocked" in msg:
        return ("COLLECTOR_BLOCKED", "Reddit is not responding. Try again in a few minutes.")

    return ("COLLECTOR_BLOCKED", f"Collection error: {exc}")


# -- Stage tasks --------------------------------------------------------------


def collect_task(
    collector_fn: Callable[..., list],
    phrases: list[str],
    time_range: str,
    max_posts: int,
    progress: JobProgress,
    cancellation_token: CancellationToken,
    **collector_kwargs: Any,
) -> list:
    """Run the collection stage.

    Args:
        collector_fn: The collector function (e.g. collect_reddit_posts).
        phrases: Search phrases.
        time_range: Time range for collection (e.g. "week", "month").
        max_posts: Maximum posts to collect.
        progress: Progress tracker for status updates.
        cancellation_token: Cooperative cancellation.
        **collector_kwargs: Additional kwargs passed to the collector.

    Returns:
        List of collected posts.

    Raises:
        CancelledError: If the cancellation token is set.
        TaskError: With COLLECTOR_EMPTY if no posts found, or other collector errors.
    """
    cancellation_token.check()
    progress.update(stage="COLLECTING", items_completed=0, items_total=0, message="Starting collection...")

    try:
        posts = collector_fn(
            phrases=phrases,
            time_range=time_range,
            max_posts=max_posts,
            **collector_kwargs,
        )
    except CancelledError:
        raise
    except Exception as exc:
        code, msg = _classify_collector_error(exc)
        raise TaskError(code, msg) from exc

    if not posts:
        raise TaskError(
            "COLLECTOR_EMPTY",
            f"No posts found for '{', '.join(phrases)}'. Try broader search terms or a longer time range.",
        )

    progress.update(
        items_completed=len(posts),
        items_total=len(posts),
        message=f"Collected {len(posts)} posts",
    )
    logger.info("Collection complete: %d posts", len(posts))
    return posts


def analyze_task(
    analyzer_fn: Callable[..., tuple[list, int]],
    posts: list,
    provider: Any,
    progress: JobProgress,
    cancellation_token: CancellationToken,
) -> tuple[list, int]:
    """Run the sentiment analysis stage.

    Args:
        analyzer_fn: The analyzer function (e.g. analyze_posts).
        posts: List of Post objects from the collector.
        provider: LLM provider instance.
        progress: Progress tracker.
        cancellation_token: Cooperative cancellation.

    Returns:
        Tuple of (analyzed_posts, skipped_count).

    Raises:
        CancelledError: If the cancellation token is set.
        TaskError: With provider or analysis error codes.
    """
    cancellation_token.check()
    progress.update(stage="ANALYZING", items_completed=0, items_total=len(posts), message="Starting analysis...")

    def _progress_callback(completed: int, total: int, current_id: str = "") -> None:
        progress.update(
            items_completed=completed,
            items_total=total,
            message=f"Analyzing post {completed}/{total}",
        )

    try:
        analyzed_posts, skipped = analyzer_fn(
            posts=posts,
            provider=provider,
            progress_callback=_progress_callback,
            cancellation_token=cancellation_token,
        )
    except CancelledError:
        raise
    except Exception as exc:
        code, msg = _classify_provider_error(exc)
        raise TaskError(code, msg) from exc

    if skipped > 0:
        logger.warning("Analysis partial: %d of %d posts skipped", skipped, len(posts))

    progress.update(
        items_completed=len(analyzed_posts),
        message=f"Analysis complete ({len(analyzed_posts)} of {len(posts)} posts)",
    )
    return analyzed_posts, skipped


def theme_task(
    thematic_fn: Callable[..., Any],
    analyzed_posts: list,
    provider: Any,
    phrase: str,
    progress: JobProgress,
    cancellation_token: CancellationToken,
) -> Any:
    """Run the thematic analysis stage.

    Args:
        thematic_fn: The thematic analyzer function (e.g. extract_themes).
        analyzed_posts: List of AnalyzedPost from the analysis stage.
        provider: LLM provider instance.
        phrase: Primary search phrase for context.
        progress: Progress tracker.
        cancellation_token: Cooperative cancellation.

    Returns:
        ThematicResult (or dict with themes).

    Raises:
        CancelledError: If the cancellation token is set.
        TaskError: With provider or analysis error codes.
    """
    cancellation_token.check()
    progress.update(stage="THEMING", items_completed=0, items_total=1, message="Extracting themes...")

    try:
        result = thematic_fn(
            posts=analyzed_posts,
            provider=provider,
            phrase=phrase,
        )
    except CancelledError:
        raise
    except Exception as exc:
        code, msg = _classify_provider_error(exc)
        raise TaskError(code, msg) from exc

    progress.update(items_completed=1, message="Theme extraction complete")
    return result


def report_task(
    job_id: str,
    topic: str,
    phrases: list[str],
    analyzed_posts: list[dict],
    themes: list[dict],
    skipped_count: int,
    progress: JobProgress,
    cancellation_token: CancellationToken,
    branding_footer: bool = True,
) -> ReportContent:
    """Run the report generation stage.

    Assembles report content (statistics, charts, executive snapshot)
    via the builder. Does not render to PDF — that happens on download.

    Args:
        job_id: Unique job identifier.
        topic: The analysis topic.
        phrases: Search phrases used.
        analyzed_posts: List of analyzed post dicts.
        themes: List of theme dicts.
        skipped_count: Number of skipped posts.
        progress: Progress tracker.
        cancellation_token: Cooperative cancellation.
        branding_footer: Whether to include branding.

    Returns:
        ReportContent dataclass.

    Raises:
        CancelledError: If the cancellation token is set.
        TaskError: On report generation failure.
    """
    cancellation_token.check()
    progress.update(stage="REPORTING", items_completed=0, items_total=1, message="Generating report...")

    try:
        content = build_report_content(
            job_id=job_id,
            topic=topic,
            phrases=phrases,
            analyzed_posts=analyzed_posts,
            themes=themes,
            skipped_count=skipped_count,
            branding_footer=branding_footer,
        )
    except Exception as exc:
        raise TaskError("REPORT_GENERATION_FAILED", f"Failed to generate report: {exc}") from exc

    progress.update(items_completed=1, message="Report ready")
    return content
```

- [ ] **Step 7.4** — Run tests, confirm all PASS (2 min)

```bash
cd "/Users/eston/Desktop/Sentiment Analysis" && python -m pytest signalstream/tests/test_jobs/test_tasks.py -v 2>&1 | tail -15
```

- [ ] **Step 7.5** — Commit (1 min)

```bash
cd "/Users/eston/Desktop/Sentiment Analysis" && git add signalstream/jobs/tasks.py signalstream/tests/test_jobs/test_tasks.py && git commit -m "feat(jobs): add pipeline stage task wrappers with error taxonomy and cancellation"
```

---

## Task 8: Pipeline Orchestration — `signalstream/jobs/pipeline.py`

**Files:**
- Create: `signalstream/jobs/pipeline.py`
- Create: `signalstream/tests/test_jobs/test_pipeline.py`

**Why:** The pipeline sequences the four stages (collect, analyze, theme, report) with state transitions, checkpointing, and structured error capture. This is the core orchestration that ties the entire analysis flow together.

### Steps

- [ ] **Step 8.1** — Write tests for pipeline execution and state transitions (5 min)

```python
# signalstream/tests/test_jobs/test_pipeline.py
"""Tests for pipeline orchestration — stage sequencing, checkpointing, error handling."""

from __future__ import annotations

from unittest.mock import MagicMock, patch, call
from dataclasses import dataclass

import pytest

from signalstream.jobs.state import CancellationToken, JobProgress, JobState, CancelledError


@dataclass
class _FakePost:
    id: str
    community: str = "r/test"


@dataclass
class _FakeAnalyzedPost:
    post: _FakePost
    analysis: dict


def _make_pipeline_config():
    """Build a minimal PipelineConfig for testing."""
    from signalstream.jobs.pipeline import PipelineConfig

    return PipelineConfig(
        job_id="pipe-001",
        topic="test topic",
        phrases=["test"],
        time_range="week",
        max_posts=50,
    )


def _mock_stages():
    """Create mocked stage functions that return realistic data."""
    collected = [_FakePost(id="1"), _FakePost(id="2"), _FakePost(id="3")]
    analyzed = [
        {"post": {"id": "1", "community": "r/test"}, "analysis": {"sentiment": "positive", "emotion": "joy", "confidence": 0.9, "key_point": "Good", "sarcasm_detected": False}},
        {"post": {"id": "2", "community": "r/test"}, "analysis": {"sentiment": "negative", "emotion": "anger", "confidence": 0.8, "key_point": "Bad", "sarcasm_detected": False}},
    ]
    themes = [{"name": "Quality", "description": "Desc", "percentage": 50.0, "post_count": 1, "sentiment_skew": "positive", "representative_quotes": []}]

    collector_fn = MagicMock(return_value=collected)
    analyzer_fn = MagicMock(return_value=(analyzed, 1))
    thematic_fn = MagicMock(return_value={"themes": themes})

    return collector_fn, analyzer_fn, thematic_fn, analyzed, themes


def test_pipeline_happy_path():
    """Full pipeline runs all 4 stages and returns COMPLETED."""
    from signalstream.jobs.pipeline import run_pipeline, PipelineConfig, PipelineResult

    config = _make_pipeline_config()
    collector_fn, analyzer_fn, thematic_fn, _, _ = _mock_stages()
    provider = MagicMock()
    token = CancellationToken()
    progress = JobProgress()

    result = run_pipeline(
        config=config,
        provider=provider,
        collector_fn=collector_fn,
        analyzer_fn=analyzer_fn,
        thematic_fn=thematic_fn,
        cancellation_token=token,
        progress=progress,
    )

    assert isinstance(result, PipelineResult)
    assert result.final_state == JobState.COMPLETED
    assert result.report_content is not None
    assert result.error is None
    collector_fn.assert_called_once()
    analyzer_fn.assert_called_once()
    thematic_fn.assert_called_once()


def test_pipeline_collection_failure():
    """Pipeline fails at collection stage with structured error."""
    from signalstream.jobs.pipeline import run_pipeline, PipelineResult
    from signalstream.jobs.tasks import TaskError

    config = _make_pipeline_config()
    collector_fn = MagicMock(return_value=[])  # Empty = COLLECTOR_EMPTY
    provider = MagicMock()
    token = CancellationToken()
    progress = JobProgress()

    result = run_pipeline(
        config=config,
        provider=provider,
        collector_fn=collector_fn,
        analyzer_fn=MagicMock(),
        thematic_fn=MagicMock(),
        cancellation_token=token,
        progress=progress,
    )

    assert result.final_state == JobState.FAILED
    assert result.error_code == "COLLECTOR_EMPTY"
    assert result.report_content is None


def test_pipeline_analysis_failure():
    """Pipeline fails at analysis stage, collection results are preserved."""
    from signalstream.jobs.pipeline import run_pipeline

    config = _make_pipeline_config()
    collector_fn = MagicMock(return_value=[_FakePost(id="1")])
    analyzer_fn = MagicMock(side_effect=ConnectionError("refused"))
    provider = MagicMock()
    token = CancellationToken()
    progress = JobProgress()

    result = run_pipeline(
        config=config,
        provider=provider,
        collector_fn=collector_fn,
        analyzer_fn=analyzer_fn,
        thematic_fn=MagicMock(),
        cancellation_token=token,
        progress=progress,
    )

    assert result.final_state == JobState.FAILED
    assert result.failed_stage == "ANALYZING"


def test_pipeline_cancellation_mid_analysis():
    """Pipeline cancellation preserves partial results."""
    from signalstream.jobs.pipeline import run_pipeline

    config = _make_pipeline_config()
    collector_fn = MagicMock(return_value=[_FakePost(id="1")])

    def _cancel_analyzer(**kwargs):
        raise CancelledError("Job cancelled")

    provider = MagicMock()
    token = CancellationToken()
    progress = JobProgress()

    result = run_pipeline(
        config=config,
        provider=provider,
        collector_fn=collector_fn,
        analyzer_fn=_cancel_analyzer,
        thematic_fn=MagicMock(),
        cancellation_token=token,
        progress=progress,
    )

    assert result.final_state == JobState.CANCELLED


def test_pipeline_state_callback():
    """Pipeline calls state_callback on each state transition."""
    from signalstream.jobs.pipeline import run_pipeline

    config = _make_pipeline_config()
    collector_fn, analyzer_fn, thematic_fn, _, _ = _mock_stages()
    provider = MagicMock()
    token = CancellationToken()
    progress = JobProgress()
    state_changes: list[str] = []

    def on_state_change(job_id: str, new_state: str, **kwargs):
        state_changes.append(new_state)

    result = run_pipeline(
        config=config,
        provider=provider,
        collector_fn=collector_fn,
        analyzer_fn=analyzer_fn,
        thematic_fn=thematic_fn,
        cancellation_token=token,
        progress=progress,
        state_callback=on_state_change,
    )

    # Should see: COLLECTING, ANALYZING, THEMING, REPORTING, COMPLETED
    assert "COLLECTING" in state_changes
    assert "ANALYZING" in state_changes
    assert "THEMING" in state_changes
    assert "REPORTING" in state_changes
    assert "COMPLETED" in state_changes
```

- [ ] **Step 8.2** — Run tests, confirm FAIL (1 min)

```bash
cd "/Users/eston/Desktop/Sentiment Analysis" && python -m pytest signalstream/tests/test_jobs/test_pipeline.py -x 2>&1 | tail -5
```

- [ ] **Step 8.3** — Implement `pipeline.py` (5 min)

```python
# signalstream/jobs/pipeline.py
"""
Pipeline orchestration — stage sequencing with state transitions and error capture.

Sequences: COLLECTING -> ANALYZING -> THEMING -> REPORTING -> COMPLETED

Each stage is wrapped by tasks.py for error handling and progress reporting.
The pipeline drives state transitions and captures structured errors on failure.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from signalstream.jobs.state import (
    CancellationToken,
    CancelledError,
    JobProgress,
    JobState,
)
from signalstream.jobs.tasks import (
    TaskError,
    analyze_task,
    collect_task,
    report_task,
    theme_task,
)
from signalstream.reports.builder import ReportContent

logger = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    """Configuration for a pipeline run."""

    job_id: str
    topic: str
    phrases: list[str]
    time_range: str = "week"
    max_posts: int = 100
    branding_footer: bool = True


@dataclass
class PipelineResult:
    """Result of a pipeline run — success or failure."""

    final_state: JobState
    report_content: ReportContent | None = None
    error: str | None = None
    error_code: str | None = None
    failed_stage: str | None = None
    collected_posts: list | None = None
    analyzed_posts: list | None = None
    skipped_count: int = 0


def run_pipeline(
    config: PipelineConfig,
    provider: Any,
    collector_fn: Callable,
    analyzer_fn: Callable,
    thematic_fn: Callable,
    cancellation_token: CancellationToken,
    progress: JobProgress,
    state_callback: Callable[..., None] | None = None,
) -> PipelineResult:
    """Execute the full analysis pipeline.

    Sequences four stages:
    1. COLLECTING — fetch posts from social platforms
    2. ANALYZING — per-post sentiment analysis via LLM
    3. THEMING — cross-post thematic extraction via LLM
    4. REPORTING — assemble report content with charts

    On failure, captures the error code, message, and which stage failed.
    On cancellation, returns CANCELLED state with any partial results.

    Args:
        config: Pipeline configuration (job_id, topic, phrases, etc.).
        provider: LLM provider instance (from Plan 1).
        collector_fn: Data collection function.
        analyzer_fn: Sentiment analysis function.
        thematic_fn: Thematic analysis function.
        cancellation_token: Cooperative cancellation token.
        progress: Progress tracker for status API.
        state_callback: Optional callback called on each state transition.
            Signature: callback(job_id, new_state, **kwargs)

    Returns:
        PipelineResult with final state, report content (if completed),
        or error details (if failed).
    """
    collected_posts: list = []
    analyzed_posts: list = []
    skipped_count: int = 0
    themes: list = []

    def _transition(new_state: JobState, **kwargs: Any) -> None:
        """Report a state transition."""
        if state_callback:
            try:
                state_callback(config.job_id, new_state.value, **kwargs)
            except Exception:
                logger.exception("State callback error (non-fatal)")

    try:
        # -- Stage 1: Collection ------------------------------------------
        _transition(JobState.COLLECTING)
        collected_posts = collect_task(
            collector_fn=collector_fn,
            phrases=config.phrases,
            time_range=config.time_range,
            max_posts=config.max_posts,
            progress=progress,
            cancellation_token=cancellation_token,
        )

        # -- Stage 2: Analysis --------------------------------------------
        _transition(JobState.ANALYZING)
        analyzed_posts, skipped_count = analyze_task(
            analyzer_fn=analyzer_fn,
            posts=collected_posts,
            provider=provider,
            progress=progress,
            cancellation_token=cancellation_token,
        )

        # -- Stage 3: Thematic extraction ---------------------------------
        _transition(JobState.THEMING)
        thematic_result = theme_task(
            thematic_fn=thematic_fn,
            analyzed_posts=analyzed_posts,
            provider=provider,
            phrase=config.phrases[0] if config.phrases else config.topic,
            progress=progress,
            cancellation_token=cancellation_token,
        )

        # Normalize thematic result — may be a dict or object
        if isinstance(thematic_result, dict):
            themes = thematic_result.get("themes", [])
        elif hasattr(thematic_result, "themes"):
            themes = thematic_result.themes
        else:
            themes = []

        # -- Stage 4: Report generation -----------------------------------
        _transition(JobState.REPORTING)
        report_content = report_task(
            job_id=config.job_id,
            topic=config.topic,
            phrases=config.phrases,
            analyzed_posts=analyzed_posts,
            themes=themes,
            skipped_count=skipped_count,
            progress=progress,
            cancellation_token=cancellation_token,
            branding_footer=config.branding_footer,
        )

        # -- Success -------------------------------------------------------
        _transition(JobState.COMPLETED)
        return PipelineResult(
            final_state=JobState.COMPLETED,
            report_content=report_content,
            collected_posts=collected_posts,
            analyzed_posts=analyzed_posts,
            skipped_count=skipped_count,
        )

    except CancelledError:
        _transition(JobState.CANCELLED)
        logger.info("Pipeline cancelled for job %s", config.job_id)
        return PipelineResult(
            final_state=JobState.CANCELLED,
            collected_posts=collected_posts if collected_posts else None,
            analyzed_posts=analyzed_posts if analyzed_posts else None,
            skipped_count=skipped_count,
        )

    except TaskError as exc:
        failed_stage = progress.stage or "UNKNOWN"
        _transition(JobState.FAILED, error_code=exc.error_code, error=str(exc))
        logger.error("Pipeline failed at %s: [%s] %s", failed_stage, exc.error_code, exc)
        return PipelineResult(
            final_state=JobState.FAILED,
            error=str(exc),
            error_code=exc.error_code,
            failed_stage=failed_stage,
            collected_posts=collected_posts if collected_posts else None,
            analyzed_posts=analyzed_posts if analyzed_posts else None,
            skipped_count=skipped_count,
        )

    except Exception as exc:
        failed_stage = progress.stage or "UNKNOWN"
        _transition(JobState.FAILED, error_code="INTERNAL_ERROR", error=str(exc))
        logger.exception("Unexpected pipeline error at %s", failed_stage)
        return PipelineResult(
            final_state=JobState.FAILED,
            error=f"Unexpected error: {exc}",
            error_code="INTERNAL_ERROR",
            failed_stage=failed_stage,
            collected_posts=collected_posts if collected_posts else None,
            analyzed_posts=analyzed_posts if analyzed_posts else None,
            skipped_count=skipped_count,
        )
```

- [ ] **Step 8.4** — Run tests, confirm all PASS (2 min)

```bash
cd "/Users/eston/Desktop/Sentiment Analysis" && python -m pytest signalstream/tests/test_jobs/test_pipeline.py -v 2>&1 | tail -15
```

- [ ] **Step 8.5** — Commit (1 min)

```bash
cd "/Users/eston/Desktop/Sentiment Analysis" && git add signalstream/jobs/pipeline.py signalstream/tests/test_jobs/test_pipeline.py && git commit -m "feat(jobs): add pipeline orchestration with state transitions and error capture"
```

---

## Task 9: Job Manager — `signalstream/jobs/manager.py`

**Files:**
- Create: `signalstream/jobs/manager.py`
- Create: `signalstream/tests/test_jobs/test_manager.py`

**Why:** The job manager is the top-level entry point for the web layer. It manages a thread pool (max 2 concurrent jobs), handles submit/cancel/status, persists job metadata to the DB, and implements graceful shutdown on SIGTERM/SIGINT.

### Steps

- [ ] **Step 9.1** — Write tests for job submission, status, and cancellation (5 min)

```python
# signalstream/tests/test_jobs/test_manager.py
"""Tests for the job manager — thread pool, submit/cancel/status, shutdown."""

from __future__ import annotations

import time
import threading
from unittest.mock import MagicMock, patch

import pytest

from signalstream.jobs.state import JobState


def _make_mock_db():
    """Create a mock DB repository."""
    db = MagicMock()
    db.save_job = MagicMock()
    db.update_job_status = MagicMock()
    db.get_job = MagicMock(return_value=None)
    db.save_job_statistics = MagicMock()
    return db


def _slow_collector(**kwargs):
    """Collector that takes a moment to run."""
    time.sleep(0.1)
    return [{"id": "1"}, {"id": "2"}]


def _fast_analyzer(**kwargs):
    """Analyzer that returns instantly."""
    return ([{"post": {"id": "1", "community": "r/test"}, "analysis": {"sentiment": "positive", "emotion": "joy", "confidence": 0.9, "key_point": "Ok", "sarcasm_detected": False}}], 0)


def _fast_thematic(**kwargs):
    """Thematic analyzer that returns instantly."""
    return {"themes": []}


def test_submit_job():
    """submit_job returns a job_id and the job starts running."""
    from signalstream.jobs.manager import JobManager

    db = _make_mock_db()
    manager = JobManager(db=db, max_workers=2)

    try:
        job_id = manager.submit_job(
            topic="test",
            phrases=["test"],
            time_range="week",
            max_posts=10,
            provider=MagicMock(),
            collector_fn=_slow_collector,
            analyzer_fn=_fast_analyzer,
            thematic_fn=_fast_thematic,
        )

        assert isinstance(job_id, str)
        assert len(job_id) > 0

        # Job should have a status
        status = manager.get_status(job_id)
        assert status is not None
    finally:
        manager.shutdown(wait=True, timeout=5)


def test_get_status_returns_progress():
    """get_status returns a dict with stage, items, message, elapsed."""
    from signalstream.jobs.manager import JobManager

    db = _make_mock_db()
    manager = JobManager(db=db, max_workers=2)

    try:
        job_id = manager.submit_job(
            topic="test",
            phrases=["test"],
            time_range="week",
            max_posts=10,
            provider=MagicMock(),
            collector_fn=_slow_collector,
            analyzer_fn=_fast_analyzer,
            thematic_fn=_fast_thematic,
        )

        status = manager.get_status(job_id)
        assert "stage" in status
        assert "items_completed" in status
        assert "items_total" in status
        assert "elapsed_seconds" in status
        assert "state" in status
    finally:
        manager.shutdown(wait=True, timeout=5)


def test_get_status_unknown_job():
    """get_status returns None for unknown job_id."""
    from signalstream.jobs.manager import JobManager

    db = _make_mock_db()
    manager = JobManager(db=db, max_workers=2)

    try:
        assert manager.get_status("nonexistent-id") is None
    finally:
        manager.shutdown(wait=True, timeout=5)


def test_cancel_job():
    """cancel_job sets the cancellation token for a running job."""
    from signalstream.jobs.manager import JobManager

    db = _make_mock_db()
    manager = JobManager(db=db, max_workers=2)

    def _blocking_collector(**kwargs):
        time.sleep(10)
        return []

    try:
        job_id = manager.submit_job(
            topic="test",
            phrases=["test"],
            time_range="week",
            max_posts=10,
            provider=MagicMock(),
            collector_fn=_blocking_collector,
            analyzer_fn=_fast_analyzer,
            thematic_fn=_fast_thematic,
        )

        time.sleep(0.05)
        cancelled = manager.cancel_job(job_id)
        assert cancelled is True
    finally:
        manager.shutdown(wait=True, timeout=5)


def test_cancel_unknown_job():
    """cancel_job returns False for unknown job_id."""
    from signalstream.jobs.manager import JobManager

    db = _make_mock_db()
    manager = JobManager(db=db, max_workers=2)

    try:
        assert manager.cancel_job("nonexistent") is False
    finally:
        manager.shutdown(wait=True, timeout=5)


def test_max_workers_limit():
    """Only max_workers jobs can run concurrently."""
    from signalstream.jobs.manager import JobManager

    db = _make_mock_db()
    manager = JobManager(db=db, max_workers=1)

    started = threading.Event()
    block = threading.Event()

    def _blocking_collector(**kwargs):
        started.set()
        block.wait(timeout=5)
        return [{"id": "1"}]

    try:
        # First job — should start immediately
        job1 = manager.submit_job(
            topic="test1", phrases=["t"], time_range="week", max_posts=5,
            provider=MagicMock(), collector_fn=_blocking_collector,
            analyzer_fn=_fast_analyzer, thematic_fn=_fast_thematic,
        )
        started.wait(timeout=2)

        # Second job — should be queued (only 1 worker)
        job2 = manager.submit_job(
            topic="test2", phrases=["t"], time_range="week", max_posts=5,
            provider=MagicMock(), collector_fn=lambda **kw: [{"id": "2"}],
            analyzer_fn=_fast_analyzer, thematic_fn=_fast_thematic,
        )

        status2 = manager.get_status(job2)
        # Job 2 should be pending while job 1 is blocking the single worker
        assert status2["state"] in ("PENDING", "COLLECTING")

        block.set()  # Unblock first job
    finally:
        manager.shutdown(wait=True, timeout=5)


def test_shutdown_graceful():
    """shutdown() completes or cancels running jobs and prevents new submissions."""
    from signalstream.jobs.manager import JobManager

    db = _make_mock_db()
    manager = JobManager(db=db, max_workers=2)

    try:
        job_id = manager.submit_job(
            topic="test", phrases=["test"], time_range="week", max_posts=10,
            provider=MagicMock(), collector_fn=_slow_collector,
            analyzer_fn=_fast_analyzer, thematic_fn=_fast_thematic,
        )
    finally:
        manager.shutdown(wait=True, timeout=5)

    # After shutdown, new submissions should be rejected
    with pytest.raises(RuntimeError, match="shutdown"):
        manager.submit_job(
            topic="too late", phrases=["test"], time_range="week", max_posts=10,
            provider=MagicMock(), collector_fn=_slow_collector,
            analyzer_fn=_fast_analyzer, thematic_fn=_fast_thematic,
        )


def test_job_completes_with_result():
    """A completed job has its result stored and accessible."""
    from signalstream.jobs.manager import JobManager

    db = _make_mock_db()
    manager = JobManager(db=db, max_workers=2)

    def _instant_collector(**kwargs):
        return [{"id": "1"}]

    try:
        job_id = manager.submit_job(
            topic="test", phrases=["test"], time_range="week", max_posts=10,
            provider=MagicMock(), collector_fn=_instant_collector,
            analyzer_fn=_fast_analyzer, thematic_fn=_fast_thematic,
        )

        # Wait for completion
        for _ in range(50):
            status = manager.get_status(job_id)
            if status and status["state"] in ("COMPLETED", "FAILED"):
                break
            time.sleep(0.1)

        result = manager.get_result(job_id)
        assert result is not None
    finally:
        manager.shutdown(wait=True, timeout=5)
```

- [ ] **Step 9.2** — Run tests, confirm FAIL (1 min)

```bash
cd "/Users/eston/Desktop/Sentiment Analysis" && python -m pytest signalstream/tests/test_jobs/test_manager.py -x 2>&1 | tail -5
```

- [ ] **Step 9.3** — Implement `manager.py` (5 min)

```python
# signalstream/jobs/manager.py
"""
Job manager — thread pool, submit/cancel/status, graceful shutdown.

Manages the lifecycle of analysis jobs. Each job runs in a thread from
a bounded pool (max 2 by default). The manager persists job metadata
to the database and provides status/cancel/result APIs for the web layer.

Graceful shutdown:
    SIGTERM/SIGINT -> (1) stop accepting new jobs, (2) set cancellation tokens,
    (3) wait up to 30s for checkpoints, (4) persist partial results,
    (5) close DB, (6) exit.
"""

from __future__ import annotations

import logging
import signal
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable

from signalstream.jobs.pipeline import PipelineConfig, PipelineResult, run_pipeline
from signalstream.jobs.state import CancellationToken, JobProgress, JobState

logger = logging.getLogger(__name__)


class _JobEntry:
    """Internal tracking for a submitted job."""

    __slots__ = ("job_id", "config", "provider", "collector_fn", "analyzer_fn",
                 "thematic_fn", "cancellation_token", "progress", "future",
                 "result", "state")

    def __init__(
        self,
        job_id: str,
        config: PipelineConfig,
        provider: Any,
        collector_fn: Callable,
        analyzer_fn: Callable,
        thematic_fn: Callable,
    ):
        self.job_id = job_id
        self.config = config
        self.provider = provider
        self.collector_fn = collector_fn
        self.analyzer_fn = analyzer_fn
        self.thematic_fn = thematic_fn
        self.cancellation_token = CancellationToken()
        self.progress = JobProgress()
        self.future: Future | None = None
        self.result: PipelineResult | None = None
        self.state = JobState.PENDING


class JobManager:
    """Manages analysis job lifecycle with a bounded thread pool.

    Usage:
        manager = JobManager(db=db_repo, max_workers=2)
        job_id = manager.submit_job(topic=..., ...)
        status = manager.get_status(job_id)
        manager.cancel_job(job_id)
        manager.shutdown(wait=True)

    Args:
        db: Database repository instance (from Plan 1). Used for persisting
            job metadata and status. API keys are never persisted.
        max_workers: Maximum concurrent jobs. Default 2.
    """

    def __init__(self, db: Any, max_workers: int = 2) -> None:
        self._db = db
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="signalstream-job")
        self._jobs: dict[str, _JobEntry] = {}
        self._lock = threading.Lock()
        self._shutdown = False

    def submit_job(
        self,
        topic: str,
        phrases: list[str],
        time_range: str,
        max_posts: int,
        provider: Any,
        collector_fn: Callable,
        analyzer_fn: Callable,
        thematic_fn: Callable,
        branding_footer: bool = True,
    ) -> str:
        """Submit a new analysis job to the thread pool.

        Args:
            topic: Analysis topic / query.
            phrases: Search phrases for collection.
            time_range: Time range for collection (e.g. "week").
            max_posts: Maximum posts to collect.
            provider: LLM provider instance (not persisted).
            collector_fn: Collection function.
            analyzer_fn: Analysis function.
            thematic_fn: Thematic analysis function.
            branding_footer: Whether to include branding in report.

        Returns:
            Unique job ID string.

        Raises:
            RuntimeError: If the manager has been shut down.
        """
        if self._shutdown:
            raise RuntimeError("Job manager is shutdown — cannot accept new jobs")

        job_id = str(uuid.uuid4())
        config = PipelineConfig(
            job_id=job_id,
            topic=topic,
            phrases=phrases,
            time_range=time_range,
            max_posts=max_posts,
            branding_footer=branding_footer,
        )

        entry = _JobEntry(
            job_id=job_id,
            config=config,
            provider=provider,
            collector_fn=collector_fn,
            analyzer_fn=analyzer_fn,
            thematic_fn=thematic_fn,
        )

        with self._lock:
            self._jobs[job_id] = entry

        # Persist initial job metadata to DB (never credentials)
        try:
            self._db.save_job({
                "job_id": job_id,
                "topic": topic,
                "phrases": phrases,
                "status": JobState.PENDING.value,
                "time_range": time_range,
                "max_posts": max_posts,
            })
        except Exception:
            logger.exception("Failed to persist job metadata (non-fatal)")

        # Submit to thread pool
        future = self._pool.submit(self._run_job, entry)
        entry.future = future
        future.add_done_callback(lambda f: self._on_job_done(job_id, f))

        logger.info("Submitted job %s: topic='%s', phrases=%s", job_id, topic, phrases)
        return job_id

    def get_status(self, job_id: str) -> dict[str, Any] | None:
        """Get current status of a job.

        Returns:
            Status dict with keys: state, stage, items_completed, items_total,
            message, elapsed_seconds. Or None if job_id not found.
        """
        with self._lock:
            entry = self._jobs.get(job_id)

        if entry is None:
            return None

        status = entry.progress.to_dict()
        status["state"] = entry.state.value
        status["job_id"] = job_id

        # Include error info if failed
        if entry.result and entry.result.error:
            status["error"] = entry.result.error
            status["error_code"] = entry.result.error_code

        return status

    def get_result(self, job_id: str) -> PipelineResult | None:
        """Get the final result of a completed job.

        Returns:
            PipelineResult or None if job is not found or still running.
        """
        with self._lock:
            entry = self._jobs.get(job_id)

        if entry is None:
            return None
        return entry.result

    def cancel_job(self, job_id: str) -> bool:
        """Request cancellation of a running job.

        Cancellation is cooperative — the current item completes, then the
        pipeline exits cleanly.

        Returns:
            True if cancellation was requested, False if job_id not found.
        """
        with self._lock:
            entry = self._jobs.get(job_id)

        if entry is None:
            return False

        entry.cancellation_token.cancel()
        logger.info("Cancellation requested for job %s", job_id)
        return True

    def shutdown(self, wait: bool = True, timeout: int = 30) -> None:
        """Graceful shutdown — stop accepting jobs, cancel running, wait for checkpoints.

        Args:
            wait: Whether to wait for running jobs to complete.
            timeout: Maximum seconds to wait for running jobs.
        """
        self._shutdown = True
        logger.info("Job manager shutdown initiated")

        # Cancel all running jobs
        with self._lock:
            for entry in self._jobs.values():
                if entry.state not in (JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED):
                    entry.cancellation_token.cancel()

        self._pool.shutdown(wait=wait)
        logger.info("Job manager shutdown complete")

    def register_signals(self) -> None:
        """Register SIGTERM and SIGINT handlers for graceful shutdown.

        Call this from the main thread only (signal handlers must be
        registered from the main thread).
        """
        def _handler(signum: int, frame: Any) -> None:
            signame = signal.Signals(signum).name
            logger.info("Received %s — initiating graceful shutdown", signame)
            self.shutdown(wait=True, timeout=30)

        signal.signal(signal.SIGTERM, _handler)
        signal.signal(signal.SIGINT, _handler)

    # -- Internal -------------------------------------------------------------

    def _run_job(self, entry: _JobEntry) -> PipelineResult:
        """Execute a job pipeline in a worker thread."""
        entry.state = JobState.COLLECTING

        def _state_callback(job_id: str, new_state: str, **kwargs: Any) -> None:
            try:
                state = JobState(new_state)
                entry.state = state
                self._db.update_job_status(job_id, new_state, **kwargs)
            except Exception:
                logger.exception("State callback DB update failed (non-fatal)")

        result = run_pipeline(
            config=entry.config,
            provider=entry.provider,
            collector_fn=entry.collector_fn,
            analyzer_fn=entry.analyzer_fn,
            thematic_fn=entry.thematic_fn,
            cancellation_token=entry.cancellation_token,
            progress=entry.progress,
            state_callback=_state_callback,
        )

        entry.result = result
        entry.state = result.final_state
        return result

    def _on_job_done(self, job_id: str, future: Future) -> None:
        """Callback when a job future completes (success or failure)."""
        with self._lock:
            entry = self._jobs.get(job_id)

        if entry is None:
            return

        exc = future.exception()
        if exc is not None:
            logger.error("Job %s raised unexpected exception: %s", job_id, exc)
            entry.state = JobState.FAILED
            try:
                self._db.update_job_status(job_id, JobState.FAILED.value, error=str(exc))
            except Exception:
                logger.exception("Failed to update job status in DB")
        else:
            result = future.result()
            if result:
                logger.info("Job %s finished: %s", job_id, result.final_state.value)
```

- [ ] **Step 9.4** — Run tests, confirm all PASS (2 min)

```bash
cd "/Users/eston/Desktop/Sentiment Analysis" && python -m pytest signalstream/tests/test_jobs/test_manager.py -v 2>&1 | tail -20
```

- [ ] **Step 9.5** — Commit (1 min)

```bash
cd "/Users/eston/Desktop/Sentiment Analysis" && git add signalstream/jobs/manager.py signalstream/tests/test_jobs/test_manager.py && git commit -m "feat(jobs): add job manager with thread pool, cancellation, and graceful shutdown"
```

---

## Task 10: Integration Tests — Full Pipeline with Mock LLM

**Files:**
- Create: `signalstream/tests/test_jobs/test_integration.py`

**Why:** Integration tests verify the entire pipeline from submission through report generation using mock providers. This validates that all modules work together: state transitions, progress updates, chart generation, report assembly, and error handling.

### Steps

- [ ] **Step 10.1** — Write integration tests (5 min)

```python
# signalstream/tests/test_jobs/test_integration.py
"""Integration tests — full pipeline with mock LLM and collector."""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock

import pytest

from signalstream.jobs.state import JobState


def _make_mock_db():
    db = MagicMock()
    db.save_job = MagicMock()
    db.update_job_status = MagicMock()
    db.get_job = MagicMock(return_value=None)
    db.save_job_statistics = MagicMock()
    return db


def _mock_collector(phrases, time_range, max_posts, **kwargs):
    """Return realistic mock posts."""
    posts = []
    communities = ["r/python", "r/programming", "r/learnpython"]
    for i in range(min(max_posts, 10)):
        posts.append({
            "platform": "reddit",
            "id": f"post-{i}",
            "author": f"user_{i}",
            "text": f"This is test post number {i} about {phrases[0]}.",
            "title": f"Post {i}",
            "timestamp": "2026-03-15T00:00:00+00:00",
            "url": f"https://reddit.com/r/python/comments/post-{i}",
            "community": communities[i % len(communities)],
            "engagement": i * 10,
            "comments": [],
            "phrase_matches": phrases,
        })
    return posts


def _mock_analyzer(posts, provider, progress_callback=None, cancellation_token=None, **kwargs):
    """Return analyzed posts with deterministic results."""
    sentiments = ["positive", "negative", "neutral", "positive", "positive"]
    emotions = ["joy", "anger", "trust", "surprise", "joy"]
    results = []
    for i, post in enumerate(posts):
        post_dict = post if isinstance(post, dict) else {"id": str(i), "community": "r/test"}
        result = {
            "post": post_dict,
            "analysis": {
                "sentiment": sentiments[i % len(sentiments)],
                "emotion": emotions[i % len(emotions)],
                "confidence": 0.85,
                "key_point": f"Key insight from post {i}",
                "sarcasm_detected": False,
            },
        }
        results.append(result)
        if progress_callback:
            progress_callback(i + 1, len(posts), post_dict.get("id", str(i)))
    return results, 0


def _mock_thematic(posts, provider, phrase, **kwargs):
    """Return realistic mock themes."""
    return {
        "themes": [
            {
                "name": "Code Quality",
                "description": "Discussion about maintaining code standards",
                "percentage": 45.0,
                "post_count": 5,
                "sentiment_skew": "positive",
                "representative_quotes": ["Code quality is important", "Clean code matters"],
            },
            {
                "name": "Tooling",
                "description": "IDE and development tool preferences",
                "percentage": 30.0,
                "post_count": 3,
                "sentiment_skew": "neutral",
                "representative_quotes": ["I prefer VS Code"],
            },
            {
                "name": "Performance",
                "description": "Runtime performance concerns",
                "percentage": 15.0,
                "post_count": 2,
                "sentiment_skew": "negative",
                "representative_quotes": ["Python is slow"],
            },
        ]
    }


def test_full_pipeline_happy_path():
    """Complete pipeline: submit job, wait for completion, verify report."""
    from signalstream.jobs.manager import JobManager

    db = _make_mock_db()
    manager = JobManager(db=db, max_workers=2)

    try:
        job_id = manager.submit_job(
            topic="Python sentiment",
            phrases=["python", "coding"],
            time_range="week",
            max_posts=10,
            provider=MagicMock(),
            collector_fn=_mock_collector,
            analyzer_fn=_mock_analyzer,
            thematic_fn=_mock_thematic,
        )

        # Poll until complete
        for _ in range(100):
            status = manager.get_status(job_id)
            if status and status["state"] in ("COMPLETED", "FAILED"):
                break
            time.sleep(0.1)

        # Verify completion
        final_status = manager.get_status(job_id)
        assert final_status["state"] == "COMPLETED"

        # Verify result
        result = manager.get_result(job_id)
        assert result is not None
        assert result.final_state == JobState.COMPLETED
        assert result.report_content is not None
        assert result.report_content.total_posts == 10
        assert result.report_content.topic == "Python sentiment"
        assert len(result.report_content.themes) == 3

        # Verify charts were generated
        charts = result.report_content.charts
        assert "sentiment" in charts
        assert "emotion" in charts
        assert "themes" in charts
        assert "community" in charts

        # Verify statistics
        stats = result.report_content.statistics
        assert sum(stats["sentiment_distribution"].values()) == 10
        assert sum(stats["emotion_distribution"].values()) == 10

        # Verify executive snapshot
        snap = result.report_content.executive_snapshot
        assert snap["total_posts"] == 10
        assert snap["dominant_sentiment"] == "positive"  # 6 positive out of 10

    finally:
        manager.shutdown(wait=True, timeout=10)


def test_full_pipeline_json_export():
    """Pipeline result can be exported to JSON."""
    from signalstream.jobs.manager import JobManager
    from signalstream.reports.exports import export_json

    db = _make_mock_db()
    manager = JobManager(db=db, max_workers=2)

    try:
        job_id = manager.submit_job(
            topic="JSON test",
            phrases=["test"],
            time_range="week",
            max_posts=5,
            provider=MagicMock(),
            collector_fn=_mock_collector,
            analyzer_fn=_mock_analyzer,
            thematic_fn=_mock_thematic,
        )

        for _ in range(100):
            status = manager.get_status(job_id)
            if status and status["state"] == "COMPLETED":
                break
            time.sleep(0.1)

        result = manager.get_result(job_id)
        assert result is not None
        assert result.report_content is not None

        json_str = export_json(result.report_content)
        parsed = json.loads(json_str)
        assert parsed["topic"] == "JSON test"
        assert parsed["total_posts"] == 5
        assert "statistics" in parsed

    finally:
        manager.shutdown(wait=True, timeout=10)


def test_full_pipeline_html_render():
    """Pipeline result can be rendered to HTML."""
    from signalstream.jobs.manager import JobManager
    from signalstream.reports.renderer import render_html

    db = _make_mock_db()
    manager = JobManager(db=db, max_workers=2)

    try:
        job_id = manager.submit_job(
            topic="HTML test",
            phrases=["test"],
            time_range="week",
            max_posts=5,
            provider=MagicMock(),
            collector_fn=_mock_collector,
            analyzer_fn=_mock_analyzer,
            thematic_fn=_mock_thematic,
        )

        for _ in range(100):
            status = manager.get_status(job_id)
            if status and status["state"] == "COMPLETED":
                break
            time.sleep(0.1)

        result = manager.get_result(job_id)
        assert result is not None
        assert result.report_content is not None

        html = render_html(result.report_content)
        assert "Sentiment Analysis Report" in html
        assert "HTML test" in html
        assert "Executive Snapshot" in html
        assert "Powered by Signalstream" in html

    finally:
        manager.shutdown(wait=True, timeout=10)


def test_pipeline_collector_empty():
    """Pipeline with empty collection results in FAILED state with COLLECTOR_EMPTY."""
    from signalstream.jobs.manager import JobManager

    db = _make_mock_db()
    manager = JobManager(db=db, max_workers=2)

    try:
        job_id = manager.submit_job(
            topic="empty test",
            phrases=["nonexistent-topic-xyz"],
            time_range="week",
            max_posts=10,
            provider=MagicMock(),
            collector_fn=lambda **kw: [],  # Returns empty
            analyzer_fn=_mock_analyzer,
            thematic_fn=_mock_thematic,
        )

        for _ in range(50):
            status = manager.get_status(job_id)
            if status and status["state"] == "FAILED":
                break
            time.sleep(0.1)

        final_status = manager.get_status(job_id)
        assert final_status["state"] == "FAILED"
        assert final_status.get("error_code") == "COLLECTOR_EMPTY"

    finally:
        manager.shutdown(wait=True, timeout=5)


def test_pipeline_cancellation():
    """Cancelling a running job transitions to CANCELLED state."""
    from signalstream.jobs.manager import JobManager

    db = _make_mock_db()
    manager = JobManager(db=db, max_workers=2)

    started = __import__("threading").Event()

    def _slow_collector(**kwargs):
        started.set()
        time.sleep(30)  # Will be cancelled before this completes
        return []

    try:
        job_id = manager.submit_job(
            topic="cancel test",
            phrases=["test"],
            time_range="week",
            max_posts=10,
            provider=MagicMock(),
            collector_fn=_slow_collector,
            analyzer_fn=_mock_analyzer,
            thematic_fn=_mock_thematic,
        )

        started.wait(timeout=5)
        manager.cancel_job(job_id)

        for _ in range(50):
            status = manager.get_status(job_id)
            if status and status["state"] in ("CANCELLED", "FAILED"):
                break
            time.sleep(0.1)

        result = manager.get_result(job_id)
        # The job should have transitioned to CANCELLED or FAILED
        assert result is not None
        assert result.final_state in (JobState.CANCELLED, JobState.FAILED)

    finally:
        manager.shutdown(wait=True, timeout=5)


def test_two_concurrent_jobs():
    """Two jobs can run simultaneously in the thread pool."""
    from signalstream.jobs.manager import JobManager

    db = _make_mock_db()
    manager = JobManager(db=db, max_workers=2)

    try:
        job1 = manager.submit_job(
            topic="job 1", phrases=["python"], time_range="week", max_posts=5,
            provider=MagicMock(), collector_fn=_mock_collector,
            analyzer_fn=_mock_analyzer, thematic_fn=_mock_thematic,
        )
        job2 = manager.submit_job(
            topic="job 2", phrases=["rust"], time_range="week", max_posts=5,
            provider=MagicMock(), collector_fn=_mock_collector,
            analyzer_fn=_mock_analyzer, thematic_fn=_mock_thematic,
        )

        # Wait for both to complete
        for _ in range(100):
            s1 = manager.get_status(job1)
            s2 = manager.get_status(job2)
            if (s1 and s1["state"] == "COMPLETED" and
                    s2 and s2["state"] == "COMPLETED"):
                break
            time.sleep(0.1)

        r1 = manager.get_result(job1)
        r2 = manager.get_result(job2)
        assert r1 is not None and r1.final_state == JobState.COMPLETED
        assert r2 is not None and r2.final_state == JobState.COMPLETED

    finally:
        manager.shutdown(wait=True, timeout=10)
```

- [ ] **Step 10.2** — Run integration tests (2 min)

```bash
cd "/Users/eston/Desktop/Sentiment Analysis" && python -m pytest signalstream/tests/test_jobs/test_integration.py -v 2>&1 | tail -20
```

- [ ] **Step 10.3** — Run the complete test suite for Plan 2 modules (2 min)

```bash
cd "/Users/eston/Desktop/Sentiment Analysis" && python -m pytest signalstream/tests/test_reports/ signalstream/tests/test_jobs/ -v --tb=short 2>&1 | tail -30
```

- [ ] **Step 10.4** — Commit (1 min)

```bash
cd "/Users/eston/Desktop/Sentiment Analysis" && git add signalstream/tests/test_jobs/test_integration.py && git commit -m "test(jobs): add full pipeline integration tests with mock LLM"
```

---

## Summary

### Files Created (Plan 2)

**Reports package (`signalstream/reports/`):**
| File | Purpose |
|------|---------|
| `__init__.py` | Package init |
| `charts.py` | Thread-safe matplotlib chart generation (BOARD-010) |
| `builder.py` | Report content assembly (statistics, charts, snapshot) |
| `renderer.py` | WeasyPrint PDF rendering with SSRF-safe url_fetcher (BOARD-002) |
| `exports.py` | JSON export with text truncation |
| `pdf_templates/report.html` | Jinja2 report template (7 cards) |
| `pdf_templates/styles.css` | PDF stylesheet |

**Jobs package (`signalstream/jobs/`):**
| File | Purpose |
|------|---------|
| `__init__.py` | Package init |
| `state.py` | JobState enum, CancellationToken, JobProgress |
| `tasks.py` | Per-stage wrappers with error taxonomy |
| `pipeline.py` | Stage sequencing with state transitions |
| `manager.py` | Thread pool (max 2), submit/cancel/status, graceful shutdown |

**Tests (`signalstream/tests/`):**
| File | Tests |
|------|-------|
| `test_reports/test_charts.py` | Chart generation, thread safety, empty inputs |
| `test_reports/test_builder.py` | Statistics, snapshot, chart assembly |
| `test_reports/test_renderer.py` | HTML rendering, PDF rendering, SSRF protection |
| `test_reports/test_exports.py` | JSON export, text truncation, chart inclusion |
| `test_jobs/test_state.py` | State machine, transitions, cancellation, progress |
| `test_jobs/test_tasks.py` | Stage tasks, error classification, cancellation |
| `test_jobs/test_pipeline.py` | Pipeline sequencing, failure, cancellation |
| `test_jobs/test_manager.py` | Thread pool, submit/cancel, shutdown |
| `test_jobs/test_integration.py` | Full pipeline end-to-end with mock LLM |

### Board Findings Addressed

| Board ID | Finding | How Addressed |
|----------|---------|---------------|
| BOARD-002 | WeasyPrint SSRF | `_safe_url_fetcher` blocks all non-data: URIs |
| BOARD-010 | Matplotlib thread safety | `Agg` backend, OO API, `threading.Lock` |
| ALPHA-002 | No cancellation | `CancellationToken` with cooperative checking |
| Section 7 | No error taxonomy | `TaskError` with structured error codes |
| Section 4 | No graceful shutdown | `JobManager.shutdown()` with signal handlers |
| Section 4 | No progress reporting | `JobProgress` with `to_dict()` for API |

### Dependency Map

```
Plan 1 (Foundation)
    db/repositories.py
    llm/router.py, llm/config.py
    collectors/reddit.py
    analyzers/sentiment.py, analyzers/thematic.py, analyzers/schemas.py
        |
        v
Plan 2 (This Plan)
    reports/charts.py      <-- standalone, no Plan 1 deps
    reports/builder.py     <-- imports charts.py
    reports/renderer.py    <-- imports builder (via template), Jinja2, WeasyPrint
    reports/exports.py     <-- imports builder (via dataclass)
    jobs/state.py          <-- standalone, no Plan 1 deps
    jobs/tasks.py          <-- imports state.py, builder.py, Plan 1 analyzers
    jobs/pipeline.py       <-- imports tasks.py, state.py
    jobs/manager.py        <-- imports pipeline.py, state.py, Plan 1 db
        |
        v
Plan 3 (Web Layer)
    app/routes/analysis.py <-- imports manager.py
    app/routes/api.py      <-- imports manager.py, exports.py, renderer.py
```
