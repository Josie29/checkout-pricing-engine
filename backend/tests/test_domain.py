import pytest
from pydantic import ValidationError

from app.domain import (
    Adjustment,
    Cart,
    LineAllocation,
    LineItem,
    Phase,
    PricedLine,
    PricingResult,
)


def make_line_item(**overrides: object) -> LineItem:
    """Build a valid LineItem, applying keyword overrides."""
    fields: dict[str, object] = {
        "sku": "COF-ETH",
        "name": "Ethiopia Yirgacheffe, 12oz",
        "category": "Coffee Beans",
        "unit_price_cents": 1600,
        "qty": 1,
    }
    fields.update(overrides)
    return LineItem.model_validate(fields)


def make_priced_line(**overrides: object) -> PricedLine:
    """Build a valid PricedLine, applying keyword overrides."""
    fields: dict[str, object] = {
        "sku": "COF-ETH",
        "name": "Ethiopia Yirgacheffe, 12oz",
        "category": "Coffee Beans",
        "unit_price_cents": 1600,
        "qty": 2,
        "line_subtotal_cents": 3200,
        "discount_cents": 200,
        "line_total_cents": 3000,
    }
    fields.update(overrides)
    return PricedLine.model_validate(fields)


class TestLineItemAndCart:
    """Input validation beyond what bare Pydantic types enforce."""

    @pytest.mark.parametrize("field", ["sku", "category"])
    def test_whitespace_only_string_rejected(self, field: str) -> None:
        """Space-only SKU/category is rejected, not accepted as non-empty.

        Catches a space-only value slipping past min-length checks — such a
        line could never be matched by a promotion target or an adjustment
        allocation, so the breakdown would silently omit it.
        """
        with pytest.raises(ValidationError):
            make_line_item(**{field: "   "})

    def test_zero_qty_rejected(self) -> None:
        """A qty-0 line is rejected.

        Catches a weightless line entering pricing and diluting proportional
        discount allocation.
        """
        with pytest.raises(ValidationError):
            make_line_item(qty=0)

    def test_negative_unit_price_rejected(self) -> None:
        """A negative unit price is rejected.

        Catches a negative price sneaking in as a disguised discount and
        breaking the never-negative-totals invariant downstream.
        """
        with pytest.raises(ValidationError):
            make_line_item(unit_price_cents=-1)

    def test_empty_cart_rejected(self) -> None:
        """An empty cart is rejected.

        There is nothing to price; the API should reject rather than return a
        degenerate zero result.
        """
        with pytest.raises(ValidationError):
            Cart(items=[])

    def test_duplicate_skus_rejected(self) -> None:
        """Two lines sharing a SKU are rejected.

        Catches duplicate SKUs, which would make adjustment allocations
        (keyed by SKU) ambiguous in the itemized breakdown.
        """
        with pytest.raises(ValidationError):
            Cart(items=[make_line_item(), make_line_item()])

    def test_cart_is_immutable(self) -> None:
        """Cart fields cannot be reassigned after construction.

        Catches a promotion's apply() mutating the cascade state it was
        handed, which would corrupt every later phase's eligibility checks.
        """
        cart = Cart(items=[make_line_item()])
        with pytest.raises(ValidationError):
            cart.items = []  # pyright: ignore[reportAttributeAccessIssue]

    def test_subtotal_sums_line_subtotals(self) -> None:
        """Cart subtotal is the exact sum of its line subtotals.

        Catches the subtotal disagreeing with the cart's own lines — the
        number every cart-phase threshold (e.g. 15% off $50.00+) is checked
        against.
        """
        cart = Cart(
            items=[
                make_line_item(qty=2),  # 3200
                make_line_item(sku="MUG-CLS", unit_price_cents=1200),  # 1200
            ]
        )
        assert cart.subtotal_cents == 4400


class TestAdjustment:
    """The trace-to-itemization guards on a single adjustment."""

    def test_allocations_must_sum_to_amount(self) -> None:
        """Allocations off by a cent from the amount are rejected.

        Catches an explanation trace advertising one discount while the
        per-line split totals another — the receipt wouldn't add up.
        """
        with pytest.raises(ValidationError):
            Adjustment(
                promotion_id="P2",
                promotion_name="15% off $50.00+",
                phase=Phase.CART,
                amount_cents=100,
                line_allocations=[LineAllocation(sku="COF-ETH", amount_cents=99)],
            )

    def test_positive_amount_requires_allocations(self) -> None:
        """A positive non-shipping amount without allocations is rejected.

        Catches an item/cart discount with no per-line attribution — the
        itemized breakdown could never account for where the money went.
        """
        with pytest.raises(ValidationError):
            Adjustment(
                promotion_id="P4",
                promotion_name="$5.00 off Ceramic Pour-Over Dripper",
                phase=Phase.ITEM,
                amount_cents=500,
            )

    def test_shipping_adjustment_must_not_have_allocations(self) -> None:
        """A shipping adjustment with line allocations is rejected.

        Catches a shipping discount also charged against product lines — the
        same cents would be discounted twice in the breakdown.
        """
        with pytest.raises(ValidationError):
            Adjustment(
                promotion_id="P7",
                promotion_name="Free shipping $100.00+",
                phase=Phase.SHIPPING,
                amount_cents=1000,
                line_allocations=[LineAllocation(sku="COF-ETH", amount_cents=1000)],
            )

    def test_shipping_adjustment_without_allocations_is_valid(self) -> None:
        """A plain shipping adjustment validates.

        Catches over-tightening the guard so a legitimate free-shipping trace
        entry can't be represented at all.
        """
        adj = Adjustment(
            promotion_id="P7",
            promotion_name="Free shipping $100.00+",
            phase=Phase.SHIPPING,
            amount_cents=1000,
        )
        assert adj.line_allocations == []

    def test_duplicate_allocation_skus_rejected(self) -> None:
        """Two allocations to the same SKU in one adjustment are rejected.

        Catches one adjustment splitting its amount across the same line
        twice, hiding a double-application inside a single trace entry.
        """
        with pytest.raises(ValidationError):
            Adjustment(
                promotion_id="P1",
                promotion_name="Coffee Beans: buy 2 get 1 free",
                phase=Phase.ITEM,
                amount_cents=200,
                line_allocations=[
                    LineAllocation(sku="COF-ETH", amount_cents=100),
                    LineAllocation(sku="COF-ETH", amount_cents=100),
                ],
            )


class TestPricedLine:
    """Per-line arithmetic guards."""

    def test_subtotal_must_be_price_times_qty(self) -> None:
        """A line subtotal not equal to price times qty is rejected.

        Catches a breakdown line whose displayed subtotal disagrees with its
        own unit price and quantity.
        """
        with pytest.raises(ValidationError):
            make_priced_line(line_subtotal_cents=3199)

    def test_total_must_be_subtotal_minus_discount(self) -> None:
        """A line total off from subtotal minus discount is rejected.

        Catches per-line drift: one cent off here means the itemization no
        longer sums to the final price.
        """
        with pytest.raises(ValidationError):
            make_priced_line(line_total_cents=2999)

    def test_discount_exceeding_subtotal_rejected(self) -> None:
        """A discount bigger than the line is rejected.

        Catches a negative line total — the never-negative-totals invariant
        at line granularity.
        """
        with pytest.raises(ValidationError):
            make_priced_line(discount_cents=3300, line_total_cents=-100)


class TestPricingResult:
    """Whole-result guards: breakdown, trace, and totals must tie out exactly."""

    @staticmethod
    def valid_result_fields() -> dict[str, object]:
        """A consistent two-line result with one cart-phase adjustment."""
        return {
            "lines": [
                make_priced_line(),  # 3200 - 200 = 3000
                make_priced_line(
                    sku="MUG-CLS",
                    name="Classic Stoneware Mug",
                    category="Drinkware",
                    unit_price_cents=1200,
                    qty=1,
                    line_subtotal_cents=1200,
                    discount_cents=100,
                    line_total_cents=1100,
                ),
            ],
            "adjustments": [
                Adjustment(
                    promotion_id="P2",
                    promotion_name="15% off $50.00+",
                    phase=Phase.CART,
                    amount_cents=300,
                    line_allocations=[
                        LineAllocation(sku="COF-ETH", amount_cents=200),
                        LineAllocation(sku="MUG-CLS", amount_cents=100),
                    ],
                )
            ],
            "subtotal_cents": 4400,
            "discount_total_cents": 300,
            "shipping_cents": 1000,
            "total_cents": 5100,
        }

    def test_consistent_result_validates(self) -> None:
        """A fully consistent result passes every guard.

        Catches the guards rejecting a perfectly consistent result — the
        engine could then never return anything. Also pins optimal's default.
        """
        result = PricingResult.model_validate(self.valid_result_fields())
        assert result.total_cents == 5100
        assert result.optimal is False

    def test_subtotal_mismatch_rejected(self) -> None:
        """A subtotal that isn't the sum of the lines is rejected.

        Catches a displayed subtotal disagreeing with the displayed lines —
        the first place a shopper would spot drift.
        """
        fields = self.valid_result_fields()
        fields["subtotal_cents"] = 4401
        with pytest.raises(ValidationError):
            PricingResult.model_validate(fields)

    def test_discount_total_mismatch_rejected(self) -> None:
        """A discount total that isn't the sum of adjustments is rejected.

        Catches the headline "you saved $X" figure disagreeing with the
        per-promotion trace entries beneath it.
        """
        fields = self.valid_result_fields()
        fields["discount_total_cents"] = 299
        with pytest.raises(ValidationError):
            PricingResult.model_validate(fields)

    def test_total_mismatch_rejected(self) -> None:
        """A total that isn't line totals plus shipping is rejected.

        Catches the charged total drifting from the itemization — the core
        itemization-sums-to-final-price invariant.
        """
        fields = self.valid_result_fields()
        fields["total_cents"] = 5101
        with pytest.raises(ValidationError):
            PricingResult.model_validate(fields)

    def test_line_discount_must_match_trace_allocations(self) -> None:
        """A line discount the trace never allocated is rejected.

        Catches a line showing a discount with no matching trace allocation
        (or vice versa) — the explanation would not explain the breakdown.
        """
        fields = self.valid_result_fields()
        lines = fields["lines"]
        assert isinstance(lines, list)
        lines[0] = make_priced_line(discount_cents=150, line_total_cents=3050)
        with pytest.raises(ValidationError):
            PricingResult.model_validate(fields)

    def test_allocation_to_unknown_sku_rejected(self) -> None:
        """An allocation to a SKU absent from the lines is rejected.

        Catches trace money attributed to a line that isn't in the breakdown
        — discount cents leaking out of the itemization entirely.
        """
        fields = self.valid_result_fields()
        fields["adjustments"] = [
            Adjustment(
                promotion_id="P2",
                promotion_name="15% off $50.00+",
                phase=Phase.CART,
                amount_cents=300,
                line_allocations=[LineAllocation(sku="GHOST-SKU", amount_cents=300)],
            )
        ]
        with pytest.raises(ValidationError):
            PricingResult.model_validate(fields)

    def test_shipping_discount_needs_no_line_allocations(self) -> None:
        """A result with a shipping adjustment and reduced shipping validates.

        Catches the result-level guard demanding line allocations for a
        shipping adjustment, which by design has none — free shipping would
        become unrepresentable.
        """
        fields = self.valid_result_fields()
        adjustments = fields["adjustments"]
        assert isinstance(adjustments, list)
        adjustments.append(
            Adjustment(
                promotion_id="P7",
                promotion_name="Free shipping $100.00+",
                phase=Phase.SHIPPING,
                amount_cents=1000,
            )
        )
        fields["discount_total_cents"] = 1300
        fields["shipping_cents"] = 0
        fields["total_cents"] = 4100
        result = PricingResult.model_validate(fields)
        assert result.shipping_cents == 0
