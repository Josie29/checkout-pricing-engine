from hypothesis import given
from hypothesis import strategies as st

from app.clusters import derive_clusters
from app.domain import Cart, LineItem, Phase
from app.engine import EngineConfig, PromotionStatus, price_combination, price_naive
from app.optimizer import optimize
from app.promotion_kinds import FixedOffItem
from app.promotions import (
    CategoryTarget,
    Promotion,
    SkuTarget,
    targets_can_overlap,
)
from app.seeds import load_seed_catalog, load_seed_promotions
from tests.legality import assert_no_overlapping_pair

CATALOG = {item.sku: item for item in load_seed_catalog()}
SEED_PROMOTIONS = load_seed_promotions()
SEED_IDS = [promo.id for promo in SEED_PROMOTIONS]


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


def applied_ids(statuses: dict[str, PromotionStatus]) -> set[str]:
    """The promotion ids a result reports as applied."""
    return {
        promo_id
        for promo_id, status in statuses.items()
        if status is PromotionStatus.APPLIED
    }


class TestOracles:
    """Hand-computed optima the cluster-product search must reproduce."""

    def test_p4_p2_conflict_withholds_the_eligible_p4(self) -> None:
        """On a 5000c cart, the optimizer withholds P4 to keep P2's 15%.

        The optimizer's defining scenario (docs/optimizer-spec.md): savings
        are non-additive. Catches the search only resolving cluster
        conflicts without ever *withholding* an individually-eligible,
        non-conflicting promotion.

        Hand arithmetic — cart BREW-V60 (2800c) + MUG-TVL (2200c) = 5000c,
        claimed {P4, P2}; four combinations:
          {}       -> 5000 + 1000 shipping = 6000
          {P4}     -> 5000 - 500 = 4500 + 1000 = 5500  (the naive pick:
                      post-item 4500 < P2's 5000 threshold, P2 forfeited)
          {P2}     -> 15% of 5000 = 750 -> 4250 + 1000 = 5250  <- optimum
          {P4,P2}  -> P2 ineligible mid-cascade, prices as {P4} = 5500
        P2's 750c splits 2800:2200 -> floor shares 420/330, no remainder.
        """
        cart = Cart(items=[line("BREW-V60"), line("MUG-TVL")])
        naive = price_naive(cart, SEED_PROMOTIONS, {"P4", "P2"})
        outcome = optimize(cart, SEED_PROMOTIONS, {"P4", "P2"})
        result = outcome.result
        assert naive.result.total_cents == 5500
        assert result.total_cents == 5250
        assert result.total_cents < naive.result.total_cents
        assert result.optimal is True
        assert [adj.promotion_id for adj in result.adjustments] == ["P2"]
        assert result.adjustments[0].amount_cents == 750
        assert [
            (li.sku, li.discount_cents, li.line_total_cents) for li in result.lines
        ] == [("BREW-V60", 420, 2380), ("MUG-TVL", 330, 1870)]
        # The withheld-but-eligible P4 stays claimed — same status as
        # claimed-but-ineligible; the UI contract has no fourth value.
        assert outcome.statuses == {
            "P1": PromotionStatus.AVAILABLE,
            "P6": PromotionStatus.AVAILABLE,
            "P4": PromotionStatus.CLAIMED,
            "P2": PromotionStatus.APPLIED,
            "P5": PromotionStatus.AVAILABLE,
            "P7": PromotionStatus.AVAILABLE,
        }

    def test_no_conflict_cart_matches_the_naive_result(self) -> None:
        """On the 7500c golden cart, optimizer and naive agree exactly.

        Catches the optimizer 'improving' on a cart where the naive pick is
        already optimal — shoppers would see two engines disagree for no
        reason, and the runtime sanity check would mask a real bug.

        Hand arithmetic — COF-ETH x2 (3200c) + COF-DEC (1500c) + BREW-V60
        (2800c) = 7500c, everything claimed. P5/P7 need a 10000c subtotal
        the cart can never reach: never eligible. P2 (15%, 5000c min) stays
        eligible at any reachable post-item subtotal (>= 7500 - 2000 =
        5500), and total = 85% of post-item + 1000, so the optimum takes
        the largest item-phase discounts: bean cluster P1 (frees COF-DEC,
        1500c) beats P6 (20% of 4700c beans = 940c), plus P4 (500c).
        Post-item 5500, P2 = 825 -> 4675 + 1000 = 5675 — the naive pick.
        """
        cart = Cart(items=[line("COF-ETH", qty=2), line("COF-DEC"), line("BREW-V60")])
        naive = price_naive(cart, SEED_PROMOTIONS, set(SEED_IDS))
        outcome = optimize(cart, SEED_PROMOTIONS, set(SEED_IDS))
        assert outcome.result.total_cents == 5675
        assert outcome.result.total_cents == naive.result.total_cents
        assert outcome.result.optimal is True
        assert applied_ids(outcome.statuses) == {"P1", "P4", "P2"}
        assert outcome.result.adjustments == naive.result.adjustments


@st.composite
def seeded_carts(draw: st.DrawFn) -> Cart:
    """A cart of 1-8 distinct catalog SKUs, each at quantity 1-6."""
    skus = draw(
        st.lists(st.sampled_from(sorted(CATALOG)), min_size=1, max_size=8, unique=True)
    )
    return Cart(items=[line(sku, qty=draw(st.integers(1, 6))) for sku in skus])


class TestOptimizerProperties:
    """docs/testing-strategy.md's property layer for the optimizer."""

    @given(cart=seeded_carts(), claimed=st.sets(st.sampled_from(SEED_IDS)))
    def test_never_worse_than_naive_and_invariants_hold(
        self, cart: Cart, claimed: set[str]
    ) -> None:
        """Random carts x claimed subsets: optimizer <= naive, receipt adds up.

        Catches any cart shape where the search returns a worse total than
        the engine it exists to beat, applies an unclaimed promotion,
        stacks two promotions onto the same line, or produces a receipt
        whose lines, trace, and totals disagree by a cent — and any drift
        between the winner and the shared `price_combination` core.
        """
        naive = price_naive(cart, SEED_PROMOTIONS, claimed)
        outcome = optimize(cart, SEED_PROMOTIONS, claimed)
        result = outcome.result
        assert result.total_cents <= naive.result.total_cents
        assert result.optimal is True  # seed space is 36 combos, under the cap
        applied = applied_ids(outcome.statuses)
        assert applied <= claimed
        assert applied == {adj.promotion_id for adj in result.adjustments}
        # Totals tie out (the domain validators re-check on construction;
        # asserting here keeps the property explicit, not incidental).
        assert (
            sum(li.line_total_cents for li in result.lines) + result.shipping_cents
            == result.total_cents
        )
        assert (
            sum(adj.amount_cents for adj in result.adjustments)
            == result.discount_total_cents
        )
        applied_promos = [promo for promo in SEED_PROMOTIONS if promo.id in applied]
        assert_no_overlapping_pair(applied_promos, cart)
        assert price_combination(cart, applied_promos) == result.model_copy(
            update={"optimal": False}
        )

    @given(
        cart=seeded_carts(),
        claimed=st.lists(st.sampled_from(SEED_IDS), unique=True),
    )
    def test_result_is_invariant_to_claimed_id_input_order(
        self, cart: Cart, claimed: list[str]
    ) -> None:
        """Reversing the claimed-id list changes nothing in the outcome.

        Catches the winner (or its tie-break) depending on toggle order —
        two shoppers claiming the same promos in a different order must
        see the identical price and statuses.
        """
        forward = optimize(cart, SEED_PROMOTIONS, claimed)
        backward = optimize(cart, SEED_PROMOTIONS, list(reversed(claimed)))
        assert forward == backward


def fixed_off(promo_id: str, target: SkuTarget | CategoryTarget) -> Promotion:
    """A synthetic Item-phase promotion with an arbitrary line target."""
    return FixedOffItem(id=promo_id, name=promo_id, target=target, amount_off_cents=100)


# Line-target synthetics whose overlap depends on the drawn cart's lines:
# the SKU targets overlap their category targets only when the matching
# line is actually present.
SYNTHETIC_ITEM_PROMOS = [
    fixed_off("SYN-ETH", SkuTarget(sku="COF-ETH")),
    fixed_off("SYN-GEAR", CategoryTarget(category="Brew Gear")),
    fixed_off("SYN-V60", SkuTarget(sku="BREW-V60")),
]


class TestClusterPartitionProperty:
    """The optimizer's search space: clusters are exactly the overlap closure."""

    @given(cart=seeded_carts())
    def test_clusters_are_connected_components_of_cart_overlap(
        self, cart: Cart
    ) -> None:
        """Per phase, clusters == connected components of `targets_can_overlap`.

        Two promotions share a cluster iff a chain of cart-overlapping
        targets connects them on *this* cart (docs/optimizer-spec.md).
        Catches under-merging (two bean deals stack, double-discounting)
        and over-merging (disjoint promos forced mutually exclusive,
        denying a legal stack) — recomputed here by BFS as an independent
        oracle for clusters.py's union-find.
        """
        promotions = SEED_PROMOTIONS + SYNTHETIC_ITEM_PROMOS
        clusters = derive_clusters(cart, promotions)
        for phase in Phase:
            members = [promo for promo in promotions if promo.phase is phase]
            remaining = list(members)
            components: set[frozenset[str]] = set()
            while remaining:
                group = [remaining.pop(0)]
                grew = True
                while grew:
                    grew = False
                    for other in list(remaining):
                        if any(
                            targets_can_overlap(other.target, member.target, cart)
                            for member in group
                        ):
                            group.append(other)
                            remaining.remove(other)
                            grew = True
                components.add(frozenset(promo.id for promo in group))
            derived = {
                frozenset(promo.id for promo in cluster.promotions)
                for cluster in clusters.for_phase(phase)
            }
            assert derived == components


class TestPerLineExclusivity:
    """The optimizer searches within a cluster, not just across clusters."""

    def test_two_sku_deals_beat_the_category_deal_that_chains_them(self) -> None:
        """A1+A2 (200c) wins over the bean deal (100c) they share a cluster with.

        The optimizer half of the shopper-visible regression, and a real
        oracle: naive takes the first-declared B1 for 100c, so this result
        only exists if the search enumerates *combinations* within a
        cluster instead of one-member-or-none. Catches a return to
        per-cluster exclusivity, which caps the shopper's saving at 100c.
        """
        cart = Cart(items=[line("COF-ETH"), line("COF-COL")])
        promos = [
            fixed_off("B1", CategoryTarget(category="Coffee Beans")),
            fixed_off("A1", SkuTarget(sku="COF-ETH")),
            fixed_off("A2", SkuTarget(sku="COF-COL")),
        ]
        claimed = {"B1", "A1", "A2"}
        naive = price_naive(cart, promos, claimed)
        outcome = optimize(cart, promos, claimed)
        # 1600 + 1400 = 3000 subtotal, 1000 flat shipping.
        assert naive.result.total_cents == 3900  # B1 alone: -100
        assert outcome.result.total_cents == 3800  # A1 + A2: -200
        assert applied_ids(outcome.statuses) == {"A1", "A2"}
        assert outcome.statuses["B1"] is PromotionStatus.CLAIMED

    def test_star_cluster_past_the_cap_falls_back(self) -> None:
        """One category deal over ten SKU deals (2**10 + 1 outcomes) bails out.

        The blow-up the independent-set enumeration introduced: these all
        land in ONE cluster, which the old k+1 rule sized at 12. Catches
        the cap being measured before enumeration (or not at all), which
        would hang the request instead of degrading to `optimal: false`.
        """
        cart = Cart(
            items=[
                LineItem(
                    sku=f"SYN-{i}", category="Synthetic", unit_price_cents=1000, qty=1
                )
                for i in range(10)
            ]
        )
        promos = [fixed_off("HUB", CategoryTarget(category="Synthetic"))] + [
            fixed_off(f"X{i}", SkuTarget(sku=f"SYN-{i}")) for i in range(10)
        ]
        claimed = {promo.id for promo in promos}
        outcome = optimize(cart, promos, claimed)
        assert outcome == price_naive(cart, promos, claimed)
        assert outcome.result.optimal is False

    def test_huge_star_cluster_is_instant_not_exponential(self) -> None:
        """A cluster of 2**30 outcomes returns without enumerating them.

        The cap has to bound enumeration *as it runs*: counting a cluster's
        independent sets means walking them, so measuring first and
        capping after would hang here for hours. Catches `legal_outcomes`
        being called without its limit — the suite stops instead of
        finishing in milliseconds.
        """
        cart = Cart(
            items=[
                LineItem(
                    sku=f"SYN-{i}", category="Synthetic", unit_price_cents=1000, qty=1
                )
                for i in range(30)
            ]
        )
        promos = [fixed_off("HUB", CategoryTarget(category="Synthetic"))] + [
            fixed_off(f"X{i}", SkuTarget(sku=f"SYN-{i}")) for i in range(30)
        ]
        claimed = {promo.id for promo in promos}
        outcome = optimize(cart, promos, claimed)
        assert outcome == price_naive(cart, promos, claimed)
        assert outcome.result.optimal is False

    def test_trace_lists_a_phase_s_promotions_in_declaration_order(self) -> None:
        """Picks from two clusters are traced in declaration order, not cluster order.

        Clusters are ordered by their first member, so taking a late member
        of an early cluster (Z) alongside an early member of a later
        cluster (Y) emits them reversed unless the combination is sorted.
        Catches the receipt's "How your deals applied" list jumping around
        for no reason a shopper can see — and the frozen golden traces
        drifting with unrelated promotion additions.
        """
        cart = Cart(
            items=[
                LineItem(
                    sku="SKU-A", category="Synthetic", unit_price_cents=5000, qty=1
                ),
                LineItem(
                    sku="SKU-B", category="Synthetic", unit_price_cents=5000, qty=1
                ),
            ]
        )
        # X and Z share SKU-A (one cluster, first member X); Y is its own.
        promos = [
            fixed_off("X", SkuTarget(sku="SKU-A")),
            fixed_off("Y", SkuTarget(sku="SKU-B")),
            FixedOffItem(
                id="Z", name="Z", target=SkuTarget(sku="SKU-A"), amount_off_cents=300
            ),
        ]
        outcome = optimize(cart, promos, {"X", "Y", "Z"})
        # Z (300) beats X (100) on SKU-A, and Y applies on SKU-B.
        assert applied_ids(outcome.statuses) == {"Y", "Z"}
        assert [adj.promotion_id for adj in outcome.result.adjustments] == ["Y", "Z"]


def synthetic_catalog(count: int) -> tuple[Cart, list[Promotion]]:
    """`count` disjoint one-line/one-promo pairs: `count` singleton clusters.

    Each promotion targets its own SKU, so the cluster product is
    2**count — the knob the cap tests turn.

    Args:
        count: Number of lines and promotions to build.

    Returns:
        The cart and its promotion list.
    """
    cart = Cart(
        items=[
            LineItem(sku=f"SYN-{i}", category="Synthetic", unit_price_cents=1000, qty=1)
            for i in range(count)
        ]
    )
    promotions = [fixed_off(f"X{i}", SkuTarget(sku=f"SYN-{i}")) for i in range(count)]
    return cart, promotions


class TestClusterProductCap:
    """docs/optimizer-spec.md's fallback for pathological catalogs."""

    def test_over_cap_falls_back_to_naive_with_optimal_false(self) -> None:
        """Ten singleton clusters (2^10 = 1024 > 512) skip the search.

        Catches the cap being ignored: a real search over these clusters
        would return `optimal: True`, so the exact-naive-outcome assert
        fails fast (1024 combos price in well under a second) instead of
        hanging.
        """
        cart, promotions = synthetic_catalog(10)
        claimed = {promo.id for promo in promotions}
        outcome = optimize(cart, promotions, claimed)
        assert outcome == price_naive(cart, promotions, claimed)
        assert outcome.result.optimal is False

    def test_far_over_cap_is_instant_not_exponential(self) -> None:
        """Forty singleton clusters (2^40 combos) return without searching.

        The no-search-explosion guarantee: with the cap working this is
        instant; enumerating 2^40 combinations would effectively hang the
        suite. Catches the fallback merely labeling the result while still
        enumerating.
        """
        cart, promotions = synthetic_catalog(40)
        claimed = {promo.id for promo in promotions}
        outcome = optimize(cart, promotions, claimed)
        assert outcome == price_naive(cart, promotions, claimed)
        assert outcome.result.optimal is False

    def test_raising_the_cap_restores_the_search(self) -> None:
        """The same ten clusters search fine under a 1024 cap.

        The control proving the cap (not the catalog shape) triggers the
        fallback. All ten disjoint 100c-off promos apply — withholding any
        one costs 100c — so the optimum matches naive's totals but is
        labeled optimal.
        """
        cart, promotions = synthetic_catalog(10)
        claimed = {promo.id for promo in promotions}
        config = EngineConfig(cluster_product_cap=1024)
        outcome = optimize(cart, promotions, claimed, config)
        naive = price_naive(cart, promotions, claimed, config)
        assert outcome.result.optimal is True
        assert outcome.result.total_cents == naive.result.total_cents == 10000
        assert applied_ids(outcome.statuses) == claimed
