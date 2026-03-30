"""Tests for signalstream.collectors.base — sanitization and abstract interface."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from signalstream.collectors.base import BaseCollector, sanitize_post
from signalstream.db.models import Comment, Post


def _make_post(**overrides) -> Post:
    defaults = dict(
        platform="reddit", id="p1", author="user1",
        text="Clean text", title="Clean title",
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        url="https://example.com", community="test", engagement=10,
    )
    defaults.update(overrides)
    return Post(**defaults)


class TestSanitizePost:
    def test_strips_script_tags_from_text(self) -> None:
        post = _make_post(text='Hello <script>alert("xss")</script> world')
        sanitized = sanitize_post(post)
        assert "<script>" not in sanitized.text
        assert "Hello" in sanitized.text
        assert "world" in sanitized.text

    def test_strips_script_tags_from_title(self) -> None:
        post = _make_post(title='Title <script>evil()</script>')
        sanitized = sanitize_post(post)
        assert "<script>" not in (sanitized.title or "")

    def test_sanitizes_comment_bodies(self) -> None:
        comment = Comment(
            id="c1", body='<img src=x onerror=alert(1)> Nice post',
            author="u1", score=5,
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            depth=1,
        )
        post = _make_post(comments=[comment])
        sanitized = sanitize_post(post)
        assert "onerror" not in sanitized.comments[0].body

    def test_sanitizes_nested_replies(self) -> None:
        reply = Comment(
            id="r1", body='<a href="javascript:void(0)">click</a>',
            author="u2", score=1,
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            depth=2,
        )
        comment = Comment(
            id="c1", body="Safe", author="u1", score=5,
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
            depth=1, replies=[reply],
        )
        post = _make_post(comments=[comment])
        sanitized = sanitize_post(post)
        assert "javascript:" not in sanitized.comments[0].replies[0].body

    def test_preserves_clean_text(self) -> None:
        post = _make_post(text="This is perfectly clean text with no HTML.")
        sanitized = sanitize_post(post)
        assert sanitized.text == "This is perfectly clean text with no HTML."

    def test_handles_none_title(self) -> None:
        post = _make_post(title=None)
        sanitized = sanitize_post(post)
        assert sanitized.title is None

    def test_returns_new_post_object(self) -> None:
        post = _make_post()
        sanitized = sanitize_post(post)
        assert sanitized is not post


class TestBaseCollector:
    def test_cannot_instantiate_directly(self) -> None:
        with pytest.raises(TypeError):
            BaseCollector()  # type: ignore[abstract]
