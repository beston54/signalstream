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

# -- Color palettes ---------------------------------------------------

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

# -- Internal helpers -------------------------------------------------


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
    # Clear and close the figure to free memory (OO API only)
    fig.clear()
    del fig
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode("utf-8")
    return f"data:image/png;base64,{b64}"


def _get_color(
    name: str,
    palette: dict[str, str],
    fallback_palette: list[str],
    idx: int = 0,
) -> str:
    """Look up a named color or fall back to rotating palette."""
    return palette.get(
        name.lower(),
        fallback_palette[idx % len(fallback_palette)],
    )


# -- Public chart generators ------------------------------------------


def generate_emotion_chart(
    emotions: dict[str, int], dpi: int = 150,
) -> str:
    """Horizontal bar chart of emotion distribution.

    Returns base64 data URI string, or "" if empty/all zeros.
    """
    filtered = {k: v for k, v in emotions.items() if v > 0}
    if not filtered:
        return ""

    sorted_items = sorted(
        filtered.items(), key=lambda x: x[1], reverse=True,
    )
    labels = [item[0].capitalize() for item in sorted_items]
    values = [item[1] for item in sorted_items]
    colors = [
        _get_color(item[0], EMOTION_COLORS, CHART_PALETTE, i)
        for i, item in enumerate(sorted_items)
    ]
    total = sum(values)

    with _chart_lock:
        height = max(2.5, len(sorted_items) * 0.5 + 1)
        fig = Figure(figsize=(7, height))
        ax = fig.add_subplot(111)

        bars = ax.barh(
            labels, values, color=colors,
            height=0.55, edgecolor="none", alpha=0.92,
        )

        for bar, val in zip(bars, values, strict=False):
            pct = (val / total * 100) if total > 0 else 0
            ax.text(
                bar.get_width() + 0.3,
                bar.get_y() + bar.get_height() / 2,
                f"{val} ({pct:.0f}%)",
                va="center", fontsize=9, fontweight="bold",
            )

        ax.set_title(
            "Emotional Tone Distribution",
            fontweight="bold", fontsize=14,
        )
        ax.invert_yaxis()
        ax.set_xlabel("Number of Posts")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.annotate(
            f"n={total}",
            xy=(1.0, -0.08), xycoords="axes fraction",
            ha="right", va="top",
            fontsize=8, fontstyle="italic", color="#6B7280",
        )

        return _fig_to_data_uri(fig, dpi)


def generate_sentiment_chart(
    sentiments: dict[str, int], dpi: int = 150,
) -> str:
    """Donut chart of sentiment split.

    Returns base64 data URI string, or "" if empty.
    """
    filtered = {k: v for k, v in sentiments.items() if v > 0}
    if not filtered:
        return ""

    labels = [k.capitalize() for k in filtered]
    values = list(filtered.values())
    colors = [
        SENTIMENT_COLORS.get(k.lower(), "#94A3B8")
        for k in filtered
    ]
    total = sum(values)

    with _chart_lock:
        fig = Figure(figsize=(6, 5))
        ax = fig.add_subplot(111)

        def _autopct(pct: float) -> str:
            count = int(round(pct / 100 * total))
            return f"{pct:.1f}%\n({count})"

        wedges, texts, autotexts = ax.pie(
            values,
            labels=labels,
            colors=colors,
            autopct=_autopct,
            startangle=90,
            pctdistance=0.75,
            wedgeprops={
                "width": 0.4,
                "edgecolor": "white",
                "linewidth": 2,
            },
        )
        for autotext in autotexts:
            autotext.set_fontsize(9)
            autotext.set_fontweight("bold")
        for text in texts:
            text.set_fontsize(10)

        ax.set_title(
            "Sentiment Split",
            fontweight="bold", fontsize=14,
        )
        ax.annotate(
            f"n={total}",
            xy=(0.5, -0.05), xycoords="axes fraction",
            ha="center", va="top",
            fontsize=8, fontstyle="italic", color="#6B7280",
        )

        return _fig_to_data_uri(fig, dpi)


def generate_theme_chart(
    themes: list[dict[str, Any]], dpi: int = 150,
) -> str:
    """Horizontal bar chart of theme frequency by percentage.

    Returns base64 data URI string, or "" if empty.
    """
    if not themes:
        return ""

    sorted_themes = sorted(
        themes, key=lambda t: t.get("percentage", 0),
        reverse=True,
    )[:8]
    labels = [t["name"][:25] for t in sorted_themes]
    values = [t["percentage"] for t in sorted_themes]
    counts = [t.get("post_count", 0) for t in sorted_themes]
    colors = [
        CHART_PALETTE[i % len(CHART_PALETTE)]
        for i in range(len(sorted_themes))
    ]

    with _chart_lock:
        height = max(2.5, len(sorted_themes) * 0.5 + 1)
        fig = Figure(figsize=(7, height))
        ax = fig.add_subplot(111)

        bars = ax.barh(
            labels, values, color=colors,
            height=0.55, edgecolor="none", alpha=0.92,
        )

        for bar, pct, count in zip(
            bars, values, counts, strict=False,
        ):
            ax.text(
                bar.get_width() + 0.5,
                bar.get_y() + bar.get_height() / 2,
                f"{pct:.0f}% ({count} posts)",
                va="center", fontsize=9, fontweight="bold",
            )

        ax.set_title(
            "Key Themes", fontweight="bold", fontsize=14,
        )
        ax.invert_yaxis()
        ax.set_xlabel("Prevalence (%)")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        return _fig_to_data_uri(fig, dpi)


def generate_community_chart(
    communities: dict[str, dict[str, int]],
    dpi: int = 150,
) -> str:
    """Grouped bar chart of sentiment by community.

    Returns base64 data URI string, or "" if empty.
    """
    if not communities:
        return ""

    import numpy as np

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
        fig_w = max(7, len(comm_labels) * 1.2)
        fig = Figure(figsize=(fig_w, 5))
        ax = fig.add_subplot(111)

        for i, key in enumerate(present_keys):
            vals = [
                data.get(key, 0) for _, data in sorted_comms
            ]
            offset = (i - len(present_keys) / 2 + 0.5) * width
            ax.bar(
                x + offset, vals, width=width,
                label=key.capitalize(),
                color=SENTIMENT_COLORS.get(key, "#94A3B8"),
                edgecolor="none", alpha=0.9,
            )

        ax.set_title(
            "Community Breakdown",
            fontweight="bold", fontsize=14,
        )
        ax.set_ylabel("Number of Posts")
        ax.set_xticks(x)
        ax.set_xticklabels(
            comm_labels, rotation=35, ha="right", fontsize=9,
        )
        ax.legend(fontsize=9, frameon=False)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)

        total = sum(
            sum(d.values()) for _, d in sorted_comms
        )
        ax.annotate(
            f"n={total}",
            xy=(1.0, 1.0), xycoords="axes fraction",
            ha="right", va="top",
            fontsize=8, fontstyle="italic", color="#6B7280",
        )

        return _fig_to_data_uri(fig, dpi)


def generate_all_charts(
    statistics: dict[str, Any],
    themes: list[dict[str, Any]],
    dpi: int = 150,
) -> dict[str, str]:
    """Generate all report charts.

    Returns dict of chart name to data URI. Skips charts with
    missing or empty data. Never raises -- logs errors and returns
    partial results.
    """
    charts: dict[str, str] = {}

    generators = [
        ("sentiment", lambda: generate_sentiment_chart(
            statistics.get("sentiment_distribution", {}), dpi,
        )),
        ("emotion", lambda: generate_emotion_chart(
            statistics.get("emotion_distribution", {}), dpi,
        )),
        ("themes", lambda: generate_theme_chart(themes, dpi)),
        ("community", lambda: generate_community_chart(
            statistics.get("community_breakdown", {}), dpi,
        )),
    ]

    for name, gen in generators:
        try:
            result = gen()
            if result:
                charts[name] = result
        except Exception:
            logger.exception(
                "Failed to generate %s chart", name,
            )

    return charts
