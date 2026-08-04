from collections.abc import Sequence
from typing import ClassVar, Self

from pydantic import Field, model_validator

from app.domain import Adjustment, Cart, LineAllocation, LineItem, Phase
from app.money import allocate_proportionally, percent_of_cents
from app.promotions import (
    CartTarget,
    CategoryTarget,
    Promotion,
    PromotionTarget,
    ShippingTarget,
    SkuTarget,
    register_promotion,
)

LineTarget = SkuTarget | CategoryTarget
"""The two target kinds that select individual cart lines."""


def _as_line_target(target: PromotionTarget, kind_name: str) -> LineTarget:
    """Narrow `target` to a line-scoped target, failing loud otherwise.

    Item-phase kinds act on individual lines, so a cart- or shipping-scoped
    target is a seed-authoring error that must surface at load time, not as
    an AttributeError mid-pricing.

    Args:
        target: The promotion's authored target.
        kind_name: The kind's registry key, for the error message.

    Returns:
        The same target, narrowed to `SkuTarget | CategoryTarget`.

    Raises:
        ValueError: If `target` is not SKU- or category-scoped.
    """
    if isinstance(target, LineTarget):
        return target
    raise ValueError(f"{kind_name} promotions require a SKU or category target")


def _matched_items(target: LineTarget, cart: Cart) -> list[LineItem]:
    """Cart lines the line-scoped target acts on, in cart order."""
    return [item for item in cart.items if target.matches_line(item)]


def _line_allocations(
    items: Sequence[LineItem], shares: Sequence[int]
) -> list[LineAllocation]:
    """Pair lines with their allocated shares, omitting zero-cent shares.

    Zero shares (a zero-subtotal line, or a zero-amount adjustment) are left
    out of the trace so the explanation only names lines that actually
    received a discount. Deterministic: order follows `items`.

    Args:
        items: The matched lines, in cart order.
        shares: One integer-cent share per line, same order.

    Returns:
        One `LineAllocation` per line with a positive share.
    """
    return [
        LineAllocation(sku=item.sku, amount_cents=share)
        for item, share in zip(items, shares, strict=True)
        if share > 0
    ]


@register_promotion("BXGY")
class BuyXGetYFree(Promotion):
    """Buy-X-get-one-free: cheapest matched unit is free (P1).

    Condition: total quantity across target-matched lines is at least
    `min_qty`. Effect, exactly as docs/seed-promotions.md states it: the
    single cheapest matched unit is free — one unit, one line, its unit
    price as the discount. Ties on unit price break toward the smaller SKU
    string so the freed line is deterministic.
    """

    phase: ClassVar[Phase] = Phase.ITEM

    min_qty: int = Field(ge=1)

    @model_validator(mode="after")
    def _require_line_target(self) -> Self:
        """Reject cart/shipping targets at construction time.

        Returns:
            The validated promotion.

        Raises:
            ValueError: If the authored target is not line-scoped.
        """
        _as_line_target(self.target, "BXGY")
        return self

    def is_eligible(self, cart: Cart) -> bool:
        """Whether matched lines carry at least `min_qty` units in total.

        Args:
            cart: Phase-cascade state to check the condition against.

        Returns:
            True if the summed quantity of matched lines is >= `min_qty`.
        """
        target = _as_line_target(self.target, "BXGY")
        return sum(item.qty for item in _matched_items(target, cart)) >= self.min_qty

    def apply(self, cart: Cart) -> Adjustment:
        """Discount the cheapest matched unit's price off its line.

        Args:
            cart: Eligible phase-cascade state; never mutated.

        Returns:
            An adjustment allocating the cheapest matched unit price to the
            line carrying it (no allocations when that price is zero).
        """
        target = _as_line_target(self.target, "BXGY")
        cheapest = min(
            _matched_items(target, cart),
            key=lambda item: (item.unit_price_cents, item.sku),
        )
        amount = cheapest.unit_price_cents
        return Adjustment(
            promotion_id=self.id,
            promotion_name=self.name,
            phase=self.phase,
            amount_cents=amount,
            line_allocations=_line_allocations([cheapest], [amount]),
        )


@register_promotion("PCT_OFF_ITEM")
class PercentOffItem(Promotion):
    """Percent off every matched unit, gated on matched quantity (P6).

    Condition: total quantity across target-matched lines is at least
    `min_qty`. Effect: `percent_off`% off the matched lines' combined
    subtotal — computed once at that aggregate (round half-up, see
    `percent_of_cents`), then split across the matched lines
    proportionally to their subtotals with no rounding drift.
    """

    phase: ClassVar[Phase] = Phase.ITEM

    min_qty: int = Field(ge=1)
    percent_off: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def _require_line_target(self) -> Self:
        """Reject cart/shipping targets at construction time.

        Returns:
            The validated promotion.

        Raises:
            ValueError: If the authored target is not line-scoped.
        """
        _as_line_target(self.target, "PCT_OFF_ITEM")
        return self

    def is_eligible(self, cart: Cart) -> bool:
        """Whether matched lines carry at least `min_qty` units in total.

        Args:
            cart: Phase-cascade state to check the condition against.

        Returns:
            True if the summed quantity of matched lines is >= `min_qty`.
        """
        target = _as_line_target(self.target, "PCT_OFF_ITEM")
        return sum(item.qty for item in _matched_items(target, cart)) >= self.min_qty

    def apply(self, cart: Cart) -> Adjustment:
        """Take `percent_off`% off the matched lines' combined subtotal.

        Args:
            cart: Eligible phase-cascade state; never mutated.

        Returns:
            An adjustment whose amount is the rounded aggregate percentage,
            allocated across matched lines proportionally to their subtotals.
        """
        target = _as_line_target(self.target, "PCT_OFF_ITEM")
        matched = _matched_items(target, cart)
        weights = [item.line_subtotal_cents for item in matched]
        amount = percent_of_cents(sum(weights), self.percent_off)
        shares = allocate_proportionally(amount, weights)
        return Adjustment(
            promotion_id=self.id,
            promotion_name=self.name,
            phase=self.phase,
            amount_cents=amount,
            line_allocations=_line_allocations(matched, shares),
        )


@register_promotion("FIXED_OFF_ITEM")
class FixedOffItem(Promotion):
    """Fixed cents off the matched lines, capped at their value (P4).

    Condition: none beyond presence — eligible whenever any line matches
    the target. Effect: `amount_off_cents` off the matched lines' combined
    subtotal, capped at that subtotal so no line is ever driven negative,
    split proportionally when the target matches more than one line.
    """

    phase: ClassVar[Phase] = Phase.ITEM

    amount_off_cents: int = Field(ge=0)

    @model_validator(mode="after")
    def _require_line_target(self) -> Self:
        """Reject cart/shipping targets at construction time.

        Returns:
            The validated promotion.

        Raises:
            ValueError: If the authored target is not line-scoped.
        """
        _as_line_target(self.target, "FIXED_OFF_ITEM")
        return self

    def is_eligible(self, cart: Cart) -> bool:
        """Whether any cart line matches the target.

        Args:
            cart: Phase-cascade state to check the condition against.

        Returns:
            True if at least one line matches.
        """
        target = _as_line_target(self.target, "FIXED_OFF_ITEM")
        return bool(_matched_items(target, cart))

    def apply(self, cart: Cart) -> Adjustment:
        """Discount `amount_off_cents`, capped at the matched subtotal.

        Args:
            cart: Eligible phase-cascade state; never mutated.

        Returns:
            An adjustment for the capped amount, allocated across matched
            lines proportionally to their subtotals.
        """
        target = _as_line_target(self.target, "FIXED_OFF_ITEM")
        matched = _matched_items(target, cart)
        weights = [item.line_subtotal_cents for item in matched]
        # The cap: never discount more than the matched lines are worth.
        amount = min(self.amount_off_cents, sum(weights))
        shares = allocate_proportionally(amount, weights)
        return Adjustment(
            promotion_id=self.id,
            promotion_name=self.name,
            phase=self.phase,
            amount_cents=amount,
            line_allocations=_line_allocations(matched, shares),
        )


@register_promotion("PCT_OFF_CART")
class PercentOffCart(Promotion):
    """Percent off the whole cart subtotal, gated on that subtotal (P2/P5).

    Condition: the cart's subtotal is at least `min_subtotal_cents`. The
    `cart` handed in is the post-Item-phase cascade state
    (docs/seed-promotions.md's phase table), so both the condition and the
    effect read that subtotal as given — never recomputed from the original
    request. Effect: `percent_off`% of the subtotal (round half-up, once,
    at the aggregate), allocated across all lines proportionally to their
    subtotals.
    """

    phase: ClassVar[Phase] = Phase.CART

    min_subtotal_cents: int = Field(ge=0)
    percent_off: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def _require_cart_target(self) -> Self:
        """Reject any target other than the cart singleton.

        Returns:
            The validated promotion.

        Raises:
            ValueError: If the authored target is not `CartTarget`.
        """
        if not isinstance(self.target, CartTarget):
            raise ValueError("PCT_OFF_CART promotions require the cart target")
        return self

    def is_eligible(self, cart: Cart) -> bool:
        """Whether the (post-Item) subtotal meets the threshold.

        Args:
            cart: Phase-cascade state to check the condition against.

        Returns:
            True if `cart.subtotal_cents` is >= `min_subtotal_cents`.
        """
        return cart.subtotal_cents >= self.min_subtotal_cents

    def apply(self, cart: Cart) -> Adjustment:
        """Take `percent_off`% off the cart subtotal.

        Args:
            cart: Eligible phase-cascade state; never mutated.

        Returns:
            An adjustment whose amount is the rounded aggregate percentage,
            allocated across every line proportionally to its subtotal.
        """
        weights = [item.line_subtotal_cents for item in cart.items]
        amount = percent_of_cents(cart.subtotal_cents, self.percent_off)
        shares = allocate_proportionally(amount, weights)
        return Adjustment(
            promotion_id=self.id,
            promotion_name=self.name,
            phase=self.phase,
            amount_cents=amount,
            line_allocations=_line_allocations(cart.items, shares),
        )


@register_promotion("FREE_SHIPPING")
class FreeShipping(Promotion):
    """Free shipping over a subtotal threshold (P7).

    Condition: the cart's subtotal (post-Cart-phase cascade state) is at
    least `min_subtotal_cents`. Effect: shipping -> $0, expressed as a
    shipping-phase adjustment whose amount is the full shipping charge
    being waived — see `shipping_baseline_cents` for how the engine (#21)
    supplies that charge.
    """

    phase: ClassVar[Phase] = Phase.SHIPPING

    min_subtotal_cents: int = Field(ge=0)

    shipping_baseline_cents: int = Field(default=1000, ge=0)
    """The shipping charge this promotion waives, in integer cents.

    The baseline is engine configuration, not promotion data
    (docs/core-engine-spec.md's flat $10 / 1000 cents — the default here
    mirrors it). Seed files should omit this field; the engine (#21) owns
    the real value and must inject its configured baseline via
    `promotion.model_copy(update={"shipping_baseline_cents": ...})` before
    calling `apply` whenever its config differs from the default, so the
    adjustment amount always equals the charge actually being zeroed.
    """

    @model_validator(mode="after")
    def _require_shipping_target(self) -> Self:
        """Reject any target other than the shipping singleton.

        Returns:
            The validated promotion.

        Raises:
            ValueError: If the authored target is not `ShippingTarget`.
        """
        if not isinstance(self.target, ShippingTarget):
            raise ValueError("FREE_SHIPPING promotions require the shipping target")
        return self

    def is_eligible(self, cart: Cart) -> bool:
        """Whether the (post-Cart) subtotal meets the threshold.

        Args:
            cart: Phase-cascade state to check the condition against.

        Returns:
            True if `cart.subtotal_cents` is >= `min_subtotal_cents`.
        """
        return cart.subtotal_cents >= self.min_subtotal_cents

    def apply(self, cart: Cart) -> Adjustment:
        """Waive the shipping charge entirely.

        Args:
            cart: Eligible phase-cascade state; never mutated (and not
                otherwise read — the effect is on shipping, not lines).

        Returns:
            A shipping-phase adjustment for `shipping_baseline_cents`, with
            no line allocations (shipping is not a line).
        """
        return Adjustment(
            promotion_id=self.id,
            promotion_name=self.name,
            phase=self.phase,
            amount_cents=self.shipping_baseline_cents,
        )
