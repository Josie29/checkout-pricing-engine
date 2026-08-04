import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict

from app.main import app as fastapi_app

client = TestClient(fastapi_app)

# The enumerated stacking/exclusivity matrix (docs/testing-strategy.md's last
# layer): for every relevant pair (and triple/quad) of seed promotions, a
# purpose-built cart on which every claimed promotion is INDIVIDUALLY eligible,
# and a frozen answer for whether they co-apply. Exclusivity is structural —
# phase cardinality per conflict cluster (docs/seed-promotions.md) — so this
# suite pins the derived behavior promo by promo instead of trusting the
# derivation. All expected totals are hand-computed from the seed doc's rules,
# never read off an engine run.


class MatrixRow(BaseModel):
    """One matrix entry: a purpose-built cart plus the frozen outcome."""

    model_config = ConfigDict(frozen=True)

    label: str
    items: list[dict[str, object]]
    claimed: list[str]
    expected_applied: set[str]
    expected_total_cents: int


def _line(
    sku: str, category: str, unit_price_cents: int, qty: int
) -> dict[str, object]:
    """A /price cart line payload."""
    return {
        "sku": sku,
        "category": category,
        "unit_price_cents": unit_price_cents,
        "qty": qty,
    }


def _beans(sku: str, price: int, qty: int) -> dict[str, object]:
    """A Coffee Beans cart line payload."""
    return _line(sku, "Coffee Beans", price, qty)


_DRIPPER = _line("BREW-V60", "Brew Gear", 2800, 1)
_GRINDER_X2 = _line("BREW-GRD", "Brew Gear", 4500, 2)
_GRINDER_X3 = _line("BREW-GRD", "Brew Gear", 4500, 3)


MATRIX: list[MatrixRow] = [
    # --- Never-pairs: same conflict cluster, exactly one may apply. ---------
    #
    # P1 + P6 share the Item-phase Coffee Beans cluster. Cart: ETH x2 (3200)
    # + COL x2 (2800) = 6000, bean qty 4 — both individually eligible.
    # P1 frees the cheapest unit (1400) > P6's 20% of 6000 (1200), so the
    # optimizer keeps P1 and P6 stays claimed-not-applied.
    # Total: 6000 - 1400 + 1000 shipping = 5600.
    MatrixRow(
        label="P1+P6 same item cluster: only P1 applies",
        items=[_beans("COF-ETH", 1600, 2), _beans("COF-COL", 1400, 2)],
        claimed=["P1", "P6"],
        expected_applied={"P1"},
        expected_total_cents=5600,
    ),
    # P2 + P5 share the single Cart-phase cluster (both target the
    # subtotal). Cart: grinders x3 = 13500, over both the 5000 and 10000
    # thresholds — both individually eligible. P5's 20% (2700) > P2's 15%
    # (2025), so P5 wins the cluster. Total: 13500 - 2700 + 1000 = 11800.
    MatrixRow(
        label="P2+P5 same cart cluster: only P5 applies",
        items=[_GRINDER_X3],
        claimed=["P2", "P5"],
        expected_applied={"P5"},
        expected_total_cents=11800,
    ),
    # --- Co-applying pairs: distinct clusters, both must stack. ------------
    #
    # P1 + P4: two disjoint Item-phase clusters (beans vs BREW-V60).
    # Cart: COL x3 (4200) + dripper (2800) = 7000. P1 frees 1400, P4 takes
    # 500. Total: 7000 - 1900 + 1000 = 6100.
    MatrixRow(
        label="P1+P4 disjoint item clusters: both apply",
        items=[_beans("COF-COL", 1400, 3), _DRIPPER],
        claimed=["P1", "P4"],
        expected_applied={"P1", "P4"},
        expected_total_cents=6100,
    ),
    # P6 + P4: same two disjoint Item clusters, the other bean deal.
    # Same 7000 cart. P6 = 20% of the 4200 bean subtotal = 840, P4 = 500.
    # Total: 7000 - 1340 + 1000 = 6660.
    MatrixRow(
        label="P6+P4 disjoint item clusters: both apply",
        items=[_beans("COF-COL", 1400, 3), _DRIPPER],
        claimed=["P6", "P4"],
        expected_applied={"P6", "P4"},
        expected_total_cents=6660,
    ),
    # Item + Cart (P1 + P2): different phases always stack when the Cart
    # threshold survives the item discount. Cart: ETH x3 (4800) + grinder
    # (4500) = 9300. P1 frees 1600 -> post-item 7700 >= 5000, P2 = 15% of
    # 7700 = 1155. Total: 7700 - 1155 + 1000 = 7545.
    MatrixRow(
        label="P1+P2 item+cart phases: both apply",
        items=[_beans("COF-ETH", 1600, 3), _line("BREW-GRD", "Brew Gear", 4500, 1)],
        claimed=["P1", "P2"],
        expected_applied={"P1", "P2"},
        expected_total_cents=7545,
    ),
    # Item + Cart (P4 + P2) — the withholding pair, on a cart rich enough
    # that they DO stack (contrast tests/test_golden.py's $50-boundary
    # cart where P4 is withheld). Cart: dripper (2800) + grinder x1 (4500)
    # = 7300. P4 -> post-item 6800 >= 5000, P2 = 15% of 6800 = 1020.
    # Total: 6800 - 1020 + 1000 = 6780.
    MatrixRow(
        label="P4+P2 item+cart with threshold headroom: both apply",
        items=[_DRIPPER, _line("BREW-GRD", "Brew Gear", 4500, 1)],
        claimed=["P4", "P2"],
        expected_applied={"P4", "P2"},
        expected_total_cents=6780,
    ),
    # Item + Shipping (P4 + P7). Cart: dripper (2800) + grinders x2 (9000)
    # = 11800. P4 -> post-item 11300 >= 10000, P7 zeroes the 1000 baseline.
    # Total: 11300 + 0 = 11300.
    MatrixRow(
        label="P4+P7 item+shipping phases: both apply",
        items=[_DRIPPER, _GRINDER_X2],
        claimed=["P4", "P7"],
        expected_applied={"P4", "P7"},
        expected_total_cents=11300,
    ),
    # Cart + Shipping (P5 + P7). Cart: grinders x3 = 13500. P5 = 2700 ->
    # post-cart 10800, still >= 10000, so P7 survives the cart discount.
    # Total: 10800 + 0 = 10800.
    MatrixRow(
        label="P5+P7 cart+shipping phases: both apply",
        items=[_GRINDER_X3],
        claimed=["P5", "P7"],
        expected_applied={"P5", "P7"},
        expected_total_cents=10800,
    ),
    # --- Triples: one cluster conflict inside a legal stack. ---------------
    #
    # P1 + P6 + P4: the bean cluster resolves to one winner, P4 stacks on
    # top. Cart: ETH x2 (3200) + COL x2 (2800) + dripper (2800) = 8800.
    # Bean cluster: P1 (1400) > P6 (20% of 6000 = 1200) -> P1. Plus P4's
    # 500. Total: 8800 - 1900 + 1000 = 7900.
    MatrixRow(
        label="P1+P6+P4 triple: bean cluster picks P1, P4 stacks",
        items=[_beans("COF-ETH", 1600, 2), _beans("COF-COL", 1400, 2), _DRIPPER],
        claimed=["P1", "P6", "P4"],
        expected_applied={"P1", "P4"},
        expected_total_cents=7900,
    ),
    # P2 + P5 + P7: the cart cluster resolves to one winner, shipping
    # stacks. Cart: grinders x3 = 13500. Candidates: P5 (2700) leaves
    # 10800 >= 10000 so P7 still fires -> 10800; P2 (2025) leaves 11475
    # with free shipping -> 11475. P5 + P7 wins, P2 stays claimed.
    MatrixRow(
        label="P2+P5+P7 triple: cart cluster picks P5, P7 stacks",
        items=[_GRINDER_X3],
        claimed=["P2", "P5", "P7"],
        expected_applied={"P5", "P7"},
        expected_total_cents=10800,
    ),
    # --- The full-stack quad: one promo from every cluster, all legal. -----
    #
    # P1 + P4 + P2 + P7 on a cart expensive enough that both thresholds
    # survive the item discounts. Cart: ETH x3 (4800) + dripper (2800) +
    # grinders x2 (9000) = 16600.
    #   Item: P1 frees 1600, P4 takes 500 -> post-item 14500 (>= 5000)
    #   Cart: P2 = 15% of 14500 = 2175  -> post-cart 12325 (>= 10000)
    #   Ship: P7 zeroes the 1000 baseline
    #   Total: 12325 + 0 = 12325
    # Withholding any member only raises the total (each item cent saved
    # costs 0.85 net cents while thresholds hold, and they hold with
    # 2325 cents of headroom), so the engine legally stacks all four.
    MatrixRow(
        label="P1+P4+P2+P7 quad: all four stack",
        items=[_beans("COF-ETH", 1600, 3), _DRIPPER, _GRINDER_X2],
        claimed=["P1", "P4", "P2", "P7"],
        expected_applied={"P1", "P4", "P2", "P7"},
        expected_total_cents=12325,
    ),
]


def _price(cart_items: list[dict[str, object]], claimed: list[str]) -> httpx.Response:
    """POST /price with the given cart lines and claimed promotion ids."""
    return client.post(
        "/price",
        json={"cart": {"items": cart_items}, "claimed_promotion_ids": claimed},
    )


_ROW_IDS = [row.label for row in MATRIX]


class TestStackingMatrix:
    """docs/testing-strategy.md's stacking/exclusivity matrix, row by row."""

    @pytest.mark.parametrize("row", MATRIX, ids=_ROW_IDS)
    def test_each_claimed_promotion_is_individually_eligible(
        self, row: MatrixRow
    ) -> None:
        """Claiming each row promo alone on the row's cart applies it.

        The precondition that makes the matrix meaningful: a "never
        co-apply" verdict proves nothing if one of the pair was never
        eligible on that cart to begin with. Catches a cart edit (or a
        promotion threshold change) silently turning an exclusivity row
        into a vacuous pass.
        """
        for promo_id in row.claimed:
            response = _price(row.items, [promo_id])
            assert response.status_code == 200
            applied = [adj["promotion_id"] for adj in response.json()["adjustments"]]
            assert applied == [promo_id], (
                f"{promo_id} alone must apply on the {row.label!r} cart"
            )

    @pytest.mark.parametrize("row", MATRIX, ids=_ROW_IDS)
    def test_co_application_matches_the_matrix(self, row: MatrixRow) -> None:
        """Claiming the row's promotions together applies exactly the frozen set.

        The matrix itself. Catches structural exclusivity breaking in
        either direction: two same-cluster promos stacking (the shopper is
        double-discounted — P1+P6 or P2+P5 both applying) or a legal
        cross-cluster/cross-phase stack being denied (the shopper loses a
        promised deal — e.g. the P1+P4+P2+P7 quad collapsing to three).
        For never-pairs it also pins WHICH member wins, and that the loser
        is reported "claimed", not dropped or errored.
        """
        response = _price(row.items, row.claimed)
        assert response.status_code == 200
        body = response.json()
        applied_ids = [adj["promotion_id"] for adj in body["adjustments"]]
        # No promotion may appear twice in the trace (double-application).
        assert len(applied_ids) == len(set(applied_ids))
        assert set(applied_ids) == row.expected_applied
        assert body["total_cents"] == row.expected_total_cents
        statuses = body["promotion_statuses"]
        for promo_id in row.claimed:
            expected = "applied" if promo_id in row.expected_applied else "claimed"
            assert statuses[promo_id] == expected, (
                f"{promo_id} must be {expected} on the {row.label!r} cart"
            )
