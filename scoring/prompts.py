SYSTEM_PROMPT = "You are an academic research analyst. Always respond in valid JSON."

RELEVANCE_PROMPT = """Determine the paper's final relevance using the best available evidence.

Interest profile summary:
{interest_summary}
Core topics: {core_topics}
Must-have constraints: {must_have}
Exclude constraints: {exclude}

Paper title: {title}
Evidence level: {evidence_level}
Accessible content:
{content}

Return JSON with exactly these keys:
- topic_match: integer 0, 1, or 2
- must_have_match: integer 0, 1, or 2, or null when no must-have constraints exist
- exclude_match: integer 0, 1, or 2, or null when no exclude constraints exist
- evidence_quality: integer 0, 1, or 2
- content_alignment: integer 0, 1, or 2
- actionability: integer 0, 1, or 2
- matched_aspects: array of matched topics or constraints
- reason: concise English explanation

Rubric definitions:
- topic_match: 0 = not aligned with the core topic, 1 = related but not central, 2 = central to the paper's main content.
- must_have_match: 0 = not present, 1 = partially or indirectly present, 2 = clearly present.
- exclude_match: 0 = no exclude hit, 1 = possible or borderline exclude hit, 2 = clear exclude hit.
- evidence_quality: 0 = evidence is weak, speculative, or mostly conceptual, with little concrete validation. 1 = evidence includes a method and some concrete results, but validation is limited or incomplete. 2 = evidence is strong and well supported, with substantial results, comparisons, or clear validation.
- content_alignment: 0 = the accessible content is not meaningfully aligned with the user's monitoring interests. 1 = the accessible content is partly aligned, but the match is indirect, partial, or not central. 2 = the accessible content is clearly and centrally aligned with the user's monitoring interests.
- actionability: 0 = low follow-up value for the monitoring workflow; not worth special attention beyond a basic record. 1 = some follow-up value; worth noting in the report, but not a high-priority item. 2 = high follow-up value; worth prioritizing for follow-up, tracking, deeper review, or manual attention.

Additional scoring rules:
- Score each field independently.
- Do not use topical relevance alone to raise evidence_quality or actionability.
- Do not use scientific rigor alone to raise content_alignment or actionability.
- Novelty may increase actionability when it creates follow-up value, but novelty alone does not guarantee a high actionability score.

JSON only, no markdown fences."""

ABSTRACT_GATE_PROMPT = """Determine the abstract-stage candidate rubric for this paper.

Interest profile summary:
{interest_summary}
Core topics: {core_topics}
Must-have constraints: {must_have}
Exclude constraints: {exclude}

Paper title: {title}
Abstract:
{abstract}

Return JSON with exactly these keys:
- topic_match: integer 0, 1, or 2
- must_have_match: integer 0, 1, or 2, or null when no must-have constraints exist
- exclude_match: integer 0, 1, or 2, or null when no exclude constraints exist
- evidence_strength: integer 0, 1, or 2
- focus_specificity: integer 0, 1, or 2
- matched_aspects: array of matched topics or constraints
- reason: concise English explanation

Rubric definitions:
- topic_match: 0 = the abstract is clearly not about the user's monitored topic; use this only when the mismatch is semantically clear, not just because keywords differ or synonyms are used. 1 = partially related or indirectly connected to the core topics. 2 = clearly centered on the core topics.
- must_have_match: 0 = not reflected, 1 = weak or indirect signal, 2 = clearly reflected.
- exclude_match: 0 = no exclude hit, 1 = possible or borderline exclude hit, 2 = clear exclude hit.
- evidence_strength: 0 = vague abstract without concrete method or result signal, 1 = some concrete method, object, or result signal, 2 = clear task, method, and result or validation signal.
- focus_specificity: 0 = too broad, 1 = somewhat focused, 2 = tightly focused on the user's interest.

Additional scoring rules:
- Evaluate topic_match by semantic meaning, not keyword overlap alone.
- Do not assign topic_match = 0 just because the abstract uses different terminology, synonyms, or adjacent phrasing.

JSON only, no markdown fences."""

ABSTRACT_VOTING_PROMPT = """Determine whether this paper abstract is relevant to the user's monitoring interest.

Interest profile summary:
{interest_summary}
Core topics: {core_topics}
Must-have constraints: {must_have}
Exclude constraints: {exclude}

Paper title: {title}
Abstract:
{abstract}

Return JSON with exactly these keys:
- is_relevant: boolean
- confidence: one of high, medium, low
- topic_match: one of yes, partial, no
- must_have_match: one of yes, partial, no, or null when no must-have constraints exist
- exclude_match: one of yes, possible, no, or null when no exclude constraints exist
- matched_aspects: array of matched topics or constraints
- reason: concise English explanation

Rules:
- Judge relevance by semantic meaning, not keyword overlap alone.
- A must-have constraint is a helpful positive signal, but not a hard requirement for relevance.
- Exclude constraints act as a veto for this judge. If the abstract clearly matches an exclude constraint, set exclude_match=yes and is_relevant=false.
- Use only the abstract and the stated interest profile. Do not assume unsupported details from the full paper.
- Return strict JSON only. Do not wrap the answer in markdown fences.
- All enum values must be JSON strings with double quotes.
- Use JSON null for absent optional fields; never return the string "null".

Example valid JSON:
{{"is_relevant": true, "confidence": "medium", "topic_match": "partial", "must_have_match": null, "exclude_match": "no", "matched_aspects": ["example topic"], "reason": "Brief explanation."}}

JSON only, no markdown fences."""
