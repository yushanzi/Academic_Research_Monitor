ANALYSIS_PROMPT = """Analyze the following paper and provide the analysis in Chinese.

Interest profile summary:
{interest_summary}
Paper title: {title}
Evidence level: {evidence_level}
Content:
{content}

Respond in JSON with exactly these keys:
- research_direction: brief description of the research area and direction (1-2 sentences in Chinese)
- innovation_points: 2-3 core innovation points (array of Chinese strings)
- summary: 150-220 Chinese characters summarizing the paper
- consistency_with_abstract: one of supports_abstract, weakens_abstract, or unclear
- consistency_reason: concise Chinese explanation of whether the accessible content supports or weakens the abstract-level relevance judgement. If only the abstract is available, return unclear and explain that no full text was available.

JSON only, no markdown fences."""

TREND_PROMPT = """Based on the following {count} selected papers, provide a trend analysis and follow-up suggestions in Chinese.

Interest profile summary:
{interest_summary}

Papers:
{paper_list}

Respond in JSON with exactly these keys:
- trends: trend summary in Chinese (2-3 paragraphs)
- suggestions: array of 3-5 Chinese follow-up suggestions

JSON only, no markdown fences."""
