"""
Adversarial/edge-case hardening for app/narrative.py, separate from
test_narrative.py's happy-path contract tests. Where test_narrative.py
proves the grounding check works, this file tries to break it: near-miss
claim ids, partial contamination, and Ollama responses that are
malformed in ways a real (if misbehaving) local model can actually
produce - not just clean HTTP failures. `format` (Ollama's JSON-schema
constraint on the model's output, see NARRATIVE_RESPONSE_SCHEMA) makes a
conforming response LIKELY, not guaranteed; this suite exists because
"the schema says it's a string" and "it IS a string" are different
claims, and only testing the first one is how a crash bug ships.

One of these tests (test_a_non_string_narrative_field_does_not_crash_the_caller)
originally failed against the code as first written: a `{"narrative": 123}`
response passed json.loads() fine, then crashed on `.strip()` with an
uncaught AttributeError instead of falling back like every other malformed
response. Fixed in app.narrative._call_ollama (explicit isinstance check);
this test is what would catch a regression of that fix.
"""

import uuid
from unittest.mock import patch

import httpx

from app.models import ClaimScore, Explanation, SharedEntityEvidence, Thresholds, now_utc
from app.narrative import _is_grounded, generate_narrative


def _make_score(claim_id=None, other_ids=()):
    claim_id = claim_id or uuid.uuid4()
    return ClaimScore(
        claim_id=claim_id,
        model_version="xgboost-ring-classifier-1.0.0",
        scored_at=now_utc(),
        fraud_score=0.9,
        decision_hint="FLAG",
        ring_id="leiden-1",
        rung="xgboost",
        explanation=Explanation(
            summary="Part of a flagged cluster.",
            evidence=[
                SharedEntityEvidence(
                    entity_type="PHONE", entity_value="+9*****71",
                    entity_degree=len(other_ids) + 1, shared_with_claim_ids=list(other_ids),
                ),
            ],
            thresholds=Thresholds(flag_at=0.26, review_at=0.01),
        ),
    )


def _fake_ollama_response(content: str) -> httpx.Response:
    return httpx.Response(
        200, json={"message": {"content": content}},
        request=httpx.Request("POST", "http://localhost:11434/api/chat"),
    )


# --- Grounding check: no leniency ------------------------------------------

def test_is_grounded_rejects_an_id_one_hex_digit_off_from_an_allowed_one():
    allowed = uuid.uuid4()
    near_miss = str(allowed)[:-1] + ("0" if str(allowed)[-1] != "0" else "1")
    text = f"This claim connects to claim {near_miss}."

    # A near-miss is still an invented id - the check must not treat "close enough"
    # as grounded, or a model could point an investigator at the wrong claim by a
    # single mistyped/hallucinated character and still pass.
    assert _is_grounded(text, {str(allowed)}) is False


def test_is_grounded_rejects_text_that_mixes_one_allowed_and_one_invented_id():
    allowed = uuid.uuid4()
    invented = uuid.uuid4()
    text = f"Shares evidence with claim {allowed}, and also claim {invented}."

    # One invented id anywhere in the text fails the WHOLE narrative - grounding
    # is not "mostly correct," a caller can't tell which half to trust.
    assert _is_grounded(text, {str(allowed)}) is False


def test_is_grounded_accepts_the_same_allowed_id_mentioned_many_times():
    allowed = uuid.uuid4()
    text = f"Claim {allowed} appears here, and again as {allowed}, and once more: {allowed}."

    assert _is_grounded(text, {str(allowed)}) is True


def test_is_grounded_is_case_insensitive_for_allowed_ids():
    allowed = uuid.uuid4()
    text = f"Connects to claim {str(allowed).upper()}."

    assert _is_grounded(text, {str(allowed)}) is True


# --- Ollama responses that are malformed, not just unreachable -------------

def test_a_non_json_content_string_falls_back_instead_of_raising():
    score = _make_score()
    with patch("app.narrative.httpx.post", return_value=_fake_ollama_response("not json at all")):
        result = generate_narrative(score)

    assert result.model_version == "template-fallback"
    assert result.text == score.explanation.summary


def test_valid_json_missing_the_narrative_key_falls_back():
    score = _make_score()
    with patch("app.narrative.httpx.post", return_value=_fake_ollama_response('{"summary": "wrong key"}')):
        result = generate_narrative(score)

    assert result.model_version == "template-fallback"


def test_a_non_string_narrative_field_does_not_crash_the_caller():
    # {"narrative": 123} satisfies "valid JSON" but not the schema's "type": "string" -
    # this is the case that originally crashed with an uncaught AttributeError on
    # `.strip()` instead of falling back (see module docstring).
    score = _make_score()
    with patch("app.narrative.httpx.post", return_value=_fake_ollama_response('{"narrative": 123}')):
        result = generate_narrative(score)  # must not raise

    assert result.model_version == "template-fallback"
    assert result.text == score.explanation.summary


def test_a_null_narrative_field_does_not_crash_the_caller():
    score = _make_score()
    with patch("app.narrative.httpx.post", return_value=_fake_ollama_response('{"narrative": null}')):
        result = generate_narrative(score)

    assert result.model_version == "template-fallback"


def test_a_pathologically_long_model_output_still_gets_checked_and_falls_back():
    other = uuid.uuid4()
    invented = uuid.uuid4()
    # A long response that's mostly grounded but hides one invented id near the end -
    # the check must scan the whole text, not just a prefix a naive truncation might use.
    huge_narrative = f"This claim shares a phone with {other}. " + ("Filler sentence. " * 2000) \
        + f"It is also connected to {invented}."
    score = _make_score(other_ids=[other])

    with patch("app.narrative.httpx.post",
               return_value=_fake_ollama_response(f'{{"narrative": {huge_narrative!r}}}')):
        result = generate_narrative(score)

    assert result.model_version == "template-fallback"


# --- Structural invariant: the prompt never carries more than it's given ---

def test_the_prompt_only_ever_contains_the_already_masked_entity_value():
    # app.explain masks every entity_value before it ever becomes evidence (see
    # mask_entity_value) - this asserts app.narrative faithfully passes that masked
    # value through and never reaches past the ClaimScore object for a raw one, which
    # is the structural reason narrative.py has no raw-claimant-text attack surface
    # to begin with (see the module docstring).
    from app.narrative import _build_prompt

    score = _make_score()
    masked_value = score.explanation.evidence[0].entity_value
    assert masked_value == "+9*****71"

    prompt = _build_prompt(score)
    assert masked_value in prompt
    # No unmasked phone number is reconstructable from the prompt - there is none
    # anywhere in the ClaimScore this function was given to build it from.
    assert "+919876500071" not in prompt
