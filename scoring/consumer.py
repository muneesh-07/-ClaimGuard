#!/usr/bin/env python3
"""
Consumes claim.submitted (published by the Java backend's transactional
outbox), scores the claim through the same detector app/main.py's
/score/batch uses, and publishes the result to claim.scored for the
Java backend's ScoringResultConsumer to pick up. This is the M7 async
wiring from docs/EXECUTION_PLAN.md - the piece that makes scoring
happen automatically instead of only when something calls
POST /score/batch directly.

Run with: cd scoring && uv run python consumer.py
"""

import json
import logging
import uuid

from kafka import KafkaConsumer, KafkaProducer

from app.db import SessionLocal
from app.scoring import refresh, score_claims

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("claim-scoring-consumer")

BOOTSTRAP_SERVERS = "localhost:9092"


# Deserializes a raw Kafka message value from JSON bytes.
def _deserialize(value: bytes):
    return json.loads(value.decode("utf-8"))


# Serializes a value to JSON bytes for publishing.
def _serialize(value) -> bytes:
    return json.dumps(value, default=str).encode("utf-8")


# Scores one claim, refreshing the cached graph first if the claim isn't in it yet (a claim
# submitted after the last refresh). The refresh is a full rebuild (~9s at 51k claims) - the
# known, documented cost of not having M9's incremental local-push path yet.
def _score_with_refresh_fallback(session, claim_id: uuid.UUID):
    results = score_claims(session, [claim_id])
    if results:
        return results[0]

    log.info("Claim %s not in the cached graph yet - refreshing...", claim_id)
    refresh(session)
    results = score_claims(session, [claim_id])
    return results[0] if results else None


def main() -> None:
    consumer = KafkaConsumer(
        "claim.submitted",
        bootstrap_servers=BOOTSTRAP_SERVERS,
        group_id="claimguard-scoring",
        auto_offset_reset="earliest",
        value_deserializer=_deserialize,
    )
    producer = KafkaProducer(bootstrap_servers=BOOTSTRAP_SERVERS, value_serializer=_serialize)

    # A single session, reused for this process's whole lifetime rather than opened per
    # message - but committed after every use (see below), never left open. An earlier
    # version of this loop never committed at all, which meant every read left its
    # transaction open indefinitely; a session idle-in-transaction for hours was found
    # holding a lock that blocked an unrelated TRUNCATE on these same tables during
    # Tier 0 dataset regeneration - a real, observed incident, not a hypothetical one.
    session = SessionLocal()
    log.info("Building initial graph...")
    claims_scored = refresh(session)
    session.commit()
    log.info("Ready - %d claims scored in the initial graph. Listening on claim.submitted...",
              claims_scored)

    for message in consumer:
        claim_id = uuid.UUID(message.value["claim_id"])
        log.info("Received claim.submitted for %s", claim_id)

        score = _score_with_refresh_fallback(session, claim_id)
        session.commit()
        if score is None:
            log.warning("Claim %s has no entity links even after refresh, skipping", claim_id)
            continue

        payload = score.model_dump(mode="json")
        producer.send("claim.scored", payload)
        producer.flush()
        log.info("Published claim.scored for %s: score=%.4f hint=%s rung=%s",
                  claim_id, score.fraud_score, score.decision_hint, score.rung)


if __name__ == "__main__":
    main()
