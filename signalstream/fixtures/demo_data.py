"""Demo data fixture — pre-computed analysis for dead-end prevention.

Loaded when user clicks "Try with demo data". Ships with the package so
the user always has a forward path even without an LLM provider.
"""

from __future__ import annotations

DEMO_JOB = {
    "job_id": "demo-remote-work-2026",
    "topic": "remote work",
    "status": "completed",
    "time_range": "month",
    "max_posts": 50,
    "created_at": "2026-03-29T12:00:00Z",
    "completed_at": "2026-03-29T12:01:23Z",
    "provider": "demo",
    "model": "demo-model",
}

DEMO_STATISTICS = {
    "total_posts": 47,
    "analyzed_posts": 45,
    "skipped_posts": 2,
    "dominant_sentiment": "mixed",
    "dominant_emotion": "frustration",
    "estimated_cost": 0.00,
    "sentiment_counts": {
        "positive": 14,
        "negative": 16,
        "neutral": 8,
        "mixed": 7,
    },
    "emotion_counts": {
        "frustration": 12,
        "hope": 9,
        "joy": 7,
        "anger": 6,
        "surprise": 4,
        "sadness": 3,
        "fear": 2,
        "disgust": 2,
    },
    "community_counts": {
        "r/antiwork": 11,
        "r/remotework": 9,
        "r/cscareerquestions": 8,
        "r/technology": 7,
        "r/productivity": 6,
        "r/startups": 4,
        "r/workfromhome": 2,
    },
    "themes": [
        {
            "name": "Return-to-office mandates",
            "description": (
                "Strong negative reaction to companies forcing RTO policies, "
                "with many citing broken promises about permanent remote work."
            ),
            "percentage": 34.0,
            "post_count": 16,
            "sentiment_skew": "negative",
            "representative_quotes": [
                "My company promised permanent remote, now they want 3 days in office. Trust is gone.",
                "Every RTO announcement I see makes me update my resume immediately.",
            ],
        },
        {
            "name": "Productivity and autonomy",
            "description": (
                "Workers report higher productivity and satisfaction when "
                "given autonomy over their work location."
            ),
            "percentage": 26.0,
            "post_count": 12,
            "sentiment_skew": "positive",
            "representative_quotes": [
                "I get more done in 6 hours at home than 8 in the office. No contest.",
                "The freedom to structure my own day has been life-changing for my output.",
            ],
        },
        {
            "name": "Social isolation concerns",
            "description": (
                "Some workers express loneliness and difficulty maintaining "
                "team bonds without in-person interaction."
            ),
            "percentage": 19.0,
            "post_count": 9,
            "sentiment_skew": "negative",
            "representative_quotes": [
                "I love WFH but honestly I miss having work friends I see daily.",
                "New hires have it rough. Hard to build relationships over Zoom.",
            ],
        },
        {
            "name": "Hybrid as compromise",
            "description": (
                "Growing sentiment that 2-3 days hybrid represents a reasonable "
                "middle ground, though implementation varies widely."
            ),
            "percentage": 15.0,
            "post_count": 7,
            "sentiment_skew": "neutral",
            "representative_quotes": [
                "2 days in office feels like the sweet spot. Enough for collaboration, enough freedom.",
                "Hybrid only works if the office days are actually useful, not just attendance theater.",
            ],
        },
        {
            "name": "Geographic arbitrage",
            "description": (
                "Workers leveraging remote work to live in lower cost-of-living "
                "areas while keeping higher salaries."
            ),
            "percentage": 6.0,
            "post_count": 3,
            "sentiment_skew": "positive",
            "representative_quotes": [
                "Moved from SF to Boise. Same salary, mortgage is 1/4 of what rent was.",
            ],
        },
    ],
}


def load_demo_data() -> tuple[dict, dict]:
    """Return (job_dict, statistics_dict) for the demo analysis.

    These are static snapshots — no LLM calls, no network requests.
    """
    return DEMO_JOB, DEMO_STATISTICS
