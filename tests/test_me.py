"""Milestone 8: identity response requires server-side authentication."""
from fastapi.testclient import TestClient
from app import main, security
from app.security import Principal


def test_me_requires_key():
    main.app.dependency_overrides.clear()
    try:
        with TestClient(main.app) as client:
            response = client.get("/me")
            assert response.status_code == 401
    finally:
        main.app.dependency_overrides.clear()


def test_me_does_not_expose_secret():
    test_user = Principal(user_id=21, tenant_id=4, role="reader", username="analyst")
    main.app.dependency_overrides[security.require_principal] = lambda: test_user
    try:
        with TestClient(main.app) as client:
            response = client.get("/me")
            assert response.status_code == 200
            assert response.json() == {
                "user_id": 21, "tenant_id": 4, "username": "analyst", "role": "reader"
            }
            assert "key" not in response.text.lower()
    finally:
        main.app.dependency_overrides.clear()
