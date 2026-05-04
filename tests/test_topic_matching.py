import unittest

from models import InterestProfile
from sources.base import (
    deduplicate_papers,
    find_matching_topics,
    matches_interest_profile,
    matches_topics,
)


class TopicMatchingTests(unittest.TestCase):
    def test_matches_exact_phrase(self):
        text = "This paper studies protein folding dynamics using diffusion models."
        topics = ["protein folding dynamics"]

        self.assertTrue(matches_topics(text, topics))

    def test_matches_significant_keyword_overlap(self):
        text = "We present a system for small molecule design and drug discovery."
        topics = ["small molecule drug discovery and design"]

        self.assertTrue(matches_topics(text, topics))

    def test_avoids_generic_partial_match(self):
        text = "This work focuses on molecule transport in plant cells."
        topics = ["small molecule drug discovery and design"]

        self.assertFalse(matches_topics(text, topics))

    def test_returns_multiple_matching_topics(self):
        text = (
            "This paper studies protein folding dynamics and small molecule "
            "drug discovery using shared generative models."
        )
        topics = [
            "protein folding dynamics",
            "small molecule drug discovery and design",
        ]

        matched = find_matching_topics(text, topics)

        self.assertEqual(matched, topics)

    def test_deduplicate_merges_matched_topics(self):
        papers = [
            {
                "title": "Shared paper",
                "doi": "10.1000/test",
                "matched_topics": ["topic-a"],
            },
            {
                "title": "Shared paper",
                "doi": "10.1000/test",
                "matched_topics": ["topic-b"],
            },
        ]

        deduped = deduplicate_papers(papers)

        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0].matched_topics, ["topic-a", "topic-b"])

    def test_interest_profile_requires_at_least_one_must_have_match(self):
        profile = InterestProfile(
            core_topics=["protein folding"],
            synonyms=["folding model"],
            must_have=["experimental validation", "wet lab"],
        )

        matched, matched_topics = matches_interest_profile(
            "This protein folding paper uses a strong folding model but includes no experiments.",
            profile,
        )

        self.assertFalse(matched)
        self.assertEqual(matched_topics, [])

    def test_interest_profile_accepts_any_must_have_match(self):
        profile = InterestProfile(
            core_topics=["protein folding"],
            synonyms=["folding model"],
            must_have=["experimental validation", "wet lab"],
        )

        matched, matched_topics = matches_interest_profile(
            "This protein folding paper includes experimental validation and a new folding model.",
            profile,
        )

        self.assertTrue(matched)
        self.assertIn("protein folding", matched_topics)
        self.assertIn("experimental validation", matched_topics)

    def test_interest_profile_exclude_still_overrides_must_have(self):
        profile = InterestProfile(
            core_topics=["protein folding"],
            must_have=["experimental validation"],
            exclude=["review"],
        )

        matched, matched_topics = matches_interest_profile(
            "A review of protein folding with experimental validation.",
            profile,
        )

        self.assertFalse(matched)
        self.assertEqual(matched_topics, [])


if __name__ == "__main__":
    unittest.main()
