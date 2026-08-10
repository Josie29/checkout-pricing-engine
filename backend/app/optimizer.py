from collections.abc import Collection, Sequence
from itertools import product

from app.clusters import derive_clusters
from app.domain import Cart, PricingResult
from app.engine import (
    EngineConfig,
    EngineOutcome,
    PromotionStatus,
    price_combination,
    price_naive,
)
from app.promotions import Promotion


def optimize(
    cart: Cart,
    promotions: Sequence[Promotion],
    claimed_ids: Collection[str],
    config: EngineConfig | None = None,
    pinned_ids: Collection[str] = (),
) -> EngineOutcome:
    """Find the best-allowed promotion combination (docs/optimizer-spec.md).

    Enumerates the cartesian product of every conflict cluster's legal
    outcomes across all three phases — a cluster contributes its
    independent sets, so mutually exclusive members yield "one or none"
    while members targeting different lines may be taken together — prices
    each full combination through the unchanged `price_combination`
    cascade, and returns the minimum-total result labeled `optimal: True`.
    Because every cluster's outcomes include the empty set, the search can
    withhold an individually-eligible promotion when doing so yields a
    better total (the P4/P2 threshold interaction).

    Tie-break, applied as a sort key on
    `(total_cents, applied count, sorted applied ids)`: fewest promotions
    applied, then the lexicographically smallest sorted tuple of applied
    promotion ids. Keyed on the ids that actually applied (the result's
    adjustments), not the proposed combination — combinations whose extra
    members turn out ineligible collapse onto the same key and the same
    result, so the winner is deterministic and independent of claimed-id
    input order.

    Pinning (`pinned_ids`) constrains the search to combinations in which
    every pinned promotion *actually applies* — not merely appears, since a
    member can turn out ineligible mid-cascade and contribute nothing. It
    is the shopper overriding the optimizer at checkout ("I want that deal
    instead"), and it is strictly a restriction: the winner is the best
    combination among those honoring the pins, so a pinned result is never
    better than the unpinned optimum and usually worse. A pin implies a
    claim. Pinning is also the only way to force a promotion the search
    would otherwise withhold for a better downstream total (the P4/P2
    threshold interaction) — those two do not conflict, so no amount of
    un-claiming rivals would surface P4.

    Fallbacks, both returning the naive engine's outcome unchanged
    (`optimal: False`): the cluster-outcome product exceeding
    `config.cluster_product_cap` — including when a single cluster's
    independent sets do so on their own — and, when pins are given, no
    combination managing to apply all of them (an unsatisfiable pin, e.g.
    two pinned promotions that conflict, or one that is ineligible on this
    cart). The naive fallback has no notion of pins and does not honor
    them; a caller that needs to distinguish "pins honored" from "fell
    back" should compare the pinned ids against the result's adjustments.

    Args:
        cart: The cart to price.
        promotions: The full promotion list, in declaration order.
        claimed_ids: Ids of the promotions the shopper toggled on. Must be
            a subset of the ids in `promotions`; only claimed promotions
            are searched over.
        config: Engine configuration; defaults to `EngineConfig()`.
        pinned_ids: Ids the shopper forced on. Must be a subset of the ids
            in `promotions`; treated as claimed whether or not they also
            appear in `claimed_ids`. Empty leaves the search unconstrained.

    Returns:
        The best combination's priced result (`optimal` True) plus one
        status per promotion — a claimed promotion the search chose to
        withhold stays `claimed`, exactly like claimed-but-ineligible. On
        either fallback, the naive outcome (`optimal` False).

    Raises:
        ValueError: If `promotions` repeat an id, `claimed_ids` or
            `pinned_ids` references an unknown id, or a constructed result
            fails the domain model's invariant validators.
        EngineInvariantError: If a pricing invariant is violated while
            pricing a combination — a bug, not a bad request.
    """
    engine_config = config if config is not None else EngineConfig()
    ids = [promotion.id for promotion in promotions]
    if len(ids) != len(set(ids)):
        raise ValueError("promotions must have unique ids")
    unknown = sorted(set(claimed_ids) - set(ids))
    if unknown:
        raise ValueError(f"claimed ids not in the promotion list: {unknown}")
    unknown_pins = sorted(set(pinned_ids) - set(ids))
    if unknown_pins:
        raise ValueError(f"pinned ids not in the promotion list: {unknown_pins}")
    pinned_set = set(pinned_ids)
    # A pin implies a claim: forcing a deal on is strictly stronger than
    # toggling it on, so a caller never has to send both.
    claimed_set = set(claimed_ids) | pinned_set
    claimed = [promotion for promotion in promotions if promotion.id in claimed_set]

    cap = engine_config.cluster_product_cap
    clusters = derive_clusters(cart, claimed).all_clusters()
    # Each cluster contributes its independent sets, enumerated under the
    # cap so a pathological cluster cannot blow up before it is measured.
    options: list[tuple[tuple[Promotion, ...], ...]] = []
    search_space = 1
    for cluster in clusters:
        outcomes = cluster.legal_outcomes(cart, limit=cap)
        if outcomes is None:
            return price_naive(cart, promotions, claimed_set, engine_config)
        options.append(outcomes)
        search_space *= len(outcomes)
        if search_space > cap:
            return price_naive(cart, promotions, claimed_set, engine_config)

    # Clusters arrive Item -> Cart -> Shipping, but a phase's clusters are
    # ordered by first member, so flattening alone can emit a phase's picks
    # out of declaration order; sorting restores the canonical trace order
    # `price_combination` applies within each phase.
    declaration_order = {
        promotion.id: index for index, promotion in enumerate(promotions)
    }
    best: PricingResult | None = None
    best_key: tuple[int, int, tuple[str, ...]] | None = None
    for choice in product(*options):
        combination = sorted(
            (promotion for outcome in choice for promotion in outcome),
            key=lambda promotion: declaration_order[promotion.id],
        )
        # Cheap pre-filter: a combination that does not even contain every
        # pin cannot apply them all, so skip pricing it.
        if not pinned_set.issubset({promotion.id for promotion in combination}):
            continue
        result = price_combination(cart, combination, engine_config)
        applied = sorted(adj.promotion_id for adj in result.adjustments)
        # Containing a pin is not enough — a member can be dropped
        # mid-cascade once upstream discounts move its threshold. The
        # shopper asked for the deal to apply, not to be considered.
        if not pinned_set.issubset(applied):
            continue
        key = (result.total_cents, len(applied), tuple(applied))
        if best_key is None or key < best_key:
            best, best_key = result, key
    if best is None:
        # Unsatisfiable pins (conflicting, or ineligible on this cart).
        # Nothing legal honors the shopper's override, so fall back rather
        # than silently pricing something they did not ask for.
        return price_naive(cart, promotions, claimed_set, engine_config)

    applied_ids = {adjustment.promotion_id for adjustment in best.adjustments}
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
    return EngineOutcome(
        result=best.model_copy(update={"optimal": True}), statuses=statuses
    )
