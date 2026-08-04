from enum import StrEnum
from typing import Annotated, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator


class Phase(StrEnum):
    """Promotion application phase; declaration order is the cascade order.

    Per docs/seed-promotions.md, phases run Item -> Cart -> Shipping and each
    phase's eligibility is checked against the previous phase's output. Phase
    is a property of a promotion *type*, never authored per instance.
    """

    ITEM = "item"
    CART = "cart"
    SHIPPING = "shipping"


def _require_nonblank(value: str) -> str:
    """Reject empty or whitespace-only strings without coercing them.

    Args:
        value: The string to check.

    Returns:
        The value, unchanged (no stripping).

    Raises:
        ValueError: If the string is empty or whitespace-only.
    """
    if not value.strip():
        raise ValueError("must not be empty or whitespace-only")
    return value


NonBlankStr = Annotated[str, AfterValidator(_require_nonblank)]


class LineItem(BaseModel):
    """One cart entry: a SKU at an integer-cent unit price and a quantity."""

    model_config = ConfigDict(frozen=True)

    sku: NonBlankStr
    name: str | None = None
    category: NonBlankStr
    unit_price_cents: int = Field(ge=0)
    qty: int = Field(ge=1)

    @property
    def line_subtotal_cents(self) -> int:
        """Pre-discount subtotal for this line (unit price times quantity)."""
        return self.unit_price_cents * self.qty


class Cart(BaseModel):
    """The shopper's cart — the pricing engine's input.

    Immutable (frozen) so promotion `apply` implementations cannot mutate the
    cascade state they are handed.
    """

    model_config = ConfigDict(frozen=True)

    items: list[LineItem] = Field(min_length=1)

    @model_validator(mode="after")
    def _require_unique_skus(self) -> Self:
        """Reject carts with two lines for the same SKU.

        SKU is the line key that adjustments allocate against; duplicates
        would make the itemized breakdown ambiguous. Callers merge quantities
        into one line instead.

        Returns:
            The validated cart.

        Raises:
            ValueError: If two line items share a SKU.
        """
        skus = [item.sku for item in self.items]
        if len(skus) != len(set(skus)):
            raise ValueError("cart line items must have unique SKUs")
        return self

    @property
    def subtotal_cents(self) -> int:
        """Pre-discount cart subtotal in integer cents."""
        return sum(item.line_subtotal_cents for item in self.items)


class LineAllocation(BaseModel):
    """The portion of one adjustment's discount attributed to one line (by SKU)."""

    model_config = ConfigDict(frozen=True)

    sku: NonBlankStr
    amount_cents: int = Field(ge=0)


class Adjustment(BaseModel):
    """Explanation-trace record: one promotion's applied effect.

    Names which promotion applied, in which phase, the total discount in
    integer cents, and how that discount is split across lines. Shipping-phase
    adjustments reduce the shipping charge, not any line, so they carry no
    line allocations.
    """

    model_config = ConfigDict(frozen=True)

    promotion_id: NonBlankStr
    promotion_name: NonBlankStr
    phase: Phase
    amount_cents: int = Field(ge=0)
    line_allocations: list[LineAllocation] = Field(default_factory=list[LineAllocation])

    @model_validator(mode="after")
    def _check_allocations(self) -> Self:
        """Guard the trace-to-itemization invariant on this adjustment.

        Shipping adjustments must carry no line allocations; every other
        adjustment's allocations must sum exactly to `amount_cents` (so a
        positive amount requires allocations) and reference each SKU at most
        once.

        Returns:
            The validated adjustment.

        Raises:
            ValueError: If allocations are present on a shipping adjustment,
                do not sum exactly to `amount_cents`, or repeat a SKU.
        """
        if self.phase is Phase.SHIPPING:
            if self.line_allocations:
                raise ValueError("shipping adjustments must not have line allocations")
            return self
        allocated = sum(alloc.amount_cents for alloc in self.line_allocations)
        if allocated != self.amount_cents:
            raise ValueError(
                f"line allocations sum to {allocated}, expected {self.amount_cents}"
            )
        skus = [alloc.sku for alloc in self.line_allocations]
        if len(skus) != len(set(skus)):
            raise ValueError("line allocations must reference each SKU at most once")
        return self


class PricedLine(BaseModel):
    """One line of the itemized breakdown after discounts."""

    model_config = ConfigDict(frozen=True)

    sku: NonBlankStr
    name: str | None = None
    category: NonBlankStr
    unit_price_cents: int = Field(ge=0)
    qty: int = Field(ge=1)
    line_subtotal_cents: int = Field(ge=0)
    discount_cents: int = Field(ge=0)
    line_total_cents: int = Field(ge=0)

    @model_validator(mode="after")
    def _check_arithmetic(self) -> Self:
        """Guard per-line arithmetic: subtotal and total must tie out exactly.

        Returns:
            The validated line.

        Raises:
            ValueError: If `line_subtotal_cents` is not unit price times qty,
                or `line_total_cents` is not subtotal minus discount.
        """
        if self.line_subtotal_cents != self.unit_price_cents * self.qty:
            raise ValueError("line_subtotal_cents must equal unit_price_cents * qty")
        if self.line_total_cents != self.line_subtotal_cents - self.discount_cents:
            raise ValueError(
                "line_total_cents must equal line_subtotal_cents - discount_cents"
            )
        return self


class PricingResult(BaseModel):
    """Full pricing output: itemized breakdown, explanation trace, and totals.

    `shipping_cents` is the shipping actually charged (already net of any
    shipping-phase adjustment); item/cart-phase discounts land on the lines.
    `optimal` marks whether the optimizer's combination (vs. the naive
    engine's) produced this result.
    """

    model_config = ConfigDict(frozen=True)

    lines: list[PricedLine] = Field(min_length=1)
    adjustments: list[Adjustment] = Field(default_factory=list[Adjustment])
    subtotal_cents: int = Field(ge=0)
    discount_total_cents: int = Field(ge=0)
    shipping_cents: int = Field(ge=0)
    total_cents: int = Field(ge=0)
    optimal: bool = False

    @model_validator(mode="after")
    def _check_invariants(self) -> Self:
        """Guard the itemization-sums-exactly invariant (docs/scope.md).

        Raises rather than clamps: a result whose breakdown, trace, and totals
        disagree by even one cent is a bug, not a tolerance.

        Returns:
            The validated result.

        Raises:
            ValueError: If lines repeat a SKU, an allocation references an
                unknown SKU, line subtotals don't sum to `subtotal_cents`,
                per-line discounts don't tie out to the non-shipping trace,
                adjustment amounts don't sum to `discount_total_cents`, or
                line totals plus shipping don't equal `total_cents`.
        """
        skus = [line.sku for line in self.lines]
        if len(skus) != len(set(skus)):
            raise ValueError("priced lines must have unique SKUs")
        if sum(line.line_subtotal_cents for line in self.lines) != self.subtotal_cents:
            raise ValueError("line subtotals must sum exactly to subtotal_cents")
        adjustment_sum = sum(adj.amount_cents for adj in self.adjustments)
        if adjustment_sum != self.discount_total_cents:
            raise ValueError(
                "adjustment amounts must sum exactly to discount_total_cents"
            )
        allocated_by_sku = dict.fromkeys(skus, 0)
        for adj in self.adjustments:
            for alloc in adj.line_allocations:
                if alloc.sku not in allocated_by_sku:
                    raise ValueError(
                        f"allocation references SKU {alloc.sku!r} not present in lines"
                    )
                allocated_by_sku[alloc.sku] += alloc.amount_cents
        for line in self.lines:
            if allocated_by_sku[line.sku] != line.discount_cents:
                raise ValueError(
                    f"line {line.sku!r} discount_cents does not equal the sum of"
                    " allocations to it in the adjustment trace"
                )
        if (
            sum(line.line_total_cents for line in self.lines) + self.shipping_cents
            != self.total_cents
        ):
            raise ValueError(
                "line totals plus shipping_cents must equal total_cents exactly"
            )
        return self
