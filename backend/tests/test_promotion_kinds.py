import pytest

from app.domain import Cart, LineAllocation, LineItem, Phase
from app.promotion_kinds import (
    BuyXGetYFree,
    FixedOffItem,
    FreeShipping,
    PercentOffCart,
    PercentOffItem,
)
from app.promotions import CartTarget, CategoryTarget, ShippingTarget, SkuTarget
from app.seed_loader import SeedLoadError, parse_promotions


def line(sku: str, category: str, unit_price_cents: int, qty: int = 1) -> LineItem:
    """Build a cart line with the fields these tests vary."""
    return LineItem(
        sku=sku, category=category, unit_price_cents=unit_price_cents, qty=qty
    )


def beans_cart() -> Cart:
    """Three bean lines at distinct unit prices, plus one non-bean line."""
    return Cart(
        items=[
            line("COF-ETH", "Coffee Beans", 1600, qty=2),
            line("COF-COL", "Coffee Beans", 1400),
            line("COF-DEC", "Coffee Beans", 1500),
            line("SNK-BSC", "Snacks", 900, qty=5),
        ]
    )


class TestBuyXGetYFree:
    """P1's math: qty condition across lines, cheapest-unit selection."""

    @staticmethod
    def promo(min_qty: int = 3) -> BuyXGetYFree:
        """A beans BXGY promotion like seed P1."""
        return BuyXGetYFree(
            id="P1",
            name="Beans: buy 2 get 1 free",
            target=CategoryTarget(category="Coffee Beans"),
            min_qty=min_qty,
        )

    def test_cheapest_unit_across_multiple_lines_is_freed(self) -> None:
        """The freed unit is the cheapest across all matching lines.

        Catches freeing a unit from the first or largest line instead — a
        shopper promised "cheapest free" would see the wrong (pricier or
        cheaper-than-owed) unit discounted on the receipt.
        """
        adjustment = self.promo().apply(beans_cart())
        assert adjustment.amount_cents == 1400
        assert adjustment.line_allocations == [
            LineAllocation(sku="COF-COL", amount_cents=1400)
        ]

    def test_quantity_condition_sums_across_matching_lines(self) -> None:
        """Three single-unit bean lines satisfy min_qty=3 together.

        Catches counting per line instead of across the category — a shopper
        buying three different beans would be denied the promised deal.
        """
        cart = Cart(
            items=[
                line("COF-ETH", "Coffee Beans", 1600),
                line("COF-COL", "Coffee Beans", 1400),
                line("COF-DEC", "Coffee Beans", 1500),
            ]
        )
        assert self.promo().is_eligible(cart)

    def test_non_matching_lines_count_for_nothing(self) -> None:
        """Non-target lines neither satisfy the condition nor get freed.

        Catches a cheap non-bean item (the 900c biscotti) being selected as
        the "cheapest unit", or its quantity unlocking a beans-only deal.
        """
        promo = self.promo()
        snacks_only = Cart(items=[line("SNK-BSC", "Snacks", 900, qty=5)])
        assert not promo.is_eligible(snacks_only)
        adjustment = promo.apply(beans_cart())
        assert all(a.sku != "SNK-BSC" for a in adjustment.line_allocations)
        assert adjustment.amount_cents == 1400  # cheapest bean, not the snack

    def test_equal_unit_prices_tie_break_by_sku(self) -> None:
        """A unit-price tie frees the line with the smaller SKU string.

        Catches nondeterministic tie-breaking — repricing the same cart
        would flip which line shows the free unit between requests.
        """
        cart = Cart(
            items=[
                line("COF-ETH", "Coffee Beans", 1400, qty=2),
                line("COF-COL", "Coffee Beans", 1400),
            ]
        )
        adjustment = self.promo().apply(cart)
        assert adjustment.line_allocations == [
            LineAllocation(sku="COF-COL", amount_cents=1400)
        ]


class TestPercentOffItem:
    """P6's math: aggregate percentage, drift-free split, matched lines only."""

    @staticmethod
    def promo(percent_off: int = 20, min_qty: int = 3) -> PercentOffItem:
        """A beans percent-off promotion like seed P6."""
        return PercentOffItem(
            id="P6",
            name="Beans: bulk 20% off",
            target=CategoryTarget(category="Coffee Beans"),
            min_qty=min_qty,
            percent_off=percent_off,
        )

    def test_odd_cents_across_three_lines_sum_exactly(self) -> None:
        """20% of an odd-cent subtotal splits across 3 lines with no drift.

        Catches per-line re-rounding: 20% of 333+333+335=1001 is 200 cents,
        and the line shares must sum to exactly 200 — a receipt whose line
        discounts disagree with the advertised total by a cent.
        """
        cart = Cart(
            items=[
                line("COF-ETH", "Coffee Beans", 333),
                line("COF-COL", "Coffee Beans", 333),
                line("COF-DEC", "Coffee Beans", 335),
            ]
        )
        adjustment = self.promo().apply(cart)
        assert adjustment.amount_cents == 200
        assert sum(a.amount_cents for a in adjustment.line_allocations) == 200
        # Largest-remainder split: floors are 66/66/66, the two leftover
        # cents go to the largest fractional remainders (COF-DEC, then the
        # earlier of the tied bean lines).
        assert adjustment.line_allocations == [
            LineAllocation(sku="COF-ETH", amount_cents=67),
            LineAllocation(sku="COF-COL", amount_cents=66),
            LineAllocation(sku="COF-DEC", amount_cents=67),
        ]

    def test_half_cent_rounds_up_at_the_aggregate(self) -> None:
        """A half-cent percentage result rounds up (half-up rule).

        Catches the rounding rule silently changing: 15% of 30 cents is
        4.5, and the shopper must see 5 — half-up is the documented,
        customer-favorable choice.
        """
        cart = Cart(items=[line("COF-ETH", "Coffee Beans", 10, qty=3)])
        adjustment = self.promo(percent_off=15).apply(cart)
        assert adjustment.amount_cents == 5

    def test_only_matching_lines_are_discounted(self) -> None:
        """Non-target lines get no share and no weight in the percentage.

        Catches the discount base leaking to the whole cart — a 20% beans
        deal must not shave cents off the biscotti line.
        """
        adjustment = self.promo().apply(beans_cart())
        # 20% of the bean subtotal only: 3200+1400+1500 = 6100 -> 1220.
        assert adjustment.amount_cents == 1220
        assert {a.sku for a in adjustment.line_allocations} == {
            "COF-ETH",
            "COF-COL",
            "COF-DEC",
        }

    def test_explanation_names_phase_and_promotion(self) -> None:
        """The adjustment carries the promotion identity and Item phase.

        Catches a mislabeled trace — the breakdown panel would attribute
        the discount to the wrong promotion or the wrong cascade phase.
        """
        adjustment = self.promo().apply(beans_cart())
        assert adjustment.promotion_id == "P6"
        assert adjustment.promotion_name == "Beans: bulk 20% off"
        assert adjustment.phase is Phase.ITEM


class TestFixedOffItem:
    """P4's math: flat discount, capped so no line goes negative."""

    @staticmethod
    def promo(amount_off_cents: int = 500) -> FixedOffItem:
        """A dripper fixed-off promotion like seed P4."""
        return FixedOffItem(
            id="P4",
            name="$5 off pour-over dripper",
            target=SkuTarget(sku="BREW-V60"),
            amount_off_cents=amount_off_cents,
        )

    def test_full_amount_when_line_covers_it(self) -> None:
        """The full $5 comes off when the matched line is worth more.

        Catches the discount being scaled or partially applied — the seed
        table promises a flat 500 cents off the 2800-cent dripper.
        """
        cart = Cart(items=[line("BREW-V60", "Brew Gear", 2800)])
        adjustment = self.promo().apply(cart)
        assert adjustment.amount_cents == 500
        assert adjustment.line_allocations == [
            LineAllocation(sku="BREW-V60", amount_cents=500)
        ]

    def test_discount_is_capped_at_the_line_value(self) -> None:
        """A discount bigger than the matched line caps at the line's value.

        Catches a negative line: $5 off a 300-cent item must discount
        exactly 300, never drive the line (or the cart total) below zero.
        """
        big_off = self.promo(amount_off_cents=500)
        cart = Cart(items=[line("BREW-V60", "Brew Gear", 300)])
        adjustment = big_off.apply(cart)
        assert adjustment.amount_cents == 300
        assert adjustment.line_allocations == [
            LineAllocation(sku="BREW-V60", amount_cents=300)
        ]

    def test_category_target_splits_and_caps_across_lines(self) -> None:
        """With a category target, the cap and split use all matched lines.

        Catches the cap being applied per line instead of across the
        matched subtotal — 900 off 300+200=500 of matched value must
        discount exactly 500, split 300/200.
        """
        promo = FixedOffItem(
            id="PX",
            name="Cheap gear blowout",
            target=CategoryTarget(category="Brew Gear"),
            amount_off_cents=900,
        )
        cart = Cart(
            items=[
                line("BREW-V60", "Brew Gear", 300),
                line("BREW-GRD", "Brew Gear", 200),
                line("MUG-CLS", "Drinkware", 1200),
            ]
        )
        adjustment = promo.apply(cart)
        assert adjustment.amount_cents == 500
        assert adjustment.line_allocations == [
            LineAllocation(sku="BREW-V60", amount_cents=300),
            LineAllocation(sku="BREW-GRD", amount_cents=200),
        ]


class TestPercentOffCart:
    """P2/P5's math: subtotal percentage spread across every line."""

    @staticmethod
    def promo(percent_off: int = 15, min_subtotal_cents: int = 5000) -> PercentOffCart:
        """A cart percent-off promotion like seed P2."""
        return PercentOffCart(
            id="P2",
            name="15% off $50+",
            target=CartTarget(),
            min_subtotal_cents=min_subtotal_cents,
            percent_off=percent_off,
        )

    def test_discount_spreads_across_all_lines_exactly(self) -> None:
        """The cart-wide percentage allocates over every line, drift-free.

        Catches a lost or doubled cent when 15% of an awkward subtotal
        (5199 -> 780) spreads over three lines — line discounts must sum
        to exactly the advertised cart discount.
        """
        cart = Cart(
            items=[
                line("COF-ETH", "Coffee Beans", 1600),
                line("COF-COL", "Coffee Beans", 1400),
                line("MUG-TVL", "Drinkware", 2199),
            ]
        )
        adjustment = self.promo().apply(cart)
        assert adjustment.amount_cents == 780
        # Largest-remainder split of 780 over weights 1600/1400/2199.
        assert adjustment.line_allocations == [
            LineAllocation(sku="COF-ETH", amount_cents=240),
            LineAllocation(sku="COF-COL", amount_cents=210),
            LineAllocation(sku="MUG-TVL", amount_cents=330),
        ]
        assert adjustment.phase is Phase.CART

    def test_condition_reads_the_cart_it_is_handed(self) -> None:
        """Eligibility uses the given cart's subtotal, nothing else.

        Catches the threshold being checked against some recomputed or
        stale subtotal — the phase table says Cart phase reads the
        post-Item state it is handed, which is exactly this Cart object.
        """
        promo = self.promo(min_subtotal_cents=5000)
        at_threshold = Cart(items=[line("MUG-TVL", "Drinkware", 2500, qty=2)])
        below = Cart(items=[line("MUG-TVL", "Drinkware", 4999)])
        assert promo.is_eligible(at_threshold)
        assert not promo.is_eligible(below)


class TestFreeShipping:
    """P7's effect: a shipping-phase adjustment for the waived charge."""

    @staticmethod
    def promo() -> FreeShipping:
        """A free-shipping promotion like seed P7."""
        return FreeShipping(
            id="P7",
            name="Free shipping $100+",
            target=ShippingTarget(),
            min_subtotal_cents=10000,
        )

    def test_waives_the_default_baseline(self) -> None:
        """The adjustment waives the flat $10 baseline with no line spread.

        Catches the receipt not showing the 1000-cent shipping charge
        zeroed out — or a shipping discount wrongly landing on item lines.
        """
        cart = Cart(items=[line("BREW-GRD", "Brew Gear", 4500, qty=3)])
        adjustment = self.promo().apply(cart)
        assert adjustment.amount_cents == 1000
        assert adjustment.phase is Phase.SHIPPING
        assert adjustment.line_allocations == []

    def test_engine_configured_baseline_overrides_default(self) -> None:
        """An engine-injected baseline changes the waived amount.

        Catches #21's config injection silently not taking: if the engine
        charges a different shipping rate, the adjustment must waive that
        rate exactly, or shipping math stops summing to zero.
        """
        promo = self.promo().model_copy(update={"shipping_baseline_cents": 750})
        cart = Cart(items=[line("BREW-GRD", "Brew Gear", 4500, qty=3)])
        assert promo.apply(cart).amount_cents == 750


class TestTargetKindGuards:
    """Seeding a kind with the wrong target scope must fail at load time."""

    @pytest.mark.parametrize(
        ("type_key", "extra", "bad_target"),
        [
            ("BXGY", {"min_qty": 3}, {"kind": "cart"}),
            ("PCT_OFF_ITEM", {"min_qty": 3, "percent_off": 20}, {"kind": "shipping"}),
            ("FIXED_OFF_ITEM", {"amount_off_cents": 500}, {"kind": "cart"}),
            (
                "PCT_OFF_CART",
                {"min_subtotal_cents": 5000, "percent_off": 15},
                {"kind": "sku", "sku": "BREW-V60"},
            ),
            ("FREE_SHIPPING", {"min_subtotal_cents": 10000}, {"kind": "cart"}),
        ],
    )
    def test_wrong_target_scope_fails_loud(
        self, type_key: str, extra: dict[str, object], bad_target: dict[str, str]
    ) -> None:
        """A seed entry pairing a kind with an out-of-scope target raises.

        Catches a seed typo (e.g. a BXGY aimed at the cart) surfacing as a
        crash or silent no-op during pricing instead of a load-time error.
        """
        entry: dict[str, object] = {
            "type": type_key,
            "id": "BAD",
            "name": "Mis-scoped promo",
            "target": bad_target,
            **extra,
        }
        with pytest.raises(SeedLoadError):
            parse_promotions([entry])
