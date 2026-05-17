"""
shortly — a minimal URL shortener service.

Endpoints:
  POST /shorten     Create a short code for a given URL.
  GET  /<code>      Redirect to the original URL for the given code.
  GET  /healthz     Liveness probe — returns 200 if the service is up.

Storage: in-memory dict for v0.1. Swapped for Redis in Week 2, DynamoDB in Week 4.
"""

import secrets
import string
from urllib.parse import urlparse

from flask import Flask, jsonify, redirect, request, abort


app = Flask(__name__)

# In-memory store: short_code -> long_url
# This is fine for v0.1 because everything runs in a single Python process.
# It does NOT survive restarts, and it does NOT scale beyond one process.
# Both limitations are deliberate — we replace this with Redis (Week 2)
# and DynamoDB (Week 4) as the project evolves.
url_store: dict[str, str] = {}

# Short codes use lowercase letters + digits — URL-safe, no ambiguity (no 0/O confusion).
ALPHABET = string.ascii_lowercase + string.digits
CODE_LENGTH = 6  # 36^6 = ~2.2 billion possible codes — plenty for a demo


def generate_code() -> str:
    """Generate a 6-character random short code using a cryptographically
    secure RNG. secrets.choice is the right call here over random.choice
    — it's slower but unpredictable, which matters even for a URL shortener
    because guessable codes leak private links."""
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


def is_valid_url(url: str) -> bool:
    """Reject anything that isn't a plausible http(s) URL.
    Real production validation is hard (IDN, punycode, private IPs, etc.) —
    we keep this minimal and document it as a future hardening item."""
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


@app.route("/healthz", methods=["GET"])
def healthz():
    """Liveness probe. Kubernetes will call this — keep it cheap and side-effect-free."""
    return jsonify(status="ok"), 200


@app.route("/shorten", methods=["POST"])
def shorten():
    """Create a short code for a long URL.

    Expected payload: JSON {"url": "https://example.com/some/long/path"}
    Returns:          JSON {"short_code": "abc123", "short_url": "/abc123"}
    """
    payload = request.get_json(silent=True) or {}
    long_url = payload.get("url", "").strip()

    if not is_valid_url(long_url):
        # 400 Bad Request — client sent us something we can't use.
        return jsonify(error="invalid_url",
                       message="Provide a valid http(s) URL"), 400

    # Collision handling: regenerate if the code already exists.
    # With 6 chars and 2.2B possible codes, collisions are astronomically rare
    # at our scale — but defensively coding for them is cheap and correct.
    code = generate_code()
    while code in url_store:
        code = generate_code()

    url_store[code] = long_url

    return jsonify(short_code=code,
                   short_url=f"/{code}",
                   long_url=long_url), 201


@app.route("/<code>", methods=["GET"])
def redirect_to_long(code: str):
    """Look up the long URL for a short code and redirect to it."""
    long_url = url_store.get(code)
    if long_url is None:
        # 404 Not Found — no such code in the store.
        abort(404)
    # 302 Found (default redirect). For permanent redirects in production
    # you'd use 301, but 302 is correct for short links that might change.
    return redirect(long_url, code=302)


@app.errorhandler(404)
def not_found(_err):
    return jsonify(error="not_found", message="No such short code"), 404


if __name__ == "__main__":
    # Bind to 0.0.0.0 so the app is reachable from outside the container
    # once we Dockerize in Week 2. host="127.0.0.1" would lock it to localhost.
    # Debug mode is fine for local dev; we disable it in production.
    app.run(host="0.0.0.0", port=5000, debug=True)