import httpx
from fastapi.testclient import TestClient

from app.main import app as fastapi_app

client = TestClient(fastapi_app)

# Every expected value in this file is hand-derived from docs/seed-promotions.md
# and the rounding rules in docs (whole-int percents, half-up at the aggregate,
# largest-remainder split, ties toward the earlier index) — never copied from an
# engine run. Each test freezes the COMPLETE /price response body so a reviewer
# can check the receipt line by line against the narrated arithmetic.


def _price(cart_items: list[dict[str, object]], claimed: list[str]) -> httpx.Response:
    """POST /price with the given cart lines and claimed promotion ids."""
    return client.post(
        "/price",
        json={"cart": {"items": cart_items}, "claimed_promotion_ids": claimed},
    )


class TestGoldenReceipts:
    """Hand-picked cart+promotion stories with fully frozen response bodies."""

    def test_three_colombia_bags_with_bxgy_cheapest_free(self) -> None:
        """A shopper buys three bags of Colombia beans with buy-2-get-1 on.

        The simplest single-promo receipt: if this drifts by a cent, every
        BXGY receipt in the shop is wrong. Catches the free unit being
        priced at anything but one unit's price, the discount landing on
        the wrong line, or the flat $10 shipping being dropped.

        Hand arithmetic:
          subtotal = 3 x 1400            = 4200
          P1 (qty 3 >= 3): cheapest matched unit free = 1400, on COF-COL
          line total     = 4200 - 1400   = 2800
          shipping       = flat baseline = 1000
          total          = 2800 + 1000   = 3800
        Only P1 is claimed; the optimizer agrees with naive (applying the
        only deal beats skipping it), so the response is labeled optimal.
        """
        response = _price(
            [
                {
                    "sku": "COF-COL",
                    "name": "Colombia Supremo, 12oz",
                    "category": "Coffee Beans",
                    "unit_price_cents": 1400,
                    "qty": 3,
                }
            ],
            ["P1"],
        )
        assert response.status_code == 200
        assert response.json() == {
            "lines": [
                {
                    "sku": "COF-COL",
                    "name": "Colombia Supremo, 12oz",
                    "category": "Coffee Beans",
                    "unit_price_cents": 1400,
                    "qty": 3,
                    "line_subtotal_cents": 4200,
                    "discount_cents": 1400,
                    "line_total_cents": 2800,
                }
            ],
            "adjustments": [
                {
                    "promotion_id": "P1",
                    "promotion_name": "Coffee Beans: buy 2 get 1 free",
                    "phase": "item",
                    "amount_cents": 1400,
                    "line_allocations": [{"sku": "COF-COL", "amount_cents": 1400}],
                }
            ],
            "subtotal_cents": 4200,
            "discount_total_cents": 1400,
            "shipping_cents": 1000,
            "total_cents": 3800,
            "optimal": True,
            "phase_subtotals": {
                "after_item_cents": 2800,
                "after_cart_cents": 2800,
            },
            "promotion_statuses": {
                "P1": "applied",
                "P6": "available",
                "P4": "available",
                "P2": "available",
                "P5": "available",
                "P7": "available",
            },
            # Availability is the "why" behind those statuses. Both bean
            # deals qualify (3 bags >= min 3) and conflict, because COF-COL
            # is a Coffee Beans line both target. P4's dripper is not in the
            # cart. The cart/shipping thresholds are measured against the
            # cascade state, i.e. the post-item 2800 — NOT the 4200 subtotal:
            #   P2: 5000 - 2800 = 2200 short
            #   P5/P7: 10000 - 2800 = 7200 short
            "promotion_availability": {
                "P1": {"eligible": True, "gap": None, "conflicts_with": ["P6"]},
                "P6": {"eligible": True, "gap": None, "conflicts_with": ["P1"]},
                "P4": {"eligible": False, "gap": None, "conflicts_with": []},
                "P2": {
                    "eligible": False,
                    "gap": {"subtotal_short_cents": 2200, "qty_short": None},
                    "conflicts_with": ["P5"],
                },
                "P5": {
                    "eligible": False,
                    "gap": {"subtotal_short_cents": 7200, "qty_short": None},
                    "conflicts_with": ["P2"],
                },
                "P7": {
                    "eligible": False,
                    "gap": {"subtotal_short_cents": 7200, "qty_short": None},
                    "conflicts_with": [],
                },
            },
        }

    def test_bean_cluster_conflict_optimizer_picks_p6_over_p1(self) -> None:
        """Six bags of Ethiopia with both bean deals toggled: P6 must win.

        P1 and P6 share the Coffee Beans conflict cluster, so only one can
        apply — and the shopper must get the better one. Catches the API
        returning the naive first-declared pick (P1) instead of the
        optimizer's, and the losing deal leaking any status but "claimed".

        Hand arithmetic — subtotal = 6 x 1600 = 9600, claimed {P1, P6}:
          {}   -> 9600 + 1000 shipping            = 10600
          {P1} -> cheapest unit free: 9600 - 1600 = 8000 + 1000 = 9000
          {P6} -> 20% of 9600 = 1920: 9600 - 1920 = 7680 + 1000 = 8680  <- best
        (P1 is the naive engine's pick — it is declared first — so this
        receipt only exists because the optimizer overrides it.)
        """
        response = _price(
            [
                {
                    "sku": "COF-ETH",
                    "name": "Ethiopia Yirgacheffe, 12oz",
                    "category": "Coffee Beans",
                    "unit_price_cents": 1600,
                    "qty": 6,
                }
            ],
            ["P1", "P6"],
        )
        assert response.status_code == 200
        assert response.json() == {
            "lines": [
                {
                    "sku": "COF-ETH",
                    "name": "Ethiopia Yirgacheffe, 12oz",
                    "category": "Coffee Beans",
                    "unit_price_cents": 1600,
                    "qty": 6,
                    "line_subtotal_cents": 9600,
                    "discount_cents": 1920,
                    "line_total_cents": 7680,
                }
            ],
            "adjustments": [
                {
                    "promotion_id": "P6",
                    "promotion_name": "Coffee Beans: 20% off (min 3)",
                    "phase": "item",
                    "amount_cents": 1920,
                    "line_allocations": [{"sku": "COF-ETH", "amount_cents": 1920}],
                }
            ],
            "subtotal_cents": 9600,
            "discount_total_cents": 1920,
            "shipping_cents": 1000,
            "total_cents": 8680,
            "optimal": True,
            "phase_subtotals": {
                "after_item_cents": 7680,
                "after_cart_cents": 7680,
            },
            "promotion_statuses": {
                "P1": "claimed",
                "P6": "applied",
                "P4": "available",
                "P2": "available",
                "P5": "available",
                "P7": "available",
            },
            # The status contract cannot say why P1 is "claimed"; this can.
            # P1 is eligible and merely lost its slot to P6 (the checkout
            # keeps it live and lets the shopper force it), whereas P5/P7
            # are genuinely unqualified against the post-item 7680:
            #   P5/P7: 10000 - 7680 = 2320 short
            # P2 qualifies unclaimed (7680 >= 5000) — eligibility is a fact
            # about the cart, independent of what the shopper toggled.
            "promotion_availability": {
                "P1": {"eligible": True, "gap": None, "conflicts_with": ["P6"]},
                "P6": {"eligible": True, "gap": None, "conflicts_with": ["P1"]},
                "P4": {"eligible": False, "gap": None, "conflicts_with": []},
                "P2": {"eligible": True, "gap": None, "conflicts_with": ["P5"]},
                "P5": {
                    "eligible": False,
                    "gap": {"subtotal_short_cents": 2320, "qty_short": None},
                    "conflicts_with": ["P2"],
                },
                "P7": {
                    "eligible": False,
                    "gap": {"subtotal_short_cents": 2320, "qty_short": None},
                    "conflicts_with": [],
                },
            },
        }

    def test_p4_withheld_at_the_fifty_dollar_boundary(self) -> None:
        """Dripper + tumbler land exactly on $50; taking P4 would forfeit P2.

        The API-level twin of the optimizer oracle
        (tests/test_optimizer.py::TestOracles): the full frozen receipt for
        the withholding story. Catches the served response applying the
        eligible-but-worse P4 (naive behavior, total 5500), and freezes the
        exact 4250 + 1000 receipt including P2's per-line split.

        Hand arithmetic — subtotal 2800 + 2200 = 5000, claimed {P4, P2}:
          {P4}     -> 5000 - 500 = 4500 < 5000 threshold kills P2
                      4500 + 1000                       = 5500
          {P2}     -> 15% of 5000 = 750
                      4250 + 1000                       = 5250  <- best
          {P4,P2}  -> P2 ineligible mid-cascade, prices as {P4} = 5500
        P2's 750 splits by line subtotals 2800:2200 out of 5000:
          BREW-V60: 750 * 2800 / 5000 = 420 exactly
          MUG-TVL:  750 * 2200 / 5000 = 330 exactly (no remainder cents)
        P4 stays "claimed": the status contract cannot distinguish withheld
        from ineligible, which is exactly why `promotion_availability` is
        frozen alongside it below — there P4 reads `eligible: true` with no
        gap, the one state that means "qualifies, but a rival won".
        """
        response = _price(
            [
                {
                    "sku": "BREW-V60",
                    "name": "Ceramic Pour-Over Dripper",
                    "category": "Brew Gear",
                    "unit_price_cents": 2800,
                    "qty": 1,
                },
                {
                    "sku": "MUG-TVL",
                    "name": "Travel Tumbler",
                    "category": "Drinkware",
                    "unit_price_cents": 2200,
                    "qty": 1,
                },
            ],
            ["P4", "P2"],
        )
        assert response.status_code == 200
        assert response.json() == {
            "lines": [
                {
                    "sku": "BREW-V60",
                    "name": "Ceramic Pour-Over Dripper",
                    "category": "Brew Gear",
                    "unit_price_cents": 2800,
                    "qty": 1,
                    "line_subtotal_cents": 2800,
                    "discount_cents": 420,
                    "line_total_cents": 2380,
                },
                {
                    "sku": "MUG-TVL",
                    "name": "Travel Tumbler",
                    "category": "Drinkware",
                    "unit_price_cents": 2200,
                    "qty": 1,
                    "line_subtotal_cents": 2200,
                    "discount_cents": 330,
                    "line_total_cents": 1870,
                },
            ],
            "adjustments": [
                {
                    "promotion_id": "P2",
                    "promotion_name": "15% off $50.00+",
                    "phase": "cart",
                    "amount_cents": 750,
                    "line_allocations": [
                        {"sku": "BREW-V60", "amount_cents": 420},
                        {"sku": "MUG-TVL", "amount_cents": 330},
                    ],
                }
            ],
            "subtotal_cents": 5000,
            "discount_total_cents": 750,
            "shipping_cents": 1000,
            "total_cents": 5250,
            "optimal": True,
            "phase_subtotals": {
                "after_item_cents": 5000,
                "after_cart_cents": 4250,
            },
            "promotion_statuses": {
                "P1": "available",
                "P6": "available",
                "P4": "claimed",
                "P2": "applied",
                "P5": "available",
                "P7": "available",
            },
            # P4: eligible, no gap, and NOT applied — the withheld state the
            # docstring calls out. The bean deals are unqualified for a
            # different reason (no Coffee Beans line at all, so 3 units
            # short of min_qty 3), which is why one greys out and the other
            # does not. Note the empty conflict lists: with no Coffee Beans
            # line on this cart, P1 and P6 cannot collide, so exclusivity is
            # a property of the cart, not of the promotion pair.
            #   P5: 10000 - 5000 (post-item) = 5000 short
            #   P7: 10000 - 4250 (post-cart) = 5750 short
            "promotion_availability": {
                "P1": {
                    "eligible": False,
                    "gap": {"subtotal_short_cents": None, "qty_short": 3},
                    "conflicts_with": [],
                },
                "P6": {
                    "eligible": False,
                    "gap": {"subtotal_short_cents": None, "qty_short": 3},
                    "conflicts_with": [],
                },
                "P4": {"eligible": True, "gap": None, "conflicts_with": []},
                "P2": {"eligible": True, "gap": None, "conflicts_with": ["P5"]},
                "P5": {
                    "eligible": False,
                    "gap": {"subtotal_short_cents": 5000, "qty_short": None},
                    "conflicts_with": ["P2"],
                },
                "P7": {
                    "eligible": False,
                    "gap": {"subtotal_short_cents": 5750, "qty_short": None},
                    "conflicts_with": [],
                },
            },
        }

    def test_full_stack_receipt_item_cart_and_free_shipping(self) -> None:
        """A big gear order stacks an item deal, 20% off, and free shipping.

        The all-three-phases receipt: catches any phase reading the wrong
        cascade state (P5 must discount the post-item subtotal, P7 must
        check the post-cart subtotal) and catches free shipping being
        applied without the trace entry that zeroes the $10 — the receipt
        would not add up.

        Hand arithmetic — 3 grinders (13500) + dripper (2800) = 16300,
        claimed {P4, P5, P7}:
          Item:  P4 takes 500 off BREW-V60 -> post-item 15800
                 (lines now 13500 / 2300)
          Cart:  15800 >= 10000, P5 = 20% of 15800 = 3160
                 split by post-item line values 13500:2300 of 15800:
                   BREW-GRD: 3160 * 13500 / 15800 = 2700 exactly
                   BREW-V60: 3160 *  2300 / 15800 =  460 exactly
                 post-cart 15800 - 3160 = 12640
          Ship:  12640 >= 10000, P7 waives the full 1000 baseline
          total  = 12640 + 0 = 12640
          discounts = 500 + 3160 + 1000 = 4660
        Withholding checks (why this stack is also the optimum): dropping
        P4 gives 0.8 x 16300 = 13040 > 12640; dropping P5 gives 15800;
        dropping P7 adds 1000 back. Naive picks the same set, so the
        optimizer confirms it as optimal.
        """
        response = _price(
            [
                {
                    "sku": "BREW-GRD",
                    "name": "Manual Burr Grinder",
                    "category": "Brew Gear",
                    "unit_price_cents": 4500,
                    "qty": 3,
                },
                {
                    "sku": "BREW-V60",
                    "name": "Ceramic Pour-Over Dripper",
                    "category": "Brew Gear",
                    "unit_price_cents": 2800,
                    "qty": 1,
                },
            ],
            ["P4", "P5", "P7"],
        )
        assert response.status_code == 200
        assert response.json() == {
            "lines": [
                {
                    "sku": "BREW-GRD",
                    "name": "Manual Burr Grinder",
                    "category": "Brew Gear",
                    "unit_price_cents": 4500,
                    "qty": 3,
                    "line_subtotal_cents": 13500,
                    "discount_cents": 2700,
                    "line_total_cents": 10800,
                },
                {
                    "sku": "BREW-V60",
                    "name": "Ceramic Pour-Over Dripper",
                    "category": "Brew Gear",
                    "unit_price_cents": 2800,
                    "qty": 1,
                    "line_subtotal_cents": 2800,
                    "discount_cents": 960,
                    "line_total_cents": 1840,
                },
            ],
            "adjustments": [
                {
                    "promotion_id": "P4",
                    "promotion_name": "$5.00 off Ceramic Pour-Over Dripper",
                    "phase": "item",
                    "amount_cents": 500,
                    "line_allocations": [{"sku": "BREW-V60", "amount_cents": 500}],
                },
                {
                    "promotion_id": "P5",
                    "promotion_name": "20% off $100.00+",
                    "phase": "cart",
                    "amount_cents": 3160,
                    "line_allocations": [
                        {"sku": "BREW-GRD", "amount_cents": 2700},
                        {"sku": "BREW-V60", "amount_cents": 460},
                    ],
                },
                {
                    "promotion_id": "P7",
                    "promotion_name": "Free shipping $100.00+",
                    "phase": "shipping",
                    "amount_cents": 1000,
                    "line_allocations": [],
                },
            ],
            "subtotal_cents": 16300,
            "discount_total_cents": 4660,
            "shipping_cents": 0,
            "total_cents": 12640,
            "optimal": True,
            "phase_subtotals": {
                "after_item_cents": 15800,
                "after_cart_cents": 12640,
            },
            "promotion_statuses": {
                "P1": "available",
                "P6": "available",
                "P4": "applied",
                "P2": "available",
                "P5": "applied",
                "P7": "applied",
            },
            # Every gear-cart deal qualifies, including the unclaimed P2 —
            # 15800 clears its 5000 bar too; it simply lost the cart slot to
            # the better P5 (they always conflict: one cart subtotal, one
            # winner). Only the bean deals fall short, by the full min_qty 3
            # since no Coffee Beans line exists.
            "promotion_availability": {
                "P1": {
                    "eligible": False,
                    "gap": {"subtotal_short_cents": None, "qty_short": 3},
                    "conflicts_with": [],
                },
                "P6": {
                    "eligible": False,
                    "gap": {"subtotal_short_cents": None, "qty_short": 3},
                    "conflicts_with": [],
                },
                "P4": {"eligible": True, "gap": None, "conflicts_with": []},
                "P2": {"eligible": True, "gap": None, "conflicts_with": ["P5"]},
                "P5": {"eligible": True, "gap": None, "conflicts_with": ["P2"]},
                "P7": {"eligible": True, "gap": None, "conflicts_with": []},
            },
        }

    def test_rounding_showcase_half_up_then_largest_remainder(self) -> None:
        """15% of an odd $53.30 clearance cart: every rounding rule on show.

        The one receipt that exercises the full money contract at once —
        half-up at the aggregate, largest-remainder split, tie toward the
        earlier line. Catches any change to the rounding rules (per-line
        re-rounding, banker's rounding, tie toward the larger remainderless
        share) that would silently redistribute cents on real receipts.

        The cart uses clearance lines at odd prices — the API prices
        whatever the cart declares; the seed catalog is only the UI's
        pick-list, and round-number seed prices can never produce a
        fractional 15%.

        Hand arithmetic — lines 1868 + 1868 + 1594 = 5330, claimed {P2}:
          aggregate: 15% of 5330 = 799.5 -> rounds HALF-UP to 800
          largest-remainder split of 800 over weights 1868/1868/1594
          (total weight 5330):
            CLR-A: 800*1868 = 1,494,400; // 5330 = 280, remainder 2000
            CLR-B: same as CLR-A       ->        280, remainder 2000
            CLR-C: 800*1594 = 1,275,200; // 5330 = 239, remainder 1330
          floors sum to 799 -> 1 leftover cent; remainders tie at 2000
          between CLR-A and CLR-B, and the tie breaks toward the EARLIER
          index, so CLR-A gets the cent:
            shares = 281 / 280 / 239   (sum = 800 exactly)
          totals: 1587 + 1588 + 1355 = 4530; + 1000 shipping = 5530
        """
        response = _price(
            [
                {
                    "sku": "CLR-A",
                    "name": "Clearance Grab Bag A",
                    "category": "Clearance",
                    "unit_price_cents": 1868,
                    "qty": 1,
                },
                {
                    "sku": "CLR-B",
                    "name": "Clearance Grab Bag B",
                    "category": "Clearance",
                    "unit_price_cents": 1868,
                    "qty": 1,
                },
                {
                    "sku": "CLR-C",
                    "name": "Clearance Grab Bag C",
                    "category": "Clearance",
                    "unit_price_cents": 1594,
                    "qty": 1,
                },
            ],
            ["P2"],
        )
        assert response.status_code == 200
        assert response.json() == {
            "lines": [
                {
                    "sku": "CLR-A",
                    "name": "Clearance Grab Bag A",
                    "category": "Clearance",
                    "unit_price_cents": 1868,
                    "qty": 1,
                    "line_subtotal_cents": 1868,
                    "discount_cents": 281,
                    "line_total_cents": 1587,
                },
                {
                    "sku": "CLR-B",
                    "name": "Clearance Grab Bag B",
                    "category": "Clearance",
                    "unit_price_cents": 1868,
                    "qty": 1,
                    "line_subtotal_cents": 1868,
                    "discount_cents": 280,
                    "line_total_cents": 1588,
                },
                {
                    "sku": "CLR-C",
                    "name": "Clearance Grab Bag C",
                    "category": "Clearance",
                    "unit_price_cents": 1594,
                    "qty": 1,
                    "line_subtotal_cents": 1594,
                    "discount_cents": 239,
                    "line_total_cents": 1355,
                },
            ],
            "adjustments": [
                {
                    "promotion_id": "P2",
                    "promotion_name": "15% off $50.00+",
                    "phase": "cart",
                    "amount_cents": 800,
                    "line_allocations": [
                        {"sku": "CLR-A", "amount_cents": 281},
                        {"sku": "CLR-B", "amount_cents": 280},
                        {"sku": "CLR-C", "amount_cents": 239},
                    ],
                }
            ],
            "subtotal_cents": 5330,
            "discount_total_cents": 800,
            "shipping_cents": 1000,
            "total_cents": 5530,
            "optimal": True,
            "phase_subtotals": {
                "after_item_cents": 5330,
                "after_cart_cents": 4530,
            },
            "promotion_statuses": {
                "P1": "available",
                "P6": "available",
                "P4": "available",
                "P2": "applied",
                "P5": "available",
                "P7": "available",
            },
            # Clearance lines match no promotion target, so the item deals
            # are unqualified and conflict-free. The two shortfalls read off
            # different cascade states, which is the whole point of
            # measuring after deals:
            #   P5 (cart phase):     10000 - 5330 (post-item) = 4670 short
            #   P7 (shipping phase): 10000 - 4530 (post-cart) = 5470 short
            # P7 is further from qualifying than P5 precisely because P2's
            # 800 landed in between.
            "promotion_availability": {
                "P1": {
                    "eligible": False,
                    "gap": {"subtotal_short_cents": None, "qty_short": 3},
                    "conflicts_with": [],
                },
                "P6": {
                    "eligible": False,
                    "gap": {"subtotal_short_cents": None, "qty_short": 3},
                    "conflicts_with": [],
                },
                "P4": {"eligible": False, "gap": None, "conflicts_with": []},
                "P2": {"eligible": True, "gap": None, "conflicts_with": ["P5"]},
                "P5": {
                    "eligible": False,
                    "gap": {"subtotal_short_cents": 4670, "qty_short": None},
                    "conflicts_with": ["P2"],
                },
                "P7": {
                    "eligible": False,
                    "gap": {"subtotal_short_cents": 5470, "qty_short": None},
                    "conflicts_with": [],
                },
            },
        }
