"""Abstract collector interface and content sanitization.

Every collector inherits from BaseCollector and uses sanitize_post() to clean
all text fields before returning results. Sanitization is mandatory — it is
enforced by the base class's collect() template method.

Uses nh3 for HTML sanitization (BOARD-003).
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import replace

import nh3

from signalstream.db.models import Comment, Post

logger = logging.getLogger(__name__)


def _sanitize_text(text: str) -> str:
    """Strip all HTML tags from text, keeping only safe content."""
    return nh3.clean(text, tags=set())


def _sanitize_comment(comment: Comment) -> Comment:
    """Recursively sanitize a comment and its replies."""
    return Comment(
        id=comment.id,
        body=_sanitize_text(comment.body),
        author=comment.author,
        score=comment.score,
        timestamp=comment.timestamp,
        depth=comment.depth,
        replies=[_sanitize_comment(r) for r in comment.replies],
    )


def sanitize_post(post: Post) -> Post:
    """Sanitize all text fields in a Post using nh3.

    Applies nh3.clean() to post.text, post.title, and all comment.body fields
    recursively. Returns a new Post object — the original is not mutated.

    This is not optional — every collector must call this before returning
    results (enforced by BaseCollector).
    """
    return replace(
        post,
        text=_sanitize_text(post.text),
        title=_sanitize_text(post.title) if post.title is not None else None,
        comments=[_sanitize_comment(c) for c in post.comments],
    )


class BaseCollector(ABC):
    """Abstract base for data collectors.

    Subclasses implement _collect_raw() to fetch posts from a platform.
    The public collect() method calls _collect_raw() and then sanitizes
    all results automatically.
    """

    def collect(
        self,
        query: str,
        *,
        max_posts: int = 100,
        time_range: str = "week",
    ) -> list[Post]:
        """Collect posts matching a query, with automatic sanitization."""
        raw_posts = self._collect_raw(query, max_posts=max_posts, time_range=time_range)
        sanitized = [sanitize_post(p) for p in raw_posts]
        logger.info(
            "Collected and sanitized %d posts for query '%s'",
            len(sanitized), query,
        )
        return sanitized

    @abstractmethod
    def _collect_raw(
        self,
        query: str,
        *,
        max_posts: int = 100,
        time_range: str = "week",
    ) -> list[Post]:
        """Fetch raw (unsanitized) posts from the platform."""
        ...
