
"""
Tests for the shortly URL shortener service.

Uses Flask's built-in test client — no need to actually run the server.
The test client makes in-process requests against the WSGI app directly,
which is faster and more reliable than spinning up an HTTP server for tests.

Each test follows the AAA pattern:
  Arrange  → set up inputs and state
  Act      → call the endpoint under test
  Assert   → verify the response is what we expected
"""

import pytest

from app import app, url_store

# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    """A Flask test client with the URL store cleared before each test.

    Clearing the in-memory store between tests is important — without it,
    test order would matter (one test's data would leak into the next),
    and the suite would be flaky. The cleanup is the same principle as
    `setUp` in unittest or `beforeEach` in JS test frameworks.
    """
    app.config["TESTING"] = True
    url_store.clear()
    with app.test_client() as test_client:
        yield test_client


# ── /healthz tests ────────────────────────────────────────────────────────

def test_healthz_returns_200(client):
    """The liveness probe must be cheap, fast, and always return 200 when up.
    Kubernetes relies on this — if /healthz ever returns non-200, the pod
    gets killed and restarted. So this test guards a contract with our
    future orchestration layer."""
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
    """Only http(s) is accepted — protects against file://, ftp://, javascript:,
    and other schemes that could be abused if we blindly redirected to them."""
    response = client.post("/shorten", json={"url": "ftp://example.com"})
    assert response.status_code == 400


# ── /<code> redirect tests ────────────────────────────────────────────────

def test_redirect_to_long_url(client):
    """End-to-end: shorten a URL, then look up the code, verify redirect."""
    # Arrange — create a short code first.
    create = client.post("/shorten", json={"url": "https://example.com/page"})
    code = create.get_json()["short_code"]

    # Act — request the short code, but don't follow the redirect automatically
    # (follow_redirects=False keeps the test focused on what *this* endpoint returns).
    response = client.get(f"/{code}", follow_redirects=False)

    # Assert
    assert response.status_code == 302
    assert response.headers["Location"] == "https://example.com/page"


def test_unknown_code_returns_404(client):
    """Looking up a code that was never created should be a clean 404,
    not an internal error."""
    response = client.get("/zzzzzz")
    assert response.status_code == 404
    assert response.get_json()["error"] == "not_found"


# ── Behavioural / integration tests ───────────────────────────────────────

def test_two_shortens_produce_different_codes(client):
    """Same input, called twice, should yield two distinct codes — proves
    the generator is producing fresh codes and not caching by URL.
    (If we later added URL deduplication, this test would change.)"""
    r1 = client.post("/shorten", json={"url": "https://example.com"})
    r2 = client.post("/shorten", json={"url": "https://example.com"})
    assert r1.get_json()["short_code"] != r2.get_json()["short_code"]
