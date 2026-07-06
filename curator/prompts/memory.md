<!-- version: 1 -->
You are analyzing photo curation corrections made by a user to identify patterns in their taste.

CORRECTIONS (JSON array):
<<CORRECTIONS>>

Find at most 3 generalizable taste preferences. Each must be supported by at least 3 corrections.
For each, provide:
- statement: one plain English sentence describing the preference
- evidence_refs: list of photo filenames that support it
- confidence: 0.0–1.0
- config_hint: optional whitelisted config path that could be nudged (e.g. "triage.blur_sharp_min"), or null
- key: a short snake_case identifier (e.g. "blur_leniency_kids")

Return only generalizations with evidence_count >= 3. If none qualify, return an empty list.
