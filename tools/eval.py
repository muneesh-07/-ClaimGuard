#!/usr/bin/env python3
"""
Evaluates the M6 ring detector against the ground truth from
tools/gen_rings.py: ring-level recall, claim-level precision@k, and
lift at top 1%/5%, plus the same numbers for a single-claim baseline
(claim amount alone - no graph, no entity sharing) so the comparison
is explicit, per docs/EXECUTION_PLAN.md M6.

Reuses the exact graph-building and detector code the live scoring
service runs (app.graph, app.detector) rather than a second
implementation, so this evaluates what's actually deployed. Because of
that dependency, run it with the scoring service's environment:

    cd scoring && uv run python ../tools/eval.py

or `make eval` from the repo root.
"""

import argparse
import csv
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scoring"))

from app.db import SessionLocal  # noqa: E402
from app.detector import detect  # noqa: E402
from app.graph import build_graph  # noqa: E402


# Loads claim_id -> ring_id for every claim that is genuinely a ring member (camouflage and background-collision claims are deliberately absent from this file, see tools/gen_rings.py).
def load_ground_truth(path: Path) -> dict[str, str]:
    with path.open() as f:
        return {row["claim_id"]: row["ring_id"] for row in csv.DictReader(f)}


# Precision@k: of the top-k claims by score, what fraction are true ring members.
def precision_at_k(ranked_claim_ids: list[str], ground_truth: dict[str, str], k: int) -> float:
    top_k = ranked_claim_ids[:k]
    if not top_k:
        return 0.0
    return sum(1 for c in top_k if c in ground_truth) / len(top_k)


# Ring-level recall: a planted ring counts as "recovered" if a majority of its members
# ended up sharing the same detected ring_id - i.e. the detector actually found it as
# one cluster, not just individually flagged its members as unrelated high scorers.
def ring_level_recall(ground_truth: dict[str, str], verdicts: dict) -> tuple[float, int, int]:
    rings: dict[str, list[str]] = {}
    for claim_id, ring_id in ground_truth.items():
        rings.setdefault(ring_id, []).append(claim_id)

    recovered = 0
    for _true_ring_id, members in rings.items():
        detected_ring_ids = [verdicts[c].ring_id for c in members if c in verdicts and verdicts[c].ring_id]
        if not detected_ring_ids:
            continue
        most_common = max(set(detected_ring_ids), key=detected_ring_ids.count)
        purity = detected_ring_ids.count(most_common) / len(members)
        if purity >= 0.5:
            recovered += 1

    return recovered / len(rings), recovered, len(rings)


# Prints one baseline's full metric report: precision@k at a few k values, and lift at top 1%/5% over the base rate.
def report(name: str, ranked_claim_ids: list[str], ground_truth: dict[str, str]) -> None:
    total = len(ranked_claim_ids)
    base_rate = len(ground_truth) / total

    print(f"\n--- {name} ---")
    print(f"{'k':>8}  {'precision@k':>12}  {'lift':>8}")
    for k in (50, 100, int(total * 0.01), int(total * 0.05)):
        p = precision_at_k(ranked_claim_ids, ground_truth, k)
        lift = p / base_rate if base_rate > 0 else float("nan")
        label = f"{k}" if k not in (int(total * 0.01), int(total * 0.05)) else (
            f"{k} (1%)" if k == int(total * 0.01) else f"{k} (5%)"
        )
        print(f"{label:>8}  {p:>12.3f}  {lift:>8.2f}x")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ground-truth", type=Path,
                         default=Path(__file__).resolve().parent.parent / "data" / "ground_truth_rings.csv")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ground_truth = load_ground_truth(args.ground_truth)

    session = SessionLocal()
    try:
        g = build_graph(session)
        verdicts = detect(g)
    finally:
        session.close()

    total_claims = len(verdicts)
    print(f"Graph: {total_claims} claims, {len(ground_truth)} true ring members "
          f"across {len(set(ground_truth.values()))} planted rings "
          f"(base rate {len(ground_truth) / total_claims:.4%})")

    recall, recovered, total_rings = ring_level_recall(ground_truth, verdicts)
    print(f"\nRing-level recall: {recovered}/{total_rings} rings recovered as a single "
          f"cluster ({recall:.1%})")

    ranked_by_detector = sorted(verdicts, key=lambda c: verdicts[c].fraud_score, reverse=True)
    report("Ring detector (M6)", ranked_by_detector, ground_truth)

    # Single-claim baseline: claim amount z-score, no graph, no entity-sharing information
    # at all - exactly the "single-claim scoring" the whole project is positioned against.
    amounts = {v["name"]: v["claim_amount"] for v in g.vs if v["kind"] == "claim"}
    mean_amount = statistics.mean(amounts.values())
    stdev_amount = statistics.pstdev(amounts.values()) or 1.0
    ranked_by_amount = sorted(amounts, key=lambda c: abs(amounts[c] - mean_amount) / stdev_amount, reverse=True)
    report("Single-claim baseline (amount z-score)", ranked_by_amount, ground_truth)

    flagged = [c for c, v in verdicts.items() if v.fraud_score >= 0.75]
    flagged_precision = sum(1 for c in flagged if c in ground_truth) / len(flagged) if flagged else 0.0
    print(f"\nAll FLAGged claims: {len(flagged)}, precision {flagged_precision:.3f}")


if __name__ == "__main__":
    main()
