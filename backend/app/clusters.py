from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.domain import Cart, Phase
from app.promotions import Promotion, targets_can_overlap


class ConflictCluster(BaseModel):
    """One connected group of possibly-conflicting promotions in a phase.

    A cluster is a connected component of the phase's target-overlap graph,
    not a set of mutually exclusive promotions. Legality is pairwise
    (docs/seed-promotions.md: at most one Item-phase promo *per line item*),
    so several members can apply together as long as no two of them touch
    the same line — see `legal_outcomes`. Clusters exist to decompose the
    optimizer's search, not to define legality. Members are kept in
    declaration order.
    """

    model_config = ConfigDict(frozen=True)

    phase: Phase
    promotions: tuple[Promotion, ...] = Field(min_length=1)

    def legal_outcomes(
        self, cart: Cart, limit: int | None = None
    ) -> tuple[tuple[Promotion, ...], ...] | None:
        """Every legal subset of this cluster's members for `cart`.

        A subset is legal iff no two members' targets overlap on `cart` —
        an independent set in the cluster's overlap graph. Because a
        cluster is a connected *component*, its members are not mutually
        exclusive: two per-SKU promotions chained into one cluster by a
        category promotion overlapping both never touch the same line, and
        may both apply. The empty subset (withhold the whole cluster) is
        always legal and always returned.

        Args:
            cart: The cart overlap is decided against.
            limit: Give up and return None once more than this many
                outcomes exist. Bounds the work when a cluster's
                independent sets explode — one category promotion over *n*
                per-SKU promotions has 2**n + 1 of them. None enumerates
                fully.

        Returns:
            The legal subsets, each in declaration order, or None if the
            count exceeds `limit`.
        """
        members = self.promotions
        overlaps = [
            [
                targets_can_overlap(first.target, second.target, cart)
                for second in members
            ]
            for first in members
        ]
        outcomes: list[tuple[Promotion, ...]] = []

        def walk(index: int, chosen: list[int]) -> bool:
            """Extend `chosen` with members from `index` on; False if over `limit`."""
            if index == len(members):
                outcomes.append(tuple(members[position] for position in chosen))
                return limit is None or len(outcomes) <= limit
            if not walk(index + 1, chosen):
                return False
            if any(overlaps[index][position] for position in chosen):
                return True
            return walk(index + 1, [*chosen, index])

        return tuple(outcomes) if walk(0, []) else None


class PhaseClusters(BaseModel):
    """Conflict clusters for every phase, the shared engine/optimizer input.

    The optimizer (#25, docs/optimizer-spec.md) enumerates the cartesian
    product of every cluster's `legal_outcomes`. Clusters appear in
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
        returned cluster's `legal_outcomes` (docs/optimizer-spec.md).

        Returns:
            Item clusters, then Cart, then Shipping.
        """
        return self.item + self.cart + self.shipping


def derive_clusters(cart: Cart, promotions: Sequence[Promotion]) -> PhaseClusters:
    """Partition promotions into per-phase conflict clusters for `cart`.

    Two promotions of the same phase share a cluster iff their targets can
    overlap on this cart (`targets_can_overlap`), taken to transitive
    closure: A~B and B~C put A and C together even when A and C never
    overlap directly, because whether A and C may co-apply depends on
    whether B is applied too — they belong to one search sub-problem.
    Sharing a cluster does *not* make A and C exclusive; that is decided
    pairwise by `ConflictCluster.legal_outcomes`. Cart- and Shipping-phase
    targets are singleton resources that always overlap within their kind,
    so each of those phases collapses to one cluster whose members really
    are mutually exclusive — the phase-cardinality rule of
    docs/seed-promotions.md. Overlap is checked against the original
    cart's lines: targets match on SKU/category, which no phase changes.

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
