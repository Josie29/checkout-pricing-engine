# Scope — Project 5: Pricing / Rules Engine for a Checkout

High-level component breakdown. Backend is the focus; frontend stays minimal.

## Backend

| Component | What it is | Priority |
|---|---|---|
| Domain model | Cart, LineItem, Promotion, Adjustment, PricingResult (itemized breakdown + explanation) | Core |
| Money handling | Integer cents everywhere; discount allocation across lines must sum exactly (no rounding drift) | Core |
| Promotion abstraction | Common interface so a new promotion kind is a contained change (one new class + registration) | Core |
| Concrete promotions (3–4 kinds) | Buy-X-get-Y free (quantity), % off over threshold (cart), free shipping over threshold (cart), fixed amount off item | Core |
| Stacking/combination engine | Deterministic application order, exclusivity rules, repeatable results — the hard part | Core |
| Explanation trace | Per-promotion: what applied, to which lines, what it did in dollars | Core |
| Invariant guards | Never negative totals, no double-application, itemization sums to final price, input validation | Core |
| Pricing API | `POST /price` (cart + active promotion ids → itemized result) | Core |
| Promotions API | List promotions + active state (seeded data; no authoring CRUD) | Core |
| Tests | Unit per promotion kind, combination/stacking cases, property-based invariant tests, golden examples | Core |
| Best-allowed-combination optimizer | Pick optimal legal promo set for shopper (docs/optimizer-spec.md) | Core |

## Frontend (single page, minimal)

| Component | What it is | Priority |
|---|---|---|
| Cart builder | Add/remove items, edit qty/price (from a small seeded catalog) | Core |
| Promotion toggles | Checkbox list of promotions, on/off | Core |
| Price breakdown panel | Itemized lines, per-promotion explanation, final total; recomputes on change | Core |
| Error/empty states | Loading, API failure, no results | Core |

## Deferred (TODO: document in DECISIONS.md)

- Auth / multi-tenant anything
- Promotion authoring UI or CRUD (seeded config instead)
- Persistence beyond seeded promotions (pricing is a pure function of inputs)
- Multi-currency, tax, real shipping rates
- Real checkout flow (payment, orders)
- User-attribute-based promotion conditions (e.g. an `is_member` flag) — simplification for now; every condition is cart/item-derived
- Promotion expiration/usage limits — expiration dates, one-time-use vs. N-uses vs. unlimited-in-period. Undecided, needs its own decision; today's promotions are always-available with no usage tracking
- Cloud deployment — optional bonus per BRIEF.md (issue #6), not attempted until Core is done and stable. Decided: Railway, two separate services (backend, frontend) under one Railway project, infra as code via a checked-in `railway.toml` — not configured by hand through the dashboard. Full plan in `docs/deployment-plan.md`.
