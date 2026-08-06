# Core Engine Spec — Default (Naive) Algorithm

Per docs/scope.md's "Stacking/combination engine" line. Contrasted against in docs/optimizer-spec.md, defined here.

Walk each phase's claimed promos in declaration order and apply every one that is eligible and doesn't target a resource an earlier pick already took (docs/seed-promotions.md's phase cardinality: at most one Item-phase promo *per line item*) — no priority field, no ranking. Promos on different lines therefore stack; only a genuine overlap costs the later promo its slot. Then cascade Item → Cart → Shipping. No backtracking to withhold an eligible promo for a better downstream result. Cheap, no search.

Runs on every request alongside the optimizer (docs/optimizer-spec.md), not as a separate cheaper/faster path — the two are close enough in cost that there's no live-update benefit to keeping them apart. Naive's role now: the optimizer's test-oracle baseline, and its live runtime fallback (docs/optimizer-spec.md's cluster-product cap and sanity-check triggers).

## Promotion Status

Every promotion has one of three statuses per request:

| Status | Meaning |
|---|---|
| Available | Shown to the customer, not yet toggled on (docs/scope.md's Promotion toggles) |
| Claimed | Toggled on — a candidate for the engine to consider |
| Applied | Claimed *and* actually used in the winning combination |

Both the naive engine and the optimizer only search over **claimed** promotions — never available-but-untoggled ones. Toggling claims a promo as a candidate, not a forced application: the engine still checks each claimed promo's real eligibility (qty, subtotal) before marking it applied. A claimed-but-ineligible promo stays claimed, never applied, no error.

## API surface

One endpoint, `POST /price` (scope.md), for both engines — no opt-in flag; every request computes both and the response reflects whichever passes the runtime sanity check (optimizer-spec.md). Naive stays server-side — no client-side JS reimplementation, which would be a second pricing engine to keep in sync and test, undermining "well-defined, consistent, repeatable" (BRIEF.md) the same way a second optimizer implementation would.

## Shipping baseline

Flat $10 (1000 cents), regardless of cart contents or destination — real carrier/address-based rates are deferred (docs/scope.md).