"""Reddit collector — public JSON endpoints with optional PRAW upgrade path.

Rate limited to 30 RPM for public JSON. User-Agent identifies the tool.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from signalstream.collectors.base import BaseCollector
from signalstream.collectors.http import RateLimiter, ResilientClient
from signalstream.db.models import Post

logger = logging.getLogger(__name__)

_USER_AGENT = "Signalstream/0.1.0"
_REDDIT_BASE_URL = "https://www.reddit.com"
_PUBLIC_JSON_RPM = 30


class RedditCollector(BaseCollector):
    """Collect posts from Reddit via public JSON endpoints."""

    def __init__(self, user_agent: str = _USER_AGENT) -> None:
        self._rate_limiter = RateLimiter(rpm=_PUBLIC_JSON_RPM)
        self._client = ResilientClient(
            user_agent=user_agent,
            retries=3,
            base_delay=2.0,
            rate_limiter=self._rate_limiter,
        )

    def _collect_raw(
        self,
        query: str,
        *,
        max_posts: int = 100,
        time_range: str = "week",
    ) -> list[Post]:
        posts: list[Post] = []
        seen_ids: set[str] = set()
        after: str | None = None

        per_page = min(25, max_posts)

        while len(posts) < max_posts:
            params: dict = {
                "q": query,
                "sort": "relevance",
                "t": time_range,
                "limit": per_page,
                "raw_json": 1,
            }
            if after:
                params["after"] = after

            try:
                response = self._client.get(
                    f"{_REDDIT_BASE_URL}/search.json",
                    params=params,
                )
                if response.status_code != 200:
                    logger.warning(
                        "Reddit search returned status %d", response.status_code
                    )
                    break

                data = response.json()

            except Exception as e:
                logger.error("Reddit search request failed: %s", e)
                break

            children = data.get("data", {}).get("children", [])
            if not children:
                break

            for child in children:
                if len(posts) >= max_posts:
                    break

                post_data = child.get("data", {})
                post_id = post_data.get("id", "")
                dedup_key = f"reddit:{post_id}"

                if dedup_key in seen_ids:
                    continue
                seen_ids.add(dedup_key)

                post = self._parse_post(post_data)
                post.phrase_matches = [query]
                posts.append(post)

            after = data.get("data", {}).get("after")
            if not after:
                break

        logger.info(
            "Reddit collected %d posts for query '%s' (time_range=%s)",
            len(posts), query, time_range,
        )
        return posts

    @staticmethod
    def _parse_post(data: dict) -> Post:
        created_utc = data.get("created_utc", 0)
        timestamp = datetime.fromtimestamp(created_utc, tz=timezone.utc)

        permalink = data.get("permalink", "")
        url = f"https://www.reddit.com{permalink}" if permalink else ""

        return Post(
            platform="reddit",
            id=data.get("id", ""),
            author=data.get("author", "[deleted]"),
            text=data.get("selftext", ""),
            title=data.get("title"),
            timestamp=timestamp,
            url=url,
            community=data.get("subreddit", ""),
            engagement=data.get("score", 0),
            upvote_ratio=data.get("upvote_ratio"),
            flair=data.get("link_flair_text"),
            is_crosspost=bool(data.get("is_crosspost_child", False)),
            crosspost_source=data.get("crosspost_parent"),
        )
