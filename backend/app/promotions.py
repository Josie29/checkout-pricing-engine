import inspect
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain import Adjustment, Cart, LineItem, NonBlankStr, Phase


class SkuTarget(BaseModel):
    """Targets the cart lines carrying one specific SKU."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["sku"] = "sku"
    sku: NonBlankStr

    def matches_line(self, item: LineItem) -> bool:
        """Whether `item` is one of the lines this target acts on.

        Args:
            item: A cart line.

        Returns:
            True if the line's SKU equals this target's SKU.
        """
        return item.sku == self.sku


class CategoryTarget(BaseModel):
    """Targets every cart line in one category."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["category"] = "category"
    category: NonBlankStr

    def matches_line(self, item: LineItem) -> bool:
        """Whether `item` is one of the lines this target acts on.

        Args:
            item: A cart line.

        Returns:
            True if the line's category equals this target's category.
        """
        return item.category == self.category


class CartTarget(BaseModel):
    """Singleton marker: targets the cart subtotal as a whole.

    Carries no data — every cart-phase promotion acts on the one subtotal,
    so any two `CartTarget`s overlap by construction.
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["cart"] = "cart"


class ShippingTarget(BaseModel):
    """Singleton marker: targets the shipping charge.

    Carries no data — every shipping-phase promotion acts on the one shipping
    fee, so any two `ShippingTarget`s overlap by construction.
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["shipping"] = "shipping"


PromotionTarget = Annotated[
    SkuTarget | CategoryTarget | CartTarget | ShippingTarget,
    Field(discriminator="kind"),
]

# The two target kinds scoped to individual cart lines; the other two are
# singleton whole-cart resources.
_LINE_SCOPED_TARGETS = (SkuTarget, CategoryTarget)


def targets_can_overlap(
    first: PromotionTarget, second: PromotionTarget, cart: Cart
) -> bool:
    """Whether two targets can claim the same pricing resource on `cart`.

    The one operation the target union exists to support
    (docs/promotion-abstraction-spec.md): the engine and optimizer derive
    conflict clusters by asking this for the cart being priced
    (docs/optimizer-spec.md, "targets can overlap on a given cart").

    Line-scoped targets (SKU/category) overlap iff some line item in `cart`
    is matched by both — the domain model deliberately does not bind a SKU to
    a fixed category, so overlap is decided against the cart's actual lines,
    not a catalog. `CartTarget` and `ShippingTarget` are singleton resources:
    each overlaps exactly its own kind, on any cart, and never a line-scoped
    target. Symmetric and deterministic.

    Args:
        first: One promotion's target.
        second: The other promotion's target.
        cart: The cart clusters are being derived for (the phase-cascade
            state at the relevant phase).

    Returns:
        True if both targets can act on the same resource of `cart`.
    """
    if isinstance(first, _LINE_SCOPED_TARGETS) and isinstance(
        second, _LINE_SCOPED_TARGETS
    ):
        return any(
            first.matches_line(item) and second.matches_line(item)
            for item in cart.items
        )
    return first.kind == second.kind


class Promotion(BaseModel, ABC):
    """Abstract interface every promotion kind implements.

    The contained-change contract (docs/promotion-abstraction-spec.md): a new
    kind is one subclass plus one `@register_promotion` call — no edits to the
    stacking engine, the seed loader, or other kinds. Each concrete class
    declares its own typed condition/effect fields (`min_qty`, `discount_pct`,
    ...) and encodes them directly in `is_eligible`/`apply`; there is no
    generic Condition/Effect object model.
    """

    model_config = ConfigDict(frozen=True)

    id: NonBlankStr
    name: NonBlankStr
    target: PromotionTarget

    phase: ClassVar[Phase]
    """Cascade phase, set once per subclass — a property of the kind.

    Deliberately a `ClassVar`, not a field: a seed file must not be able to
    author, say, a BXGY instance into the Cart phase (docs/seed-promotions.md,
    "Phase is a property of Type").
    """

    @abstractmethod
    def is_eligible(self, cart: Cart) -> bool:
        """Whether this promotion's condition holds for `cart`.

        A pure predicate: deterministic for a given cart, no mutation, no
        side effects. `cart` is the phase-cascade state at this promotion's
        phase (docs/seed-promotions.md's phase table), not necessarily the
        original request payload.

        Args:
            cart: Phase-cascade state to check the condition against.

        Returns:
            True if the promotion can be applied to `cart`.
        """

    @abstractmethod
    def apply(self, cart: Cart) -> Adjustment:
        """Compute this promotion's effect on an eligible `cart`.

        Only ever called after `is_eligible(cart)` returned True for the same
        cart (the engine's Claimed -> Applied transition in
        docs/core-engine-spec.md). Implementations may assume eligibility and
        must not re-check it or mutate `cart`.

        Args:
            cart: Phase-cascade state the promotion applies to; never mutated.

        Returns:
            An adjustment naming what was discounted, on which lines, and by
            how much in integer cents.
        """


PROMOTION_REGISTRY: dict[str, type[Promotion]] = {}
"""All registered promotion kinds, keyed by their seed `type` string.

Populated by `@register_promotion` at class-definition time; the seed loader
builds its discriminated union from this mapping, so registering is the only
wiring a new kind needs.
"""


def register_promotion[P: Promotion](
    type_key: str,
) -> Callable[[type[P]], type[P]]:
    """Build a class decorator registering a promotion kind under `type_key`.

    `type_key` is the `type` string seed entries use to name the kind
    (docs/seed-promotions.md's promotions table).

    Args:
        type_key: Unique, non-blank registry key for the kind.

    Returns:
        A decorator that validates and registers the class, returning it
        unchanged. The decorator raises `ValueError` if `type_key` is already
        registered, or if the class is still abstract or has not set
        `phase: ClassVar[Phase]` — each a miswired kind that must fail at
        import time, not at first seed load.

    Raises:
        ValueError: If `type_key` is empty or whitespace-only.
    """
    if not type_key.strip():
        raise ValueError("promotion type_key must not be blank")

    def decorator(cls: type[P]) -> type[P]:
        """Validate `cls` as a registrable kind and add it to the registry.

        Args:
            cls: The concrete `Promotion` subclass being registered.

        Returns:
            `cls`, unchanged.

        Raises:
            ValueError: If `type_key` is already registered, `cls` is
                abstract, or `cls` has not set `phase`.
        """
        if type_key in PROMOTION_REGISTRY:
            raise ValueError(
                f"duplicate promotion type_key {type_key!r}: already registered"
                f" by {PROMOTION_REGISTRY[type_key].__name__}"
            )
        if inspect.isabstract(cls):
            raise ValueError(
                f"cannot register abstract class {cls.__name__} under"
                f" {type_key!r}: is_eligible/apply must be implemented"
            )
        if not isinstance(getattr(cls, "phase", None), Phase):
            raise ValueError(
                f"cannot register {cls.__name__} under {type_key!r}: it must"
                " set `phase: ClassVar[Phase]`"
            )
        PROMOTION_REGISTRY[type_key] = cls
        return cls

    return decorator
