#!/usr/bin/env python3
"""
Evaluates app/narrative.py's local-LLM narrative generator against real
FLAGged claims: how often it passes its own grounding check versus falls
back to the deterministic template, and how long generation actually
takes on an 8GB Apple Silicon laptop with llama3.2:3b. Same discipline
as tools/train_model.py's ablation report - the number that goes in the
README is one this script produced, not a hand-typed estimate.

Requires a running local Ollama server with llama3.2:3b pulled
(`ollama pull llama3.2:3b`) and a trained Tier 1 model (`make train-model`).

Run with: cd scoring && uv run python ../tools/eval_narrative.py
"""

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scoring"))

from app.db import SessionLocal  # noqa: E402
from app.explain import build_model_score  # noqa: E402
from app.features import build_feature_context  # noqa: E402
from app.graph import build_graph  # noqa: E402
from app.model import load as load_classifier  # noqa: E402
from app.narrative import generate_narrative  # noqa: E402

SAMPLE_SIZE = 20
MODELS_DIR = Path(__file__).resolve().parent.parent / "scoring" / "models"


# Walks a shuffled claim order and keeps only real FLAGged claims (scored by the
# live Tier 1 model), stopping as soon as `count` are found rather than scoring
# the whole ~51k-claim population - the eval only needs a representative sample.
def sample_flagged_claims(g, ctx, classifier, count: int, seed: int = 42):
    claim_names = [v["name"] for v in g.vs if v["kind"] == "claim"]
    rng = random.Random(seed)
    rng.shuffle(claim_names)

    flagged = []
    for name in claim_names:
        score = build_model_score(g, ctx, classifier, name)
        if score and score.decision_hint == "FLAG":
            flagged.append(score)
            if len(flagged) >= count:
                break
    return flagged


def main() -> None:
    classifier = load_classifier()
    if classifier is None:
        print("No trained model found - run `make train-model` first.")
        return

    session = SessionLocal()
    try:
        g = build_graph(session)
        ctx = build_feature_context(g)
    finally:
        session.close()

    print(f"Sampling up to {SAMPLE_SIZE} FLAGged claims from {g.vcount():,} graph vertices...")
    flagged = sample_flagged_claims(g, ctx, classifier, SAMPLE_SIZE)
    if not flagged:
        print("No FLAGged claims found in the current graph - nothing to evaluate.")
        return
    print(f"Found {len(flagged)} FLAGged claims.\n")

    results = []
    for score in flagged:
        result = generate_narrative(score)
        results.append(result)
        tag = "grounded" if result.model_version.startswith("ollama") else "fell back"
        print(f"  {score.claim_id}  {result.generation_ms:>7.0f}ms  {tag:>10}  model={result.model_version}")

    n = len(results)
    grounded = sum(1 for r in results if r.model_version.startswith("ollama"))
    fell_back = n - grounded
    latencies = sorted(r.generation_ms for r in results)

    report = {
        "sample_size": n,
        "narrative_model": results[0].model_version if grounded else "unavailable",
        "grounded_rate": round(grounded / n, 4),
        "fallback_rate": round(fell_back / n, 4),
        "latency_ms": {
            "mean": round(sum(latencies) / n, 1),
            "median": round(latencies[n // 2], 1),
            "p95": round(latencies[min(int(n * 0.95), n - 1)], 1),
        },
        "sample_narratives": [
            {
                "claim_id": str(s.claim_id),
                "narrative": r.text,
                "grounded": r.model_version.startswith("ollama"),
            }
            for s, r in list(zip(flagged, results, strict=True))[:5]
        ],
    }

    print(f"\nPassed the grounding check: {grounded}/{n} ({report['grounded_rate']:.1%})")
    print(f"Fell back to the deterministic template: {fell_back}/{n} ({report['fallback_rate']:.1%})")
    print(f"Latency (ms) - mean {report['latency_ms']['mean']}  "
          f"median {report['latency_ms']['median']}  p95 {report['latency_ms']['p95']}")

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = MODELS_DIR / "narrative_eval_report.json"
    report_path.write_text(json.dumps(report, indent=2))
    print(f"\nReport written to {report_path}")


if __name__ == "__main__":
    main()
