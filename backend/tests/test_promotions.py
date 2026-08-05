import json
from pathlib import Path
from typing import ClassVar

import pytest
from pydantic import BaseModel

# Imported for its side effect: registers the five seeded kinds.
import app.promotion_kinds  # noqa: F401  # pyright: ignore[reportUnusedImport]
from app.domain import Adjustment, Cart, LineAllocation, LineItem, Phase
from app.promotions import (
    PROMOTION_REGISTRY,
    CartTarget,
    CategoryTarget,
    Promotion,
    ShippingTarget,
    SkuTarget,
    register_promotion,
    targets_can_overlap,
)
from app.seed_loader import SeedLoadError, load_promotions, parse_promotions

DUMMY_TYPE = "TEST_FLAT_OFF_CATEGORY"


@register_promotion(DUMMY_TYPE)
class FlatOffCategoryDummy(Promotion):
    """Test-only kind: flat cents off the cheapest line the target matches.

    Registered from this test module — deliberately NOT shipped in app/ — to
    prove the contained-change property: the seed loader and the generic
    contract below pick it up with zero edits outside this file. The real
    seeded kinds are a separate task (#20).
    """

    phase: ClassVar[Phase] = Phase.ITEM

    min_qty: int
    discount_cents: int

    def _matching_items(self, cart: Cart) -> list[LineItem]:
        """Cart lines matched by this promotion's line-scoped target."""
        target = self.target
        if not isinstance(target, SkuTarget | CategoryTarget):
            raise TypeError("dummy kind is only ever seeded with a line target")
        return [item for item in cart.items if target.matches_line(item)]

    def is_eligible(self, cart: Cart) -> bool:
        """Whether the matched lines carry at least `min_qty` units.

        Args:
            cart: Phase-cascade state to check the condition against.

        Returns:
            True if total matched quantity is at or above `min_qty`.
        """
        return sum(item.qty for item in self._matching_items(cart)) >= self.min_qty

    def apply(self, cart: Cart) -> Adjustment:
        """Discount the cheapest matched line by `discount_cents`, capped.

        Deterministic: the cheapest line ties break by SKU, and the discount
        is capped at that line's subtotal so the adjustment can never exceed
        the line.

        Args:
            cart: Eligible phase-cascade state; never mutated.

        Returns:
            A single-line adjustment for the capped discount.
        """
        cheapest = min(
            self._matching_items(cart),
            key=lambda item: (item.unit_price_cents, item.sku),
        )
        amount = min(self.discount_cents, cheapest.line_subtotal_cents)
        return Adjustment(
            promotion_id=self.id,
            promotion_name=self.name,
            phase=self.phase,
            amount_cents=amount,
            line_allocations=[LineAllocation(sku=cheapest.sku, amount_cents=amount)],
        )


def make_line_item(**overrides: object) -> LineItem:
    """Build a valid LineItem, applying keyword overrides."""
    fields: dict[str, object] = {
        "sku": "COF-ETH",
        "name": "Ethiopia Yirgacheffe, 12oz",
        "category": "Coffee Beans",
        "unit_price_cents": 1600,
        "qty": 1,
    }
    fields.update(overrides)
    return LineItem.model_validate(fields)


class KindContractFixture(BaseModel):
    """Per-kind inputs for the generic contract tests below."""

    seed_entry: dict[str, object]
    eligible_cart: Cart
    ineligible_cart: Cart


# One fixture per registered kind. A new kind (#20's five real ones included)
# adds one entry here and inherits every generic contract test for free.
CONTRACT_FIXTURES: dict[str, KindContractFixture] = {
    DUMMY_TYPE: KindContractFixture(
        seed_entry={
            "type": DUMMY_TYPE,
            "id": "T1",
            "name": "Test: flat off beans",
            "target": {"kind": "category", "category": "Coffee Beans"},
            "min_qty": 2,
            "discount_cents": 300,
        },
        # Boundary pair: exactly at min_qty vs. one unit below it.
        eligible_cart=Cart(items=[make_line_item(qty=2)]),
        ineligible_cart=Cart(items=[make_line_item(qty=1)]),
    ),
    "BXGY": KindContractFixture(
        seed_entry={
            "type": "BXGY",
            "id": "P1",
            "name": "Coffee Beans: buy 2 get 1 free",
            "target": {"kind": "category", "category": "Coffee Beans"},
            "min_qty": 3,
        },
        # Boundary pair: qty 3 (summed across two bean lines) vs. qty 2.
        eligible_cart=Cart(
            items=[
                make_line_item(qty=2),
                make_line_item(sku="COF-COL", unit_price_cents=1400),
            ]
        ),
        ineligible_cart=Cart(items=[make_line_item(qty=2)]),
    ),
    "PCT_OFF_ITEM": KindContractFixture(
        seed_entry={
            "type": "PCT_OFF_ITEM",
            "id": "P6",
            "name": "Coffee Beans: 20% off (min 3)",
            "target": {"kind": "category", "category": "Coffee Beans"},
            "min_qty": 3,
            "percent_off": 20,
        },
        # Boundary pair: exactly at min_qty vs. one unit below it.
        eligible_cart=Cart(items=[make_line_item(qty=3)]),
        ineligible_cart=Cart(items=[make_line_item(qty=2)]),
    ),
    "FIXED_OFF_ITEM": KindContractFixture(
        seed_entry={
            "type": "FIXED_OFF_ITEM",
            "id": "P4",
            "name": "$5.00 off Ceramic Pour-Over Dripper",
            "target": {"kind": "sku", "sku": "BREW-V60"},
            "amount_off_cents": 500,
        },
        # No authored condition: the boundary is target presence vs. absence.
        eligible_cart=Cart(
            items=[
                make_line_item(
                    sku="BREW-V60", category="Brew Gear", unit_price_cents=2800
                )
            ]
        ),
        ineligible_cart=Cart(
            items=[
                make_line_item(
                    sku="MUG-CLS", category="Drinkware", unit_price_cents=1200
                )
            ]
        ),
    ),
    "PCT_OFF_CART": KindContractFixture(
        seed_entry={
            "type": "PCT_OFF_CART",
            "id": "P2",
            "name": "15% off $50.00+",
            "target": {"kind": "cart"},
            "min_subtotal_cents": 5000,
            "percent_off": 15,
        },
        # Boundary pair: subtotal exactly 5000 vs. 4999 cents.
        eligible_cart=Cart(items=[make_line_item(unit_price_cents=2500, qty=2)]),
        ineligible_cart=Cart(items=[make_line_item(unit_price_cents=4999)]),
    ),
    "FREE_SHIPPING": KindContractFixture(
        seed_entry={
            "type": "FREE_SHIPPING",
            "id": "P7",
            "name": "Free shipping $100.00+",
            "target": {"kind": "shipping"},
            "min_subtotal_cents": 10000,
        },
        # Boundary pair: subtotal exactly 10000 vs. 9999 cents.
        eligible_cart=Cart(items=[make_line_item(unit_price_cents=2500, qty=4)]),
        ineligible_cart=Cart(items=[make_line_item(unit_price_cents=9999)]),
    ),
}


def parse_fixture_promotion(type_key: str) -> Promotion:
    """Round-trip one kind's fixture seed entry through the loader."""
    (promotion,) = parse_promotions([CONTRACT_FIXTURES[type_key].seed_entry])
    return promotion


class TestGenericPromotionContract:
    """The per-kind contract the engine and optimizer rely on uniformly.

    Parametrized across every entry in PROMOTION_REGISTRY (spec's "Test
    contract" section) — a new registered kind gets this coverage for free.
    """

    def test_every_registered_kind_has_contract_fixtures(self) -> None:
        """Every registered kind has a fixture; every fixture has a kind.

        Catches a new kind registering without contract coverage — it would
        otherwise silently skip the eligibility/purity guarantees the
        stacking engine assumes hold for every kind.
        """
        assert set(CONTRACT_FIXTURES) == set(PROMOTION_REGISTRY)

    @pytest.mark.parametrize("type_key", sorted(PROMOTION_REGISTRY))
    def test_seed_entry_round_trips_through_loader(self, type_key: str) -> None:
        """A seed entry comes back as the registered class, fields intact.

        Catches the loader mapping a `type` key to the wrong class or
        dropping kind-specific config — the promotion would then price with
        defaults the seed author never wrote.
        """
        promotion = parse_fixture_promotion(type_key)
        assert type(promotion) is PROMOTION_REGISTRY[type_key]
        for field, expected in CONTRACT_FIXTURES[type_key].seed_entry.items():
            if field == "type":
                continue
            actual = getattr(promotion, field)
            if isinstance(actual, BaseModel):
                actual = actual.model_dump()
            assert actual == expected, f"seed field {field!r} did not round-trip"

    @pytest.mark.parametrize("type_key", sorted(PROMOTION_REGISTRY))
    def test_phase_is_a_classvar_not_a_field(self, type_key: str) -> None:
        """`phase` is a class-level property of the kind, not a seed field.

        Catches `phase` becoming authorable per instance — a seed file could
        then move a kind into the wrong phase and silently break the
        Item -> Cart -> Shipping cascade's determinism.
        """
        cls = PROMOTION_REGISTRY[type_key]
        assert "phase" not in cls.model_fields
        assert isinstance(cls.phase, Phase)

    @pytest.mark.parametrize("type_key", sorted(PROMOTION_REGISTRY))
    def test_is_eligible_boundary(self, type_key: str) -> None:
        """`is_eligible` flips exactly at the kind's condition boundary.

        Catches an off-by-one condition (>= vs >) — a shopper exactly at a
        threshold would be denied a promotion the seed table promises them,
        or granted one just below it.
        """
        promotion = parse_fixture_promotion(type_key)
        fixture = CONTRACT_FIXTURES[type_key]
        assert not promotion.is_eligible(fixture.ineligible_cart)
        assert promotion.is_eligible(fixture.eligible_cart)

    @pytest.mark.parametrize("type_key", sorted(PROMOTION_REGISTRY))
    def test_is_eligible_is_pure(self, type_key: str) -> None:
        """`is_eligible` does not mutate the cart and repeats its answer.

        Catches an eligibility check corrupting the cascade state it was
        handed — every later phase would then price a cart the shopper
        doesn't have.
        """
        promotion = parse_fixture_promotion(type_key)
        cart = CONTRACT_FIXTURES[type_key].eligible_cart
        before = cart.model_dump()
        assert promotion.is_eligible(cart) == promotion.is_eligible(cart)
        assert cart.model_dump() == before

    @pytest.mark.parametrize("type_key", sorted(PROMOTION_REGISTRY))
    def test_apply_is_deterministic_and_does_not_mutate(self, type_key: str) -> None:
        """`apply` on an eligible cart is repeatable and leaves it unchanged.

        Catches nondeterministic discounts (same cart, different receipt on
        refresh) and catches `apply` mutating its input, which would corrupt
        every later phase's eligibility checks.
        """
        promotion = parse_fixture_promotion(type_key)
        cart = CONTRACT_FIXTURES[type_key].eligible_cart
        before = cart.model_dump()
        first = promotion.apply(cart)
        second = promotion.apply(cart)
        assert isinstance(first, Adjustment)
        assert first == second
        assert first.phase is PROMOTION_REGISTRY[type_key].phase
        assert cart.model_dump() == before


class TestRegistry:
    """Registration wiring must fail loudly at import time, not at load time."""

    def test_duplicate_type_key_registration_fails(self) -> None:
        """Registering a second class under a taken key raises.

        Catches two kinds silently fighting over one `type` string — seed
        entries would validate into whichever class registered last.
        """

        class SecondClaimant(FlatOffCategoryDummy):
            """Attempts to reuse the dummy's already-taken type key."""

        with pytest.raises(ValueError, match="duplicate promotion type_key"):
            register_promotion(DUMMY_TYPE)(SecondClaimant)
        assert PROMOTION_REGISTRY[DUMMY_TYPE] is FlatOffCategoryDummy

    def test_blank_type_key_rejected(self) -> None:
        """A whitespace-only type key is rejected before any class binds.

        Catches an unnameable kind entering the registry — no seed entry
        could ever reference it, and the union would carry a blank tag.
        """
        with pytest.raises(ValueError, match="must not be blank"):
            register_promotion("   ")

    def test_abstract_class_registration_fails(self) -> None:
        """Registering a class that never implemented the interface raises.

        Catches a half-written kind entering the registry — the failure
        would otherwise surface as a TypeError at first seed load instead of
        at definition.
        """

        class StillAbstract(Promotion):
            """Sets phase but implements neither abstract method."""

            phase: ClassVar[Phase] = Phase.ITEM

        with pytest.raises(ValueError, match="abstract"):
            register_promotion("TEST_ABSTRACT")(StillAbstract)
        assert "TEST_ABSTRACT" not in PROMOTION_REGISTRY

    def test_missing_phase_registration_fails(self) -> None:
        """Registering a concrete kind that never set `phase` raises.

        Catches a kind with no cascade phase — the engine could not place it
        in the Item/Cart/Shipping order, and every instance would crash on
        first `phase` access instead of at definition.
        """

        class NoPhase(Promotion):
            """Implements the interface but never sets `phase`."""

            def is_eligible(self, cart: Cart) -> bool:
                """Trivially eligible; never called in this test."""
                return True

            def apply(self, cart: Cart) -> Adjustment:
                """Never called in this test."""
                raise NotImplementedError

        with pytest.raises(ValueError, match="phase"):
            register_promotion("TEST_NO_PHASE")(NoPhase)
        assert "TEST_NO_PHASE" not in PROMOTION_REGISTRY

    def test_dummy_kind_registered_from_this_module(self) -> None:
        """The test-only kind is present in the registry under its key.

        Catches the registry not being writable from outside app/ — the
        contained-change property (#19's whole point) would be broken for
        real kinds added later.
        """
        assert PROMOTION_REGISTRY[DUMMY_TYPE] is FlatOffCategoryDummy


class TestSeedLoader:
    """Loader must fail loud on anything it does not fully understand."""

    def test_unknown_type_key_fails_loud(self) -> None:
        """An entry naming an unregistered type raises, never skips.

        Catches a typo'd or not-yet-deployed `type` in a seed file silently
        dropping a promotion the business expects to be live.
        """
        entry = dict(CONTRACT_FIXTURES[DUMMY_TYPE].seed_entry, type="NO_SUCH_KIND")
        with pytest.raises(SeedLoadError):
            parse_promotions([entry])

    def test_missing_type_key_fails_loud(self) -> None:
        """An entry with no `type` key raises.

        Catches an untagged entry — the loader has no way to pick a class,
        and guessing one would price carts with the wrong rules.
        """
        entry = dict(CONTRACT_FIXTURES[DUMMY_TYPE].seed_entry)
        del entry["type"]
        with pytest.raises(SeedLoadError):
            parse_promotions([entry])

    def test_invalid_kind_config_fails_loud(self) -> None:
        """A well-tagged entry with invalid kind fields raises.

        Catches malformed condition/effect config (e.g. a non-numeric
        quantity) being coerced or defaulted into a live promotion.
        """
        entry = dict(CONTRACT_FIXTURES[DUMMY_TYPE].seed_entry, min_qty="lots")
        with pytest.raises(SeedLoadError):
            parse_promotions([entry])

    def test_non_list_payload_fails_loud(self) -> None:
        """A payload that is not a top-level list raises.

        Catches a seed file wrapping entries in an object (or being a single
        entry) — accepting it loosely would let format drift hide entries.
        """
        with pytest.raises(SeedLoadError):
            parse_promotions({"promotions": [CONTRACT_FIXTURES[DUMMY_TYPE].seed_entry]})

    def test_duplicate_ids_fail_loud(self) -> None:
        """Two entries sharing an id raise.

        Catches a copy-pasted seed entry — duplicate ids would make the
        explanation trace ambiguous about which promotion applied.
        """
        entry = CONTRACT_FIXTURES[DUMMY_TYPE].seed_entry
        with pytest.raises(SeedLoadError, match="unique ids"):
            parse_promotions([entry, dict(entry, name="Same id again")])

    def test_seed_file_round_trip(self, tmp_path: Path) -> None:
        """A JSON seed file on disk loads into the registered classes.

        Catches file-level plumbing breaking (encoding, parsing, ordering)
        even when in-memory validation works — this is the path the app
        boots through.
        """
        seed_path = tmp_path / "promotions.json"
        entries = [fixture.seed_entry for fixture in CONTRACT_FIXTURES.values()]
        seed_path.write_text(json.dumps(entries), encoding="utf-8")
        promotions = load_promotions(seed_path)
        assert [type(p) for p in promotions] == [
            PROMOTION_REGISTRY[str(entry["type"])] for entry in entries
        ]

    def test_invalid_json_file_fails_loud(self, tmp_path: Path) -> None:
        """A file that is not valid JSON raises with the path in the message.

        Catches a truncated or hand-mangled seed file booting the app with
        no promotions instead of refusing to start.
        """
        seed_path = tmp_path / "promotions.json"
        seed_path.write_text("not json {", encoding="utf-8")
        with pytest.raises(SeedLoadError, match="not valid JSON"):
            load_promotions(seed_path)

    def test_missing_file_fails_loud(self, tmp_path: Path) -> None:
        """A nonexistent seed path raises SeedLoadError, not a bare OSError.

        Catches a misconfigured seed path surfacing as an unhandled crash
        with no hint that it is a seed-loading problem.
        """
        with pytest.raises(SeedLoadError, match="cannot read"):
            load_promotions(tmp_path / "nope.json")


class TestTargetOverlap:
    """The one operation the target union exists for: cluster derivation."""

    @staticmethod
    def overlap_cart() -> Cart:
        """A cart mirroring the seed catalog's category assignments."""
        return Cart(
            items=[
                make_line_item(),  # COF-ETH / Coffee Beans
                make_line_item(sku="COF-COL", unit_price_cents=1400),
                make_line_item(
                    sku="BREW-V60", category="Brew Gear", unit_price_cents=2800
                ),
            ]
        )

    def test_same_category_targets_overlap(self) -> None:
        """Two targets on the same category overlap when its lines exist.

        Catches P1/P6 (both Category: Coffee Beans) not clustering — the
        engine would apply both to the same lines, a double application.
        """
        beans = CategoryTarget(category="Coffee Beans")
        assert targets_can_overlap(beans, beans, self.overlap_cart())

    def test_sku_target_outside_category_does_not_overlap(self) -> None:
        """A SKU target in another category is independent of a category one.

        Catches P4 (SKU: BREW-V60) wrongly clustering with P1/P6 (Category:
        Coffee Beans) — a shopper would lose a legal stack the seed doc
        explicitly allows (docs/seed-promotions.md, "P4 doesn't [conflict]").
        """
        beans = CategoryTarget(category="Coffee Beans")
        dripper = SkuTarget(sku="BREW-V60")
        cart = self.overlap_cart()
        assert not targets_can_overlap(beans, dripper, cart)
        assert not targets_can_overlap(dripper, beans, cart)

    def test_sku_target_inside_category_overlaps(self) -> None:
        """A SKU target overlaps a category target containing that line.

        Catches a SKU promo and a category promo hitting the same physical
        line without clustering — the same cents discounted twice.
        """
        beans = CategoryTarget(category="Coffee Beans")
        ethiopia = SkuTarget(sku="COF-ETH")
        assert targets_can_overlap(beans, ethiopia, self.overlap_cart())

    def test_different_skus_do_not_overlap(self) -> None:
        """Targets on two different SKUs never overlap.

        Catches unrelated per-item promos being forced into one cluster,
        outlawing a stack that touches disjoint lines.
        """
        cart = self.overlap_cart()
        assert not targets_can_overlap(
            SkuTarget(sku="COF-ETH"), SkuTarget(sku="BREW-V60"), cart
        )
        assert targets_can_overlap(
            SkuTarget(sku="COF-ETH"), SkuTarget(sku="COF-ETH"), cart
        )

    def test_singleton_targets_overlap_only_their_own_kind(self) -> None:
        """Cart and shipping targets each overlap themselves, nothing else.

        Catches P2/P5 (both cart subtotal) not clustering — two cart-wide
        discounts would stack — or cart/shipping wrongly conflicting, which
        would forbid the legal 15%-off + free-shipping combination.
        """
        cart = self.overlap_cart()
        assert targets_can_overlap(CartTarget(), CartTarget(), cart)
        assert targets_can_overlap(ShippingTarget(), ShippingTarget(), cart)
        assert not targets_can_overlap(CartTarget(), ShippingTarget(), cart)
        assert not targets_can_overlap(
            CartTarget(), CategoryTarget(category="Coffee Beans"), cart
        )
        assert not targets_can_overlap(SkuTarget(sku="COF-ETH"), ShippingTarget(), cart)
