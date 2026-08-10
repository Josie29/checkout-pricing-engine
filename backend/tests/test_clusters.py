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


def outcome_ids(cluster: ConflictCluster, cart: Cart) -> list[list[str]]:
    """Promotion ids per legal outcome of `cluster`, in enumeration order."""
    outcomes = cluster.legal_outcomes(cart)
    assert outcomes is not None  # no limit passed
    return [[promo.id for promo in outcome] for outcome in outcomes]


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

        Clustering is the optimizer's search decomposition, not the
        exclusivity rule: A and C may still co-apply (see
        `TestLegalOutcomes`), but whether they may depends on whether B is
        applied, so all three must be searched together. Catches splitting
        them into separate sub-problems, where each could independently
        choose B and double-discount the bean lines.
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


class TestLegalOutcomes:
    """A cluster's outcomes are its independent sets, not one-member-or-none."""

    def test_chained_cluster_still_lets_the_disjoint_pair_co_apply(self) -> None:
        """In cluster [A, B, C], A and C may be taken together; B may not join.

        The regression for the shopper-visible bug: two per-SKU deals on
        different lines were chained into one cluster by a category deal
        that overlapped both, and the one-member-per-cluster rule silently
        dropped one of them. Catches any return to per-cluster exclusivity
        — and, in the other direction, catches B being offered alongside a
        SKU deal it genuinely conflicts with.
        """
        promos = [
            fixed_off("A", SkuTarget(sku="COF-ETH")),
            fixed_off("B", CategoryTarget(category="Coffee Beans")),
            fixed_off("C", SkuTarget(sku="COF-COL")),
        ]
        cart = Cart(items=[line("COF-ETH"), line("COF-COL")])
        (cluster,) = derive_clusters(cart, promos).item
        assert outcome_ids(cluster, cart) == [[], ["C"], ["B"], ["A"], ["A", "C"]]

    def test_mutually_exclusive_cluster_offers_one_member_or_none(self) -> None:
        """P1/P6 both target every bean line, so the old k+1 rule still holds.

        Catches the independent-set enumeration going too far the other way
        and offering {P1, P6} — two bean deals stacked on one line, the
        double-discount the cluster exists to prevent.
        """
        cart = Cart(items=[line("COF-ETH", qty=3)])
        item_clusters = derive_clusters(cart, SEED_PROMOTIONS).item
        beans = next(cl for cl in item_clusters if cl.promotions[0].id == "P1")
        assert outcome_ids(beans, cart) == [[], ["P6"], ["P1"]]

    def test_enumeration_stops_at_the_limit(self) -> None:
        """A cluster past `limit` returns None instead of enumerating it.

        The optimizer's blow-up guard: one category deal over n per-SKU
        deals has 2**n + 1 outcomes. Catches the limit being ignored, which
        would hang the request on a catalog the cap is meant to reject.
        """
        promos = [fixed_off("HUB", CategoryTarget(category="Coffee Beans"))] + [
            fixed_off(f"S{index}", SkuTarget(sku=sku))
            for index, sku in enumerate(["COF-ETH", "COF-COL"])
        ]
        cart = Cart(items=[line("COF-ETH"), line("COF-COL")])
        (cluster,) = derive_clusters(cart, promos).item
        # Outcomes: {}, {S0}, {S1}, {S0,S1}, {HUB} = 5.
        assert cluster.legal_outcomes(cart, limit=5) is not None
        assert cluster.legal_outcomes(cart, limit=4) is None
