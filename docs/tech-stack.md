# Tech Stack — Pricing / Rules Engine

## Backend

- **FastAPI + Pydantic v2** — domain model and API request/response validation share the same classes, no duplicate schema layer.
- **pytest + Hypothesis** — unit tests per promotion kind, property-based tests for invariants (itemization sums to total, never negative, no double-application).
- **Ruff + Pyright**, wired into pre-commit and CI, for deterministic lint/type enforcement (see clean-code enforcement plan). Pyright over mypy: 2–5x faster, ~95-98% typing-spec conformance vs mypy's ~58%, and it's what VS Code/Pylance already uses for editor feedback — one type checker instead of two disagreeing ones.

## Frontend

- **Vite + React + TypeScript** — lowest-friction toolchain for the three minimal components (cart builder, promotion toggles, price breakdown panel).

## Config / promotion storage

- **Pydantic-validated JSON/YAML seed files**, not a database. Pricing is a pure function of cart + active promotion ids (scope.md); there's no authoring CRUD to persist against. Config lives in git, is diffable, and is trivially loadable in tests.

## Rejected alternatives

| Option | Why not |
|---|---|
| Litestar | Faster than FastAPI on paper, but smaller ecosystem and less reviewer-familiar — not worth the tradeoff at this scale. |
| Fastify/Express/NestJS (TS backend) | Would unify language with the frontend, but splits domain modeling (Zod) from typed objects in a way Pydantic doesn't; NestJS's DI/module ceremony is overkill for a solo take-home. |
| htmx | Matches "frontend stays minimal" in spirit, but couples the UI to server-rendered fragments when the backend is already a pure JSON API (`POST /price`). |
| SQLite / Postgres | No CRUD or query needs — adds a migration story for data that's read-only and seeded. |

## Open sub-decisions from issue #2

- **Promotion persistence** — resolved: validated config files, not a DB (see above).
- **Where stacking rules live** (per-promotion metadata vs. global rule config) — still open; this is a stacking-engine design question, not a stack pick, so leaving it for implementation/DECISIONS.md.
