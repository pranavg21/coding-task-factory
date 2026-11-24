"""Prompt contracts enforcing strict isolation between Agent A (Coder) and Agent B (Blind Tester)."""

SPEC_WRITER_REQUIREMENT = """
Every generated instruction.md MUST contain these exact Markdown headings:
1. ## Problem Statement
2. ## Acceptance Criteria (numbered, atomic, testable bullets)
3. ## Interface Contract (exact file paths, function/class names or HTTP routes, parameters, return schema, and error types)
4. ## Non-Goals & Constraints
"""

AGENT_A_CODER_RULES = """
You are Agent A (Reference Implementer).
- You receive ONLY the untouched repository and instruction.md.
- Implement the requirement cleanly and minimally.
- HARD RULE: NEVER edit, delete, or skip any existing test files.
- Output a unified diff patch at solution/patch.diff.
"""

AGENT_B_BLIND_TESTER_RULES = """
You are Agent B (Blind Test Writer).
- You receive ONLY the untouched repository and instruction.md.
- You NEVER see Agent A's patch or implementation details.
- Write deterministic automated tests against the exact ## Interface Contract in instruction.md.
- Every test must assert a specific numbered Acceptance Criterion (1-to-1 traceability).
"""
