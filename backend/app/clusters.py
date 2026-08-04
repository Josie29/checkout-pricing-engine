from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.domain import Cart, Phase
from app.promotions import Promotion, targets_can_overlap


class ConflictCluster(BaseModel):
    """One group of mutually exclusive promotions within a phase.

    Cluster legality (docs/optimizer-spec.md): at most one member of a
    cluster may apply to a cart. Members are kept in declaration order —
    the naive engine's first-eligible tie-break reads them front to back.
    """

    model_config = ConfigDict(frozen=True)

    phase: Phase
    promotions: tuple[Promotion, ...] = Field(min_length=1)


class PhaseClusters(BaseModel):
    """Conflict clusters for every phase, the shared engine/optimizer input.

    The naive engine (docs/core-engine-spec.md) picks the first eligible
    member per cluster; the optimizer (#25, docs/optimizer-spec.md)
    enumerates each cluster's `k + 1` outcomes instead. Clusters appear in
    declaration order of their first member; members in declaration order.
    """

    model_config = ConfigDict(frozen=True)

    item: tuple[ConflictCluster, ...] = ()
    cart: tuple[ConflictCluster, ...] = ()
    shipping: tuple[ConflictCluster, ...] = ()

    def for_phase(self, phase: Phase) -> tuple[ConflictCluster, ...]:
        """Clusters belonging to one phase.

        Args:
            phase: The cascade phase to select.

        Returns:
            That phase's clusters, in declaration order of first member.
        """
        match phase:
            case Phase.ITEM:
                return self.item
            case Phase.CART:
                return self.cart
            case Phase.SHIPPING:
                return self.shipping

    def all_clusters(self) -> tuple[ConflictCluster, ...]:
        """Every cluster across all phases, in cascade-phase order.

        The optimizer's enumeration space: the cartesian product of each
        returned cluster's outcomes (docs/optimizer-spec.md).

        Returns:
            Item clusters, then Cart, then Shipping.
        """
        return self.item + self.cart + self.shipping


def derive_clusters(cart: Cart, promotions: Sequence[Promotion]) -> PhaseClusters:
    """Partition promotions into per-phase conflict clusters for `cart`.

    Two promotions of the same phase share a cluster iff their targets can
    overlap on this cart (`targets_can_overlap`), taken to transitive
    closure: A~B and B~C put A and C together even when A and C never
    overlap directly, because B cannot be exclusive with both separately.
    Cart- and Shipping-phase targets are singleton resources that always
    overlap within their kind, so each of those phases collapses to one
    cluster of all its promotions — the phase-cardinality rule of
    docs/seed-promotions.md restated as clusters. Overlap is checked
    against the original cart's lines: targets match on SKU/category,
    which no phase changes.

    Args:
        cart: The cart being priced.
        promotions: Candidate promotions, in declaration order.

    Returns:
        Clusters per phase. Deterministic for a given cart and promotion
        order: clusters are ordered by their first member's declaration
        position, members by declaration position.
    """
    by_phase: dict[Phase, list[Promotion]] = {phase: [] for phase in Phase}
    for promotion in promotions:
        by_phase[promotion.phase].append(promotion)
    return PhaseClusters(
        item=_phase_clusters(cart, Phase.ITEM, by_phase[Phase.ITEM]),
        cart=_phase_clusters(cart, Phase.CART, by_phase[Phase.CART]),
        shipping=_phase_clusters(cart, Phase.SHIPPING, by_phase[Phase.SHIPPING]),
    )


def _phase_clusters(
    cart: Cart, phase: Phase, members: Sequence[Promotion]
) -> tuple[ConflictCluster, ...]:
    """Union-find the transitive closure of target overlap for one phase.

    Args:
        cart: The cart overlap is decided against.
        phase: The phase every member belongs to.
        members: That phase's promotions, in declaration order.

    Returns:
        The phase's clusters, ordered by first member's position.
    """
    parent = list(range(len(members)))

    def find(index: int) -> int:
        """Root of `index`'s set, with path compression."""
        root = index
        while parent[root] != root:
            root = parent[root]
        while parent[index] != root:
            parent[index], index = root, parent[index]
        return root

    for i in range(len(members)):
        for j in range(i + 1, len(members)):
            if targets_can_overlap(members[i].target, members[j].target, cart):
                # Union: attach the later root under the earlier one so the
                # representative is always the smallest declaration index.
                root_i, root_j = sorted((find(i), find(j)))
                parent[root_j] = root_i

    grouped: dict[int, list[Promotion]] = {}
    for index, member in enumerate(members):
        grouped.setdefault(find(index), []).append(member)
    # Root indices ascend with declaration position, so sorting roots orders
    # clusters by their first member's declaration position.
    return tuple(
        ConflictCluster(phase=phase, promotions=tuple(grouped[root]))
        for root in sorted(grouped)
    )
