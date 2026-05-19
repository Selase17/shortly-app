
# syntax=docker/dockerfile:1.7
# ↑ Enables modern Dockerfile features (e.g. better caching, --mount). Pinning the
#   frontend version means our build behaves identically on any Docker version.

# ╭──────────────────────────────────────────────────────────────────────╮
# │ Stage 1 — BUILDER                                                    │
# │ Installs Python dependencies into a virtual environment we can copy. │
# │ This stage may contain build tools, compilers, dev headers — all of  │
# │ which we DO NOT want in the final image.                             │
# ╰──────────────────────────────────────────────────────────────────────╯
FROM python:3.12-slim AS builder

# Don't write .pyc files (saves a tiny bit of space) and don't buffer stdout
# (so logs appear immediately in `docker logs`, not after the process exits).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Copy only requirements.txt first so this layer caches well —
# if app.py changes but requirements don't, Docker reuses this expensive layer.
COPY requirements.txt .

# Install deps into a dedicated venv inside the builder. Using a venv (rather
# than installing system-wide) means we can copy ONE directory into the final
# image with all our deps, leaving everything else behind.
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --upgrade pip && \
    /opt/venv/bin/pip install -r requirements.txt

# ╭──────────────────────────────────────────────────────────────────────╮
# │ Stage 2 — RUNTIME                                                    │
# │ A clean, minimal image with ONLY the venv + app code. No build tools,│
# │ no pip cache, no test deps. Smallest possible attack surface.        │
# ╰──────────────────────────────────────────────────────────────────────╯
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"
#   ↑ Putting the venv on PATH means `python` and `flask` resolve to the
#     venv versions automatically — no need to call /opt/venv/bin/python.

# Create a non-root user to run the app. Running as root inside a container is
# a security anti-pattern: if the app is compromised, the attacker has root
# inside the container, making escapes / privilege escalation easier.
# UID 1000 is conventional for non-system users.
RUN groupadd --system --gid 1000 app && \
    useradd  --system --uid 1000 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app

# Copy the venv from the builder. --chown ensures our non-root user can read it
# without us having to chmod recursively at runtime (which would slow startup).
COPY --from=builder --chown=app:app /opt/venv /opt/venv

# Copy ONLY the application code. Tests, dev requirements, caches, .git, .venv
# all stay out — partly because of .dockerignore, partly because we name files explicitly.
COPY --chown=app:app app.py ./

# Drop privileges. Every command from here on runs as the unprivileged `app` user.
USER app

# Document the port. EXPOSE is metadata only — it doesn't actually publish the port.
# Publishing happens with `docker run -p` at runtime. But this metadata is read by
# `docker inspect`, by docker-compose, and by tools like Kubernetes, so it's worth setting.
EXPOSE 5000

# A built-in healthcheck means `docker ps` shows whether the container is healthy.
# It's the same `/healthz` endpoint our future Kubernetes liveness probe will use.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request, sys; \
                   sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:5000/healthz').status==200 else 1)"

# Run the app. We use the JSON-array form (exec form) so signals like SIGTERM
# reach Python directly — important for graceful shutdown when Kubernetes
# tells the pod to stop. The shell form (CMD python app.py) wraps in /bin/sh
# which swallows signals and leads to ungraceful kills.
CMD ["python", "app.py"]