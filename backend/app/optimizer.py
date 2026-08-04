import math
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
) -> EngineOutcome:
    """Find the best-allowed promotion combination (docs/optimizer-spec.md).

    Enumerates the cartesian product of every conflict cluster's outcomes
    across all three phases — a cluster of size k contributes k+1 options
    (one member or none) — prices each full combination through the
    unchanged `price_combination` cascade, and returns the minimum-total
    result labeled `optimal: True`. Because the search includes "none" per
    cluster, it can withhold an individually-eligible promotion when doing
    so yields a better total (the P4/P2 threshold interaction).

    Tie-break, applied as a sort key on
    `(total_cents, applied count, sorted applied ids)`: fewest promotions
    applied, then the lexicographically smallest sorted tuple of applied
    promotion ids. Keyed on the ids that actually applied (the result's
    adjustments), not the proposed combination — combinations whose extra
    members turn out ineligible collapse onto the same key and the same
    result, so the winner is deterministic and independent of claimed-id
    input order.

    Fallback: if the cluster-outcome product exceeds
    `config.cluster_product_cap`, the search is skipped entirely and the
    naive engine's outcome is returned unchanged (`optimal: False`).

    Args:
        cart: The cart to price.
        promotions: The full promotion list, in declaration order.
        claimed_ids: Ids of the promotions the shopper toggled on. Must be
            a subset of the ids in `promotions`; only claimed promotions
            are searched over.
        config: Engine configuration; defaults to `EngineConfig()`.

    Returns:
        The best combination's priced result (`optimal` True) plus one
        status per promotion — a claimed promotion the search chose to
        withhold stays `claimed`, exactly like claimed-but-ineligible. On
        cap fallback, the naive outcome (`optimal` False).

    Raises:
        ValueError: If `promotions` repeat an id, `claimed_ids` references
            an unknown id, or a constructed result fails the domain
            model's invariant validators.
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
    claimed_set = set(claimed_ids)
    claimed = [promotion for promotion in promotions if promotion.id in claimed_set]

    clusters = derive_clusters(cart, claimed).all_clusters()
    search_space = math.prod(len(cluster.promotions) + 1 for cluster in clusters)
    if search_space > engine_config.cluster_product_cap:
        return price_naive(cart, promotions, claimed_ids, engine_config)

    # Each cluster's k+1 outcomes: withhold the cluster (None) or apply one
    # member. Clusters arrive Item -> Cart -> Shipping, members in
    # declaration order, so each combination is already in canonical
    # cascade/trace order for `price_combination`.
    options: list[tuple[Promotion | None, ...]] = [
        (None, *cluster.promotions) for cluster in clusters
    ]
    best: PricingResult | None = None
    best_key: tuple[int, int, tuple[str, ...]] | None = None
    for choice in product(*options):
        combination = [promotion for promotion in choice if promotion is not None]
        result = price_combination(cart, combination, engine_config)
        applied = sorted(adj.promotion_id for adj in result.adjustments)
        key = (result.total_cents, len(applied), tuple(applied))
        if best_key is None or key < best_key:
            best, best_key = result, key
    assert best is not None  # options is never empty per-axis: product yields >= 1

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
