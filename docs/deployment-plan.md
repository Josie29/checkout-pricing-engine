# Deployment Plan — Pricing / Rules Engine

Bonus per BRIEF.md (issue #6). Not attempted until Core scope (docs/scope.md) is done, tested, and green on `main`. Nothing here blocks or reshapes Core work — it's additive.

Assumes the standard `backend/` + `frontend/` top-level split (matches the global testing convention of `backend/tests/` and frontend `src/__tests__/`). Confirm against actual layout once Core lands.

## Platform

| Component | Choice | Reason |
|---|---|---|
| Cloud platform | Railway | Lowest setup friction for a small service + static frontend — no servers to patch, native Docker builds, GitHub-integrated CD. No infra needs (DB, queues, volumes) beyond compute, so a heavier platform buys nothing. |

## Topology — two services, one project

| Service | What it runs | Build |
|---|---|---|
| `api` | FastAPI backend (`backend/`) | Dockerfile |
| `web` | Vite production build (`frontend/`) | Static site (Railway static hosting) |

Each service's Railway "Root Directory" is set to its subfolder, so the two build independently from one repo. `api` exposes `POST /price`, `GET /promotions`, and a new `GET /health` (healthcheck target — doesn't exist yet, add during Core API work). `web` serves the built `dist/` with SPA fallback to `index.html`.

## IaC — `railway.toml` per service

`backend/railway.toml` and `frontend/railway.toml`, committed to the repo:

| Config | Captures |
|---|---|
| `[build]` | Dockerfile path (`api`) / static build command + output dir (`web`) |
| `[deploy].startCommand` | `uvicorn` invocation (`api` only) |
| `[deploy].healthcheckPath` | `/health` (`api` only) |
| `[deploy].restartPolicyType` | `ON_FAILURE`, bounded retry count |
| `[build].watchPatterns` | Scope each service's rebuild trigger to its own directory — a frontend-only change shouldn't rebuild `api` and vice versa |

This is the part of "infrastructure as code" Railway can express declaratively: build/deploy/runtime behavior, versioned and reviewable in PRs.

### What's still a one-time manual step (and how it's still not hand-clicking)

Railway has no equivalent to Terraform's declarative project/service creation — creating the project, creating the two services, linking the GitHub repo, and setting each service's root directory happens once, via CLI or dashboard. To keep this reproducible rather than tribal knowledge, that bootstrap is captured as a checked-in `scripts/railway-bootstrap.sh` using the `railway` CLI (`railway init`, `railway service create`, `railway up --service`, `railway variables set`) — rerunnable, diffable, not a set of undocumented dashboard clicks. This is the deliberate reason Terraform's Railway provider was rejected below: it would formalize the *same* API calls the CLI already makes, at the cost of a state backend, for a project that's created exactly once.

## Env wiring

| Var | Service | Value | Set via |
|---|---|---|---|
| `CORS_ORIGINS` | `api` | `web`'s public domain | `railway variables set` (reference variable, not committed) |
| `VITE_API_BASE_URL` | `web` (build-time) | `api`'s public domain | `railway variables set` (reference variable, not committed) |

Neither value is a secret — deferred to variables rather than `railway.toml` only because Railway-assigned domains don't exist until first deploy (chicken-and-egg); expect one redeploy of each service after the other's domain is known, then it's stable.

## CD

GitHub integration on both services: push to `main` → Railway builds and deploys whichever service(s) the diff touches, per `watchPatterns`. No separate CI-triggered deploy step needed — Railway's build *is* gated by GitHub, and the existing CI checks (`ruff`, `pyright`, `pytest`, `eslint`, `tsc`) already gate merge to `main` per `testing-strategy.md` / `clean-code-enforcement.md`.

## Rejected alternatives

| Option | Why not |
|---|---|
| Single service (FastAPI serves the built frontend via `StaticFiles`) | Less ceremony (no CORS, one domain), but couples frontend/backend release cadence and blurs the "backend API, frontend static build" split scope.md already draws. Two services costs one CORS var and one extra `railway.toml` — worth it for the cleaner boundary. |
| Fly.io | Comparable friction to Railway, no tooling already available in this environment, no advantage for a stateless single-region service. |
| Terraform (Railway provider) | Would formalize project/service creation as declarative resources, but needs a state backend (Terraform Cloud or self-hosted) for infra that's created once and rarely touched again — ceremony disproportionate to two services and no other cloud resources. |
| Render / Heroku-style PaaS | No meaningful difference from Railway for this workload; Railway chosen on tooling already present, not a feature gap in the alternatives. |

## Deferred

- Custom domain — Railway-provided subdomains are enough for a take-home submission.
- Autoscaling / multiple instances — the API is stateless (pure function, no DB), so this is trivial to add later if needed; not configured now since load isn't a requirement here.
- Secrets management — no real secrets exist yet (`CORS_ORIGINS`/`VITE_API_BASE_URL` are public URLs, not credentials); revisit if that changes.

## Timebox placement

Last PR in the project, after backend, frontend, tests, and CI are merged and green on `main`. Estimated as a small, contained slice: two `railway.toml` files, one `Dockerfile`, one `/health` endpoint, one bootstrap script, README updates — not a source of scope creep against Core.
