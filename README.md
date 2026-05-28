<!-- # shortly-app
A URL shortener service — first of three projects in a DevOps portfolio series. Python + Flask, ships with Docker, CI/CD, and security scanning.


[![CI](https://github.com/Selase17/shortly-app/actions/workflows/ci.yml/badge.svg)](https://github.com/Selase17/shortly-app/actions/workflows/ci.yml)


[![CD](https://github.com/Selase17/shortly-app/actions/workflows/cd.yml/badge.svg)](https://github.com/Selase17/shortly-app/actions/workflows/cd.yml)
[![Docker Hub](https://img.shields.io/docker/v/selase/shortly-app?label=docker%20hub&logo=docker)](https://hub.docker.com/r/selase/shortly-app) -->


# shortly-app

[![CI](https://github.com/Selase17/shortly-app/actions/workflows/ci.yml/badge.svg)](https://github.com/Selase17/shortly-app/actions/workflows/ci.yml)
[![CD](https://github.com/Selase17/shortly-app/actions/workflows/cd.yml/badge.svg)](https://github.com/Selase17/shortly-app/actions/workflows/cd.yml)
[![Docker Hub](https://img.shields.io/docker/v/selase/shortly-app?label=docker%20hub&logo=docker)](https://hub.docker.com/r/selase/shortly-app)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue?logo=python&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green.svg)

A small URL shortener service, built as the first of three projects in a DevOps
portfolio series. The application itself is deliberately simple — the focus is
on the engineering *around* the code: testing, containerisation, CI/CD, and
security scanning, all built to production patterns.

> **Portfolio series:** This is **Project A** of three. The same product is
> shipped at progressively higher levels of engineering maturity:
> **A — `shortly-app`** (this repo): the service, containerised, with full CI/CD.
> > **B — [shortly-k8s](https://github.com/Selase17/shortly-k8s):** Kubernetes deployment with Helm and Prometheus/Grafana observability.
> **C — `shortly-infra`** *(planned)*: AWS infrastructure provisioned with Terraform.

---

## What it does

A URL shortener exposes two core operations: take a long URL and return a short
code, then redirect anyone who visits that code back to the original URL.

| Method | Endpoint     | Purpose                                            |
| ------ | ------------ | -------------------------------------------------- |
| `POST` | `/shorten`   | Create a short code for a given URL                |
| `GET`  | `/<code>`    | Redirect (302) to the original URL                 |
| `GET`  | `/healthz`   | Liveness probe — returns 200 when the service is up |

```
Client ──POST /shorten──▶  Flask app  ──store──▶  in-memory map (v0.1)
       ◀──201 + code────                                  │
                                                          │
Client ──GET /<code>───▶   Flask app  ──lookup───────────┘
       ◀──302 redirect───
```

> **Storage note:** v0.1 uses an in-memory dictionary. This is intentional — it
> keeps Project A focused on the delivery pipeline. The store is swapped for a
> persistent backend (Redis, then DynamoDB) in Projects B and C. A Redis service
> is already wired into `docker-compose.yml` in preparation.

---

## Tech stack

- **Language:** Python 3.12 (tested on 3.11, 3.12, 3.13)
- **Framework:** Flask
- **Testing:** pytest
- **Linting:** ruff
- **Container:** Docker (multi-stage build, non-root user)
- **Orchestration (local):** Docker Compose
- **CI/CD:** GitHub Actions
- **Security scanning:** Trivy (image + dependency CVEs)
- **Registry:** Docker Hub

---

## Quick start

### Run from Docker Hub (fastest)

```bash
docker pull selase/shortly-app:latest
docker run -p 5000:5000 selase/shortly-app:latest
curl http://localhost:5000/healthz
```

### Run the full stack locally (app + Redis)

```bash
git clone https://github.com/Selase17/shortly-app.git
cd shortly-app
make up          # docker compose up -d
curl http://localhost:5000/healthz
make down        # stop and remove
```

Run `make help` to see all available commands.

### Run from source (for development)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python app.py            # serves on http://localhost:5000
pytest -v                # run the test suite
ruff check .             # lint
```

### Try the API

```bash
# Shorten a URL
curl -X POST http://localhost:5000/shorten \
  -H "Content-Type: application/json" \
  -d '{"url":"https://github.com/Selase17/shortly-app"}'
# → {"short_code":"a3f9k2","short_url":"/a3f9k2","long_url":"..."}

# Follow the short code (returns a 302 redirect)
curl -i http://localhost:5000/a3f9k2
```

---

## How it's built

The interesting part of this project is the engineering around the application.

**Testing.** Every endpoint has automated tests covering the happy path, input
validation (rejecting non-`http(s)` schemes and malformed URLs), redirect
behaviour, 404 handling, and code uniqueness. The suite runs in well under a
second so it fits naturally into CI.

**Container.** A multi-stage Dockerfile separates the build environment from the
runtime, producing a small final image (~48 MB of application layers on top of
`python:3.12-slim`). The container runs as a non-root user, includes a built-in
healthcheck, and uses the exec form of `CMD` so signals reach the process
directly for graceful shutdown.

**Continuous Integration** (`.github/workflows/ci.yml`). On every push and pull
request: ruff lint plus a pytest matrix across Python 3.11, 3.12, and 3.13,
running as parallel jobs with concurrency cancellation to avoid wasting runner
minutes on superseded commits.

**Continuous Delivery** (`.github/workflows/cd.yml`). On every push to `main`:
the image is built, scanned by Trivy, and — *only if the scan finds no HIGH or
CRITICAL vulnerabilities* — pushed to Docker Hub. The image is tagged with both
`latest` and the short git SHA, so any running container is traceable to the
exact commit that produced it. Credentials are scoped Docker Hub access tokens
stored as encrypted repository secrets, never committed to the repo.

The ordering matters: the image is fully scanned **before** authentication to
the registry even happens. Scan-then-push, never push-then-scan.

---

## What I learned

- **Multi-stage Docker builds matter.** Separating build and runtime stages, and
  using `python:3.12-slim` over the full image, kept the final image lean without
  the compatibility risks that Alpine's musl libc can introduce with Python wheels.

- **CI catches what local checks miss.** On its first run, the pipeline flagged
  lint issues (import ordering, a missing trailing newline) that passed locally —
  a concrete reminder of why independent verification in CI is valuable.

- **Security scanning needs sensible gating.** Trivy is configured to fail on HIGH
  and CRITICAL findings but to ignore unfixed CVEs — failing a build over a
  vulnerability with no available patch just blocks delivery with no action to
  take. Gating on *actionable* findings keeps the pipeline trustworthy.

- **Secrets management is its own discipline.** Docker Hub auth uses a scoped
  access token (not a password) stored as an encrypted GitHub Actions secret. A
  secret-name mismatch caused a real pipeline failure during development, debugged
  by reading the Actions logs — the everyday reality of CI/CD work.

- **Pin everything for reproducibility.** Base image, Python version, and
  dependencies are all pinned so a build today produces the same result as a build
  next month.

---

## Production hardening checklist

This project demonstrates the delivery pipeline end to end. For real production
use, the following would be added:

- [ ] Persistent storage backend (Redis / DynamoDB) replacing the in-memory map
- [ ] A production WSGI server (gunicorn / uvicorn) instead of Flask's dev server, with `debug=False`
- [ ] Rate limiting on the `/shorten` endpoint to prevent abuse
- [ ] Structured JSON logging and request tracing
- [ ] Metrics endpoint (Prometheus) and dashboards (Grafana) — added in Project B
- [ ] Stricter URL validation (private-IP / SSRF protection, punycode handling)
- [ ] Multi-architecture image builds (amd64 + arm64)
- [ ] Image signing (cosign) and SBOM generation
- [ ] Deployment to an orchestrator with liveness/readiness probes — Project B (Kubernetes)
- [ ] Infrastructure provisioned as code — Project C (Terraform on AWS)

---

## License

MIT — see [LICENSE](LICENSE).