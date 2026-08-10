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

## Deferred

This section is the single source for what was cut and what comes next; `DECISIONS.md`
points here rather than repeating it.

- Auth / multi-tenant anything
- ~~Promotion authoring UI or CRUD~~ — un-deferred (issue #68) as a runtime API (`POST /promotions`) + admin form; additions persist to SQLite as of issue #75 (below). Admin is unauthenticated by scope (auth is deferred above).
- ~~Persistence beyond seeded promotions~~ — partially un-deferred (issue #75): runtime-added promotions now persist to a local SQLite file (stdlib `sqlite3`, no ORM; env `PROMOTIONS_DB_PATH`, default `backend/data/promotions.db`) and survive restarts. Everything else stays stateless: pricing is still a pure function of inputs, and a database for the catalog, carts, or orders remains out of scope
- Multi-currency, tax, real shipping rates
- Real checkout flow (payment, orders)
- User-attribute-based promotion conditions (e.g. an `is_member` flag) — simplification for now; every condition is cart/item-derived
- Promotion expiration/usage limits — expiration dates, one-time-use vs. N-uses vs. unlimited-in-period. Undecided, needs its own decision; today's promotions are always-available with no usage tracking
- Cloud deployment — optional bonus per BRIEF.md (issue #6), not attempted until Core is done and stable. Decided: Railway, two separate services (backend, frontend) under one Railway project, infra as code via a checked-in `railway.toml` — not configured by hand through the dashboard. Full plan in `docs/deployment-plan.md`.

## Next, in order

What a second pass would take on, most valuable first:

- **Promotion expiration windows and per-account usage limits** — the first thing a real business asks for, and the one deferral with no design yet.
- **Auth on the admin API** — it is unauthenticated on a public URL today, which is fine for a demo and not for anything else.
- **Move the promotion store to managed Postgres.** The SQLite file (issue #75) means the service is no longer horizontally scalable: a second instance would own its own file and its own promotion set. The store already sits behind one interface, so this is a driver swap, not a redesign.
- **A load test.** Every performance number claimed anywhere in this repo is single-process and in-process — evidence of the engine's cost, not of the service under concurrency. That distinction is currently asserted rather than shown.
- **Heuristic pruning inside the cluster search** — only if a real catalog ever trips the cluster-product cap (see the limitations below).
- Housekeeping: Starlette is deprecating its `httpx` TestClient shim; the dev dependency should move to `httpx2` when it lands.

## Known limitations of the optimizer

Both are measured, bounded, and visible to the shopper (a capped search reports `optimal: false`); neither is a correctness bug.

- **A promotion blocks lines it never discounted.** Legality is decided from promotion *targets* before pricing, not from the allocations pricing produces. So a category-wide deal excludes every per-SKU deal on that category, even on a line it left at full price — e.g. Colombia ×3 satisfies buy-2-get-1 on its own, and `$1 off Ethiopia` is still refused although Ethiopia is neither a qualifier nor a recipient. Costs a shopper ~$1–3 on a mixed bean cart. Fixing it means allocation-based legality, which is circular (you must price a combination to learn whether it was legal), so the search would lose its pre-pruning and fall back to all-subsets-plus-validation — directly worsening the cap below. Deliberately not attempted.
- **The search caps out on overlapping catalogs.** A cluster's legal outcomes are its independent sets, so one category deal over *n* per-SKU deals is `2**n + 1` combinations. With the seed set live, **6** per-SKU deals in one category exceeds `cluster_product_cap` (512) and degrades to the naive result. Measured: ~50–125 µs per cascade evaluation, so 512 ≈ 40 ms — the cap is the interactive latency budget, not an arbitrary number. Cart size and quantities do **not** grow the search; only overlapping promotions do. If a real catalog hits this, the fix is branch-and-bound with an optimistic bound (`subtotal − all remaining discounts − shipping baseline`), which is admissible without assuming anything about condition shapes — unlike the subadditivity bound `docs/optimizer-spec.md` rejected.
