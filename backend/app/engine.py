from collections.abc import Callable, Collection, Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.clusters import derive_clusters
from app.domain import Adjustment, Cart, LineItem, Phase, PricedLine, PricingResult
from app.promotions import Promotion


class EngineConfig(BaseModel):
    """Engine-owned pricing configuration, distinct from promotion data."""

    model_config = ConfigDict(frozen=True)

    shipping_baseline_cents: int = Field(default=1000, ge=0)
    """Flat shipping charge before any shipping-phase promotion.

    docs/core-engine-spec.md: $10 flat, regardless of cart contents or
    destination — carrier/address-based rates are deferred.
    """

    cluster_product_cap: int = Field(default=512, ge=1)
    """Max cluster-outcome combinations the optimizer (#25) will enumerate.

    The search space is the product of (cluster size + 1) across all
    clusters (docs/optimizer-spec.md); past this cap the optimizer skips
    the search and returns the naive result with `optimal: false`. 512 is
    ~14x today's seed-set space of 36 (nine independent binary clusters'
    worth), while bounding worst-case work to 512 cascade evaluations —
    comfortably sub-second.
    """


class PromotionStatus(StrEnum):
    """Per-request promotion status (docs/core-engine-spec.md's table)."""

    AVAILABLE = "available"
    CLAIMED = "claimed"
    APPLIED = "applied"


class EngineInvariantError(ValueError):
    """An engine-level pricing invariant was violated.

    Raised — never clamped — for violations the domain model cannot see on
    its own: a promotion applied twice, two same-cluster promotions in one
    combination, a line discounted below zero, or shipping discounted below
    zero. Any of these means a bug in the caller or a promotion kind, not a
    condition to price through.
    """


class EngineOutcome(BaseModel):
    """The naive engine's full answer: the priced result plus statuses.

    `statuses` has one entry per promotion the engine was given (claimed or
    not), so the API (#22) can report every promotion's status without
    re-deriving it.
    """

    model_config = ConfigDict(frozen=True)

    result: PricingResult
    statuses: dict[str, PromotionStatus]


PhaseSelector = Callable[[Phase, Cart], list[Promotion]]
"""Chooses which promotions apply at one phase, given that phase's input state.

The single point where the naive engine and `price_combination` differ —
everything downstream of selection (application, cascade state, result
assembly, guards) is the one shared pricing path.
"""


def price_combination(
    cart: Cart,
    combination: Sequence[Promotion],
    config: EngineConfig | None = None,
) -> PricingResult:
    """Price one explicit promotion combination through the phase cascade.

    The reusable cascade core (issue #21 for issue #25): the caller has
    already resolved conflicts down to at most one promotion per conflict
    cluster; this function prices exactly that choice. Each promotion is
    applied iff it is eligible against its phase's cascade state — an
    ineligible member is skipped without error, so an optimizer enumerating
    cluster outcomes can price combinations whose Cart/Shipping members turn
    out ineligible once upstream discounts land (they simply contribute
    nothing). Within a phase, promotions apply in the order given; pass
    declaration order for a canonical trace.

    Args:
        cart: The cart to price.
        combination: The chosen promotions, at most one per conflict
            cluster on `cart`.
        config: Engine configuration; defaults to `EngineConfig()`.

    Returns:
        The priced result for exactly this combination (`optimal` left
        False; the optimizer labels its own winner).

    Raises:
        EngineInvariantError: If two combination members share a conflict
            cluster on `cart` (including the same promotion twice), or a
            downstream pricing invariant is violated.
        ValueError: If a constructed result fails the domain model's
            invariant validators.
    """
    engine_config = config if config is not None else EngineConfig()
    for cluster in derive_clusters(cart, combination).all_clusters():
        if len(cluster.promotions) > 1:
            ids = ", ".join(promo.id for promo in cluster.promotions)
            raise EngineInvariantError(
                f"combination is illegal: promotions [{ids}] share a"
                f" {cluster.phase} conflict cluster on this cart"
            )
    by_phase: dict[Phase, list[Promotion]] = {phase: [] for phase in Phase}
    for promotion in combination:
        by_phase[promotion.phase].append(promotion)

    def select(phase: Phase, state: Cart) -> list[Promotion]:
        """The phase's chosen promotions that are eligible against `state`."""
        return [promo for promo in by_phase[phase] if promo.is_eligible(state)]

    return _run_cascade(cart, select, engine_config)


def price_naive(
    cart: Cart,
    promotions: Sequence[Promotion],
    claimed_ids: Collection[str],
    config: EngineConfig | None = None,
) -> EngineOutcome:
    """Price a cart with the naive engine (docs/core-engine-spec.md).

    Considers only claimed promotions. Per conflict cluster, applies the
    first member (declaration order — the order of `promotions`, i.e. seed
    file order) that is eligible against the phase's cascade state; no
    ranking, no backtracking to withhold a promotion for a better downstream
    total. Phases cascade Item -> Cart -> Shipping, each phase's eligibility
    checked against the previous phase's output state. A claimed promotion
    that is never eligible stays claimed — never applied, no error.

    Args:
        cart: The cart to price.
        promotions: The full promotion list, in declaration order.
        claimed_ids: Ids of the promotions the shopper toggled on. Must be
            a subset of the ids in `promotions`.
        config: Engine configuration; defaults to `EngineConfig()`.

    Returns:
        The priced result plus one status per promotion in `promotions`.

    Raises:
        ValueError: If `promotions` repeat an id, `claimed_ids` references
            an unknown id, or a constructed result fails the domain model's
            invariant validators.
        EngineInvariantError: If a pricing invariant is violated — with
            first-eligible-per-cluster selection this indicates a bug, not
            a bad request.
    """
    engine_config = config if config is not None else EngineConfig()
    ids = [promotion.id for promotion in promotions]
    if len(ids) != len(set(ids)):
        raise ValueError("promotions must have unique ids")
    unknown = sorted(set(claimed_ids) - set(ids))
    if unknown:
        raise ValueError(f"claimed ids not in the promotion list: {unknown}")
    claimed_set = set(claimed_ids)
    claimed = [promotion for promotion in promotions if promotion.id in claimed_set]
    clusters = derive_clusters(cart, claimed)

    def select(phase: Phase, state: Cart) -> list[Promotion]:
        """First eligible member of each of the phase's clusters, if any."""
        chosen: list[Promotion] = []
        for cluster in clusters.for_phase(phase):
            for member in cluster.promotions:
                if member.is_eligible(state):
                    chosen.append(member)
                    break
        return chosen

    result = _run_cascade(cart, select, engine_config)
    applied_ids = {adjustment.promotion_id for adjustment in result.adjustments}
    statuses = {
        promotion.id: (
            PromotionStatus.APPLIED
            if promotion.id in applied_ids
            else PromotionStatus.CLAIMED
            if promotion.id in claimed_set
            else PromotionStatus.AVAILABLE
        )
        for promotion in promotions
    }
    return EngineOutcome(result=result, statuses=statuses)


def _run_cascade(
    cart: Cart, select: PhaseSelector, config: EngineConfig
) -> PricingResult:
    """The one pricing path: cascade phases, apply selections, assemble.

    Runs Item -> Cart -> Shipping. At each phase, `select` is handed the
    phase's input state (the previous phase's output cart,
    docs/seed-promotions.md's phase table) and returns the promotions to
    apply there; their adjustments accumulate into per-line discounts (or
    the shipping discount) and the next phase's state is rebuilt from the
    original cart with cumulative discounts. Shipping-phase promotions that
    declare a `shipping_baseline_cents` field (see FreeShipping) get the
    configured baseline injected via `model_copy` before `apply`, so their
    adjustment always equals the charge actually waived.

    Args:
        cart: The original cart being priced.
        select: Chooses the promotions to apply per phase; must return at
            most one member of any conflict cluster, each eligible against
            the state it was handed.
        config: Engine configuration.

    Returns:
        The assembled result; the domain model's validators re-check every
        itemization invariant on construction.

    Raises:
        EngineInvariantError: If a promotion is applied twice, an
            allocation names a SKU not in the cart, a line's cumulative
            discount exceeds its value, or shipping is discounted below
            zero.
        ValueError: If the assembled result fails the domain model's
            invariant validators.
    """
    subtotals_by_sku = {item.sku: item.line_subtotal_cents for item in cart.items}
    discounts_by_sku = dict.fromkeys(subtotals_by_sku, 0)
    adjustments: list[Adjustment] = []
    applied_ids: set[str] = set()
    shipping_discount = 0
    state = cart
    for phase in Phase:
        for promotion in select(phase, state):
            if promotion.id in applied_ids:
                raise EngineInvariantError(
                    f"promotion {promotion.id!r} applied more than once"
                )
            applied_ids.add(promotion.id)
            to_apply = promotion
            if "shipping_baseline_cents" in type(promotion).model_fields:
                to_apply = promotion.model_copy(
                    update={"shipping_baseline_cents": config.shipping_baseline_cents}
                )
            adjustment = to_apply.apply(state)
            adjustments.append(adjustment)
            if phase is Phase.SHIPPING:
                shipping_discount += adjustment.amount_cents
                if shipping_discount > config.shipping_baseline_cents:
                    raise EngineInvariantError(
                        f"promotion {promotion.id!r} discounts shipping below zero"
                    )
            else:
                for allocation in adjustment.line_allocations:
                    if allocation.sku not in discounts_by_sku:
                        raise EngineInvariantError(
                            f"promotion {promotion.id!r} allocated to SKU"
                            f" {allocation.sku!r}, which is not in the cart"
                        )
                    discounts_by_sku[allocation.sku] += allocation.amount_cents
                    if (
                        discounts_by_sku[allocation.sku]
                        > subtotals_by_sku[allocation.sku]
                    ):
                        raise EngineInvariantError(
                            f"line {allocation.sku!r} discounted below zero by"
                            f" promotion {promotion.id!r}"
                        )
        state = _post_phase_cart(cart, discounts_by_sku)

    lines = [
        PricedLine(
            sku=item.sku,
            name=item.name,
            category=item.category,
            unit_price_cents=item.unit_price_cents,
            qty=item.qty,
            line_subtotal_cents=item.line_subtotal_cents,
            discount_cents=discounts_by_sku[item.sku],
            line_total_cents=item.line_subtotal_cents - discounts_by_sku[item.sku],
        )
        for item in cart.items
    ]
    shipping_cents = config.shipping_baseline_cents - shipping_discount
    return PricingResult(
        lines=lines,
        adjustments=adjustments,
        subtotal_cents=cart.subtotal_cents,
        discount_total_cents=sum(adj.amount_cents for adj in adjustments),
        shipping_cents=shipping_cents,
        total_cents=sum(line.line_total_cents for line in lines) + shipping_cents,
    )


def _post_phase_cart(cart: Cart, discounts_by_sku: dict[str, int]) -> Cart:
    """Rebuild the cascade state a later phase checks eligibility against.

    Each line collapses to qty 1 at its discounted line total, so the
    state's `subtotal_cents` and per-line weights reflect the discounts
    applied so far (docs/seed-promotions.md: "Subtotal *after* Item-phase
    discounts"). Original quantities are not preserved — no Cart- or
    Shipping-phase kind reads quantities today; a future kind that does
    needs a richer cascade state than a collapsed `Cart`.

    Args:
        cart: The original cart.
        discounts_by_sku: Cumulative discount so far per line, in cents.

    Returns:
        A new cart with each line's value net of its discounts.
    """
    return Cart(
        items=[
            LineItem(
                sku=item.sku,
                name=item.name,
                category=item.category,
                unit_price_cents=item.line_subtotal_cents - discounts_by_sku[item.sku],
                qty=1,
            )
            for item in cart.items
        ]
    )
