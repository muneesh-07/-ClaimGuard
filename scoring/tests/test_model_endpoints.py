from app.model import MODELS_DIR


def test_model_metadata_returns_the_trained_models_real_thresholds(client):
    response = client.get("/model/metadata")

    if not (MODELS_DIR / "model_metadata.json").exists():
        assert response.status_code == 404
        return

    assert response.status_code == 200
    body = response.json()
    assert body["model_version"]
    assert 0.0 <= body["review_threshold"] <= body["flag_threshold"] <= 1.0


def test_model_eval_report_includes_the_ring_injection_ablation(client):
    response = client.get("/model/eval-report")

    if not (MODELS_DIR / "eval_report.json").exists():
        assert response.status_code == 404
        return

    assert response.status_code == 200
    body = response.json()
    assert "tabular_only" in body["ablation"]
    assert "plus_graph_features" in body["ablation"]
    # The headline finding: graph features must materially beat tabular-only on AUPRC -
    # if this ever stops being true, the model wiring (not just this test) needs attention.
    assert body["ablation"]["plus_graph_features"]["auprc"] > body["ablation"]["tabular_only"]["auprc"]
