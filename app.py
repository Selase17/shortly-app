"""
shortly — a minimal URL shortener service.

Endpoints:
  POST /shorten     Create a short code for a given URL.
  GET  /<code>      Redirect to the original URL for the given code.
  GET  /healthz     Liveness/readiness probe — checks Redis connectivity.

Storage: Redis. Connection configured via environment variables so the same
image runs unchanged in docker-compose, Kubernetes, or against a managed
Redis — only the environment differs (12-Factor config principle).
"""

import os
import secrets
import string
from urllib.parse import urlparse

import redis
from flask import Flask, abort, jsonify, redirect, request

app = Flask(__name__)

# ── Redis connection ─────────────────────────────────────────────────────
# Config comes from the environment, never hardcoded. Defaults point at a
# local Redis so `python app.py` works out of the box for a developer with
# Redis on localhost; docker-compose and Kubernetes override these.
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_DB = int(os.environ.get("REDIS_DB", "0"))

# A single client instance reused across requests. redis-py maintains an
# internal connection pool, so this is efficient — we do NOT open a new
# connection per request. decode_responses=True means we get str back from
# Redis instead of bytes, which keeps the rest of the code clean.
redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=REDIS_DB,
    decode_responses=True,
    socket_connect_timeout=2,   # fail fast if Redis is unreachable
    socket_timeout=2,
)

# Short codes use lowercase letters + digits — URL-safe, unambiguous.
ALPHABET = string.ascii_lowercase + string.digits
CODE_LENGTH = 6  # 36^6 ≈ 2.2 billion possible codes


def generate_code() -> str:
    """Generate a 6-char random short code using a cryptographically secure RNG.
    secrets.choice over random.choice — guessable codes would leak private links."""
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


def is_valid_url(url: str) -> bool:
    """Reject anything that isn't a plausible http(s) URL."""
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


@app.route("/healthz", methods=["GET"])
def healthz():
    """Health probe. Now that the app depends on Redis, 'healthy' means
    'I can reach Redis' — otherwise the app can't do its job. Kubernetes will
    call this; if it fails, the pod is restarted (liveness) or pulled from the
    load balancer (readiness). We use one endpoint for both here for simplicity;
    in a larger system you'd often split liveness (is the process alive?) from
    readiness (can it serve traffic? i.e. are dependencies reachable?)."""
    try:
        redis_client.ping()
        return jsonify(status="ok"), 200
    except redis.RedisError:
        # 503 Service Unavailable — the app is up but its dependency isn't.
        return jsonify(status="degraded", reason="redis_unreachable"), 503


@app.route("/shorten", methods=["POST"])
def shorten():
    """Create a short code for a long URL.
    Payload: {"url": "https://..."}  →  {"short_code","short_url","long_url"}"""
    payload = request.get_json(silent=True) or {}
    long_url = payload.get("url", "").strip()

    if not is_valid_url(long_url):
        return jsonify(error="invalid_url",
                       message="Provide a valid http(s) URL"), 400

    try:
        # Collision handling: SETNX ("set if not exists") is atomic — it only
        # sets the key if it doesn't already exist, returning True/False. This
        # avoids a race condition where two requests generate the same code
        # between a separate "check then set". One atomic op, no race.
        code = generate_code()
        while not redis_client.set(code, long_url, nx=True):
            code = generate_code()
    except redis.RedisError:
        # Redis unreachable mid-request → clean 503, not an unhandled 500.
        return jsonify(error="storage_unavailable",
                       message="Could not store URL, try again"), 503

    return jsonify(short_code=code,
                   short_url=f"/{code}",
                   long_url=long_url), 201


@app.route("/<code>", methods=["GET"])
def redirect_to_long(code: str):
    """Look up the long URL for a short code and redirect to it."""
    try:
        long_url = redis_client.get(code)
    except redis.RedisError:
        return jsonify(error="storage_unavailable",
                       message="Could not look up URL, try again"), 503

    if long_url is None:
        abort(404)
    return redirect(long_url, code=302)


@app.errorhandler(404)
def not_found(_err):
    return jsonify(error="not_found", message="No such short code"), 404


if __name__ == "__main__":
    # Bind to 0.0.0.0 so the app is reachable from outside the container.
    # debug=True is for local dev only; production uses a real WSGI server
    # with debug disabled (noted in the README hardening checklist).
    app.run(host="0.0.0.0", port=5000, debug=True)
