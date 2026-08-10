# Availability suite: the "why" layer behind promotion_statuses (app/
# eligibility.py). The checkout renders three visually distinct states from
# it — applied, qualifies-but-beaten, does-not-qualify-with-a-shortfall — and
# a wrong answer here is a shopper being told they cannot have a deal they
# qualify for, or being sent to add $12 of beans that would not help. The
# unit cases pin the three states on hand-derived carts; the property suite
# pins the cross-cutting rules against random carts.

from typing import Any

from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain import Cart, LineItem
from app.eligibility import describe_availability
from app.engine import price_naive
from app.main import app as fastapi_app
from app.optimizer import optimize
from app.seeds import load_seed_promotions

client = TestClient(fastapi_app)

SEED_PROMOTIONS = load_seed_promotions()
SEED_IDS = [promo.id for promo in SEED_PROMOTIONS]
BY_ID = {promo.id: promo for promo in SEED_PROMOTIONS}


def bean(sku: str, price: int, qty: int) -> LineItem:
    """A Coffee Beans line, the category P1 and P6 both target."""
    return LineItem(sku=sku, category="Coffee Beans", unit_price_cents=price, qty=qty)


def gear(sku: str, price: int, qty: int = 1) -> LineItem:
    """A Brew Gear line, matched by no category promotion in the seed set."""
    return LineItem(sku=sku, category="Brew Gear", unit_price_cents=price, qty=qty)


def availability_for(cart: Cart, claimed: list[str]) -> dict[str, Any]:
    """Price a cart through the API and return its availability map."""
    response = client.post(
        "/price",
        json={
            "cart": cart.model_dump(mode="json"),
            "claimed_promotion_ids": claimed,
        },
    )
    assert response.status_code == 200
    return response.json()["promotion_availability"]


class TestThreeStates:
    """The three states the checkout must be able to tell apart."""

    def test_beaten_rival_stays_eligible_with_no_gap(self) -> None:
        """P1 loses its slot to P6 but still reads as qualifying.

        The state `promotion_statuses` cannot express: P1 is "claimed" there
        whether it was beaten or never qualified. If this regresses, the
        checkout greys out a deal the shopper could still switch to, and the
        pin control silently disappears.
        """
        cart = Cart(items=[bean("COF-ETH", 1600, 6)])
        availability = availability_for(cart, ["P1", "P6"])
        assert availability["P1"] == {
            "eligible": True,
            "gap": None,
            "conflicts_with": ["P6"],
        }

    def test_unqualified_deal_reports_the_distance_to_qualifying(self) -> None:
        """A $30 cart is 3 bags short of P1 and $20 short of P2.

        Catches the two shortfall shapes being confused or dropped — the
        grey card would then say "does not qualify" with nothing actionable,
        which is the exact dead end this feature exists to remove.
        """
        cart = Cart(items=[gear("BREW-GRD", 3000)])
        availability = availability_for(cart, SEED_IDS)
        assert availability["P1"]["eligible"] is False
        assert availability["P1"]["gap"] == {
            "subtotal_short_cents": None,
            "qty_short": 3,
        }
        assert availability["P2"]["eligible"] is False
        assert availability["P2"]["gap"] == {
            "subtotal_short_cents": 2000,
            "qty_short": None,
        }

    def test_shortfall_is_measured_after_upstream_deals_land(self) -> None:
        """A $110 cart is short of free shipping once its deals land.

        The decision this whole module turns on: eligibility is judged
        against the cascade state, not the submitted cart. Reading the raw
        $110 subtotal would show free shipping as qualifying while it
        silently never applies — the failure mode that made the old UI
        confusing. Both upstream phases move the bar, and the shipping
        threshold sees the end of that chain:
          subtotal            5 x 2200 = 11000
          item  (bean deal)   -2200            ->  8800
          cart  (15% of 8800) -1320            ->  7480
          shipping needs 10000, so P7 is 2520 short
        """
        cart = Cart(items=[bean("COF-ETH", 2200, 5)])
        availability = availability_for(cart, SEED_IDS)
        assert availability["P7"]["eligible"] is False
        assert availability["P7"]["gap"] == {
            "subtotal_short_cents": 2520,
            "qty_short": None,
        }

    def test_conflicts_depend_on_the_cart_not_the_promotion_pair(self) -> None:
        """P1 and P6 collide on a beans cart and not on a gear cart.

        Exclusivity is derived from targets overlapping *on this cart*
        (app/promotions.py). Catches conflicts being precomputed from
        promotion metadata, which would make the checkout untoggle an
        unrelated deal on carts where the two never actually compete.
        """
        beans_only = availability_for(Cart(items=[bean("COF-ETH", 1600, 3)]), SEED_IDS)
        gear_only = availability_for(Cart(items=[gear("BREW-GRD", 4500, 3)]), SEED_IDS)
        assert beans_only["P1"]["conflicts_with"] == ["P6"]
        assert gear_only["P1"]["conflicts_with"] == []
        # The cart-phase pair shares one subtotal, so it collides regardless.
        assert gear_only["P2"]["conflicts_with"] == ["P5"]


class TestAvailabilityProperties:
    """Cross-cutting rules, over random carts and claim sets."""

    carts = st.builds(
        Cart,
        items=st.lists(
            st.builds(
                LineItem,
                sku=st.sampled_from(["COF-ETH", "COF-COL", "BREW-V60", "MUG-CLS"]),
                category=st.sampled_from(["Coffee Beans", "Brew Gear", "Drinkware"]),
                unit_price_cents=st.integers(0, 40_000),
                qty=st.integers(1, 12),
            ),
            min_size=1,
            max_size=4,
            unique_by=lambda item: item.sku,
        ),
    )
    claims = st.sets(st.sampled_from(SEED_IDS))

    @settings(deadline=None)
    @given(cart=carts, claimed=claims)
    def test_everything_applied_is_reported_eligible(
        self, cart: Cart, claimed: set[str]
    ) -> None:
        """A promotion that actually discounted the cart must read eligible.

        The one contradiction that would make the UI incoherent: a deal
        shown greyed-out as "does not qualify" while its saving sits on the
        receipt above it. Runs against both engines, since either can be the
        one whose result is explained.
        """
        for outcome in (
            price_naive(cart, SEED_PROMOTIONS, claimed),
            optimize(cart, SEED_PROMOTIONS, claimed),
        ):
            availability = describe_availability(cart, SEED_PROMOTIONS, outcome.result)
            for adjustment in outcome.result.adjustments:
                assert availability[adjustment.promotion_id].eligible

    @settings(deadline=None)
    @given(cart=carts, claimed=claims)
    def test_eligible_promotions_never_carry_a_gap(
        self, cart: Cart, claimed: set[str]
    ) -> None:
        """Qualifying and "add $X to qualify" are mutually exclusive.

        Catches a gap leaking onto a live card, which would render as a
        deal that both qualifies and tells the shopper to spend more.
        """
        outcome = optimize(cart, SEED_PROMOTIONS, claimed)
        for entry in describe_availability(
            cart, SEED_PROMOTIONS, outcome.result
        ).values():
            assert not (entry.eligible and entry.gap is not None)

    @settings(deadline=None)
    @given(cart=carts, claimed=claims)
    def test_conflicts_are_symmetric_and_never_self_referential(
        self, cart: Cart, claimed: set[str]
    ) -> None:
        """If A blocks B then B blocks A, and nothing blocks itself.

        The checkout untoggles rivals by reading this list. An asymmetry
        would make pinning A drop B while pinning B leaves A on — two
        conflicting deals shown applied at once, contradicting the receipt.
        A self-reference would make a card untoggle itself on every click.
        """
        outcome = optimize(cart, SEED_PROMOTIONS, claimed)
        availability = describe_availability(cart, SEED_PROMOTIONS, outcome.result)
        for promo_id, entry in availability.items():
            assert promo_id not in entry.conflicts_with
            for other in entry.conflicts_with:
                assert promo_id in availability[other].conflicts_with

    @settings(deadline=None)
    @given(cart=carts, claimed=claims)
    def test_conflicting_promotions_are_never_both_applied(
        self, cart: Cart, claimed: set[str]
    ) -> None:
        """The conflict list agrees with what the engine actually allowed.

        Ties the advertised exclusivity to reality: if the engine can apply
        two deals the UI calls mutually exclusive, the UI's untoggling is
        lying and costs the shopper a discount they were entitled to stack.
        """
        outcome = optimize(cart, SEED_PROMOTIONS, claimed)
        availability = describe_availability(cart, SEED_PROMOTIONS, outcome.result)
        applied = {adj.promotion_id for adj in outcome.result.adjustments}
        for promo_id in applied:
            assert not (set(availability[promo_id].conflicts_with) & applied)


class TestGapsClose:
    """A reported shortfall must be the amount that actually unlocks the deal."""

    def test_adding_the_reported_subtotal_gap_qualifies_the_promotion(self) -> None:
        """Spending exactly the advertised shortfall flips P5 to eligible.

        The promise the hint makes. Catches an off-by-one (or off-by-a-
        cent) gap that sends a shopper to add $47.99 for a $48.00 threshold
        and leaves the deal still greyed out at checkout.
        """
        cart = Cart(items=[gear("BREW-GRD", 6000)])
        gap = availability_for(cart, SEED_IDS)["P5"]["gap"]
        short = gap["subtotal_short_cents"]
        assert short == 4000
        topped_up = Cart(items=[gear("BREW-GRD", 6000 + short)])
        assert availability_for(topped_up, SEED_IDS)["P5"]["eligible"] is True

    def test_adding_the_reported_qty_gap_qualifies_the_promotion(self) -> None:
        """Adding the advertised number of units flips P1 to eligible.

        The quantity-shaped twin of the case above — a wrong count here
        tells a shopper to add one bag when the deal needs two.
        """
        cart = Cart(items=[bean("COF-ETH", 1600, 1)])
        gap = availability_for(cart, SEED_IDS)["P1"]["gap"]
        short = gap["qty_short"]
        assert short == 2
        topped_up = Cart(items=[bean("COF-ETH", 1600, 1 + short)])
        assert availability_for(topped_up, SEED_IDS)["P1"]["eligible"] is True
