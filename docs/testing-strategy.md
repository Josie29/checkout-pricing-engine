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
- Dedicated frontend test suite beyond one smoke test — frontend is explicitly minimal.

## CI passing

A PR is mergeable only when all of the following exit 0:

- `ruff check` and `ruff format --check`
- `pyright`
- `pytest` (includes the Hypothesis and golden-example suites)

No flaky-test allowance — Hypothesis failures must be fixed or the property narrowed, not retried/skipped.
