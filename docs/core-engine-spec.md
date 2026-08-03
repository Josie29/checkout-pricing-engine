# Core Engine Spec — Default (Naive) Algorithm

Per docs/scope.md's "Stacking/combination engine" line. Contrasted against in docs/optimizer-spec.md, defined here.

Per cluster (docs/seed-promotions.md's phase cardinality), apply the first eligible promo found (declaration order) — no priority field, no ranking. Then cascade Item → Cart → Shipping. No backtracking to withhold an eligible promo for a better downstream result. Cheap, O(1)-ish per cluster, no search — this is what shows immediately as the cart changes. The optimizer (docs/optimizer-spec.md) is the opt-in, more expensive alternative.

## Promotion Status

Every promotion has one of three statuses per request:

| Status | Meaning |
|---|---|
| Available | Shown to the customer, not yet toggled on (docs/scope.md's Promotion toggles) |
| Claimed | Toggled on — a candidate for the engine to consider |
| Applied | Claimed *and* actually used in the winning combination |

Both the naive engine and the optimizer only search over **claimed** promotions — never available-but-untoggled ones. Toggling claims a promo as a candidate, not a forced application: the engine still checks each claimed promo's real eligibility (qty, subtotal) before marking it applied. A claimed-but-ineligible promo stays claimed, never applied, no error.
