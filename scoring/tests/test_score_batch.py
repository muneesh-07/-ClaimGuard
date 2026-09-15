import uuid


def test_score_batch_scores_claims_that_exist(client, two_linked_claims):
    claim_a, claim_b = two_linked_claims

    response = client.post("/score/batch", json={"claim_ids": [str(claim_a), str(claim_b)]})

    assert response.status_code == 200
    body = response.json()
    assert len(body["results"]) == 2
    returned_ids = {r["claim_id"] for r in body["results"]}
    assert returned_ids == {str(claim_a), str(claim_b)}
    for result in body["results"]:
        assert result["model_version"] == "stub-component-size-0.1.0"


def test_score_batch_silently_skips_unknown_claim_ids(client, two_linked_claims):
    claim_a, _ = two_linked_claims
    unknown_id = str(uuid.uuid4())

    response = client.post("/score/batch", json={"claim_ids": [str(claim_a), unknown_id]})

    assert response.status_code == 200
    body = response.json()
    assert len(body["results"]) == 1
    assert body["results"][0]["claim_id"] == str(claim_a)


def test_score_batch_rejects_an_empty_request(client):
    response = client.post("/score/batch", json={"claim_ids": []})

    assert response.status_code == 422
