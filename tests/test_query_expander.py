import unittest

from scripts.config_utils import normalize_config
from scripts.query_expander import resolve_search_phrases


class QueryExpanderTests(unittest.TestCase):
    def test_reddit_expands_europe_grid_topic(self):
        config = normalize_config(
            {
                "search": {
                    "topic": "Electricity grid expansion in Europe",
                    "auto_expand": True,
                    "reddit_expansion_count": 6,
                }
            }
        )

        phrases = resolve_search_phrases(config, platform="reddit")

        self.assertGreaterEqual(len(phrases), 4)
        self.assertIn("Electricity grid expansion in Europe", phrases)
        self.assertTrue(any("Europe" in phrase or "European" in phrase for phrase in phrases))
        self.assertTrue(any("grid" in phrase.lower() for phrase in phrases))

    def test_x_expansion_defaults_to_raw_queries(self):
        config = normalize_config(
            {
                "search": {
                    "topic": "Electricity grid expansion in Europe",
                    "auto_expand": True,
                    "x_expansion_count": 5,
                }
            }
        )

        phrases = resolve_search_phrases(config, platform="x")

        self.assertGreaterEqual(len(phrases), 3)
        self.assertTrue(all(isinstance(phrase, str) for phrase in phrases))
        self.assertTrue(all(phrase.startswith("raw:") for phrase in phrases))

    def test_x_expansion_can_disable_raw_queries(self):
        config = normalize_config(
            {
                "search": {
                    "topic": "electricity grid expansion europe",
                    "auto_expand": True,
                    "x_use_raw_queries": False,
                    "x_expansion_count": 4,
                }
            }
        )

        phrases = resolve_search_phrases(config, platform="x")

        self.assertGreaterEqual(len(phrases), 2)
        self.assertFalse(any(phrase.startswith("raw:") for phrase in phrases))

    def test_auto_expand_false_preserves_key_phrases(self):
        config = normalize_config(
            {
                "search": {
                    "topic": "ignored topic",
                    "key_phrases": ["alpha", "beta"],
                    "auto_expand": False,
                }
            }
        )

        phrases = resolve_search_phrases(config, platform="reddit")

        self.assertEqual(phrases, ["alpha", "beta"])


if __name__ == "__main__":
    unittest.main()
