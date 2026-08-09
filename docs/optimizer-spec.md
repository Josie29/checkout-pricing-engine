# Spec — Best-Allowed-Combination Optimizer

Closes the open questions in issue #5. Status: **Core**. Legality model is settled (docs/seed-promotions.md's phase cardinality rules).

## Problem

Given a cart and the active promotions, phase cardinality (at most one Item-phase promo per line item, at most one Cart-phase promo, at most one Shipping-phase promo) makes some promotion combinations illegal. The default engine applies one deterministic combination; the optimizer instead finds the *legal* combination that's best for the shopper.

Savings are non-additive — an Item-phase promotion can drop the subtotal below a Cart-phase threshold, forfeiting a bigger downstream discount (concretely: P4 can knock a cart below P2's $50 threshold). So the search space isn't just "resolve cardinality conflicts" — it must include withholding an individually-eligible, non-conflicting promotion when that produces a better total.

## Design

Readability first: the design below is the simple option, not a fallback from a more complex one — it falls directly out of the phase/cardinality structure already settled in docs/seed-promotions.md, so there's no case for reaching for something more elaborate.

**Every phase decomposes into conflict clusters, not just Item.** Two promotions share a cluster if their targets can overlap on a given cart. Within Item phase that's SKU/Category overlap (P1/P6 both target Category: Coffee Beans). Within Cart phase every promotion targets `subtotal` (P2/P5 → one cluster); Shipping phase has a single promotion today (P7 → a singleton cluster) — each phase's promotions share one target by construction, since Cart-phase effects only ever modify the subtotal and Shipping-phase effects only ever modify the shipping fee. That's the "at most one per phase" cardinality rule restated as a cluster, not a coincidence of reusing the same target string across phases.

**A cluster bounds the search; it does not define legality.** Legality is pairwise — at most one Item-phase promo *per line item* (docs/seed-promotions.md) — so a cluster's legal outcomes are its **independent sets** in the overlap graph, not "one member or none". Clusters are *connected components*, and connectivity is transitive while conflict is not: `$1 off Ethiopia` and `$1 off Colombia` never touch the same line, but a Coffee Beans promo overlapping both chains all three into one cluster. Treating the cluster as mutually exclusive would silently drop one of the two $1 deals — the shopper-visible bug this rule replaces. Membership still matters, because whether those two may co-apply depends on whether the bridging promo is applied, so all three must be searched together. Where members really are mutually exclusive (P1/P6, and every Cart/Shipping cluster by construction) the independent sets are exactly the old *k+1* outcomes, so nothing about the seed set changes.

Clusters interact only through the subtotal one phase hands the next: Item's chosen outcome sets what Cart checks eligibility against; Cart's chosen outcome sets what Shipping checks against. That last link is why Cart is no longer a free "just pick the best eligible one" choice now that P7 (free shipping, $100+) has a subtotal condition — a Cart-phase discount can knock the subtotal below $100 and cost the shopper free shipping, the same way P4 can knock it below a Cart threshold. So Cart and Shipping must be searched jointly with Item, not resolved greedily after it.

So: enumerate the cartesian product of every cluster's outcomes across all three phases, price each full combination by running the unchanged core engine, and take the minimum. No second pricing implementation — invariants and the explanation trace are inherited, and the winner's explanation is just the engine's normal trace for that combination.

## Why this doesn't need branch-and-bound

The search space is `∏ (cluster's independent-set count)` across *all* clusters in *all* phases — bounded by catalog structure, **not** by cart size or quantities. For today's seed set every cluster is mutually exclusive, so this is still `∏ (cluster_size + 1)`: Item = one cluster of 2 (P1/P6 → 3 outcomes) × one singleton (P4 → 2 outcomes) = 6; Cart = one cluster of 2 (P2/P5 → 3 outcomes); Shipping = one singleton (P7 → 2 outcomes). Total = 6 × 3 × 2 = 36 pricing evaluations. A cart with 500 units of one SKU is still the same clusters as a cart with 3 — cart size doesn't grow this.

The scaling risk is now sharper than "many promotions": a cluster whose members mostly *don't* conflict is exponential in its size — one category promo over *n* per-SKU promos has `2**n + 1` outcomes, so a shop running a per-SKU deal on ten products alongside one category deal exceeds the 512 cap and degrades to the naive result with `optimal: false`. Enumeration is therefore bounded by the cap as it runs, never counted up front, so a pathological cluster can't blow up before it's measured. Raising the cap is the lever if a real catalog hits this.

Given that, the old design's branch-and-bound with a subadditivity-assumption bound (defended by its own property test) is unnecessary complexity for the common case — the cluster decomposition already keeps the space small, with no assumption to defend. Simpler and more correct-by-construction beats a pruned search that needs a proof obligation.

## Decisions

- **Objective**: minimize final total, integer cents.
- **Tie-break** (deterministic, required for repeatability): fewest promotions applied, then lexicographically smallest set of promotion IDs.
- **Algorithm**: exhaustive cartesian product over every cluster's outcomes, across all three phases. Reuses the core engine's existing phase cascade unchanged.
- **Fallback for pathological catalogs**: if the cluster-product size exceeds a fixed cap, fall back to the default engine's single result and return `optimal: false`. Replaces the old node-budget/anytime-best-so-far machinery — this only matters for catalogs far larger than anything seeded today, and a hard cap is simpler to reason about than a search budget.
- **Runtime sanity check** (second, independent fallback trigger): both engines run on every request. The optimized result is only returned if `0 < optimized_total ≤ naive_total`; otherwise fall back to the naive result with `optimal: false`, same as the cap fallback. This turns "optimizer total ≤ default engine total" from an offline property test into a live guard against any bug the test suite didn't catch — belt and suspenders, not redundant with the test.
- **Legality model**: phase cardinality, not pairwise conflict graphs (docs/seed-promotions.md) — this is what makes clustering possible in the first place.

## API surface

`POST /price` always computes both engines (docs/core-engine-spec.md) — no opt-in flag needed. Response includes `optimal: bool` (false whenever either fallback trigger above fires) and the chosen promotion set; itemization and explanation are unchanged in shape.

## Pinning (2026-08 addition)

`pinned_promotion_ids` lets the shopper override the optimizer: the search is restricted to combinations in which every pinned promotion *actually applies* — containing it is not enough, since a member can be dropped mid-cascade once upstream discounts move its threshold. A pin implies a claim.

Pinning is the only way to take a promotion the search withheld for a better total elsewhere. The checkout's mutual-exclusion behaviour falls out of it for free (pinning one member of a cluster displaces the other), but the P4/P2 case genuinely needs it: those two do not conflict, so no amount of un-claiming rivals would ever surface P4.

Because pinning is strictly a restriction, a pinned result is worse than the unpinned optimum by construction and sometimes worse than naive. **The runtime sanity check above therefore does not apply under pins** — it would silently discard the shopper's override. The guard that replaces it is "were the pins honored"; if not (unsatisfiable pins: mutually conflicting, or ineligible on this cart) the response falls back to naive with `optimal: false`. `optimal: true` under a pin means the search was exhaustive over the combinations the shopper allowed, not that the price is the lowest available — the UI is responsible for disclosing the difference.

## Explaining the outcome

`promotion_availability` (see docs/pricing-ui-spec.md) reports, per promotion: `eligible`, judged against the *winning* combination's cascade state rather than the submitted cart; `gap`, the integer shortfall to qualifying in the promotion's own units; and `conflicts_with`, pairwise target overlap on this cart. Eligibility is measured after upstream deals land because that is the honest reason a promotion did not fire — a $110 cart really can miss a $100 free-shipping bar once $20 of item deals apply.

Kinds opt into `gap` by overriding `Promotion.gap()`, which defaults to `None`, so a new kind stays a one-class change and one whose condition is not a threshold correctly reports nothing.

## Acceptance criteria

- Oracle test: for hand-picked carts (e.g. the P4/P2 scenario), the cluster-product result matches a hand-computed optimum.
- Property tests: optimizer total ≤ default engine total; result invariant to promotion input order; cluster partitioning is correct (two promotions share a cluster iff their targets can intersect on some cart).
- Cap/fallback test: a synthetic catalog exceeding the cluster-product cap falls back cleanly with `optimal: false`.
- Runtime sanity-check test: a forced-bad optimizer result (worse than or equal to zero, or worse than naive) falls back to naive with `optimal: false` rather than being returned.
- Pinning tests: a pin forces a withheld promotion and costs the shopper relative to the free optimum; unsatisfiable pins fall back; pinning the free search's own winners reproduces its result exactly (the optimum is a fixed point of its own pins).
- Availability tests: applied implies eligible; eligible implies no gap; conflicts are symmetric and never self-referential; conflicting promotions are never both applied; a reported shortfall, once closed, makes the promotion eligible.
- All core invariants (never negative, no double-application, itemization sums to total) pass unchanged through the optimizer path.

## Non-goals

- Heuristic pruning within the cluster-product search (e.g. only branching "skip" when a promotion's discount is close to the gap to the next threshold) — add only if a real catalog ever hits the fallback cap.
- Optimizing across promotion *parameters* (only combination selection).
- Any change to default (non-optimized) pricing behavior — docs/core-engine-spec.md's first-eligible-in-declaration-order tie-break is unaffected by this spec; the optimizer doesn't need it because it evaluates rather than guesses.
