import unittest

from scripts.analyzer import build_analysis_prompt, parse_analysis_response
from scripts.collector import deduplicate_posts
from scripts.config_utils import normalize_config
from scripts.thematic_analyzer import parse_theme_response
from scripts.thematic_analyzer import calculate_overall_statistics


class ParserAndConfigTests(unittest.TestCase):
    def test_parse_analysis_response_extracts_fields(self):
        response = (
            "SENTIMENT: mixed\n"
            "EMOTION: skeptical\n"
            "CONFIDENCE: uncertain\n"
            "KEY_POINT: Users support the goal but doubt the implementation details.\n"
        )
        parsed = parse_analysis_response(response)
        self.assertEqual(parsed["sentiment"], "mixed")
        self.assertEqual(parsed["emotion"], "skeptical")
        self.assertEqual(parsed["confidence"], "uncertain")
        self.assertIn("implementation", parsed["key_point"])

    def test_parse_theme_response_extracts_sections(self):
        response = """
MAJOR_THEMES:
1. Policy coordination - 45% of posts discuss this
2. Funding concerns - 30% of posts discuss this
3. Public trust - 25% of posts discuss this

NOVEL_IDEAS:
- Citizen climate assemblies linked to local budgets
- Public dashboards for policy implementation milestones

KEY_CRITIQUES:
- Messaging is too vague (frequent)
- Costs are underspecified (occasional)

REGIONAL_PATTERNS:
- Europe: Stronger focus on coordination and standards
- United States: More debate over costs and implementation

SENTIMENT_SUMMARY:
Overall sentiment is mixed with medium confidence.
Participants support the direction but remain cautious about execution.
""".strip()

        parsed = parse_theme_response(response)
        self.assertGreaterEqual(len(parsed["major_themes"]), 3)
        self.assertEqual(parsed["major_themes"][0]["theme"], "Policy coordination")
        self.assertEqual(parsed["key_critiques"][0]["frequency"], "frequent")
        self.assertIn("Europe", parsed["regional_patterns"])
        self.assertEqual(parsed["sentiment_summary"]["overall"], "mixed")

    def test_deduplicate_posts_merges_phrase_matches_and_metrics(self):
        posts = [
            {
                "post_id": "abc123",
                "phrase_match": "climate policy",
                "title": "Post title",
                "text": "Body",
                "subreddit": "news",
                "author": "user1",
                "url": "https://example.com/1",
                "timestamp": "2026-02-01T00:00:00",
                "upvotes": 10,
                "comments": 2,
                "top_comments": [{"comment_id": "c1", "body": "A", "replies": []}],
            },
            {
                "post_id": "abc123",
                "phrase_match": "renewable energy",
                "title": "Post title",
                "text": "Body",
                "subreddit": "news",
                "author": "user1",
                "url": "https://example.com/1",
                "timestamp": "2026-02-01T00:00:00",
                "upvotes": 25,
                "comments": 5,
                "top_comments": [{"comment_id": "c1", "body": "A", "replies": []}],
            },
        ]

        deduped = deduplicate_posts(posts)
        self.assertEqual(len(deduped), 1)
        merged = deduped[0]
        self.assertEqual(merged["upvotes"], 25)
        self.assertEqual(merged["comments"], 5)
        self.assertIn("climate policy", merged.get("phrase_matches", []))
        self.assertIn("renewable energy", merged.get("phrase_matches", []))

    def test_normalize_config_coerces_common_yaml_types(self):
        config = {
            "sources": {"reddit": "true", "x": "false"},
            "output": {"data_retention_days": "30"},
            "collector": {"request_timeout_seconds": "15", "retry_backoff_seconds": "2.5"},
            "logging": {"file": "logs/test.log"},
            "analysis": {"unit": "THREAD", "max_comments_in_prompt": "4"},
        }

        normalized = normalize_config(config)
        self.assertIs(normalized["sources"]["reddit"], True)
        self.assertIs(normalized["sources"]["x"], False)
        self.assertEqual(normalized["output"]["data_retention_days"], 30)
        self.assertEqual(normalized["collector"]["request_timeout_seconds"], 15)
        self.assertEqual(normalized["collector"]["retry_backoff_seconds"], 2.5)
        self.assertEqual(normalized["analysis"]["unit"], "thread")
        self.assertEqual(normalized["analysis"]["max_comments_in_prompt"], 4)
        self.assertTrue(normalized["logging"]["file"].endswith("logs/test.log"))

    def test_build_analysis_prompt_thread_mode_includes_comment_context(self):
        post = {
            "post_id": "p1",
            "phrase_match": "electricity grid expansion in europe",
            "title": "Transmission expansion is lagging",
            "text": "Utilities warn that permitting delays are slowing new interconnectors.",
            "source_platform": "reddit",
            "community_name": "energy",
            "subreddit": "energy",
            "detected_region": "Europe",
            "detected_language": "en",
            "upvotes": 42,
            "comments": 8,
            "top_comments": [
                {
                    "body": "Permitting is the bottleneck, not engineering capacity.",
                    "replies": [{"body": "Cross-border coordination is also a problem."}],
                },
                {
                    "body": "Grid planning needs to anticipate renewable build-out years earlier.",
                    "replies": [],
                },
            ],
        }
        config = normalize_config({"analysis": {"unit": "thread"}})

        prompt = build_analysis_prompt(post, config=config)

        self.assertIn("discussion thread", prompt.lower())
        self.assertIn("THREAD CONTEXT", prompt)
        self.assertIn("C1:", prompt)
        self.assertIn("R1.1:", prompt)
        self.assertIn("COMMUNITY: energy", prompt)

    def test_calculate_overall_statistics_builds_community_sentiment_matrix(self):
        posts = [
            {
                "post_id": "r1",
                "phrase_match": "grid expansion",
                "subreddit": "energy",
                "community_name": "energy",
                "community_kind": "forum",
                "source_platform": "reddit",
                "detected_language": "en",
                "detected_region": "Europe",
                "upvotes": 20,
                "comments": 6,
                "url": "https://example.com/r1",
                "timestamp": "2026-02-01T00:00:00",
                "sentiment_analysis": {
                    "sentiment": "negative",
                    "emotion": "concerned",
                    "confidence": "certain",
                    "key_point": "Permitting delays are blocking transmission build-out.",
                    "analysis_unit": "thread",
                    "thread_context_enabled": True,
                    "thread_context_comments_used": 2,
                    "thread_context_replies_used": 1,
                },
            },
            {
                "post_id": "r2",
                "phrase_match": "grid expansion",
                "subreddit": "energy",
                "community_name": "energy",
                "community_kind": "forum",
                "source_platform": "reddit",
                "detected_language": "en",
                "detected_region": "Europe",
                "upvotes": 10,
                "comments": 2,
                "url": "https://example.com/r2",
                "timestamp": "2026-02-02T00:00:00",
                "sentiment_analysis": {
                    "sentiment": "negative",
                    "emotion": "skeptical",
                    "confidence": "questioning",
                    "key_point": "Costs remain underspecified for many proposed upgrades.",
                    "analysis_unit": "thread",
                    "thread_context_enabled": True,
                    "thread_context_comments_used": 1,
                    "thread_context_replies_used": 0,
                },
            },
            {
                "post_id": "x1",
                "phrase_match": "grid expansion",
                "subreddit": "twitter_x",
                "community_name": "Open social feed",
                "community_kind": "social",
                "source_platform": "x",
                "detected_language": "en",
                "detected_region": "Europe",
                "upvotes": 30,
                "comments": 4,
                "url": "https://example.com/x1",
                "timestamp": "2026-02-03T00:00:00",
                "sentiment_analysis": {
                    "sentiment": "positive",
                    "emotion": "hopeful",
                    "confidence": "certain",
                    "key_point": "Interconnector upgrades can unlock stranded renewable generation.",
                    "analysis_unit": "post",
                    "thread_context_enabled": False,
                    "thread_context_comments_used": 0,
                    "thread_context_replies_used": 0,
                },
            },
        ]

        stats = calculate_overall_statistics(posts, themes={})

        self.assertIn("community_sentiment_matrix", stats)
        energy = stats["community_sentiment_matrix"]["energy"]
        self.assertEqual(energy["total_posts"], 2)
        self.assertEqual(energy["dominant_sentiment"], "negative")
        self.assertEqual(energy["certain_posts"], 1)
        self.assertIn("top_key_points", energy)
        self.assertTrue(any(item["quote"] for item in energy["top_key_points"]))

        self.assertIn("analysis_context_summary", stats)
        self.assertEqual(stats["analysis_context_summary"]["analysis_unit_distribution"]["thread"], 2)
        self.assertEqual(stats["analysis_context_summary"]["analysis_unit_distribution"]["post"], 1)


if __name__ == "__main__":
    unittest.main()
