from typing import ClassVar

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.clusters import derive_clusters
from app.domain import (
    Adjustment,
    Cart,
    LineAllocation,
    LineItem,
    Phase,
    PhaseSubtotals,
)
from app.engine import (
    EngineConfig,
    EngineInvariantError,
    PromotionStatus,
    price_combination,
    price_naive,
)
from app.promotions import Promotion
from app.seeds import load_seed_catalog, load_seed_promotions

CATALOG = {item.sku: item for item in load_seed_catalog()}
SEED_PROMOTIONS = load_seed_promotions()
SEED_IDS = [promo.id for promo in SEED_PROMOTIONS]
BY_ID = {promo.id: promo for promo in SEED_PROMOTIONS}


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


def golden_cart() -> Cart:
    """Beans x3 (two SKUs) + dripper: subtotal 7500, hits P1+P4+P2."""
    return Cart(items=[line("COF-ETH", qty=2), line("COF-DEC"), line("BREW-V60")])


class TestGoldenCascade:
    """Hand-computed full cascades, exact to the cent."""

    def test_beans_and_dripper_cart_through_p1_p4_p2(self) -> None:
        """7500c cart: P1 frees the 1500c bean, P4 takes 500, P2 takes 15%.

        The end-to-end receipt a shopper sees. Catches any drift in the
        cascade math: P2 must be 15% of the *post-Item* 5500 (825c, split
        480/345 across the still-priced lines), never of the original 7500,
        and P7 must not fire on a 4675c post-Cart subtotal.
        """
        outcome = price_naive(golden_cart(), SEED_PROMOTIONS, set(SEED_IDS))
        result = outcome.result
        assert result.adjustments == [
            Adjustment(
                promotion_id="P1",
                promotion_name="Beans: buy 2 get 1 free",
                phase=Phase.ITEM,
                amount_cents=1500,
                line_allocations=[LineAllocation(sku="COF-DEC", amount_cents=1500)],
            ),
            Adjustment(
                promotion_id="P4",
                promotion_name="$5 off pour-over dripper",
                phase=Phase.ITEM,
                amount_cents=500,
                line_allocations=[LineAllocation(sku="BREW-V60", amount_cents=500)],
            ),
            Adjustment(
                promotion_id="P2",
                promotion_name="15% off $50+",
                phase=Phase.CART,
                amount_cents=825,
                line_allocations=[
                    LineAllocation(sku="COF-ETH", amount_cents=480),
                    LineAllocation(sku="BREW-V60", amount_cents=345),
                ],
            ),
        ]
        assert [
            (li.sku, li.discount_cents, li.line_total_cents) for li in result.lines
        ] == [("COF-ETH", 480, 2720), ("COF-DEC", 1500, 0), ("BREW-V60", 845, 1955)]
        assert result.subtotal_cents == 7500
        assert result.discount_total_cents == 2825
        assert result.shipping_cents == 1000
        assert result.total_cents == 5675

    def test_phase_subtotals_trace_the_cascade_boundaries(self) -> None:
        """Catches the deals explainer narrating wrong intermediate numbers.

        The checkout's "how deals work" walkthrough renders after-item and
        after-cart subtotals verbatim; if the cascade stops recording them
        (or records pre-discount values), the UI would tell shoppers a
        cart percent was taken off the wrong base.
        """
        outcome = price_naive(golden_cart(), SEED_PROMOTIONS, set(SEED_IDS))
        # 7500 - (1500 P1 + 500 P4) = 5500; 5500 - 825 P2 = 4675.
        assert outcome.result.phase_subtotals == PhaseSubtotals(
            after_item_cents=5500, after_cart_cents=4675
        )

    def test_statuses_report_applied_claimed_and_available(self) -> None:
        """On the golden cart, every status lands per the spec's table.

        Catches the API-facing status model lying: P6/P5 lose their cluster
        to P1/P2 but stay claimed (not silently dropped to available), P7 is
        claimed-but-ineligible with no error, and nothing unclaimed applies.
        """
        outcome = price_naive(golden_cart(), SEED_PROMOTIONS, set(SEED_IDS))
        assert outcome.statuses == {
            "P1": PromotionStatus.APPLIED,
            "P6": PromotionStatus.CLAIMED,
            "P4": PromotionStatus.APPLIED,
            "P2": PromotionStatus.APPLIED,
            "P5": PromotionStatus.CLAIMED,
            "P7": PromotionStatus.CLAIMED,
        }

    def test_free_shipping_zeroes_the_baseline(self) -> None:
        """A 13500c cart with P7 claimed ships free; the trace shows 1000c.

        Catches shipping being waived without an explanation-trace entry
        (the receipt would not add up) or the waived amount differing from
        the charge actually dropped.
        """
        outcome = price_naive(
            Cart(items=[line("BREW-GRD", qty=3)]), SEED_PROMOTIONS, {"P7"}
        )
        result = outcome.result
        assert result.adjustments == [
            Adjustment(
                promotion_id="P7",
                promotion_name="Free shipping $100+",
                phase=Phase.SHIPPING,
                amount_cents=1000,
            )
        ]
        assert result.shipping_cents == 0
        assert result.total_cents == 13500
        assert outcome.statuses["P7"] is PromotionStatus.APPLIED

    def test_configured_baseline_is_injected_into_free_shipping(self) -> None:
        """With a 2500c configured baseline, P7 waives exactly 2500c.

        Catches the engine applying the promotion's seeded default (1000c)
        instead of injecting its own config — shipping would go negative or
        the trace would understate the waiver whenever config changes.
        """
        cart = Cart(items=[line("BREW-GRD", qty=3)])
        config = EngineConfig(shipping_baseline_cents=2500)
        with_p7 = price_naive(cart, SEED_PROMOTIONS, {"P7"}, config).result
        assert with_p7.adjustments[0].amount_cents == 2500
        assert (with_p7.shipping_cents, with_p7.total_cents) == (0, 13500)
        without = price_naive(cart, SEED_PROMOTIONS, set(), config).result
        assert (without.shipping_cents, without.total_cents) == (2500, 16000)


class TestPostPhaseEligibility:
    """Each phase's conditions read the previous phase's output state."""

    def test_item_discount_drops_cart_below_the_p2_threshold(self) -> None:
        """P4 knocks a 5000c cart to 4500c, so claimed P2 does not apply.

        The naive engine's defining trade-off (docs/core-engine-spec.md: no
        backtracking). Catches checking P2 against the original subtotal —
        a shopper would get 15% off a threshold the cart no longer meets.
        """
        cart = Cart(items=[line("BREW-V60"), line("MUG-TVL")])
        outcome = price_naive(cart, SEED_PROMOTIONS, {"P4", "P2"})
        assert [adj.promotion_id for adj in outcome.result.adjustments] == ["P4"]
        assert outcome.statuses["P2"] is PromotionStatus.CLAIMED
        assert outcome.result.total_cents == 5500  # 5000 - 500 + 1000 shipping

    def test_same_cart_without_p4_keeps_p2(self) -> None:
        """Claiming only P2 on the 5000c cart applies it at the threshold.

        The control for the case above: catches the threshold itself being
        off by one (>= vs >) — at exactly 5000c the deal is promised.
        """
        cart = Cart(items=[line("BREW-V60"), line("MUG-TVL")])
        outcome = price_naive(cart, SEED_PROMOTIONS, {"P2"})
        assert [adj.promotion_id for adj in outcome.result.adjustments] == ["P2"]
        assert outcome.result.total_cents == 5250  # 5000 - 750 + 1000 shipping

    def test_cart_discount_drops_subtotal_below_free_shipping(self) -> None:
        """P5 pulls 11200c down to 8960c, so claimed P7 stays unapplied.

        Catches P7 reading the pre-Cart-phase subtotal — the shopper would
        get free shipping on a threshold the discounted cart misses
        (docs/optimizer-spec.md names this exact interaction).
        """
        cart = Cart(items=[line("BREW-GRD", qty=2), line("MUG-TVL")])
        outcome = price_naive(cart, SEED_PROMOTIONS, {"P5", "P7"})
        assert [adj.promotion_id for adj in outcome.result.adjustments] == ["P5"]
        assert outcome.statuses["P7"] is PromotionStatus.CLAIMED
        assert outcome.result.shipping_cents == 1000
        assert outcome.result.total_cents == 9960  # 11200 - 2240 + 1000


class TestDeclarationOrder:
    """First eligible in declaration order wins a cluster — never 'best'."""

    def test_p1_beats_p6_even_when_p6_would_save_more(self) -> None:
        """On 6x Ethiopia, P1 (1600c) applies though P6 would take 1920c.

        The naive engine's contract (docs/core-engine-spec.md): seed order,
        no ranking. Catches 'helpfully' picking the bigger discount — that
        is the optimizer's job (#25), and doing it here would make the two
        engines indistinguishable as test oracles for each other.
        """
        cart = Cart(items=[line("COF-ETH", qty=6)])
        outcome = price_naive(cart, SEED_PROMOTIONS, {"P1", "P6"})
        assert [adj.promotion_id for adj in outcome.result.adjustments] == ["P1"]
        assert outcome.result.discount_total_cents == 1600
        assert outcome.statuses["P6"] is PromotionStatus.CLAIMED

    def test_claiming_only_the_later_promotion_applies_it(self) -> None:
        """With P1 unclaimed, P6 is its cluster's first eligible member.

        Catches declaration order being applied over the full seed list
        instead of per cluster's claimed members — deselecting P1 must
        hand the cluster to P6, not to nothing.
        """
        cart = Cart(items=[line("COF-ETH", qty=6)])
        outcome = price_naive(cart, SEED_PROMOTIONS, {"P6"})
        assert [adj.promotion_id for adj in outcome.result.adjustments] == ["P6"]
        assert outcome.result.discount_total_cents == 1920


class TestStatusModel:
    """Available/claimed/applied per docs/core-engine-spec.md."""

    def test_claimed_but_ineligible_stays_claimed_without_error(self) -> None:
        """P5 claimed on a 1200c cart: no discount, no error, still claimed.

        Catches toggling being treated as a forced application or a request
        error — the spec says a claimed promotion simply waits, unapplied.
        """
        outcome = price_naive(Cart(items=[line("MUG-CLS")]), SEED_PROMOTIONS, {"P5"})
        assert outcome.result.adjustments == []
        assert outcome.result.total_cents == 2200
        assert outcome.statuses["P5"] is PromotionStatus.CLAIMED

    def test_eligible_but_unclaimed_is_never_applied(self) -> None:
        """A cart qualifying for P1 gets nothing while P1 is unclaimed.

        Catches the engine searching over available promotions — only
        claimed ones are candidates, so an untoggled deal must never
        change the price.
        """
        cart = Cart(items=[line("COF-ETH", qty=3)])
        outcome = price_naive(cart, SEED_PROMOTIONS, set())
        assert outcome.result.adjustments == []
        assert outcome.result.total_cents == 5800
        assert outcome.statuses["P1"] is PromotionStatus.AVAILABLE

    def test_unknown_claimed_id_fails_loud(self) -> None:
        """Claiming an id that no promotion carries raises, never ignores.

        Catches a frontend/backend id drift silently pricing carts as if
        the shopper had toggled nothing.
        """
        with pytest.raises(ValueError, match="P99"):
            price_naive(Cart(items=[line("MUG-CLS")]), SEED_PROMOTIONS, {"P99"})

    def test_duplicate_promotion_ids_fail_loud(self) -> None:
        """A promotion list repeating an id raises before pricing.

        Catches a doubled seed entry making 'applied' ambiguous — statuses
        are keyed by id.
        """
        with pytest.raises(ValueError, match="unique ids"):
            price_naive(
                Cart(items=[line("MUG-CLS")]), [BY_ID["P4"], BY_ID["P4"]], set()
            )


class TestPriceCombination:
    """The reusable cascade core the optimizer (#25) calls directly."""

    def test_prices_the_non_default_cluster_outcome(self) -> None:
        """Passing [P6] applies P6 — the outcome naive would never pick.

        The optimizer's whole reason to exist: it must be able to price any
        legal cluster outcome, not just the naive first-eligible one, and
        get identical arithmetic from the same cascade.
        """
        cart = Cart(items=[line("COF-ETH", qty=6)])
        result = price_combination(cart, [BY_ID["P6"]])
        assert [adj.promotion_id for adj in result.adjustments] == ["P6"]
        assert result.total_cents == 8680  # 9600 - 1920 + 1000 shipping

    def test_ineligible_member_is_skipped_without_error(self) -> None:
        """A combination whose P2 loses eligibility mid-cascade still prices.

        Catches the core raising on enumerated combinations (the optimizer
        legitimately proposes P4+P2 even though P4 kills P2's threshold) —
        it must price as P4-only, matching the naive engine on this cart.
        """
        cart = Cart(items=[line("BREW-V60"), line("MUG-TVL")])
        combination = [BY_ID["P4"], BY_ID["P2"]]
        result = price_combination(cart, combination)
        assert [adj.promotion_id for adj in result.adjustments] == ["P4"]
        assert result == price_naive(cart, SEED_PROMOTIONS, {"P4", "P2"}).result

    def test_two_same_cluster_promotions_are_rejected(self) -> None:
        """Passing P1 and P6 together raises EngineInvariantError.

        The no-double-application guard: catches an optimizer bug (or any
        future caller) stacking two bean deals on the same lines and
        undercharging every bulk-bean cart.
        """
        cart = Cart(items=[line("COF-ETH", qty=3)])
        with pytest.raises(EngineInvariantError, match="P1, P6"):
            price_combination(cart, [BY_ID["P1"], BY_ID["P6"]])

    def test_over_discounting_kind_is_caught_by_the_engine_guard(self) -> None:
        """A kind allocating more than a line's value raises, never clamps.

        The engine-level invariant the domain model cannot see until
        assembly: catches a buggy future promotion kind driving a line
        negative — the guard names the promotion instead of clamping or
        failing later with an opaque validation error.
        """

        class OverAllocatingPromo(Promotion):
            """Test-only kind that discounts one cent more than the line."""

            phase: ClassVar[Phase] = Phase.ITEM

            def is_eligible(self, cart: Cart) -> bool:
                """Always eligible.

                Args:
                    cart: Ignored.

                Returns:
                    True.
                """
                return True

            def apply(self, cart: Cart) -> Adjustment:
                """Allocate one cent more than the first line is worth.

                Args:
                    cart: The cascade state to over-discount.

                Returns:
                    An adjustment exceeding the first line's value.
                """
                item = cart.items[0]
                amount = item.line_subtotal_cents + 1
                return Adjustment(
                    promotion_id=self.id,
                    promotion_name=self.name,
                    phase=self.phase,
                    amount_cents=amount,
                    line_allocations=[
                        LineAllocation(sku=item.sku, amount_cents=amount)
                    ],
                )

        evil = OverAllocatingPromo(id="EVIL", name="Evil", target=BY_ID["P4"].target)
        with pytest.raises(EngineInvariantError, match="below zero"):
            price_combination(Cart(items=[line("MUG-CLS")]), [evil])


@st.composite
def seeded_carts(draw: st.DrawFn) -> Cart:
    """A cart of 1-8 distinct catalog SKUs, each at quantity 1-6."""
    skus = draw(
        st.lists(st.sampled_from(sorted(CATALOG)), min_size=1, max_size=8, unique=True)
    )
    return Cart(items=[line(sku, qty=draw(st.integers(1, 6))) for sku in skus])


class TestInvariantsProperty:
    """docs/testing-strategy.md's property layer for the naive engine."""

    @given(
        cart=seeded_carts(),
        claimed=st.sets(st.sampled_from(SEED_IDS)),
    )
    def test_every_result_holds_the_core_invariants(
        self, cart: Cart, claimed: set[str]
    ) -> None:
        """Random carts x claimed subsets: totals tie out, legality holds.

        Catches any cart shape where the cascade produces a receipt that
        does not add up (the PricingResult validators re-run on every
        construction), applies an unclaimed promotion, stacks two members
        of one cluster, or disagrees with the reusable core when handed
        its own applied set — the exact parity #25 relies on to trust
        `price_combination` as the single pricing path.
        """
        outcome = price_naive(cart, SEED_PROMOTIONS, claimed)
        result = outcome.result
        assert result.total_cents >= 0
        applied = {
            promo_id
            for promo_id, status in outcome.statuses.items()
            if status is PromotionStatus.APPLIED
        }
        assert applied <= claimed
        assert applied == {adj.promotion_id for adj in result.adjustments}
        claimed_promos = [promo for promo in SEED_PROMOTIONS if promo.id in claimed]
        for cluster in derive_clusters(cart, claimed_promos).all_clusters():
            in_cluster = sum(1 for promo in cluster.promotions if promo.id in applied)
            assert in_cluster <= 1
        applied_promos = [promo for promo in SEED_PROMOTIONS if promo.id in applied]
        assert price_combination(cart, applied_promos) == result
        # Determinism: repricing the identical request changes nothing.
        assert price_naive(cart, SEED_PROMOTIONS, claimed) == outcome
