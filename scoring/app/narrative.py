"""
Tier 2 of the AI upgrade: turns a claim's already-computed evidence (real
SHAP attributions from app.model, real shared-entity paths from
app.explain) into a short, investigator-readable narrative using a small
LOCAL model through Ollama - no hosted API, no new claim about what the
model can decide. This module does not decide anything: fraud_score,
ring_id, and decision_hint are already final by the time a claim gets
here (see app.explain.build_model_score / build_score). The model's only
job is turning facts that already exist into a sentence a human reads
faster than a JSON blob.

Runs on an 8GB Apple Silicon laptop with llama3.2:3b (~2GB resident) -
a 7B+ model would thrash on 8GB of unified memory, so it's the wrong
fit for this hardware. Measured on that hardware: ~13s for Ollama's
first call after a cold start (loading the model into memory), ~2-3s
per call once it's warm - see tools/eval_narrative.py for the real,
current numbers. Even warm, that's 100-1000x slower than the trained
classifier's SHAP explanation, so this is an ON-DEMAND, single-claim
path (a "generate narrative" button an investigator clicks), never a
batch/real-time scoring step - /score/batch stays fast and untouched.

The one property this module actually guarantees: the narrative cannot
contain a claim id that isn't in its own evidence. A small local model
occasionally invents plausible-sounding details ("hallucinates") when
asked to write prose about structured facts - so every generated
narrative is checked against the evidence it was given, and anything
that fails the check falls back to the deterministic template summary
app.explain already computes, rather than shipping an unverified
sentence to an investigator. tools/eval_narrative.py measures how often
that fallback actually fires, on real flagged claims.
"""

import json
import os
import re
import time
from dataclasses import dataclass

import httpx

from app.models import ClaimScore

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat")
NARRATIVE_MODEL = os.environ.get("NARRATIVE_MODEL", "llama3.2:3b")
NARRATIVE_TIMEOUT_SECONDS = 20.0

# Ollama's structured-output constraint: the model's response is forced to be a
# JSON object shaped exactly like this, so parsing it never depends on the model
# choosing to follow a prose instruction like "reply with only JSON."
NARRATIVE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {"narrative": {"type": "string"}},
    "required": ["narrative"],
}

# Matches a UUID anywhere in the model's output (case-insensitive, with or
# without hyphens isn't needed here since claim ids are always hyphenated) -
# this is the grounding check's only tool: every claim id the model mentions
# must already be one it was told about.
UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE,
)


@dataclass
class NarrativeResult:
    """One narrative attempt's outcome: the text an investigator sees, whether
    it passed the grounding check, which model actually produced it (an
    ollama tag, or "template-fallback" when the model was unavailable or
    ungrounded), and how long generation took."""

    text: str
    grounded: bool
    model_version: str
    generation_ms: float


# Collects every claim id this claim's evidence actually mentions - its own id
# plus every id in every SHARED_ENTITY's shared_with_claim_ids list. This is
# the ONLY set of claim ids the model is allowed to have learned about, so it's
# also the only set a grounded narrative is allowed to mention.
def _allowed_claim_ids(score: ClaimScore) -> set[str]:
    allowed = {str(score.claim_id)}
    for item in score.explanation.evidence:
        if item.type == "SHARED_ENTITY":
            allowed.update(str(cid) for cid in item.shared_with_claim_ids)
    return allowed


# Renders a claim's evidence as short, fact-only bullet lines for the prompt -
# reusing the exact fields app.explain already computed (masked entity values,
# real SHAP feature/value/shap_value triples) rather than re-deriving anything.
def _evidence_lines(score: ClaimScore) -> list[str]:
    lines = []
    for item in score.explanation.evidence:
        if item.type == "SHARED_ENTITY":
            lines.append(
                f"- Shares a {item.entity_type} ({item.entity_value}) with "
                f"{len(item.shared_with_claim_ids)} other claim(s); that entity appears on "
                f"{item.entity_degree} claims total."
            )
        elif item.type == "FEATURE_CONTRIBUTION":
            direction = "toward fraud" if item.shap_value >= 0 else "toward clean"
            lines.append(
                f"- Model feature '{item.feature}' = {item.feature_value:.2f}, "
                f"pushed the score {direction} (weight {item.shap_value:+.3f})."
            )
        elif item.type == "RING_METRIC":
            metric_name = item.metric.replace("_", " ")
            lines.append(f"- {metric_name}: {item.value:.0f} (baseline {item.baseline:.0f}).")
    return lines


# Builds the full prompt: the claim's facts, and an explicit instruction not to
# introduce any claim id, name, or number beyond what's given. Small local
# models follow a short, repeated constraint far more reliably than a long one.
def _build_prompt(score: ClaimScore) -> str:
    evidence_block = "\n".join(_evidence_lines(score)) or "- No shared entities or model features available."
    return (
        "You are writing a short note for a human fraud investigator. "
        "Use ONLY the facts below - do not invent claim IDs, names, dates, or numbers "
        "that are not given here. Write 2-3 plain sentences, no bullet points.\n\n"
        f"Claim: {score.claim_id}\n"
        f"Fraud score: {score.fraud_score:.2f} ({score.decision_hint})\n"
        f"Ring: {score.ring_id or 'none detected'}\n"
        f"Evidence:\n{evidence_block}\n"
    )


# Calls the local Ollama server with the narrative model, constrained to
# NARRATIVE_RESPONSE_SCHEMA. Returns None (never raises) on any failure -
# Ollama not running, the model not pulled, a timeout, or a response that
# technically parses as JSON but doesn't actually match the schema (a
# `format` constraint narrows what a model is LIKELY to return, it doesn't
# guarantee it - a `narrative` field that's null, a number, or a list is
# still a schema violation this has to handle, not trust) - since every
# caller already has a safe fallback (the deterministic template summary)
# and a missing/misbehaving local model is a legitimate, expected state,
# not a bug to surface as a 500 to whoever clicked "generate narrative."
def _call_ollama(prompt: str) -> str | None:
    try:
        response = httpx.post(
            OLLAMA_URL,
            json={
                "model": NARRATIVE_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "format": NARRATIVE_RESPONSE_SCHEMA,
                "stream": False,
                "options": {"temperature": 0.1},
            },
            timeout=NARRATIVE_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        content = response.json()["message"]["content"]
        narrative = json.loads(content)["narrative"]
        if not isinstance(narrative, str):
            raise ValueError(f"'narrative' field was {type(narrative).__name__}, not a string")
        return narrative.strip()
    except (httpx.HTTPError, KeyError, ValueError):
        return None


# The grounding check: every claim-id-shaped token in the model's text must be
# one this claim's own evidence actually mentions. A narrative that passes
# this can still be imprecise, but it cannot point an investigator at a claim
# that was never part of the evidence it was shown.
def _is_grounded(text: str, allowed_ids: set[str]) -> bool:
    if not text:
        return False
    mentioned = {m.lower() for m in UUID_PATTERN.findall(text)}
    allowed_lower = {a.lower() for a in allowed_ids}
    return mentioned.issubset(allowed_lower)


# The single entry point: generates a grounded narrative for one already-scored
# claim, falling back to the deterministic template summary (trivially grounded,
# since it's built directly from the same evidence with no free generation) if
# Ollama is unreachable or the model produced an ungrounded narrative.
def generate_narrative(score: ClaimScore) -> NarrativeResult:
    start = time.perf_counter()
    allowed_ids = _allowed_claim_ids(score)
    raw = _call_ollama(_build_prompt(score))
    elapsed_ms = (time.perf_counter() - start) * 1000

    if raw is not None and _is_grounded(raw, allowed_ids):
        return NarrativeResult(
            text=raw, grounded=True, model_version=f"ollama:{NARRATIVE_MODEL}", generation_ms=elapsed_ms,
        )

    return NarrativeResult(
        text=score.explanation.summary, grounded=True,
        model_version="template-fallback", generation_ms=elapsed_ms,
    )
