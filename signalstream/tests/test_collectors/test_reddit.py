"""Tests for signalstream.collectors.reddit."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from signalstream.collectors.reddit import RedditCollector


def _make_reddit_response(
    posts: list[dict],
    after: str | None = None,
) -> dict:
    """Build a mock Reddit JSON search response."""
    children = []
    for p in posts:
        children.append({
            "kind": "t3",
            "data": {
                "id": p.get("id", "abc123"),
                "title": p.get("title", "Test Post"),
                "selftext": p.get("selftext", "Test content"),
                "author": p.get("author", "testuser"),
                "subreddit": p.get("subreddit", "testsubreddit"),
                "score": p.get("score", 42),
                "upvote_ratio": p.get("upvote_ratio", 0.95),
                "permalink": p.get("permalink", "/r/test/comments/abc123/test_post/"),
                "created_utc": p.get("created_utc", 1735689600),
                "link_flair_text": p.get("flair", None),
                "is_crosspost_child": False,
                "crosspost_parent": None,
                "num_comments": 5,
            },
        })
    return {
        "data": {
            "children": children,
            "after": after,
        }
    }


class TestRedditCollector:
    def test_collects_posts_from_search(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = _make_reddit_response(
            [{"id": "p1", "title": "First Post"}]
        )

        with patch("signalstream.collectors.reddit.ResilientClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value = mock_client

            collector = RedditCollector()
            posts = collector.collect("Python", max_posts=10)

        assert len(posts) == 1
        assert posts[0].platform == "reddit"
        assert posts[0].community == "testsubreddit"

    def test_deduplicates_by_post_id(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = _make_reddit_response(
            [
                {"id": "p1", "title": "Duplicate"},
                {"id": "p1", "title": "Duplicate"},
            ]
        )

        with patch("signalstream.collectors.reddit.ResilientClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value = mock_client

            collector = RedditCollector()
            posts = collector.collect("test", max_posts=10)

        assert len(posts) == 1

    def test_pagination_with_after_cursor(self) -> None:
        page1 = MagicMock()
        page1.status_code = 200
        page1.json.return_value = _make_reddit_response(
            [{"id": "p1"}], after="cursor123"
        )

        page2 = MagicMock()
        page2.status_code = 200
        page2.json.return_value = _make_reddit_response(
            [{"id": "p2"}], after=None
        )

        with patch("signalstream.collectors.reddit.ResilientClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get.side_effect = [page1, page2]
            mock_client_cls.return_value = mock_client

            collector = RedditCollector()
            posts = collector.collect("test", max_posts=10)

        assert len(posts) == 2
        assert mock_client.get.call_count == 2

    def test_stops_at_max_posts(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = _make_reddit_response(
            [{"id": f"p{i}"} for i in range(25)],
            after="more_pages",
        )

        with patch("signalstream.collectors.reddit.ResilientClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value = mock_client

            collector = RedditCollector()
            posts = collector.collect("test", max_posts=5)

        assert len(posts) <= 5

    def test_user_agent_header(self) -> None:
        with patch("signalstream.collectors.reddit.ResilientClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = _make_reddit_response([])
            mock_client.get.return_value = mock_response
            mock_client_cls.return_value = mock_client

            RedditCollector()
            call_kwargs = mock_client_cls.call_args[1]
            assert "Signalstream" in call_kwargs.get("user_agent", "")
