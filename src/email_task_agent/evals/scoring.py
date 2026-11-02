"""E1 extraction scorer — implements the frozen spec of plan §9.3.

Per prediction:
  1. The evidence quote must be locatable in the thread text (exact, or fuzzy
     >= 90/100 via evidence.locate_quote). A quote under MIN_QUOTE_TOKENS or
     that cannot be found is a FALSE POSITIVE and is never matched.
  2. A prediction matches a gold task only if the quote's token overlap with
     the gold evidence sentence satisfies
         |p ∩ s| / min(|p|, |s|) >= OVERLAP_THRESHOLD.
  3. Predictions and gold tasks are paired one-to-one per thread by OPTIMAL
     (Hungarian) assignment over overlap scores — not greedy.
  4. Detection precision/recall/F1 are micro-counted over ALL threads,
     including gold-empty threads, so tasks invented from newsletters count
     against precision.
  5. Owner, due date and status are scored as accuracy over MATCHED pairs.
     Strict F1 counts a matched task correct only if all three fields agree.

Title and owner are deliberately NOT part of the match (§9.3): titles are
paraphrases, and owner-in-match would turn one wrong owner into both a false
positive and a miss.

Any change here is a scorer spec change: bump SCORER_VERSION and re-record
baselines.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from scipy.optimize import linear_sum_assignment

from email_task_agent.evidence import (
    MIN_QUOTE_TOKENS,
    OVERLAP_THRESHOLD,
    locate_quote,
    quote_overlaps_sentence,
    tokenize,
)

SCORER_VERSION = "e1-spec-v1.1"  # v1 + min-quote-length rule from the rev 5 review

# Gate metrics per §9.3; gate thresholds live in evals/gate.py.
GATE_METRICS = ("f1", "strict_f1", "owner_accuracy", "due_accuracy")


@dataclass(frozen=True)
class GoldTask:
    title: str
    owner_email: str | None
    due_date: date | None
    status: str
    evidence_sentence: str
    email_index: int


@dataclass(frozen=True)
class PredictedTask:
    title: str
    owner_email: str | None
    due_date: date | None
    status: str
    evidence_quote: str
    source_email_index: int | None = None


@dataclass(frozen=True)
class PairMatch:
    pred_index: int
    gold_index: int
    overlap: float
    owner_ok: bool
    due_ok: bool
    status_ok: bool

    @property
    def strict_ok(self) -> bool:
        return self.owner_ok and self.due_ok and self.status_ok


@dataclass(frozen=True)
class RejectedPrediction:
    pred_index: int
    reason: str  # quote_too_short | quote_not_found | unpaired
    detail: str = ""


@dataclass
class ThreadScore:
    thread_id: str
    matches: list[PairMatch] = field(default_factory=list)
    rejected: list[RejectedPrediction] = field(default_factory=list)
    missed_gold: list[int] = field(default_factory=list)  # gold indices

    @property
    def tp(self) -> int:
        return len(self.matches)

    @property
    def fp(self) -> int:
        return len(self.rejected)

    @property
    def fn(self) -> int:
        return len(self.missed_gold)


def _norm_email(email: str | None) -> str | None:
    return email.strip().casefold() if email else None


def _same_date(a: date | None, b: date | None) -> bool:
    return a == b


def score_thread(thread_id: str, gold: list[GoldTask], preds: list[PredictedTask], thread_text: str) -> ThreadScore:
    result = ThreadScore(thread_id=thread_id)

    # Step 1: quote must be locatable and long enough, else the prediction is a false positive.
    viable: list[tuple[int, PredictedTask]] = []
    for i, pred in enumerate(preds):
        if len(tokenize(pred.evidence_quote)) < MIN_QUOTE_TOKENS:
            result.rejected.append(RejectedPrediction(i, "quote_too_short", pred.evidence_quote[:80]))
            continue
        if locate_quote(pred.evidence_quote, thread_text) is None:
            result.rejected.append(RejectedPrediction(i, "quote_not_found", pred.evidence_quote[:80]))
            continue
        viable.append((i, pred))

    # Step 2: valid (pred, gold) pairs by token-overlap on the evidence sentence.
    n_p, n_g = len(viable), len(gold)
    scores = [[-1e6] * n_g for _ in range(n_p)]
    for row, (pi, pred) in enumerate(viable):
        for gi, g in enumerate(gold):
            ov = quote_overlaps_sentence(pred.evidence_quote, g.evidence_sentence)
            if ov >= OVERLAP_THRESHOLD:
                scores[row][gi] = ov

    if n_p and n_g:
        # Step 3: optimal one-to-one assignment (maximize overlap).
        rows, cols = linear_sum_assignment([[-s for s in row] for row in scores])
        for row, col in zip(rows, cols):
            if scores[row][col] < 0:  # pair existed but failed the overlap gate
                result.rejected.append(
                    RejectedPrediction(viable[row][0], "unpaired", viable[row][1].evidence_quote[:80])
                )
                continue
            pi, pred = viable[row]
            g = gold[col]
            result.matches.append(
                PairMatch(
                    pred_index=pi,
                    gold_index=col,
                    overlap=scores[row][col],
                    owner_ok=_norm_email(pred.owner_email) == _norm_email(g.owner_email),
                    due_ok=_same_date(pred.due_date, g.due_date),
                    status_ok=pred.status == g.status,
                )
            )

    # Predictions that passed step 1 but there was no gold to pair with at all.
    assigned = {m.pred_index for m in result.matches}
    for pi, pred in viable:
        if pi not in assigned:
            result.rejected.append(RejectedPrediction(pi, "unpaired", pred.evidence_quote[:80]))

    matched_gold = {m.gold_index for m in result.matches}
    result.missed_gold = [gi for gi in range(n_g) if gi not in matched_gold]
    return result


@dataclass
class ScorerReport:
    scorer_version: str
    suite: str
    threads: list[ThreadScore] = field(default_factory=list)

    @property
    def n_predictions(self) -> int:
        return sum(t.tp + t.fp for t in self.threads)

    @property
    def n_gold(self) -> int:
        return sum(t.tp + t.fn for t in self.threads)

    def metrics(self) -> dict[str, float]:
        tp = sum(t.tp for t in self.threads)
        fp = sum(t.fp for t in self.threads)
        fn = sum(t.fn for t in self.threads)
        matches = [m for t in self.threads for m in t.matches]

        def prf(numerator_tp: int, denom_p: int, denom_r: int) -> tuple[float, float, float]:
            p = numerator_tp / denom_p if denom_p else 1.0
            r = numerator_tp / denom_r if denom_r else 1.0
            f = 2 * p * r / (p + r) if p + r else 0.0
            return p, r, f

        precision, recall, f1 = prf(tp, tp + fp, tp + fn)
        strict_tp = sum(1 for m in matches if m.strict_ok)
        _, _, strict_f1 = prf(strict_tp, tp + fp, tp + fn)

        n_matches = len(matches)
        owner_accuracy = sum(m.owner_ok for m in matches) / n_matches if n_matches else 1.0
        due_accuracy = sum(m.due_ok for m in matches) / n_matches if n_matches else 1.0
        status_accuracy = sum(m.status_ok for m in matches) / n_matches if n_matches else 1.0

        return {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "strict_f1": strict_f1,
            "owner_accuracy": owner_accuracy,
            "due_accuracy": due_accuracy,
            "status_accuracy": status_accuracy,
            "tp": float(tp),
            "fp": float(fp),
            "fn": float(fn),
        }

    def missed_tasks(self) -> list[dict]:
        """Indices only; the runner (which holds the suite) adds human descriptions."""
        return [
            {"thread_id": t.thread_id, "gold_index": gi}
            for t in self.threads
            for gi in t.missed_gold
        ]

    def invented_tasks(self) -> list[dict]:
        return [
            {"thread_id": t.thread_id, "reason": r.reason, "quote": r.detail}
            for t in self.threads
            for r in t.rejected
        ]


def diff_reports(prev: ScorerReport, curr: ScorerReport) -> dict[str, list]:
    """Tasks newly missed or newly invented vs a previous report (§9.3 gate output)."""

    def key_missed(rep: ScorerReport) -> set:
        return {(t.thread_id, gi) for t in rep.threads for gi in t.missed_gold}

    def key_invented(rep: ScorerReport) -> set:
        return {(t.thread_id, r.reason, r.detail) for t in rep.threads for r in t.rejected}

    return {
        "newly_missed": [k for k in key_missed(curr) - key_missed(prev)],
        "newly_invented": [k for k in key_invented(curr) - key_invented(prev)],
    }
