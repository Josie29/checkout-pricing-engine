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

| ID | Name | Type | Phase | Target | Condition | Effect |
|---|---|---|---|---|---|---|
| P1 | Coffee Beans: buy 2 get 1 free | BXGY | Item | Category: Coffee Beans | qty ≥ 3 | cheapest unit free |
| P6 | Coffee Beans: 20% off (min 3) | PCT_OFF_ITEM | Item | Category: Coffee Beans | qty ≥ 3 | 20% off each |
| P4 | $5.00 off Ceramic Pour-Over Dripper | FIXED_OFF_ITEM | Item | SKU: BREW-V60 | none | −$5 |
| P2 | 15% off $50.00+ | PCT_OFF_CART | Cart | subtotal | subtotal ≥ $50 | 15% off subtotal |
| P5 | 20% off $100.00+ | PCT_OFF_CART | Cart | subtotal | subtotal ≥ $100 | 20% off subtotal |
| P7 | Free shipping $100.00+ | FREE_SHIPPING | Shipping | shipping | subtotal ≥ $100 | shipping → $0 |

## Phases

`Phase` is a property of `Type`, not authored per promotion instance — it's always the same for every `FIXED_OFF_ITEM`, never a per-cart choice, which is what keeps results deterministic. Phases run in a fixed order; each one's eligibility is checked against the previous phase's output, not the original cart:

| Order | Phase | Eligibility checked against |
|---|---|---|
| 1 | Item | Original line item price/qty |
| 2 | Cart | Subtotal *after* Item-phase discounts are applied |
| 3 | Shipping | Cart state after Cart-phase discounts |

### How exclusivity works

Derived structurally from phase cardinality: at most one Item-phase promo per line item (P1/P6 conflict — same Coffee Beans lines; P4 doesn't, since nothing else targets `BREW-V60`), at most one Cart-phase promo (P2/P5). Shipping phase has a single promo (P7) today, so no conflict to resolve there yet. Can't express a cross-cutting exclusion unrelated to target overlap — not needed today.



