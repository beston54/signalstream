"""
Design System Module — Signalstream

Loads design configuration (colors, typography, spacing) from config.yaml
and provides helper utilities for the report generation pipeline.
"""

import logging
from pathlib import Path
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

# Default design system values (fallback if config section is missing)
# Signalstream dark theme – designed for 4:5 card-based PDF output
DEFAULT_DESIGN = {
    "colors": {
        "primary": "#4DA8FF",           # Blue – data highlights, titles
        "secondary": "#9B8AFF",         # Violet – secondary data
        "accent": "#FFB547",            # Amber – callouts, kickers
        "background": "#0C1220",        # Deep navy – page background
        "background_card": "#161E2E",   # Card surface
        "background_elevated": "#1C2640",  # Elevated surface / hover
        "border": "#2A3550",            # Subtle borders
        "text_primary": "#F0F4F8",      # Near-white – headings
        "text_secondary": "#8899B0",    # Muted – body, labels
        "text_tertiary": "#566580",     # Footnotes, captions
        "chart_palette": [
            "#4DA8FF", "#9B8AFF", "#FFB547",
            "#5DD9A5", "#FF7B8E", "#F2CC8F", "#818CF8"
        ]
    },
    "typography": {
        "headline_font": "IBM Plex Serif",
        "body_font": "IBM Plex Sans",
        "annotation_font": "DM Mono",
        "font_dir": "assets/fonts"
    },
    "report": {
        "format": "cards",
        "max_photos": 2,
        "max_photos_per_section": 1,
        "chart_dpi": 150,
        "card_width_inches": 7.2,
        "card_height_inches": 9.0,
    }
}

# Card dimensions (4:5 ratio, maps to 1080x1350 at 150 DPI)
CARD_DIMENSIONS = {
    "width_inches": 7.2,
    "height_inches": 9.0,
    "dpi": 150,
    "width_px": 1080,
    "height_px": 1350,
}

# Sentiment label -> brand color mapping
SENTIMENT_COLORS = {
    "positive": "#5DD9A5",   # Soft emerald
    "negative": "#FF7B8E",   # Soft rose
    "neutral": "#8899B0",    # Muted
    "mixed": "#9B8AFF",      # Violet
    "unknown": "#566580",    # Tertiary
    "error": "#FF7B8E",
}

# Emotion label -> brand color mapping
# (#13 fix: no color collision with SENTIMENT_COLORS; includes H12 new labels)
EMOTION_COLORS = {
    "enthusiastic": "#34D399",  # Emerald (was #5DD9A5 which collided with positive)
    "hopeful": "#4DA8FF",       # Blue
    "curious": "#818CF8",       # Indigo
    "satisfied": "#38BDF8",     # Sky blue
    "amused": "#A78BFA",        # Light violet
    "neutral": "#8899B0",       # Muted
    "skeptical": "#F2CC8F",     # Sand
    "concerned": "#FFB547",     # Amber
    "frustrated": "#FF7B8E",    # Rose
    "angry": "#EF4444",         # Red
    # Political preset emotions
    "fearful": "#F87171",       # Red-ish
    "resigned": "#94A3B8",      # Slate gray
    "patriotic": "#3B82F6",     # Strong blue
    "defiant": "#DC2626",       # Bold red
    # Brand preset emotions
    "delighted": "#10B981",     # Emerald green
    "disappointed": "#F59E0B",  # Amber
    "confused": "#A78BFA",      # Light purple
    "loyal": "#2563EB",         # Royal blue
}

# Brand configuration
BRAND = {
    "product_name": "signalstream",
    "display_name": "Signalstream",
    "tagline": "Social Intelligence, Distilled.",
}


def load_design_config(config: dict) -> Dict[str, Any]:
    """
    Extract design system config from the full config dict,
    applying defaults for any missing keys.
    """
    design = config.get("design_system", {})

    merged = {}
    for section_key, section_defaults in DEFAULT_DESIGN.items():
        if isinstance(section_defaults, dict):
            merged[section_key] = {**section_defaults, **design.get(section_key, {})}
        else:
            merged[section_key] = design.get(section_key, section_defaults)

    return merged


def get_chart_palette(config: dict) -> List[str]:
    """Return the chart color palette from config."""
    design = load_design_config(config)
    return design["colors"]["chart_palette"]


def get_sentiment_color(sentiment: str) -> str:
    """Map a sentiment label to a brand color hex string."""
    return SENTIMENT_COLORS.get(sentiment.lower(), "#566580")


def get_emotion_color(emotion: str) -> str:
    """Map an emotion label to a brand color hex string."""
    return EMOTION_COLORS.get(emotion.lower(), "#566580")


def get_brand_config(config: dict = None) -> Dict[str, str]:
    """Return brand configuration, merging config.yaml overrides."""
    brand = dict(BRAND)
    if config:
        branding = config.get("branding", {})
        if branding.get("product_name"):
            brand["product_name"] = branding["product_name"]
        if branding.get("company_name"):
            brand["display_name"] = branding["company_name"]
        if branding.get("tagline"):
            brand["tagline"] = branding["tagline"]
    return brand


def get_font_paths(config: dict, base_dir: str = ".") -> Dict[str, Dict[str, str]]:
    """
    Return absolute paths to font files.
    """
    design = load_design_config(config)
    font_dir = Path(base_dir) / design["typography"]["font_dir"]

    return {
        "headline": {
            "regular": str(font_dir / "IBMPlexSerif-Regular.ttf"),
            "bold": str(font_dir / "IBMPlexSerif-Bold.ttf"),
            "semibold": str(font_dir / "IBMPlexSerif-SemiBold.ttf"),
        },
        "body": {
            "regular": str(font_dir / "IBMPlexSans-Regular.ttf"),
            "medium": str(font_dir / "IBMPlexSans-Medium.ttf"),
            "semibold": str(font_dir / "IBMPlexSans-SemiBold.ttf"),
            "bold": str(font_dir / "IBMPlexSans-Bold.ttf"),
        },
        "annotation": {
            "regular": str(font_dir / "DMMono-Regular.ttf"),
        }
    }
