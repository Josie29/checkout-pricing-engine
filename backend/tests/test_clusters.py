from app.clusters import ConflictCluster, derive_clusters
from app.domain import Cart, LineItem, Phase
from app.promotion_kinds import FixedOffItem
from app.promotions import CategoryTarget, Promotion, SkuTarget
from app.seeds import load_seed_catalog, load_seed_promotions

CATALOG = {item.sku: item for item in load_seed_catalog()}
SEED_PROMOTIONS = load_seed_promotions()


def line(sku: str, qty: int = 1) -> LineItem:
    """A cart line for a seeded catalog SKU at its catalog price."""
    item = CATALOG[sku]
    return LineItem(
        sku=item.sku,
        name=item.name,
        category=item.category,
        unit_price_cents=item.unit_price_cents,
        qty=qty,
    )


def cluster_ids(clusters: tuple[ConflictCluster, ...]) -> list[list[str]]:
    """Promotion ids per cluster, preserving both orderings."""
    return [[promo.id for promo in cluster.promotions] for cluster in clusters]


def fixed_off(promo_id: str, target: SkuTarget | CategoryTarget) -> Promotion:
    """A synthetic Item-phase promotion with an arbitrary line target."""
    return FixedOffItem(id=promo_id, name=promo_id, target=target, amount_off_cents=100)


class TestSeededClusters:
    """docs/seed-promotions.md's exclusivity table, derived not hand-coded."""

    def test_beans_and_dripper_cart_partitions_all_three_phases(self) -> None:
        """P1/P6 cluster together, P4 alone; P2/P5 one Cart cluster; P7 alone.

        Catches the engine treating P1 and P6 as freely stackable (a shopper
        double-dipping both bean deals) or lumping P4 in with them (a shopper
        wrongly denied the dripper discount alongside a bean deal).
        """
        cart = Cart(items=[line("COF-ETH", qty=3), line("BREW-V60")])
        clusters = derive_clusters(cart, SEED_PROMOTIONS)
        assert cluster_ids(clusters.item) == [["P1", "P6"], ["P4"]]
        assert cluster_ids(clusters.cart) == [["P2", "P5"]]
        assert cluster_ids(clusters.shipping) == [["P7"]]

    def test_overlap_is_decided_on_the_actual_cart(self) -> None:
        """On a cart with no bean lines, P1 and P6 no longer conflict.

        Catches clustering from the catalog instead of the cart — the
        cluster shape (and so the optimizer's search space) is defined per
        cart being priced (docs/optimizer-spec.md).
        """
        cart = Cart(items=[line("MUG-CLS")])
        clusters = derive_clusters(cart, SEED_PROMOTIONS)
        assert cluster_ids(clusters.item) == [["P1"], ["P6"], ["P4"]]

    def test_phase_accessors_cover_every_cluster_in_cascade_order(self) -> None:
        """`for_phase` and `all_clusters` agree and cover Item->Cart->Shipping.

        Catches the optimizer (#25) enumerating a different cluster set than
        the naive engine resolves — the two must share one partition.
        """
        cart = Cart(items=[line("COF-ETH", qty=3), line("BREW-V60")])
        clusters = derive_clusters(cart, SEED_PROMOTIONS)
        assert clusters.all_clusters() == (
            clusters.for_phase(Phase.ITEM)
            + clusters.for_phase(Phase.CART)
            + clusters.for_phase(Phase.SHIPPING)
        )
        assert [cluster.phase for cluster in clusters.all_clusters()] == [
            Phase.ITEM,
            Phase.ITEM,
            Phase.CART,
            Phase.SHIPPING,
        ]


class TestTransitiveClosure:
    """Cluster membership is the closure of pairwise overlap, not raw pairs."""

    def test_chained_overlap_merges_promotions_that_never_directly_overlap(
        self,
    ) -> None:
        """A~B and B~C put A and C in one cluster even though A never meets C.

        Catches pairwise-only clustering: A (Ethiopia-only) and C
        (Colombia-only) would land in separate clusters and both apply
        alongside B (all beans) — B would stack with two promotions it
        conflicts with, double-discounting the bean lines.
        """
        promos = [
            fixed_off("A", SkuTarget(sku="COF-ETH")),
            fixed_off("B", CategoryTarget(category="Coffee Beans")),
            fixed_off("C", SkuTarget(sku="COF-COL")),
        ]
        cart = Cart(items=[line("COF-ETH"), line("COF-COL")])
        clusters = derive_clusters(cart, promos)
        assert cluster_ids(clusters.item) == [["A", "B", "C"]]

    def test_disjoint_targets_stay_in_separate_clusters(self) -> None:
        """Without the bridging promotion, Ethiopia- and Colombia-only split.

        Catches over-merging (one giant cluster regardless of targets) —
        that would forbid legal stacking and cost shoppers real discounts.
        """
        promos = [
            fixed_off("A", SkuTarget(sku="COF-ETH")),
            fixed_off("C", SkuTarget(sku="COF-COL")),
        ]
        cart = Cart(items=[line("COF-ETH"), line("COF-COL")])
        assert cluster_ids(derive_clusters(cart, promos).item) == [["A"], ["C"]]
