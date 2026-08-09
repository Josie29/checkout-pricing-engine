# Testing Strategy — Pricing / Rules Engine

| Layer | Tool | What it catches |
|---|---|---|
| Property-based invariants | Hypothesis | Random carts × promotion combos — itemization sums to total exactly, total never negative, no double-application, deterministic regardless of promo-id order |
| Golden examples | pytest | Hand-picked cart+promotion combos with frozen expected output — legibility for a reviewer, not coverage |
| Unit, per promotion kind | pytest | Each promotion class in isolation — logic and explanation-trace output, no stacking involved |
| Integration, API layer | pytest + FastAPI TestClient | `POST /price` with a real payload, assert on the response — no mocking (no DB/auth to mock) |
| Stacking/exclusivity matrix | pytest | Explicit enumerated promotion pairs/triples that must conflict — too narrow a slice for random sampling to reliably hit |

## Explicitly out of scope

- Line-coverage targets — invariant/behavior coverage is the goal, not a %.
- Testing what Pydantic/FastAPI already enforce (e.g. 422 on a missing required field).
- Broad frontend coverage — the frontend is explicitly minimal. Revised (2026-08): the
  planned single smoke test was not enough once the deals UI carried real behaviour, so
  the frontend now also tests *which deals may be taken* and *what a click does to the
  others* — state a smoke test cannot see and where a regression silently costs a shopper
  money. Still no component-by-component suite: a test earns its place by covering
  behaviour, not by covering a file. Each added test was verified to fail against the
  behaviour it replaced.

## CI passing

A PR is mergeable only when all of the following exit 0:

- `ruff check` and `ruff format --check`
- `pyright`
- `pytest` (includes the Hypothesis and golden-example suites)

No flaky-test allowance — Hypothesis failures must be fixed or the property narrowed, not retried/skipped.
