# Spec — Best-Allowed-Combination Optimizer

Closes the open questions in issue #5. Status: **Core**. Legality model is settled (docs/seed-promotions.md's phase cardinality rules).

## Problem

Given a cart and the active promotions, phase cardinality (at most one Item-phase promo per line item, at most one Cart-phase promo, at most one Shipping-phase promo) makes some promotion combinations illegal. The default engine applies one deterministic combination; the optimizer instead finds the *legal* combination that's best for the shopper.

Savings are non-additive — an Item-phase promotion can drop the subtotal below a Cart-phase threshold, forfeiting a bigger downstream discount (concretely: P4 can knock a cart below P2's $50 threshold). So the search space isn't just "resolve cardinality conflicts" — it must include withholding an individually-eligible, non-conflicting promotion when that produces a better total.

## Design

Readability first: the design below is the simple option, not a fallback from a more complex one — it falls directly out of the phase/cardinality structure already settled in docs/seed-promotions.md, so there's no case for reaching for something more elaborate.

**Every phase decomposes into conflict clusters, not just Item.** Two promotions share a cluster if their targets can overlap on a given cart. Within Item phase that's SKU/Category overlap (P1/P6 both target Category: Coffee Beans). Within Cart phase every promotion targets `subtotal` (P2/P5 → one cluster); within Shipping phase every promotion targets `shipping` (P3/P7 → one cluster) — each phase's promotions share one target by construction, since Cart-phase effects only ever modify the subtotal and Shipping-phase effects only ever modify the shipping fee. That's the "at most one per phase" cardinality rule restated as a cluster, not a coincidence of reusing the same target string across phases. A cluster of size *k* has exactly *k+1* legal outcomes: one of its *k* promotions, or none.

Clusters interact only through the subtotal one phase hands the next: Item's chosen outcome sets what Cart checks eligibility against; Cart's chosen outcome sets what Shipping checks against. That last link is why Cart is no longer a free "just pick the best eligible one" choice now that P7 (free shipping, $100+) has a subtotal condition — a Cart-phase discount can knock the subtotal below $100 and cost the shopper free shipping, the same way P4 can knock it below a Cart threshold. So Cart and Shipping must be searched jointly with Item, not resolved greedily after it.

So: enumerate the cartesian product of every cluster's outcomes across all three phases, price each full combination by running the unchanged core engine, and take the minimum. No second pricing implementation — invariants and the explanation trace are inherited, and the winner's explanation is just the engine's normal trace for that combination.

## Why this doesn't need branch-and-bound

The search space is `∏ (cluster_size + 1)` across *all* clusters in *all* phases — bounded by catalog structure, **not** by cart size or quantities. For today's seed set: Item = one cluster of 2 (P1/P6 → 3 outcomes) × one singleton (P4 → 2 outcomes) = 6; Cart = one cluster of 2 (P2/P5 → 3 outcomes); Shipping = one cluster of 2 (P3/P7 → 3 outcomes). Total = 6 × 3 × 3 = 54 pricing evaluations. A cart with 500 units of one SKU is still the same clusters as a cart with 3 — cart size doesn't grow this. The real scaling risk is a catalog with many distinct, independently-relevant promotions across phases — that's where a fallback matters, not cart size.

Given that, the old design's branch-and-bound with a subadditivity-assumption bound (defended by its own property test) is unnecessary complexity for the common case — the cluster decomposition already keeps the space small, with no assumption to defend. Simpler and more correct-by-construction beats a pruned search that needs a proof obligation.

## Decisions

- **Objective**: minimize final total, integer cents.
- **Tie-break** (deterministic, required for repeatability): fewest promotions applied, then lexicographically smallest set of promotion IDs.
- **Algorithm**: exhaustive cartesian product over every cluster's outcomes, across all three phases. Reuses the core engine's existing phase cascade unchanged.
- **Fallback for pathological catalogs**: if the cluster-product size exceeds a fixed cap, fall back to the default engine's single result and return `optimal: false`. Replaces the old node-budget/anytime-best-so-far machinery — this only matters for catalogs far larger than anything seeded today, and a hard cap is simpler to reason about than a search budget.
- **Legality model**: phase cardinality, not pairwise conflict graphs (docs/seed-promotions.md) — this is what makes clustering possible in the first place.

## API surface

`POST /price` gains an opt-in flag (e.g. `optimize: true`). Response adds `optimal: bool` and the chosen promotion set; itemization and explanation are unchanged in shape.

## Acceptance criteria

- Oracle test: for hand-picked carts (e.g. the P4/P2 scenario, and a member spending $100+ where P3/P7 tie on price), the cluster-product result matches a hand-computed optimum.
- Property tests: optimizer total ≤ default engine total; result invariant to promotion input order; cluster partitioning is correct (two promotions share a cluster iff their targets can intersect on some cart).
- Cap/fallback test: a synthetic catalog exceeding the cluster-product cap falls back cleanly with `optimal: false`.
- All core invariants (never negative, no double-application, itemization sums to total) pass unchanged through the optimizer path.

## Non-goals

- Heuristic pruning within the cluster-product search (e.g. only branching "skip" when a promotion's discount is close to the gap to the next threshold) — add only if a real catalog ever hits the fallback cap.
- Optimizing across promotion *parameters* (only combination selection).
- Any change to default (non-optimized) pricing behavior — its still-open Cart/Shipping tie-break priority gap is unaffected by this spec; the optimizer doesn't need it because it evaluates rather than guesses.
