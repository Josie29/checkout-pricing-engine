# Checkout Pricing Engine

A pricing/rules engine for an e-commerce checkout (Project 5 of the [brief](BRIEF.md)):
given a cart and a set of active promotions, it computes an itemized final price with a
per-promotion explanation — and picks the *best allowed* combination of promotions for
the shopper, not just the first that fits.

- FastAPI + Pydantic v2 backend (`backend/`), stateless — pricing is a pure function of
  the request; promotions and catalog are seeded JSON, no database
- Vite + React + TypeScript single-page UI (`frontend/`) — builds a cart, toggles
  promotions, renders the server's itemized result verbatim (no client-side price math)
- [DECISIONS.md](DECISIONS.md) — the architectural choices and trade-offs
- `docs/` — the specs the code was built against (scope, engine, optimizer, testing)

## Run

Backend (Python 3.12+):

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/uvicorn app.main:app --port 8000
```

Frontend (Node 22+), in a second terminal:

```bash
cd frontend
npm ci
npm run dev
```

The dev UI on http://localhost:5173 talks to the API at `http://localhost:8000` by
default (override with `VITE_API_BASE_URL`). If the UI runs on a different origin than
the API, start the backend with CORS enabled:

```bash
CORS_ORIGINS=http://localhost:5173 .venv/bin/uvicorn app.main:app --port 8000
```

### API without the UI

```bash
curl -s localhost:8000/catalog
curl -s localhost:8000/promotions
curl -s localhost:8000/price -X POST -H 'content-type: application/json' -d '{
  "cart": {"items": [
    {"sku": "COF-ETH", "category": "Coffee Beans", "unit_price_cents": 1600, "qty": 3},
    {"sku": "BREW-V60", "category": "Brew Gear", "unit_price_cents": 2800, "qty": 1}
  ]},
  "claimed_promotion_ids": ["P1", "P4", "P2"]
}'
```

The response carries the itemized lines, the adjustment trace (which promotion did what,
to which lines, in cents), `promotion_statuses` (available / claimed / applied), and
`optimal` — true when the exhaustive best-combination search produced the result.

## Verify

```bash
cd backend && .venv/bin/pytest -q        # 192 tests: unit, integration, property-based,
                                         # golden receipts, exclusivity matrix, perf budget
cd frontend && npm test                  # single smoke test
```

Full CI gate (also run on every PR): `ruff check`, `ruff format --check`, `pyright`,
`pytest` (backend); `eslint`, `prettier --check`, `tsc --noEmit`, `vitest`, build
(frontend). Pre-commit hooks mirror the fast checks: `pre-commit install`.

## Deploy (Railway)

Live: [web](https://web-production-e530a.up.railway.app) ·
[api health](https://api-production-b55d.up.railway.app/health)

Infrastructure is code (`docs/deployment-plan.md`): two services in one Railway project —
`api` (Dockerfile, `backend/`) and `web` (static Vite build served with SPA fallback,
`frontend/`) — each configured by its checked-in `railway.toml` (build, start command,
`/health` healthcheck, restart policy). Everything Railway can't express declaratively
(project/service creation, domains, env wiring, deploy) is `scripts/railway-bootstrap.sh`:
rerunnable from nothing to running, and rerunnable again to redeploy. Domains are created
before the first deploy, so `CORS_ORIGINS` (api) and `VITE_API_BASE_URL` (web, build-time)
are wired up front — no second deploy needed. GitHub-integrated CD is an optional layer:
set each service's Root Directory once in the dashboard (the only non-CLI step).

## Repository layout

| Path | What |
|---|---|
| `backend/app/` | domain model, money allocation, promotion kinds + registry, cluster derivation, cascade engine, optimizer, API |
| `backend/app/seeds/` | catalog + promotion seed JSON |
| `backend/tests/` | the full test suite (see `docs/testing-strategy.md`) |
| `frontend/src/` | cart builder, promotion toggles, price/explanation panel |
| `docs/` | specs written before the code: scope, tech stack, engine, optimizer, promotion abstraction, testing, enforcement, deployment plan |
| `.claude/agents/` | the implementor/verifier agent definitions the work was built with |
