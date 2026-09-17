import uuid


def test_score_batch_flags_a_real_planted_ring_through_the_api(client, refreshed_scoring_cache):
    ring_claim_ids = refreshed_scoring_cache

    response = client.post("/score/batch", json={"claim_ids": [str(c) for c in ring_claim_ids]})

    assert response.status_code == 200
    body = response.json()
    assert len(body["results"]) == 3
    for result in body["results"]:
        assert result["decision_hint"] == "FLAG"
        # Whichever scoring method produced this (rule-based rungs or the Tier 1 trained
        # model), a FLAG decision must be internally consistent with the flag_at threshold
        # the SAME response reports - not a specific score, which is method-dependent.
        assert result["fraud_score"] >= result["explanation"]["thresholds"]["flag_at"]
        assert result["model_version"]


def test_score_batch_silently_skips_unknown_claim_ids(client, refreshed_scoring_cache):
    ring_claim_ids = refreshed_scoring_cache
    unknown_id = str(uuid.uuid4())

    response = client.post("/score/batch", json={"claim_ids": [str(ring_claim_ids[0]), unknown_id]})

    assert response.status_code == 200
    body = response.json()
    assert len(body["results"]) == 1
    assert body["results"][0]["claim_id"] == str(ring_claim_ids[0])


def test_score_batch_rejects_an_empty_request(client):
    response = client.post("/score/batch", json={"claim_ids": []})

    assert response.status_code == 422
