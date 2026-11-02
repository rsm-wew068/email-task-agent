"""Evidence-quote machinery — the frozen core of the E1 spec (plan §9.3).

The E1 eval scorer (evals/scoring.py) and the runtime Validate stage (pipeline,
M1) MUST both use these functions, so eval and runtime can never drift.

Treat any change to the constants below as a spec change: bump
evals.scoring.SCORER_VERSION and re-record the baseline.

Pinned choices (v1):
  - fuzzy location: rapidfuzz ``fuzz.partial_ratio_alignment`` at >= 90/100
  - overlap: token-set intersection over the shorter side, >= 0.5
  - quotes under 3 tokens are rejected (rev 5 review note: a 1-2 token quote
    can anchor a match on almost any sentence)
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz

FUZZY_THRESHOLD = 90.0
OVERLAP_THRESHOLD = 0.5
MIN_QUOTE_TOKENS = 3

_TOKEN_RE = re.compile(r"[\w']+", re.UNICODE)


def normalize(text: str) -> str:
    """Casefolded NFC text with collapsed whitespace.

    Punctuation is NOT stripped here: exact substring location (step 1) is
    punctuation-sensitive on purpose; tokenization handles the rest.
    """
    text = unicodedata.normalize("NFC", text)
    return re.sub(r"\s+", " ", text).casefold().strip()


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens; the only normalization used by overlap math."""
    return _TOKEN_RE.findall(normalize(text))


@dataclass(frozen=True)
class QuoteLocation:
    start: int  # character offsets into normalize(email_text), NOT the raw text
    end: int
    score: float  # 100.0 for exact, fuzzy score otherwise
    matched_text: str


def locate_quote(quote: str, email_text: str) -> QuoteLocation | None:
    """Find ``quote`` inside ``email_text``, exactly or fuzzily (>= 90/100).

    Returns None when the quote cannot be found — per §9.3 such a prediction
    is a false positive and must never be matched to a gold task.
    """
    q = normalize(quote)
    if not q:
        return None
    hay = normalize(email_text)

    exact = hay.find(q)
    if exact != -1:
        return QuoteLocation(exact, exact + len(q), 100.0, hay[exact : exact + len(q)])

    alignment = fuzz.partial_ratio_alignment(q, hay, score_cutoff=FUZZY_THRESHOLD)
    if alignment is None:
        return None
    start, end = alignment.dest_start, alignment.dest_end
    return QuoteLocation(start, end, alignment.score, hay[start:end])


def overlap_coefficient(pred_tokens: set[str], gold_tokens: set[str]) -> float:
    """|p ∩ s| / min(|p|, |s|) — 0.0 when either side is empty."""
    smaller = min(len(pred_tokens), len(gold_tokens))
    if smaller == 0:
        return 0.0
    return len(pred_tokens & gold_tokens) / smaller


def quote_overlaps_sentence(quote: str, evidence_sentence: str) -> float:
    """Token-overlap coefficient between a located quote and a gold sentence."""
    return overlap_coefficient(set(tokenize(quote)), set(tokenize(evidence_sentence)))
