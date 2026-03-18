"""
Chart Generator Module

Creates branded matplotlib charts for the intelligence report.
Returns base64-encoded PNG data URIs for embedding in HTML templates.
"""

import base64
import io
import logging
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

# Add parent directory to path for sibling imports
sys.path.insert(0, str(Path(__file__).parent))
from design_system import load_design_config, get_sentiment_color, get_emotion_color, EMOTION_COLORS

logger = logging.getLogger(__name__)

_fonts_registered = False


def _register_fonts(config: dict, base_dir: str = ".") -> tuple:
    """
    Register brand fonts with matplotlib font manager.

    Returns:
        (headline_font_name, body_font_name) for use in chart styling
    """
    global _fonts_registered
    design = load_design_config(config)
    font_dir = Path(base_dir) / design["typography"]["font_dir"]

    headline_font = design["typography"]["headline_font"]
    body_font = design["typography"]["body_font"]

    if not _fonts_registered and font_dir.exists():
        for ttf_file in font_dir.glob("*.ttf"):
            try:
                fm.fontManager.addfont(str(ttf_file))
            except Exception as e:
                logger.warning(f"Could not register font {ttf_file.name}: {e}")
        _fonts_registered = True

    return headline_font, body_font


def _apply_brand_theme(config: dict, base_dir: str = ".") -> None:
    """Apply dark-theme brand colors and typography to matplotlib rcParams."""
    design = load_design_config(config)
    colors = design["colors"]

    headline_font, body_font = _register_fonts(config, base_dir)

    plt.rcParams.update({
        'font.family': 'sans-serif',
        'font.sans-serif': [body_font, 'Helvetica Neue', 'Arial', 'sans-serif'],
        'font.serif': [headline_font, 'Georgia', 'Times New Roman', 'serif'],
        'font.size': 10,
        'axes.titlesize': 13,
        'axes.titleweight': 'bold',
        'axes.labelsize': 10,
        'axes.edgecolor': '#334155',          # subtle slate border
        'axes.labelcolor': colors["text_secondary"],
        'text.color': colors["text_primary"],
        'xtick.color': colors["text_secondary"],
        'ytick.color': colors["text_secondary"],
        'figure.facecolor': 'none',           # transparent figure bg
        'axes.facecolor': 'none',             # transparent axes bg
        'axes.grid': False,
        'axes.spines.top': False,
        'axes.spines.right': False,
        'axes.spines.left': True,
        'axes.spines.bottom': True,
        'legend.facecolor': 'none',
        'legend.edgecolor': 'none',
        'legend.labelcolor': colors["text_secondary"],
    })


def _fig_to_data_uri(fig: plt.Figure, dpi: int = 150) -> str:
    """Convert matplotlib figure to a base64 PNG data URI string with transparent bg."""
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=dpi, bbox_inches='tight',
                facecolor='none', edgecolor='none', transparent=True)
    plt.close(fig)
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode('utf-8')
    return f"data:image/png;base64,{b64}"


def generate_sentiment_chart(
    sentiment_distribution: Dict[str, int],
    config: dict,
    base_dir: str = "."
) -> str:
    """
    Generate a horizontal bar chart of sentiment distribution.

    Args:
        sentiment_distribution: {"positive": N, "negative": N, ...}
        config: Full config dict
        base_dir: Project root for font resolution

    Returns:
        Base64 data URI of the chart PNG
    """
    _apply_brand_theme(config, base_dir)
    design = load_design_config(config)

    fig, ax = plt.subplots(figsize=(
        design["report"]["chart_width_inches"],
        max(2.5, len(sentiment_distribution) * 0.6 + 1)
    ))

    labels = [s.capitalize() for s in sentiment_distribution.keys()]
    raw_labels = list(sentiment_distribution.keys())
    values = list(sentiment_distribution.values())
    colors = [get_sentiment_color(s) for s in raw_labels]
    total = sum(values) if values else 1

    bars = ax.barh(labels, values, color=colors, height=0.5,
                   edgecolor='none', alpha=0.92)

    for bar, val in zip(bars, values):
        pct = (val / total * 100) if total > 0 else 0
        ax.text(bar.get_width() + 0.3, bar.get_y() + bar.get_height() / 2,
                f'{val} ({pct:.0f}%)', va='center', fontsize=9,
                color=design["colors"]["text_primary"], fontweight='bold')

    ax.set_title('Sentiment Distribution', fontweight='bold',
                 color=design["colors"]["primary"], fontsize=14, fontfamily='serif')
    ax.invert_yaxis()
    ax.set_xlabel('Number of Posts', color=design["colors"]["text_secondary"])

    # Sample size annotation (#9)
    ax.annotate(f'n={total}', xy=(1.0, -0.08), xycoords='axes fraction',
                ha='right', va='top', fontsize=8,
                color=design["colors"]["text_secondary"], fontstyle='italic')

    return _fig_to_data_uri(fig, design["report"]["chart_dpi"])


def generate_emotion_chart(
    emotion_distribution: Dict[str, int],
    config: dict,
    base_dir: str = "."
) -> str:
    """
    Generate a horizontal bar chart of emotion distribution.

    Args:
        emotion_distribution: {"enthusiastic": N, "curious": N, ...}
        config: Full config dict
        base_dir: Project root for font resolution

    Returns:
        Base64 data URI of the chart PNG
    """
    _apply_brand_theme(config, base_dir)
    design = load_design_config(config)

    # Filter out zero-value emotions for cleaner chart
    filtered = {k: v for k, v in emotion_distribution.items() if v > 0}
    if not filtered:
        return ""

    # Sort emotions by count descending
    sorted_emotions = sorted(filtered.items(), key=lambda x: x[1], reverse=True)
    labels = [e[0].capitalize() for e in sorted_emotions]
    raw_labels = [e[0] for e in sorted_emotions]
    values = [e[1] for e in sorted_emotions]
    colors = [EMOTION_COLORS.get(e.lower(), get_emotion_color(e)) for e in raw_labels]
    total = sum(values) if values else 1

    fig, ax = plt.subplots(figsize=(
        design["report"]["chart_width_inches"],
        max(2.5, len(sorted_emotions) * 0.5 + 1)
    ))

    # Dark background matching report theme
    fig.patch.set_facecolor('#0C1220')
    ax.set_facecolor('#161E2E')

    bars = ax.barh(labels, values, color=colors, height=0.55,
                   edgecolor='none', alpha=0.92)

    # Add count and percentage labels to bars
    for bar, val in zip(bars, values):
        pct = (val / total * 100) if total > 0 else 0
        ax.text(bar.get_width() + 0.3, bar.get_y() + bar.get_height() / 2,
                f'{val} ({pct:.0f}%)', va='center', fontsize=9,
                color=design["colors"]["text_primary"], fontweight='bold')

    ax.set_title('Emotional Tone Distribution', fontweight='bold',
                 color=design["colors"]["primary"], fontsize=14, fontfamily='serif')
    ax.invert_yaxis()
    ax.set_xlabel('Number of Posts', color=design["colors"]["text_secondary"])

    # Style spines to match dark theme
    for spine in ax.spines.values():
        spine.set_color('#334155')
    ax.tick_params(axis='y', colors=design["colors"]["text_primary"])
    ax.tick_params(axis='x', colors=design["colors"]["text_secondary"])

    # Sample size annotation (#9)
    ax.annotate(f'n={total}', xy=(1.0, -0.08), xycoords='axes fraction',
                ha='right', va='top', fontsize=8,
                color=design["colors"]["text_secondary"], fontstyle='italic')

    return _fig_to_data_uri(fig, design["report"]["chart_dpi"])


def generate_subreddit_chart(
    subreddit_breakdown: Dict[str, int],
    config: dict,
    base_dir: str = "."
) -> str:
    """
    Generate a compact vertical bar chart of community/venue distribution (top N).

    Args:
        subreddit_breakdown: {"community_label": count, ...}
        config: Full config dict
        base_dir: Project root for font resolution

    Returns:
        Base64 data URI of the chart PNG
    """
    _apply_brand_theme(config, base_dir)
    design = load_design_config(config)
    palette = design["colors"]["chart_palette"]

    sorted_subs = sorted(subreddit_breakdown.items(),
                         key=lambda x: x[1], reverse=True)[:8]
    if not sorted_subs:
        return ""

    labels = [str(s[0])[:18] for s in sorted_subs]
    values = [s[1] for s in sorted_subs]
    colors = [palette[i % len(palette)] for i in range(len(labels))]

    fig, ax = plt.subplots(figsize=(
        design["report"]["chart_width_inches"],
        min(max(2.3, design["report"]["chart_height_inches"] * 0.9), 2.9)
    ))

    bars = ax.bar(range(len(labels)), values, color=colors, width=0.6,
                  edgecolor='none', alpha=0.92)

    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.1,
                str(val), ha='center', va='bottom', fontsize=8,
                color=design["colors"]["text_primary"], fontweight='bold')

    ax.set_title('Community Distribution', fontweight='bold',
                 color=design["colors"]["primary"], fontsize=14, fontfamily='serif')
    ax.set_ylabel('Posts', color=design["colors"]["text_secondary"])
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=35, ha='right', fontsize=8,
                       color=design["colors"]["text_secondary"])
    ax.margins(y=0.15)

    # Sample size annotation (#9)
    total = sum(values)
    ax.annotate(f'n={total}', xy=(1.0, 1.0), xycoords='axes fraction',
                ha='right', va='top', fontsize=8,
                color=design["colors"]["text_secondary"], fontstyle='italic')

    return _fig_to_data_uri(fig, design["report"]["chart_dpi"])


def generate_theme_cluster_chart(
    themes_by_phrase: Dict[str, Dict[str, Any]],
    config: dict,
    base_dir: str = "."
) -> str:
    """
    Generate a horizontal bar chart showing top themes across phrases.

    Args:
        themes_by_phrase: Full themes data keyed by phrase
        config: Full config dict
        base_dir: Project root for font resolution

    Returns:
        Base64 data URI of the chart PNG
    """
    _apply_brand_theme(config, base_dir)
    design = load_design_config(config)
    palette = design["colors"]["chart_palette"]

    all_themes = []
    for phrase, data in themes_by_phrase.items():
        for theme in data.get("major_themes", [])[:3]:
            all_themes.append({
                "phrase": phrase,
                "theme": theme.get("theme", "Unknown"),
                "percentage": theme.get("percentage", 0)
            })

    if not all_themes:
        return ""

    all_themes = sorted(all_themes, key=lambda t: t.get("percentage", 0), reverse=True)[:8]

    fig, ax = plt.subplots(figsize=(
        design["report"]["chart_width_inches"],
        min(max(2.4, design["report"]["chart_height_inches"]), 3.1)
    ))

    labels = [f"{t['theme'][:18]}" for t in all_themes]
    values = [t["percentage"] for t in all_themes]
    colors = [palette[i % len(palette)] for i in range(len(all_themes))]

    bars = ax.bar(range(len(labels)), values, color=colors, width=0.65,
                  edgecolor='none', alpha=0.92)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=35, ha='right', fontsize=8,
                       color=design["colors"]["text_secondary"])
    ax.set_ylabel('Prevalence (%)', color=design["colors"]["text_secondary"])
    ax.set_title('Theme Prevalence by Topic', fontweight='bold',
                 color=design["colors"]["primary"], fontsize=14, fontfamily='serif')
    ax.margins(y=0.15)

    for bar, val in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.4,
            f'{val}%',
            ha='center',
            va='bottom',
            fontsize=8,
            color=design["colors"]["text_primary"],
            fontweight='bold',
        )

    return _fig_to_data_uri(fig, design["report"]["chart_dpi"])


def generate_sentiment_trend_chart(
    historical_data: List[Dict[str, Any]],
    config: dict,
    base_dir: str = "."
) -> Optional[str]:
    """
    Generate a time-series line chart of sentiment over reporting periods.

    Args:
        historical_data: List of {"date": str, "positive": N, "negative": N, ...}
        config: Full config dict
        base_dir: Project root for font resolution

    Returns:
        Base64 data URI, or None if insufficient data points
    """
    if not historical_data or len(historical_data) < 2:
        return None

    _apply_brand_theme(config, base_dir)
    design = load_design_config(config)

    fig, ax = plt.subplots(figsize=(
        design["report"]["chart_width_inches"],
        design["report"]["chart_height_inches"]
    ))

    dates = [d["date"] for d in historical_data]

    for sentiment, color in [
        ("positive", "#34D399"),
        ("neutral", "#94A3B8"),
        ("negative", "#FB7185")
    ]:
        values = [d.get(sentiment, 0) for d in historical_data]
        ax.plot(dates, values, color=color, marker='o',
                linewidth=2.5, label=sentiment.capitalize(), markersize=6)

    ax.legend(fontsize=9, frameon=False, labelcolor='#CBD5E1')
    ax.set_title('Sentiment Trends Over Time', fontweight='bold',
                 color=design["colors"]["primary"], fontsize=14, fontfamily='serif')
    ax.set_ylabel('Number of Posts', color=design["colors"]["text_secondary"])
    plt.xticks(rotation=45, fontsize=8, color='#94A3B8')

    return _fig_to_data_uri(fig, design["report"]["chart_dpi"])


def generate_all_charts(
    statistics: Dict[str, Any],
    themes_by_phrase: Dict[str, Dict[str, Any]],
    config: dict,
    base_dir: str = ".",
    historical_data: Optional[List[Dict]] = None
) -> Dict[str, str]:
    """
    Generate all charts for the report.

    Args:
        statistics: Report statistics dict
        themes_by_phrase: Thematic analysis results
        config: Full config dict
        base_dir: Project root directory
        historical_data: Optional list of historical data points for trend chart

    Returns:
        Dict mapping chart name to base64 data URI string:
        {
            "sentiment_distribution": "data:image/png;base64,...",
            "emotion_distribution": "data:image/png;base64,...",
            "subreddit_distribution": "data:image/png;base64,...",
            "theme_clusters": "data:image/png;base64,...",
            "sentiment_trend": "data:image/png;base64,..." (if historical data exists)
        }
    """
    charts = {}

    chart_generators = [
        ("sentiment_distribution", lambda: generate_sentiment_chart(
            statistics.get("sentiment_distribution", {}), config, base_dir
        )),
        ("emotion_distribution", lambda: generate_emotion_chart(
            statistics.get("emotion_distribution", {}), config, base_dir
        )),
        ("subreddit_distribution", lambda: generate_subreddit_chart(
            statistics.get("community_breakdown", statistics.get("subreddit_breakdown", {})),
            config,
            base_dir
        )),
        ("theme_clusters", lambda: generate_theme_cluster_chart(
            themes_by_phrase, config, base_dir
        )),
    ]

    for name, generator in chart_generators:
        try:
            result = generator()
            if result:
                charts[name] = result
        except Exception as e:
            logger.error(f"Failed to generate {name} chart: {e}")

    if historical_data:
        try:
            trend = generate_sentiment_trend_chart(
                historical_data, config, base_dir)
            if trend:
                charts["sentiment_trend"] = trend
        except Exception as e:
            logger.error(f"Failed to generate trend chart: {e}")

    logger.info(f"Generated {len(charts)} charts")
    return charts
