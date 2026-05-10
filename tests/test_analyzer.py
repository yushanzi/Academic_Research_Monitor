import unittest
from unittest.mock import patch

from analysis.fulltext import analyze_papers
from config_schema import CandidateScoringConfig, RelevanceScoringConfig, app_config_from_dict
from models import InterestProfile, Paper
from scoring.rubric import candidate_to_abstract_relevance, gate_abstract_candidate, judge_relevance
from scoring.voting import _parse_judge_vote_response, judge_abstract_with_voting


class FakeProvider:
    def __init__(self, response: str):
        self.response = response
        self.last_prompt = ""
        self.last_system = ""

    def complete(self, prompt: str, system: str = "") -> str:
        self.last_prompt = prompt
        self.last_system = system
        return self.response


class AnalyzerTests(unittest.TestCase):
    def test_gate_abstract_candidate_parses_response_and_scores(self):
        provider = FakeProvider(
            """
            {
              "topic_match": 2,
              "must_have_match": 2,
              "exclude_match": 0,
              "evidence_strength": 2,
              "focus_specificity": 1,
              "matched_aspects": ["protein folding", "experimental validation"],
              "reason": "Strong topical match with clear validation signal."
            }
            """
        )
        paper = Paper(title="Test Paper", abstract="Protein folding with experiments.")
        profile = InterestProfile(core_topics=["protein folding"], must_have=["experimental validation"])

        result = gate_abstract_candidate(paper, provider, profile, CandidateScoringConfig())

        self.assertFalse(result.should_exclude)
        self.assertAlmostEqual(result.candidate_score, 0.925)
        self.assertEqual(result.topic_match, 2)
        self.assertEqual(result.must_have_match, 2)
        self.assertIn("protein folding", result.matched_aspects)

    def test_gate_abstract_candidate_uses_null_for_empty_constraints(self):
        provider = FakeProvider(
            """
            {
              "topic_match": 2,
              "must_have_match": null,
              "exclude_match": null,
              "evidence_strength": 1,
              "focus_specificity": 2,
              "matched_aspects": ["protein folding"],
              "reason": "Good abstract-only topical match."
            }
            """
        )
        paper = Paper(title="Test Paper", abstract="Protein folding study.")
        profile = InterestProfile(core_topics=["protein folding"])

        result = gate_abstract_candidate(paper, provider, profile, CandidateScoringConfig())

        self.assertIsNone(result.must_have_match)
        self.assertIsNone(result.exclude_match)
        self.assertAlmostEqual(result.candidate_score, 0.84375)

    def test_gate_abstract_candidate_requires_reason(self):
        provider = FakeProvider(
            """
            {
              "topic_match": 2,
              "must_have_match": null,
              "exclude_match": null,
              "evidence_strength": 1,
              "focus_specificity": 2,
              "matched_aspects": []
            }
            """
        )
        paper = Paper(title="Test Paper", abstract="Protein folding with experiments.")
        profile = InterestProfile(core_topics=["protein folding"])

        with self.assertRaises(RuntimeError):
            gate_abstract_candidate(paper, provider, profile, CandidateScoringConfig())

    def test_candidate_to_abstract_relevance_marks_selected_abstract(self):
        candidate_result = gate_abstract_candidate(
            Paper(title="Test Paper", abstract="Protein folding with experiments."),
            FakeProvider(
                """
                {
                  "topic_match": 2,
                  "must_have_match": 1,
                  "exclude_match": 0,
                  "evidence_strength": 2,
                  "focus_specificity": 1,
                  "matched_aspects": ["protein folding"],
                  "reason": "Strong abstract match."
                }
                """
            ),
            InterestProfile(core_topics=["protein folding"]),
            CandidateScoringConfig(),
        )

        result = candidate_to_abstract_relevance(candidate_result, CandidateScoringConfig())

        self.assertTrue(result.is_relevant)
        self.assertEqual(result.basis, "abstract_only")
        self.assertEqual(result.report_status, "selected")
        self.assertAlmostEqual(result.relevance_score, candidate_result.candidate_score)

    def test_candidate_to_abstract_relevance_allows_topic_match_zero_if_score_passes(self):
        candidate_result = gate_abstract_candidate(
            Paper(title="Test Paper", abstract="A tightly scoped study with strong method and results."),
            FakeProvider(
                """
                {
                  "topic_match": 0,
                  "must_have_match": 2,
                  "exclude_match": 0,
                  "evidence_strength": 2,
                  "focus_specificity": 2,
                  "matched_aspects": ["strong method"],
                  "reason": "Strong abstract signal despite weak topical wording overlap."
                }
                """
            ),
            InterestProfile(core_topics=["protein folding"], must_have=["strong method"]),
            CandidateScoringConfig(),
        )

        result = candidate_to_abstract_relevance(candidate_result, CandidateScoringConfig())

        self.assertAlmostEqual(result.relevance_score, 0.6)
        self.assertTrue(result.is_relevant)

    def test_judge_relevance_computes_final_score(self):
        provider = FakeProvider(
            """
            {
              "topic_match": 2,
              "must_have_match": 1,
              "exclude_match": 0,
              "evidence_quality": 2,
              "content_alignment": 2,
              "actionability": 1,
              "matched_aspects": ["protein folding"],
              "reason": "The full paper is strongly aligned with the monitoring interest."
            }
            """
        )
        paper = Paper(
            title="Test Paper",
            abstract="Protein folding abstract.",
            full_text="Detailed full text.",
            evidence_level="full_text",
        )
        profile = InterestProfile(core_topics=["protein folding"], must_have=["experimental validation"])

        result = judge_relevance(paper, provider, profile, RelevanceScoringConfig())

        self.assertTrue(result.is_relevant)
        self.assertAlmostEqual(result.relevance_score, 0.85)
        self.assertEqual(result.content_alignment, 2)

    def test_judge_relevance_prompt_clarifies_field_boundaries(self):
        provider = FakeProvider(
            """
            {
              "topic_match": 2,
              "must_have_match": null,
              "exclude_match": null,
              "evidence_quality": 1,
              "content_alignment": 2,
              "actionability": 1,
              "matched_aspects": ["protein folding"],
              "reason": "Useful to note but not a top-priority follow-up item."
            }
            """
        )
        paper = Paper(title="Test Paper", abstract="Protein folding abstract.")
        profile = InterestProfile(core_topics=["protein folding"], summary="Monitor protein folding.")

        judge_relevance(paper, provider, profile, RelevanceScoringConfig())

        self.assertEqual(provider.last_system, "You are an academic research analyst. Always respond in valid JSON.")
        self.assertIn("Score each field independently.", provider.last_prompt)
        self.assertIn("Do not use topical relevance alone to raise evidence_quality or actionability.", provider.last_prompt)
        self.assertIn("Do not use scientific rigor alone to raise content_alignment or actionability.", provider.last_prompt)
        self.assertIn("Novelty may increase actionability", provider.last_prompt)
        self.assertIn("low follow-up value for the monitoring workflow", provider.last_prompt)
        self.assertIn("clearly and centrally aligned with the user's monitoring interests", provider.last_prompt)
        self.assertIn("substantial results, comparisons, or clear validation", provider.last_prompt)

    def test_analyze_papers_parses_full_text_consistency(self):
        provider = FakeProvider(
            """
            {
              "research_direction": "蛋白质折叠建模",
              "innovation_points": ["创新点1", "创新点2"],
              "summary": "这是一段完整的全文总结。",
              "consistency_with_abstract": "weakens_abstract",
              "consistency_reason": "全文显示主要贡献偏向基础方法分析，与摘要里的应用导向表述相比相关性更弱。"
            }
            """
        )
        paper = Paper(
            title="Test Paper",
            abstract="Protein folding abstract.",
            full_text="Detailed full text.",
            evidence_level="full_text",
        )

        analyzed = analyze_papers([paper], provider, InterestProfile(summary="Monitor protein folding."))

        self.assertEqual(len(analyzed), 1)
        self.assertEqual(analyzed[0].analysis["consistency_with_abstract"], "weakens_abstract")
        self.assertIn("相关性更弱", analyzed[0].analysis["consistency_reason"])

    def test_gate_abstract_candidate_prompt_clarifies_semantic_topic_match(self):
        provider = FakeProvider(
            """
            {
              "topic_match": 1,
              "must_have_match": null,
              "exclude_match": null,
              "evidence_strength": 1,
              "focus_specificity": 1,
              "matched_aspects": ["protein folding"],
              "reason": "Semantically related abstract."
            }
            """
        )
        paper = Paper(title="Test Paper", abstract="Protein folding abstract.")
        profile = InterestProfile(core_topics=["protein folding"], summary="Monitor protein folding.")

        gate_abstract_candidate(paper, provider, profile, CandidateScoringConfig())

        self.assertIn("Evaluate topic_match by semantic meaning", provider.last_prompt)
        self.assertIn("Do not assign topic_match = 0 just because the abstract uses different terminology", provider.last_prompt)
        self.assertIn("keywords differ or synonyms are used", provider.last_prompt)

    def test_judge_abstract_with_voting_selects_on_two_of_three(self):
        config = app_config_from_dict(
            {
                "user": {"name": "monitor_a"},
                "sources": {"arxiv": {"enabled": True}},
                "llm": {"provider": "claude", "model": "fallback-model"},
                "email": {"recipient": "user@example.com"},
                "abstract_selection": {
                    "three_llm_voting": {
                        "judges": [
                            {"name": "j1", "provider": "claude", "model": "m1"},
                            {"name": "j2", "provider": "claude", "model": "m2"},
                            {"name": "j3", "provider": "claude", "model": "m3"},
                        ]
                    }
                },
            }
        )
        responses = {
            "j1": FakeProvider('{"is_relevant": true, "confidence": "high", "topic_match": "yes", "must_have_match": null, "exclude_match": null, "matched_aspects": ["protein folding"], "reason": "strong fit"}'),
            "j2": FakeProvider('{"is_relevant": true, "confidence": "medium", "topic_match": "partial", "must_have_match": null, "exclude_match": null, "matched_aspects": ["folding"], "reason": "related"}'),
            "j3": FakeProvider('{"is_relevant": false, "confidence": "medium", "topic_match": "no", "must_have_match": null, "exclude_match": null, "matched_aspects": [], "reason": "not central"}'),
        }
        with patch("scoring.voting.get_provider_from_llm_config", side_effect=lambda judge: responses[judge.name]):
            result = judge_abstract_with_voting(
                Paper(title="Test Paper", abstract="Protein folding abstract."),
                InterestProfile(core_topics=["protein folding"]),
                config.abstract_selection.three_llm_voting,
                FakeProvider("{}"),
                config.candidate_scoring,
            )

        self.assertTrue(result.is_relevant)
        self.assertEqual(result.method, "three_llm_voting")
        self.assertEqual(result.vote_summary["relevant_votes"], 2)
        self.assertFalse(result.degraded)

    def test_judge_abstract_with_voting_requires_all_remaining_when_judge_fails(self):
        config = app_config_from_dict(
            {
                "user": {"name": "monitor_a"},
                "sources": {"arxiv": {"enabled": True}},
                "llm": {"provider": "claude", "model": "fallback-model"},
                "email": {"recipient": "user@example.com"},
                "abstract_selection": {
                    "three_llm_voting": {
                        "judges": [
                            {"name": "j1", "provider": "claude", "model": "m1"},
                            {"name": "j2", "provider": "claude", "model": "m2"},
                            {"name": "j3", "provider": "claude", "model": "m3"},
                        ]
                    }
                },
            }
        )
        responses = {
            "j1": FakeProvider('{"is_relevant": true, "confidence": "high", "topic_match": "yes", "must_have_match": null, "exclude_match": null, "matched_aspects": ["protein folding"], "reason": "strong fit"}'),
            "j2": FakeProvider('{"is_relevant": false, "confidence": "low", "topic_match": "no", "must_have_match": null, "exclude_match": null, "matched_aspects": [], "reason": "not fit"}'),
        }

        def provider_factory(judge):
            if judge.name == "j3":
                raise RuntimeError("judge unavailable")
            return responses[judge.name]

        with patch("scoring.voting.get_provider_from_llm_config", side_effect=provider_factory):
            result = judge_abstract_with_voting(
                Paper(title="Test Paper", abstract="Protein folding abstract."),
                InterestProfile(core_topics=["protein folding"]),
                config.abstract_selection.three_llm_voting,
                FakeProvider("{}"),
                config.candidate_scoring,
            )

        self.assertFalse(result.is_relevant)
        self.assertTrue(result.degraded)
        self.assertEqual(result.vote_summary["decision_rule"], "all_remaining_judges_must_pass")
        self.assertEqual(result.failed_judges, ["j3"])

    def test_judge_abstract_with_voting_falls_back_to_candidate_score_when_all_judges_fail(self):
        config = app_config_from_dict(
            {
                "user": {"name": "monitor_a"},
                "sources": {"arxiv": {"enabled": True}},
                "llm": {"provider": "claude", "model": "fallback-model"},
                "email": {"recipient": "user@example.com"},
            }
        )
        fallback_provider = FakeProvider(
            """
            {
              "topic_match": 2,
              "must_have_match": null,
              "exclude_match": null,
              "evidence_strength": 1,
              "focus_specificity": 2,
              "matched_aspects": ["protein folding"],
              "reason": "Good fallback match."
            }
            """
        )
        with patch("scoring.voting.get_provider_from_llm_config", side_effect=RuntimeError("judge unavailable")):
            result = judge_abstract_with_voting(
                Paper(title="Test Paper", abstract="Protein folding abstract."),
                InterestProfile(core_topics=["protein folding"]),
                config.abstract_selection.three_llm_voting,
                fallback_provider,
                config.candidate_scoring,
            )

        self.assertTrue(result.is_relevant)
        self.assertEqual(result.basis, "abstract_candidate_score_fallback")
        self.assertTrue(result.degraded)
        self.assertEqual(len(result.failed_judges), 3)

    def test_parse_judge_vote_response_accepts_string_null_and_case_variants(self):
        vote = _parse_judge_vote_response(
            """
            {
              "is_relevant": false,
              "confidence": "HIGH",
              "topic_match": "No",
              "must_have_match": "null",
              "exclude_match": "None",
              "matched_aspects": [],
              "reason": "Not relevant."
            }
            """,
            "judge_1",
            InterestProfile(),
        )

        self.assertEqual(vote.confidence, "high")
        self.assertEqual(vote.topic_match, "no")
        self.assertIsNone(vote.must_have_match)
        self.assertIsNone(vote.exclude_match)

    def test_parse_judge_vote_response_accepts_unquoted_enum_values(self):
        vote = _parse_judge_vote_response(
            """
            {
              "is_relevant": false,
              "confidence": medium,
              "topic_match": partial,
              "must_have_match": no,
              "exclude_match": possible,
              "matched_aspects": ["protein folding"],
              "reason": "Borderline match."
            }
            """,
            "judge_1",
            InterestProfile(must_have=["experiment"], exclude=["review"]),
        )

        self.assertEqual(vote.confidence, "medium")
        self.assertEqual(vote.topic_match, "partial")
        self.assertEqual(vote.must_have_match, "no")
        self.assertEqual(vote.exclude_match, "possible")

    def test_judge_abstract_with_voting_prompt_requires_strict_json_enums(self):
        config = app_config_from_dict(
            {
                "user": {"name": "monitor_a"},
                "sources": {"arxiv": {"enabled": True}},
                "llm": {"provider": "claude", "model": "fallback-model"},
                "email": {"recipient": "user@example.com"},
            }
        )
        provider = FakeProvider(
            '{"is_relevant": true, "confidence": "high", "topic_match": "yes", "must_have_match": null, "exclude_match": null, "matched_aspects": ["protein folding"], "reason": "fit"}'
        )

        with patch("scoring.voting.get_provider_from_llm_config", return_value=provider):
            judge_abstract_with_voting(
                Paper(title="Test Paper", abstract="Protein folding abstract."),
                InterestProfile(core_topics=["protein folding"]),
                config.abstract_selection.three_llm_voting,
                FakeProvider("{}"),
                config.candidate_scoring,
            )

        self.assertIn('All enum values must be JSON strings with double quotes.', provider.last_prompt)
        self.assertIn('Use JSON null for absent optional fields; never return the string "null".', provider.last_prompt)
        self.assertIn('Example valid JSON:', provider.last_prompt)


if __name__ == "__main__":
    unittest.main()
