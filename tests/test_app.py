"""
Tests for the shortly URL shortener service.

Uses fakeredis — an in-memory emulation of Redis — so tests are fast and need
no running Redis instance. The operations the app relies on (SET with NX for
atomic collision-safe writes, GET, PING) are faithfully emulated.

Each test gets a fresh fake Redis via the `client` fixture, so tests are
isolated — one test's data never leaks into another.
"""

import fakeredis
import pytest

import app as app_module
from app import app


@pytest.fixture
def client(monkeypatch):
    """A Flask test client backed by a fresh fakeredis instance.

    We patch the module-level `redis_client` so every Redis call the app makes
    is routed to the in-memory fake. A new fake per test guarantees isolation.
    """
    fake = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(app_module, "redis_client", fake)

    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


# ── /healthz tests ────────────────────────────────────────────────────────

def test_healthz_returns_200(client):
    """With Redis reachable (the fake always responds to ping), health is ok."""
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


# ── /shorten tests ────────────────────────────────────────────────────────

def test_shorten_valid_url_returns_201_with_code(client):
    """Happy path: valid URL in, 201 + short code out."""
    response = client.post("/shorten", json={"url": "https://example.com"})
    assert response.status_code == 201
    body = response.get_json()
    assert "short_code" in body
    assert len(body["short_code"]) == 6
    assert body["long_url"] == "https://example.com"
    assert body["short_url"] == f"/{body['short_code']}"


def test_shorten_invalid_url_returns_400(client):
    """Junk URL should be rejected before being stored."""
    response = client.post("/shorten", json={"url": "not-a-real-url"})
    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_url"


def test_shorten_missing_url_returns_400(client):
    """Empty payload — same failure mode as an invalid URL."""
    response = client.post("/shorten", json={})
    assert response.status_code == 400


def test_shorten_non_http_scheme_rejected(client):
    """Only http(s) is accepted — protects against file://, ftp://, etc."""
    response = client.post("/shorten", json={"url": "ftp://example.com"})
    assert response.status_code == 400


# ── /<code> redirect tests ────────────────────────────────────────────────

def test_redirect_to_long_url(client):
    """End-to-end: shorten a URL, then look up the code, verify redirect."""
    create = client.post("/shorten", json={"url": "https://example.com/page"})
    code = create.get_json()["short_code"]

    response = client.get(f"/{code}", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"] == "https://example.com/page"


def test_unknown_code_returns_404(client):
    """Looking up a code that was never created should be a clean 404."""
    response = client.get("/zzzzzz")
    assert response.status_code == 404
    assert response.get_json()["error"] == "not_found"


# ── Behavioural test ──────────────────────────────────────────────────────

def test_two_shortens_produce_different_codes(client):
    """Same input, called twice, should yield two distinct codes — proves the
    generator produces fresh codes and we're not caching by URL."""
    r1 = client.post("/shorten", json={"url": "https://example.com"})
    r2 = client.post("/shorten", json={"url": "https://example.com"})
    assert r1.get_json()["short_code"] != r2.get_json()["short_code"]
