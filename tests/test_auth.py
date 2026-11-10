import pytest

pytestmark = pytest.mark.django_db


def test_register_then_login_then_me(api):
    resp = api.post(
        "/api/v1/auth/register/",
        {"username": "carol", "email": "c@example.com", "password": "Tr1cky-passphrase"},
        format="json",
    )
    assert resp.status_code == 201
    assert "password" not in resp.json()

    resp = api.post(
        "/api/v1/auth/token/", {"username": "carol", "password": "Tr1cky-passphrase"}, format="json"
    )
    assert resp.status_code == 200
    access = resp.json()["access"]

    api.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    resp = api.get("/api/v1/auth/me/")
    assert resp.json()["username"] == "carol"


def test_weak_password_rejected(api):
    resp = api.post("/api/v1/auth/register/", {"username": "dave", "password": "123"}, format="json")
    assert resp.status_code == 400
    assert "password" in str(resp.json()).lower()


def test_endpoints_require_auth(api):
    for url in ["/api/v1/documents/", "/api/v1/queries/", "/api/v1/auth/me/"]:
        assert api.get(url).status_code == 401
    assert api.post("/api/v1/ask/", {"question": "x"}, format="json").status_code == 401


def test_health_is_public(api):
    assert api.get("/api/v1/health/").json() == {"status": "ok"}


def test_openapi_schema_renders(api):
    resp = api.get("/api/schema/")
    assert resp.status_code == 200
    assert b"/api/v1/ask/" in resp.content
