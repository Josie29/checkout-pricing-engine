# Tech Stack — Pricing / Rules Engine

| Layer | Component | Choice | Reason |
|---|---|---|---|
| Backend | API framework | FastAPI | Async, typed, integrates natively with Pydantic for request/response validation |
| Backend | Data modeling | Pydantic v2 | Domain model and API validation share the same classes — no duplicate schema layer |
| Backend | Unit testing | pytest | Unit tests per promotion kind |
| Backend | Property-based testing | Hypothesis | Invariant tests (itemization sums to total, never negative, no double-application) |
| Backend | Linting | Ruff | Deterministic, CI-gateable |
| Backend | Type checking | Pyright | 2–5x faster, ~95-98% typing-spec conformance vs. mypy's ~58%; matches VS Code/Pylance so editor and CI agree |
| Frontend | Build tool | Vite | Fast dev server/HMR, zero-config for a small single-page app |
| Frontend | UI framework | React | Largest ecosystem, most reviewer-familiar, for three minimal components (cart builder, promotion toggles, price breakdown panel) |
| Frontend | Language | TypeScript | Matches the backend's typed philosophy (Pydantic, Pyright) |

## Rejected alternatives

| Component | Option | Why not |
|---|---|---|
| API framework | Litestar | Faster than FastAPI on paper (msgspec-based), but smaller ecosystem and less reviewer-familiar — not worth the tradeoff at this scale. |
| API framework | Django REST Framework | Its strengths (ORM, admin panel, batteries-included auth) are irrelevant for a stateless pricing API with no persistence layer; FastAPI has 3–4x the throughput and is async-native. |
| API framework | Flask | No native async, no built-in validation/serialization — would need Marshmallow/Pydantic bolted on separately, recreating what FastAPI gives for free. |
| API framework | Fastify/Express/NestJS (TS) | Would unify language with the frontend, but splits domain modeling (Zod) from typed objects in a way Pydantic doesn't; NestJS's DI/module ceremony is overkill for a solo take-home. |
| Data modeling | msgspec | 2–12x faster than Pydantic v2, but a narrower feature set (no validator decorators, thinner error messages), and FastAPI integration isn't first-party — community packages only. |
| Data modeling | attrs | Good for internal, already-trusted domain objects with composable validators, but no built-in JSON schema/serialization story — would need `cattrs` bolted on at the API boundary. |
| Data modeling | dataclasses (stdlib) | Zero dependency, but no runtime validation at all — wrong choice for objects built directly from untrusted API input. |
| Unit testing | unittest (stdlib) | No dependency, but far more boilerplate (class-based, verbose assertions) than pytest's plain functions/fixtures. |
| Property-based testing | — | Hypothesis is effectively unchallenged in the Python ecosystem (used in CPython's own test suite); no viable alternative found. |
| Linting | flake8 + isort + black + pylint | The pre-Ruff standard stack — four separate tools with overlapping config vs. Ruff's single binary, and meaningfully slower. |
| Type checking | mypy | Reference implementation, most mature plugin ecosystem (Django/Pydantic plugins), but 2–5x slower and only ~58% typing-spec conformance vs. Pyright's ~95-98%. |
| Type checking | ty (Astral) | 10–100x faster than mypy/Pyright, same vendor as Ruff, but still pre-1.0 (beta since Dec 2025) with low conformance (~15% by one estimate) — not yet a safe CI gate. |
| Build tool | Webpack | More configurable, but far slower dev server/HMR than Vite for a small SPA — extra config for no benefit here. |
| Build tool | Parcel | Zero-config like Vite, but a smaller ecosystem and less common in reviewer expectations. |
| Build tool | Create React App | Officially deprecated/unmaintained by the React team — shouldn't be used for new projects. |
| UI framework | SolidJS | Smaller bundle, no virtual DOM, but smaller ecosystem and less reviewer-familiar for a quick evaluation read. |
| UI framework | Svelte/SvelteKit | Less boilerplate, but less common/less immediately legible to a reviewer skimming code. |
| UI framework | Vue | Mature and popular, but no stronger fit than React for this scope; React is the more universally reviewer-familiar default. |
| UI framework | htmx | Matches "frontend stays minimal" in spirit, but couples the UI to server-rendered fragments when the backend is already a pure JSON API (`POST /price`). |
| Language | JavaScript | No compile-time type checking — breaks the typed-everywhere philosophy shared with Pydantic/Pyright on the backend. |
| Data persistence | SQLite / Postgres | No CRUD or query needs — adds a migration story for data that's read-only and seeded. |

## Data persistence

Pydantic-validated JSON/YAML seed files, not a database. Pricing is a pure function of inputs; there's no CRUD to persist against, and config stays diffable in git. Resolves the "promotion persistence" sub-decision from issue #2.

## Open sub-decisions from issue #2

- **Where stacking rules live** (per-promotion metadata vs. global rule config) — still open; this is a stacking-engine design question, not a stack pick, so leaving it for implementation/DECISIONS.md.
