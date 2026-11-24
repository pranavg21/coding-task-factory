"""Lightweight, stack-agnostic diff-scoped mutator for Stage 7 (Test Strength)."""
from __future__ import annotations

import re
from dataclasses import dataclass


MUTATION_RULES: list[tuple[str, str, str]] = [
    ("eq_to_neq", r"(?<![!<>=])==(?!=)", "!="),
    ("neq_to_eq", r"!=", "=="),
    ("gte_to_gt", r">=", ">"),
    ("lte_to_lt", r"<=", "<"),
    ("gt_to_lt", r"(?<![<>=])>(?![>=])", "<"),
    ("true_to_false", r"\bTrue\b", "False"),
    ("false_to_true", r"\bFalse\b", "True"),
    ("js_true_to_false", r"\btrue\b", "false"),
    ("js_false_to_true", r"\bfalse\b", "true"),
    ("and_to_or", r"\band\b", "or"),
    ("plus_to_minus", r"(?<=\w)\s\+\s(?=\w)", " - "),
    ("minus_to_plus", r"(?<=\w)\s-\s(?=\w)", " + "),
    ("max_to_min", r"\bmax\(", "min("),
    ("min_to_max", r"\bmin\(", "max("),
    ("lt_to_lte", r"(?<![<>=!])<(?![<=])", "<="),
    ("return_none", r"^(\s*)return\s+(?!None\b|;)\S.*$", r"\1return None"),
]

COMMENT_PREFIXES = ("#", "//", "/*", "*", '"""', chr(39) * 3)


@dataclass
class MutantPatch:
    mutant_id: str
    rule_name: str
    mutated_diff: str
    original_line: str
    mutated_line: str


def generate_diff_mutants(patch_text: str, max_mutants: int = 8) -> list[MutantPatch]:
    """Mutates only added lines (`+...`) inside a unified diff, one mutation per mutant."""
    lines = patch_text.splitlines()
    mutants: list[MutantPatch] = []
    counter = 1

    in_docstring = False
    for idx, line in enumerate(lines):
        if line.startswith("@@"):
            in_docstring = False
        if not line.startswith("+") or line.startswith("+++"):
            continue
        code_part = line[1:]
        stripped = code_part.strip()
        # Docstrings and comments cannot change behaviour, so mutating them only produces fake survivors.
        quotes = stripped.count('"""') + stripped.count("'''")
        if in_docstring or quotes:
            if quotes % 2 == 1:
                in_docstring = not in_docstring
            continue
        if not stripped or stripped.startswith(COMMENT_PREFIXES):
            continue

        for rule_name, pattern, replacement in MUTATION_RULES:
            if re.search(pattern, code_part):
                new_code = re.sub(pattern, replacement, code_part, count=1)
                if new_code != code_part:
                    new_lines = lines.copy()
                    new_lines[idx] = "+" + new_code
                    mutants.append(
                        MutantPatch(
                            mutant_id=f"M-{counter:02d}",
                            rule_name=rule_name,
                            mutated_diff="\n".join(new_lines) + "\n",
                            original_line=code_part.strip(),
                            mutated_line=new_code.strip(),
                        )
                    )
                    counter += 1
                    if len(mutants) >= max_mutants:
                        return mutants
                    break

    return mutants
