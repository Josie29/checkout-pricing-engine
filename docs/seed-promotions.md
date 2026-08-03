# Seed Promotions — Roast & Co (coffee & kitchenware)

## Catalog

| SKU | Name | Category | Price (cents) |
|---|---|---|---|
| COF-ETH | Ethiopia Yirgacheffe, 12oz | Coffee Beans | 1600 |
| COF-COL | Colombia Supremo, 12oz | Coffee Beans | 1400 |
| COF-DEC | Sumatra Decaf, 12oz | Coffee Beans | 1500 |
| BREW-V60 | Ceramic Pour-Over Dripper | Brew Gear | 2800 |
| BREW-GRD | Manual Burr Grinder | Brew Gear | 4500 |
| MUG-CLS | Classic Stoneware Mug | Drinkware | 1200 |
| MUG-TVL | Travel Tumbler | Drinkware | 2200 |
| SNK-BSC | Almond Biscotti, 6pk | Snacks | 900 |

Prices are integer cents, not decimal dollars — avoids floating-point rounding drift when allocating discounts across lines (scope.md's "no rounding drift" invariant). Display formatting (`$D.CC`) happens at render time in the frontend; storage/computation stays integer cents throughout.

## Promotions

| ID | Name | Type | Phase | Target | Condition | Effect | Exclusivity group |
|---|---|---|---|---|---|---|---|
| P1 | Beans: buy 2 get 1 free | BXGY | Item | Category: Coffee Beans | qty ≥ 3 | cheapest unit free | `coffee_qty` |
| P6 | Beans: bulk 20% off | PCT_OFF_ITEM | Item | Category: Coffee Beans | qty ≥ 3 | 20% off each | `coffee_qty` |
| P4 | $5 off pour-over dripper | FIXED_OFF_ITEM | Item | SKU: BREW-V60 | none | −$5 | — |
| P2 | 15% off $50+ | PCT_OFF_CART | Cart | cart | subtotal ≥ $50 | 15% off subtotal | `cart_pct` |
| P5 | 20% off $100+ | PCT_OFF_CART | Cart | cart | subtotal ≥ $100 | 20% off subtotal | `cart_pct` |
| P3 | Free shipping (members) | FREE_SHIPPING | Shipping | cart | `is_member = true` | shipping → $0 | — |

## Phases

`Phase` is a property of `Type`, not authored per promotion instance — it's always the same for every `FIXED_OFF_ITEM`, never a per-cart choice, which is what keeps results deterministic. Phases run in a fixed order; each one's eligibility is checked against the previous phase's output, not the original cart:

| Order | Phase | Eligibility checked against |
|---|---|---|
| 1 | Item | Original line item price/qty |
| 2 | Cart | Subtotal *after* Item-phase discounts are applied |
| 3 | Shipping | Cart state after Cart-phase discounts (membership flag is independent of this) |

This is why P4 (Item phase) always affects whether P2/P5 (Cart phase) qualify: P4's discount is baked into the subtotal *before* P2/P5's threshold is checked, not after. Without a declared phase order, "does P4 apply before or after the cart threshold check" would be undefined per cart — the same cart could legally get two different totals.

Open edge case, not yet resolved: two promotions in the *same* phase that overlap the same line item (e.g. a future item-level promo also targeting `BREW-V60` alongside P4) still need a composition rule — 20%-off-then-$5-off and $5-off-then-20%-off give different totals on the same line. Today's seed set doesn't trigger this, but issue #8 (promotion abstraction) needs to settle it before someone adds a promo that does.

## How exclusivity works

`Exclusivity group` is a tag, not a pairwise list: any promotions sharing the same non-empty group value are mutually exclusive — at most one from that group can apply to a given cart. P1 and P6 both tagged `coffee_qty` means a cart qualifying for both can only get one of them. Promotions with no group (P3, P4) aren't constrained by this mechanism at all.

Group membership defines which *combinations are legal* — it does not, by itself, say which promo the default (non-optimizer) engine picks when a cart triggers a real group conflict. That tie-break (e.g. an explicit priority per promotion within a group) is an open gap, deliberately not resolved yet.

Beyond declared groups, promotions can also conflict *emergently*: P4 (fixed $ off a specific item) can drop the cart subtotal below P2/P5's threshold with no group tag involved — nothing declares this conflict, the cart math just makes it happen. This is why the optimizer (issue #5) has to actually price each candidate subset rather than reason about declared conflicts alone.
