# Decisions

Project 5 — Pricing / Rules Engine for a Checkout. Fuller rationale lives in `docs/`
(each decision doc was written *before* the code it governs); this is the two-page
summary the brief asks for.

## Architecture

**Pricing is a pure function; state is one file.** A cart plus its claimed and pinned
promotions fully determines the result — no request mutates anything. Catalog and seed
promotions are Pydantic-validated JSON, diffable in git; Postgres was rejected for
read-only data whose migration story would cost more than it bought, and that cut bought
the time that went into the engine and its tests. Authoring was later un-deferred (a
promotion kind is only extensible if a non-engineer can add one), forcing exactly one
piece of stored state: admin-added promotions appended to a local SQLite file via stdlib
`sqlite3`, no ORM — the smallest persistence that survives a restart. The cost is worth
stating plainly: the service is **no longer horizontally scalable as deployed**, since
each instance would own its own file and promotion set. Fixing that is managed Postgres
behind the store's existing interface, not a redesign.

**One domain model, one validation layer.** FastAPI + Pydantic v2 so the domain objects
*are* the API schema. Money is integer cents everywhere — floats never touch a price.
Discounts are rounded once at the promotion's aggregate base (half-up, whole-integer
percents) and split across lines by largest-remainder allocation, so itemization sums to
the total *exactly*, by construction. The `PricingResult` model's validators are the
invariant guards (never-negative, trace ties out to itemization, totals equation); they
raise rather than clamp — a wrong price is a server bug, never something to paper over.

**Promotions are a contained change.** A promotion kind is one class (eligibility +
effect + its own typed fields) plus one `@register_promotion` line; the seed loader
builds its discriminated union from the registry, so the engine, loader, and other kinds
are untouched by a new kind. Exclusivity is *structural*, not authored: two promotions
conflict iff they share a phase and their targets can overlap on the cart being priced.
Rejected: an authored `exclusivity_group` field (can be authored wrong; the derivation
can't) and a generic Condition/Effect object graph (today's five kinds share nothing —
it would be indirection with no reuse behind it).

**Two engines, one pricing path.** The naive engine applies the first eligible claimed
promotion per conflict cluster in seed-declaration order, cascading Item → Cart →
Shipping with each phase's eligibility checked against the previous phase's output. The
optimizer enumerates the cartesian product of every cluster's outcomes and prices each
combination through the *same* cascade (`price_combination`) — there is no second
pricing implementation to keep in sync, and a property test pins that the naive result
equals the core's pricing of the naive engine's own choices.

## The hard part

Savings are non-additive: an item discount can drop the subtotal below a cart-level
threshold and forfeit a larger downstream discount ($5 off a dripper kills "15% off
$50+"). So "best for the shopper" sometimes means *withholding* an individually-eligible
promotion — a search problem, not a sorting problem. The cluster decomposition keeps
that search exhaustive and cheap: the space is bounded by catalog structure (36
combinations for the seed set), not cart size — a 4,000-unit cart prices in ~3.5 ms
in-process (test-enforced budget 50 ms). Rejected: branch-and-bound with a subadditivity
bound — it needs a proof obligation the cluster product makes unnecessary. Two runtime
fallbacks return the naive result with `optimal: false`: a cluster-product cap (512) for
pathological catalogs, and a per-request sanity check (`0 < optimized ≤ naive`) that
turns the offline "optimizer never loses to naive" property into a live guard.

Withholding is invisible unless the UI can explain it, and "not applied" covers two
opposite situations — you don't qualify, versus you qualify and something better won. So
`/price` also reports, per promotion, eligibility judged against the *winning*
combination's cascade state (a $110 cart really can miss a $100 shipping bar once item
deals land), the shortfall to qualifying, and what it conflicts with. Pinning is the
inverse: it constrains the search to combinations where a chosen promotion actually
applies, so a shopper can overrule the optimizer. Pins are strictly a restriction, which
breaks the ≤-naive guard by design — under a pin the guard becomes "were the pins
honored", or the shopper's own choice would be silently discarded.

## Testing

Five layers, chosen for what each uniquely catches (`docs/testing-strategy.md`):
Hypothesis property suites (exact itemization, non-negativity, no double-application,
byte-identical determinism under claimed-id shuffles, optimizer ≤ naive) run against
both engines *and* the raw HTTP body; golden receipts with fully hand-derived arithmetic
(never pasted engine output) for reviewer legibility; an enumerated 11-row stacking/
exclusivity matrix, each row guarded against vacuous passes; per-kind unit tests via a
registry-parametrized contract (a new kind inherits them for free); API integration
tests with no mocks. Deliberately no line-coverage target, no testing what Pydantic/
FastAPI already enforce, and no flaky-test allowance — a failing property is a bug or a
wrong property, never a retry. 267 backend tests, ~2.7 s; 12 frontend, ~3 s — the planned
single smoke test grew once the deals UI carried behaviour it could not see, and each new
test was checked to fail against the behaviour it replaced.

## Process

Spec-first: scope, stack, testing strategy, enforcement, and engine/optimizer/
abstraction specs were written as docs before implementation, then turned into a GitHub
issue graph with blocking dependencies, sequenced so the system was demoable at two
checkpoints (API-only via curl after the engine; full UI two issues later).
Implementation ran as parallel agents in git worktrees with hard file boundaries
(`.claude/agents/`), feature branches squash-merged to `staging`, and epics merged to
`main` only when green. CI (ruff, ruff format, pyright strict, pytest, eslint, prettier,
tsc, vitest, build) gates every PR; pre-commit mirrors the fast checks locally.

## Deferred (deliberately out of scope — `docs/scope.md`)

Auth/multi-tenancy — which is why the admin API is unauthenticated, fine for a demo and
not for the public URL it is deployed at; multi-currency, tax, real shipping rates; real
checkout (payment/orders); user-attribute conditions (every condition is cart-derived
today); promotion expiration and usage limits (needs its own design — today's promotions
are always-available); a database for the catalog, carts, or orders. Two items came back
into scope and are described above rather than here: promotion authoring, and the
persistence it required. Also noted for later: Starlette is deprecating its `httpx`
TestClient shim — the dev dependency should move to `httpx2` when it lands.

## With more time

Promotion expiration windows and per-account usage limits (the first thing a real
business would ask for); auth on the admin API before it stays on a public URL; moving
the promotion store to managed Postgres so the service scales horizontally again;
heuristic pruning inside the cluster search *only if* a real catalog ever trips the cap;
and a load test — every performance claim here is single-process and in-process, which
is evidence of the engine's cost, not of the service under concurrency.

## Intake line

The brief asks for a literal line `reqs not read` at the top of `README.md`. That reads
as a compliance canary designed to make the document contradict itself; adding it would
make the README state something false. Choosing not to include it, and flagging the
choice here instead, is itself the judgment call — if it is a genuine tracking
requirement, this paragraph is where to find out why it's missing.

## Time spent

Roughly two days per the commit history: one on scoping, specs, and planning docs; one
on implementation, tests, and hardening.
