"""
Data Exporter Module

Exports analyzed posts and thematic analysis data to CSV, JSON, and ZIP
formats for downstream analysis in Excel, R, Python, or BI tools.
"""

import csv
import io
import json
import logging
import zipfile
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


def export_posts_to_csv(analyzed_posts: list) -> str:
    """Convert analyzed posts to CSV string.

    Columns: post_id, title, text, author, community, source_platform,
    upvotes, comment_count, sentiment, emotion, emotion_intensity,
    confidence, sarcasm_detected, key_point, emotional_driver,
    detected_language, detected_region, poster_region, topic_region,
    url, timestamp, phrase_matches
    """
    output = io.StringIO()
    fieldnames = [
        'post_id', 'title', 'text', 'author', 'community', 'source_platform',
        'upvotes', 'comment_count', 'sentiment', 'emotion', 'secondary_emotion',
        'emotion_intensity', 'confidence', 'sarcasm_detected', 'key_point',
        'emotional_driver', 'detected_language', 'detected_region',
        'poster_region', 'topic_region', 'url',
        'timestamp', 'phrase_matches'
    ]

    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction='ignore')
    writer.writeheader()

    for post in analyzed_posts:
        analysis = post.get('sentiment_analysis', {}) or {}
        row = {
            'post_id': post.get('post_id', ''),
            'title': post.get('title', ''),
            'text': (post.get('text', '') or post.get('body', ''))[:500],  # Truncate long text
            'author': post.get('author', ''),
            'community': post.get('subreddit', post.get('community', '')),
            'source_platform': post.get('source_platform', ''),
            'upvotes': post.get('upvotes', 0),
            'comment_count': post.get('comments', post.get('comment_count', 0)),
            'sentiment': analysis.get('sentiment', ''),
            'emotion': analysis.get('emotion', analysis.get('primary_emotion', '')),
            'secondary_emotion': analysis.get('secondary_emotion', ''),
            'emotion_intensity': analysis.get('emotion_intensity', analysis.get('intensity', '')),
            'confidence': analysis.get('confidence', ''),
            'sarcasm_detected': analysis.get('sarcasm_detected', False),
            'key_point': analysis.get('key_point', ''),
            'emotional_driver': analysis.get('emotional_driver', ''),
            'detected_language': post.get('detected_language', ''),
            'detected_region': post.get('detected_region', ''),
            'poster_region': post.get('poster_region', ''),
            'topic_region': post.get('topic_region', ''),
            'url': post.get('url', ''),
            'timestamp': post.get('timestamp', ''),
            'phrase_matches': ', '.join(post.get('phrase_matches', [])) if isinstance(post.get('phrase_matches'), list) else str(post.get('phrase_matches', '')),
        }
        writer.writerow(row)

    return output.getvalue()


def export_themes_to_json(themes_data: dict) -> str:
    """Export thematic analysis as formatted JSON."""
    return json.dumps(themes_data, indent=2, ensure_ascii=False, default=str)


def create_export_zip(
    analyzed_posts_path: str,
    themes_path: str,
    pdf_path: Optional[str] = None,
) -> bytes:
    """Create a ZIP file containing CSV, JSON, and optionally PDF.

    Args:
        analyzed_posts_path: Path to analyzed posts JSON file
        themes_path: Path to themes JSON file
        pdf_path: Optional path to the generated PDF report

    Returns:
        ZIP file contents as bytes
    """
    # Load data
    with open(analyzed_posts_path, 'r', encoding='utf-8') as f:
        analyzed_posts = json.load(f)

    with open(themes_path, 'r', encoding='utf-8') as f:
        themes_data = json.load(f)

    # Generate exports
    csv_content = export_posts_to_csv(analyzed_posts)
    json_content = export_themes_to_json(themes_data)

    # Create ZIP
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('analyzed_posts.csv', csv_content)
        zf.writestr('thematic_analysis.json', json_content)
        zf.writestr('raw_analyzed_posts.json', json.dumps(analyzed_posts, indent=2, ensure_ascii=False, default=str))

        if pdf_path and Path(pdf_path).exists():
            pdf_name = Path(pdf_path).name
            zf.write(pdf_path, pdf_name)

    return zip_buffer.getvalue()
