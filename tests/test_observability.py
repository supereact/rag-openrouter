"""Milestone 9.4: tenant-scoped metrics, no sensitive request content."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main, security, observability
from app.security import Principal

ADMIN_A = Principal(101, 710, "admin", "admin-a")
ADMIN_B = Principal(201, 720, "admin", "admin-b")
READER_A = Principal(102, 710, "reader", "reader-a")


@pytest.fixture(autouse=True)
def reset_metrics(monkeypatch):
    monkeypatch.setenv("RAG_OBSERVABILITY_ENABLED", "true")
    with observability._lock:
        observability._metrics.clear()
    observability.reset_llm_usage()
    yield
    with observability._lock:
        observability._metrics.clear()
    observability.reset_llm_usage()


def test_success_and_failure_counts():
    with observability.measure(710, "search", "retrieval"):
        pass
    with pytest.raises(ValueError):
        with observability.measure(710, "search", "retrieval"):
            raise ValueError("a confidential question that must not be logged")
    result = observability.snapshot(710)
    row = result["metrics"][0]
    assert row["calls"] == 2 and row["errors"] == 1
    assert row["error_rate"] == 0.5
    assert row["p50_ms"] is not None and row["p95_ms"] is not None
    assert "confidential question" not in str(result)


def test_tenant_isolation():
    with observability.measure(710, "ask", "retrieval"):
        pass
    with observability.measure(720, "search", "retrieval"):
        pass
    assert [(r["operation"], r["phase"]) for r in observability.snapshot(710)["metrics"]] == [
        ("ask", "retrieval")
    ]
    assert [(r["operation"], r["phase"]) for r in observability.snapshot(720)["metrics"]] == [
        ("search", "retrieval")
    ]


def test_provider_reported_openrouter_usage_only():
    observability.reset_llm_usage()
    observability.capture_llm_usage(
        {"prompt_tokens": 100, "completion_tokens": 24, "cost": 0.00012},
        provider="openrouter",
    )
    with observability.measure(710, "ask", "generation"):
        pass
    observability.save_request_usage(710)
    row = observability.snapshot(710)["metrics"][0]
    assert row["prompt_tokens"] == 100
    assert row["completion_tokens"] == 24
    assert row["provider_cost_credits"] == pytest.approx(0.00012)
    assert row["usage_samples"] == 1
    assert row["provider_cost_samples"] == 1
    # A later request must not inherit the previous request's usage.
    observability.save_request_usage(710)
    assert observability.snapshot(710)["metrics"][0]["usage_samples"] == 1


def test_openai_tokens_without_fabricated_cost():
    observability.capture_llm_usage(
        SimpleNamespace(input_tokens=12, output_tokens=7), provider="openai"
    )
    with observability.measure(710, "ask", "generation"):
        pass
    observability.save_request_usage(710)
    row = observability.snapshot(710)["metrics"][0]
    assert (row["prompt_tokens"], row["completion_tokens"]) == (12, 7)
    assert row["provider_cost_credits"] == 0
    assert row["provider_cost_samples"] == 0


def test_invalid_usage_and_disable(monkeypatch):
    observability.capture_llm_usage(
        {"prompt_tokens": -1, "completion_tokens": "12", "cost": float("nan")},
        provider="openrouter",
    )
    with observability.measure(710, "ask", "generation"):
        pass
    observability.save_request_usage(710)
    assert observability.snapshot(710)["metrics"][0]["usage_samples"] == 0
    monkeypatch.setenv("RAG_OBSERVABILITY_ENABLED", "false")
    with observability.measure(720, "search", "retrieval"):
        pass
    assert observability.snapshot(720)["metrics"] == []
    assert observability.snapshot(720)["enabled"] is False


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "warmup_local_models", lambda: None)
    main.app.dependency_overrides.clear()
    with TestClient(main.app) as c:
        yield c
    main.app.dependency_overrides.clear()


def test_metrics_endpoint_requires_admin(client):
    assert client.get("/observability").status_code == 401
    main.app.dependency_overrides[security.require_principal] = lambda: READER_A
    assert client.get("/observability").status_code == 403
    main.app.dependency_overrides[security.require_principal] = lambda: ADMIN_A
    assert client.get("/observability").status_code == 200


def test_metrics_api_tenant_boundary_and_request_id(monkeypatch, client):
    observability._record(710, "ask", "retrieval", 25.0, True)
    observability._record(720, "ask", "generation", 600.0, False)
    main.app.dependency_overrides[security.require_principal] = lambda: ADMIN_A
    res = client.get("/observability")
    assert res.status_code == 200
    assert len(res.headers["x-request-id"]) == 32
    assert len(res.json()["metrics"]) == 1
    assert res.json()["metrics"][0]["phase"] == "retrieval"
    main.app.dependency_overrides[security.require_principal] = lambda: ADMIN_B
    other = client.get("/observability").json()
    assert other["metrics"][0]["phase"] == "generation"


def test_search_ask_telemetry_without_real_db_or_llm(monkeypatch, client):
    main.app.dependency_overrides[security.require_principal] = lambda: ADMIN_A
    monkeypatch.setattr(main.credit_budgets, "reserve_request", lambda principal: None)
    monkeypatch.setattr(main, "search_documents", lambda question, top_k, principal: [])
    monkeypatch.setattr(main, "answer_question", lambda question, hits: "No sources")
    query = {"question": "secret question: do not log", "top_k": 3}
    assert client.post("/search", json=query).status_code == 200
    assert client.post("/ask", json=query).status_code == 200
    data = client.get("/observability").json()
    phases = {(r["operation"], r["phase"]): r for r in data["metrics"]}
    assert phases[("search", "retrieval")]["calls"] == 1
    assert phases[("ask", "retrieval")]["calls"] == 1
    assert phases[("ask", "generation")]["calls"] == 1
    assert "secret question" not in str(data)


def test_ask_generation_failure_count(monkeypatch, client):
    main.app.dependency_overrides[security.require_principal] = lambda: ADMIN_A
    monkeypatch.setattr(main.credit_budgets, "reserve_request", lambda principal: None)
    monkeypatch.setattr(main, "search_documents", lambda question, top_k, principal: [])
    def broken(question, hits):
        raise RuntimeError("provider unavailable")
    monkeypatch.setattr(main, "answer_question", broken)
    res = client.post("/ask", json={"question": "Hello", "top_k": 2})
    assert res.status_code == 503
    row = next(r for r in client.get("/observability").json()["metrics"]
               if (r["operation"], r["phase"]) == ("ask", "generation"))
    assert row["calls"] == 1 and row["errors"] == 1
