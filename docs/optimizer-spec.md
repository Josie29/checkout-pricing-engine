# Spec — Best-Allowed-Combination Optimizer (Stretch)

Closes the open questions in issue #5. Status: **Stretch — do not implement until Core is done and stable.** Exclusivity representation is settled (see docs/seed-promotions.md's phase cardinality rules).

## Problem

Given a cart and the active promotions, phase cardinality (at most one Item-phase promo per line item, at most one Cart-phase promo, at most one Shipping-phase promo) makes some promotion subsets illegal. The default engine applies one deterministic combination; the optimizer instead finds the *legal* subset that is best for the shopper.

Savings are non-additive — one promotion changes the subtotal another's threshold depends on — so subsets cannot be ranked by standalone savings. Each candidate subset must be priced by actually running the engine.

Concretely: P4 (Item phase, always eligible on a cart containing `BREW-V60`, no cardinality conflict) can drop the subtotal below P2's $50 threshold, forfeiting a larger Cart-phase discount. So "legal subset" must include subsets that omit an individually-eligible, non-conflicting promotion — the search space isn't just "resolve cardinality conflicts," it's "consider withholding any promotion if doing so improves a downstream phase's result."

## Design

The optimizer is a thin search layer over the core engine. It enumerates legal subsets and calls the existing deterministic pricing function as its evaluator. No second pricing implementation: invariants and the explanation trace are inherited, and the winner's explanation is just the engine's normal trace.

## Decisions

- **Objective**: minimize final total, integer cents.
- **Tie-break** (deterministic, required for repeatability): fewest promotions, then lexicographically smallest set of promotion IDs.
- **Algorithm**: exhaustive enumeration of legal subsets with branch-and-bound pruning. Bound: sum of remaining promotions' standalone savings. Valid only if effects are subadditive (discounts shrink the subtotal, so threshold promotions never gain value in combination) — defended by a property test, not assumed.
- **Budget**: counted in engine evaluations (search nodes), not wall-clock. A time cutoff would make results nondeterministic run-to-run, contradicting "repeatable" and making tests flaky. The node budget maps to milliseconds empirically once, offline.
- **Anytime behavior**: keep best-so-far; on budget exhaustion return it with `optimal: false`. Floor guarantee: never worse than the default engine result (the search seeds with it).
- **Legality model (settled)**: phase cardinality, not pairwise conflict graphs — at most one Item-phase promo per line item, at most one Cart-phase promo, at most one Shipping-phase promo (docs/seed-promotions.md).

## API surface

`POST /price` gains an opt-in flag (e.g. `optimize: true`). Response adds `optimal: bool` and the chosen promotion set; itemization and explanation are unchanged in shape.

## Acceptance criteria

- Oracle test: on small instances, brute force over all legal subsets matches the optimizer's pick.
- Property tests: optimizer total ≤ default engine total; result invariant to promotion input order; bound-validity (subadditivity) holds under generated carts.
- Large-cart benchmark: node budget holds, degradation is graceful, and the budget-exhausted result is deterministic.
- All core invariants (never negative, no double-application, itemization sums to total) pass unchanged through the optimizer path.

## Non-goals

- Dynamic programming or heuristic search — only if measurement shows enumeration + pruning fails the budget on realistic inputs.
- Optimizing across promotion *parameters* (only subset selection).
- Any change to default (non-optimized) pricing behavior.
