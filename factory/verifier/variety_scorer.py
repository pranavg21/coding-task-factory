"""Stage 2 & 11 Variety Scorer: prevents cosmetic duplicates (Black Friday vs Christmas marquee)."""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass


STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "when", "must",
    "should", "will", "have", "return", "add", "new", "user", "users", "data",
}


def _tokenize(text: str) -> Counter[str]:
    tokens = [t for t in re.findall(r"[a-zA-Z0-9_]{3,}", text.lower()) if t not in STOPWORDS]
    return Counter(tokens)


def instruction_cosine_similarity(spec_a: str, spec_b: str) -> float:
    ca, cb = _tokenize(spec_a), _tokenize(spec_b)
    if not ca or not cb:
        return 0.0
    common = set(ca) & set(cb)
    dot = sum(ca[k] * cb[k] for k in common)
    mag_a = math.sqrt(sum(v * v for v in ca.values()))
    mag_b = math.sqrt(sum(v * v for v in cb.values()))
    return round(dot / (mag_a * mag_b), 4) if mag_a and mag_b else 0.0


def file_jaccard_overlap(files_a: list[str], files_b: list[str]) -> float:
    sa, sb = set(files_a), set(files_b)
    if not sa and not sb:
        return 0.0
    return round(len(sa & sb) / len(sa | sb), 4)


@dataclass
class DedupDecision:
    is_duplicate: bool
    max_text_similarity: float
    max_file_overlap: float
    reason: str | None = None


def check_candidate_uniqueness(
    candidate_spec: str,
    candidate_files: list[str],
    accepted_specs: list[str],
    accepted_files_list: list[list[str]],
    text_threshold: float = 0.72,
    combined_threshold: float = 0.65,
) -> DedupDecision:
    max_sim = 0.0
    max_ovl = 0.0
    for spec, files in zip(accepted_specs, accepted_files_list):
        sim = instruction_cosine_similarity(candidate_spec, spec)
        ovl = file_jaccard_overlap(candidate_files, files)
        max_sim = max(max_sim, sim)
        max_ovl = max(max_ovl, ovl)
        if sim >= text_threshold:
            return DedupDecision(True, max_sim, max_ovl, f"Instruction similarity {sim:.2f} >= {text_threshold}")
        if (0.5 * sim + 0.5 * ovl) >= combined_threshold and ovl >= 0.75:
            return DedupDecision(True, max_sim, max_ovl, f"High combined text ({sim:.2f}) + file overlap ({ovl:.2f})")
    return DedupDecision(False, max_sim, max_ovl, None)
