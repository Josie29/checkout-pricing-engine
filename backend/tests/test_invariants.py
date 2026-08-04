# Cross-cutting invariant suite (issue #26). The per-module suites already
# property-test the naive engine and optimizer over catalog-priced seeded
# carts (tests/test_engine.py, tests/test_optimizer.py); this suite widens the
# input domain — shopper-edited unit prices (zero, single cents, odd amounts),
# quantities up to 50, fully synthetic carts — and exercises every invariant
# through BOTH the engine entry points and the real `POST /price` contract,
# because the response body is what shoppers actually see. It also carries the
# large-cart performance budget test.

import time
from collections.abc import Mapping, Sequence
from typing import Any

from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain import Cart, LineItem
from app.engine import price_naive
from app.main import app as fastapi_app
from app.optimizer import optimize
from app.seeds import load_seed_catalog, load_seed_promotions

client = TestClient(fastapi_app)

CATALOG = load_seed_catalog()
CATALOG_BY_SKU = {item.sku: item for item in CATALOG}
SEED_PROMOTIONS = load_seed_promotions()
SEED_IDS = [promo.id for promo in SEED_PROMOTIONS]

# Shopper-edited unit prices: the request schema allows any non-negative
# integer-cent price, so the domain includes zero (free line), one cent, and
# odd non-round amounts — the shapes most likely to expose rounding drift.
edited_prices = st.one_of(st.sampled_from([0, 1, 99, 2801]), st.integers(0, 99_999))


@st.composite
def seeded_carts(draw: st.DrawFn) -> Cart:
    """A cart over the real catalog: random SKU subset, qty 1-50, edited prices.

    Roughly half the lines keep their catalog price; the rest carry a
    shopper-edited price drawn from `edited_prices` (including zero and odd
    cents), matching the cart builder's editable-price feature.

    Args:
        draw: Hypothesis draw function.

    Returns:
        A valid cart of 1-8 distinct catalog SKUs.
    """
    catalog_skus = st.sampled_from(sorted(CATALOG_BY_SKU))
    skus = draw(st.lists(catalog_skus, min_size=1, max_size=8, unique=True))
    items: list[LineItem] = []
    for sku in skus:
        entry = CATALOG_BY_SKU[sku]
        price = draw(edited_prices) if draw(st.booleans()) else entry.unit_price_cents
        items.append(
            LineItem(
                sku=entry.sku,
                name=entry.name,
                category=entry.category,
                unit_price_cents=price,
                qty=draw(st.integers(1, 50)),
            )
        )
    return Cart(items=items)


# Synthetic SKU/category pools deliberately mix real promotion targets
# (BREW-V60 is P4's SKU target; Coffee Beans is P1/P6's category target) with
# unknown values, so seed promotions sometimes match synthetic lines and
# sometimes miss — both paths matter.
_SYNTHETIC_SKU_POOL = ("BREW-V60", "COF-ETH", "TEA-OOL", "GADGET-1", "ZORP-99")
_SYNTHETIC_CATEGORIES = ("Coffee Beans", "Brew Gear", "Drinkware", "Snacks", "Curios")
_random_skus = st.text(
    alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-", min_size=1, max_size=12
)


@st.composite
def synthetic_carts(draw: st.DrawFn) -> Cart:
    """A fully synthetic cart: random SKUs, categories, prices, and quantities.

    Args:
        draw: Hypothesis draw function.

    Returns:
        A valid cart of 1-6 unique-SKU lines with arbitrary non-negative
        prices (up to $5000) and quantities 1-50.
    """
    skus = draw(
        st.lists(
            st.one_of(st.sampled_from(_SYNTHETIC_SKU_POOL), _random_skus),
            min_size=1,
            max_size=6,
            unique=True,
        )
    )
    return Cart(
        items=[
            LineItem(
                sku=sku,
                category=draw(st.sampled_from(_SYNTHETIC_CATEGORIES)),
                unit_price_cents=draw(st.integers(0, 500_000)),
                qty=draw(st.integers(1, 50)),
            )
            for sku in skus
        ]
    )


any_carts = st.one_of(seeded_carts(), synthetic_carts())
claimed_subsets = st.sets(st.sampled_from(SEED_IDS))
claimed_lists = st.lists(st.sampled_from(SEED_IDS), unique=True)


def price_payload(cart: Cart, claimed: Sequence[str]) -> dict[str, Any]:
    """Build the `POST /price` request body for a domain cart.

    Args:
        cart: The cart to price.
        claimed: Claimed promotion ids, in the order to send them.

    Returns:
        A JSON-serializable request body.
    """
    return {
        "cart": cart.model_dump(mode="json"),
        "claimed_promotion_ids": list(claimed),
    }


def assert_receipt_invariants(receipt: dict[str, Any]) -> None:
    """Assert the cross-cutting receipt invariants on one priced result.

    Operates on the JSON shape (`PricingResult.model_dump(mode="json")` and
    the `POST /price` body are both supersets of it), so the same checks run
    against what the engine computes and what the shopper's browser receives.

    Args:
        receipt: A dict carrying `lines`, `adjustments`, `subtotal_cents`,
            `discount_total_cents`, `shipping_cents`, and `total_cents`.

    Raises:
        AssertionError: If any invariant is violated.
    """
    lines: list[dict[str, Any]] = receipt["lines"]
    adjustments: list[dict[str, Any]] = receipt["adjustments"]

    # Invariant 2 — nothing negative: a shopper can never owe less than zero
    # on a line, on shipping, or overall (docs/scope.md's never-negative rule).
    assert receipt["total_cents"] >= 0
    assert receipt["shipping_cents"] >= 0
    for line in lines:
        assert line["line_total_cents"] >= 0
        # Per-line arithmetic ties out: the row a shopper reads is internally
        # consistent, not just the grand total.
        assert line["line_subtotal_cents"] == line["unit_price_cents"] * line["qty"]
        assert (
            line["line_total_cents"]
            == line["line_subtotal_cents"] - line["discount_cents"]
        )

    # Invariant 1 — itemization sums exactly: the receipt's rows plus shipping
    # equal the charged total to the cent, and the explanation trace accounts
    # for every discounted cent. Any drift means the breakdown lies.
    assert sum(li["line_subtotal_cents"] for li in lines) == receipt["subtotal_cents"]
    assert (
        sum(li["line_total_cents"] for li in lines) + receipt["shipping_cents"]
        == receipt["total_cents"]
    )
    assert (
        sum(adj["amount_cents"] for adj in adjustments)
        == receipt["discount_total_cents"]
    )
    allocated: dict[str, int] = {li["sku"]: 0 for li in lines}
    item_adjustments_touching: dict[str, int] = {li["sku"]: 0 for li in lines}
    for adj in adjustments:
        for alloc in adj["line_allocations"]:
            allocated[alloc["sku"]] += alloc["amount_cents"]
            if adj["phase"] == "item":
                item_adjustments_touching[alloc["sku"]] += 1
    for line in lines:
        assert allocated[line["sku"]] == line["discount_cents"]

    # Invariant 3 — no double application, phase cardinality observable in the
    # trace: a promotion appears at most once; at most one Cart-phase and one
    # Shipping-phase adjustment exist (each phase is a single conflict
    # cluster); and no line collects money from two Item-phase adjustments —
    # two Item promotions reaching the same line would mean their targets
    # overlap, i.e. an illegal same-cluster stack undercharging the cart.
    promo_ids = [adj["promotion_id"] for adj in adjustments]
    assert len(promo_ids) == len(set(promo_ids))
    assert sum(1 for adj in adjustments if adj["phase"] == "cart") <= 1
    assert sum(1 for adj in adjustments if adj["phase"] == "shipping") <= 1
    assert all(count <= 1 for count in item_adjustments_touching.values())


def assert_statuses_consistent(
    statuses: Mapping[str, str], claimed: set[str], adjustment_promo_ids: Sequence[str]
) -> None:
    """Assert invariant 6: the status map, claims, and trace agree.

    `PromotionStatus` is a `StrEnum`, so the same checks run against engine
    outcomes and the API's JSON statuses.

    Args:
        statuses: Status per promotion id, from an outcome or a response.
        claimed: The ids the request claimed.
        adjustment_promo_ids: Promotion ids appearing in the trace.

    Raises:
        AssertionError: If any consistency rule is violated.
    """
    # The toggle list shows every seeded promotion, no more, no fewer.
    assert set(statuses) == set(SEED_IDS)
    applied = {pid for pid, status in statuses.items() if status == "applied"}
    # applied ⊆ claimed ⊆ all: an untoggled deal never changes the price, and
    # nothing outside the seed set ever appears.
    assert applied <= claimed <= set(SEED_IDS)
    # The trace and the badge agree: every "applied" badge has an explanation
    # line, and every explanation line shows as "applied".
    assert applied == set(adjustment_promo_ids)
    for pid in claimed - applied:
        assert statuses[pid] == "claimed"
    for pid in set(SEED_IDS) - claimed:
        assert statuses[pid] == "available"


class TestEngineInvariants:
    """Invariants 1-3, 5, 6 through `price_naive` and `optimize` directly."""

    @settings(deadline=None)
    @given(cart=any_carts, claimed=claimed_subsets)
    def test_both_engines_hold_every_receipt_invariant(
        self, cart: Cart, claimed: set[str]
    ) -> None:
        """Random real/synthetic carts x claims: both engines' receipts add up.

        Catches any cart shape — edited prices, zero-price lines, bulk
        quantities, unknown categories — where either engine produces a
        receipt whose rows, trace, and totals disagree by a cent, goes
        negative, stacks a cluster, or reports statuses that contradict the
        trace. Also invariant 5: the optimizer must never hand the shopper a
        worse total than the engine it exists to beat.
        """
        naive = price_naive(cart, SEED_PROMOTIONS, claimed)
        optimized = optimize(cart, SEED_PROMOTIONS, claimed)
        for outcome in (naive, optimized):
            assert_receipt_invariants(outcome.result.model_dump(mode="json"))
            assert_statuses_consistent(
                outcome.statuses,
                claimed,
                [adj.promotion_id for adj in outcome.result.adjustments],
            )
        assert optimized.result.total_cents <= naive.result.total_cents

    @settings(deadline=None)
    @given(cart=any_carts, claimed=claimed_lists, data=st.data())
    def test_engines_are_deterministic_and_blind_to_claim_order(
        self, cart: Cart, claimed: list[str], data: st.DataObject
    ) -> None:
        """Repricing and reshuffling claimed ids change nothing, both engines.

        Catches nondeterminism (wall-clock, set-iteration order, dict order)
        anywhere in either pricing path: two identical requests — or the same
        toggles clicked in a different order — must price to the identical
        outcome, or shoppers see prices jitter on refresh.
        """
        shuffled = data.draw(st.permutations(claimed))
        first_naive = price_naive(cart, SEED_PROMOTIONS, claimed)
        assert first_naive == price_naive(cart, SEED_PROMOTIONS, claimed)
        assert first_naive == price_naive(cart, SEED_PROMOTIONS, shuffled)
        first_optimized = optimize(cart, SEED_PROMOTIONS, claimed)
        assert first_optimized == optimize(cart, SEED_PROMOTIONS, shuffled)


class TestApiInvariants:
    """The same invariants through `POST /price` — what shoppers actually see."""

    @settings(deadline=None)
    @given(cart=any_carts, claimed=claimed_subsets)
    def test_response_receipt_holds_every_invariant(
        self, cart: Cart, claimed: set[str]
    ) -> None:
        """Random carts x claims: the served response body adds up exactly.

        The engine properties above could hold while the API layer mangles
        the winner (dropping a field, re-serializing wrong, picking the wrong
        engine). Catches any served receipt that does not add up, any status
        map that contradicts the served trace, and — invariant 5 as shoppers
        experience it — any response worse than the naive price.
        """
        response = client.post("/price", json=price_payload(cart, sorted(claimed)))
        assert response.status_code == 200
        body = response.json()
        assert_receipt_invariants(body)
        assert_statuses_consistent(
            body["promotion_statuses"],
            claimed,
            [adj["promotion_id"] for adj in body["adjustments"]],
        )
        naive = price_naive(cart, SEED_PROMOTIONS, claimed)
        assert body["total_cents"] <= naive.result.total_cents
        # With the seed set the optimizer always searches exhaustively (36
        # combos < the 512 cap) and the flat $10 shipping keeps every total
        # positive, so the runtime sanity check must never trip: a False here
        # means the optimizer lost to naive or returned garbage — a real bug.
        assert body["optimal"] is True

    @settings(deadline=None)
    @given(cart=any_carts, claimed=claimed_lists, data=st.data())
    def test_response_is_identical_across_retries_and_claim_order(
        self, cart: Cart, claimed: list[str], data: st.DataObject
    ) -> None:
        """Same request twice, and shuffled claimed ids: byte-identical bodies.

        Catches serialization-level nondeterminism the parsed-equality engine
        test cannot see (key ordering, float leakage, locale formatting) —
        the exact bytes a shopper's browser caches must be stable.
        """
        shuffled = data.draw(st.permutations(claimed))
        first = client.post("/price", json=price_payload(cart, claimed))
        second = client.post("/price", json=price_payload(cart, claimed))
        reordered = client.post("/price", json=price_payload(cart, shuffled))
        assert first.status_code == 200
        assert first.text == second.text
        assert first.text == reordered.text


class TestLargeCartPerformance:
    """Issue #26's tight-time-budget evidence, plain pytest (not Hypothesis)."""

    def test_full_catalog_bulk_cart_prices_within_budget(self) -> None:
        """All 8 SKUs at qty 500, edited prices, all 6 promos: fast and exact.

        The worst realistic request: 4000 units, every promotion claimed,
        odd-cent edited prices. The optimizer's search space depends on
        catalog structure, not cart size (docs/optimizer-spec.md), so this
        must stay exhaustive (`optimal` true) and well inside an interactive
        budget. Catches any change that makes pricing scale with quantities
        or cart value — shoppers would watch the total spin.
        """
        items: list[dict[str, Any]] = []
        for index, entry in enumerate(CATALOG):
            price = entry.unit_price_cents
            if index % 2 == 1:
                # Shopper-edited odd-cent price on alternating lines.
                price = price * 2 + 1
            items.append(
                {
                    "sku": entry.sku,
                    "name": entry.name,
                    "category": entry.category,
                    "unit_price_cents": price,
                    "qty": 500,
                }
            )
        payload = {"cart": {"items": items}, "claimed_promotion_ids": list(SEED_IDS)}
        # Warm-up call so one-time costs (route compilation, validator
        # caches) don't pollute the latency claim.
        assert client.post("/price", json=payload).status_code == 200
        elapsed_best = float("inf")
        response = None
        for _ in range(3):
            start = time.perf_counter()
            response = client.post("/price", json=payload)
            elapsed_best = min(elapsed_best, time.perf_counter() - start)
        assert response is not None
        assert response.status_code == 200
        body = response.json()
        assert body["optimal"] is True
        assert_receipt_invariants(body)
        # Observed locally (in-process TestClient, Apple Silicon, best of
        # three): ~3.5 ms, worst of ten ~4.1 ms. The 50 ms budget is ~12x
        # the observed best, so the assert only fires on a real regression
        # (e.g. work scaling with quantities), not CI noise.
        assert elapsed_best < 0.05
