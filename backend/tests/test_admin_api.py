import json
import sqlite3
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import app.main
from app.main import app as fastapi_app
from app.promotion_store import PromotionStore, PromotionStoreLoadError
from app.seeds import PROMOTIONS_SEED_PATH, load_seed_promotions

client = TestClient(fastapi_app)

SEED_IDS = ["P1", "P6", "P4", "P2", "P5", "P7"]

# A valid seed-entry body: $2 off the travel mug, same shape as an
# app/seeds/promotions.json entry.
_MUG_FIXED_OFF: dict[str, object] = {
    "type": "FIXED_OFF_ITEM",
    "id": "A1",
    "name": "$2 off travel mug",
    "target": {"kind": "sku", "sku": "MUG-TVL"},
    "amount_off_cents": 200,
}


@pytest.fixture(autouse=True)
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the app at a fresh store backed by a temp-directory SQLite file.

    Swaps `app.main.PROMOTION_STORE` (the routes read the module global on
    every request) for a seeds-only store whose database lives under
    pytest's `tmp_path`, so each test starts from the boot state, nothing
    leaks between tests, and no test ever writes `backend/data/` into the
    repo tree. Persistence tests build a second store on the returned path
    to simulate a restart.
    """
    path = tmp_path / "promotions.db"
    monkeypatch.setattr(
        app.main, "PROMOTION_STORE", PromotionStore(load_seed_promotions(), path)
    )
    return path


def _restarted_store(path: Path) -> PromotionStore:
    """Build a second store on the same database, as a process restart would."""
    return PromotionStore(load_seed_promotions(), path)


def _price(cart_items: list[dict[str, object]], claimed: list[str]) -> httpx.Response:
    """POST /price with the given cart lines and claimed promotion ids."""
    return client.post(
        "/price",
        json={"cart": {"items": cart_items}, "claimed_promotion_ids": claimed},
    )


class TestAddPromotion:
    """POST /promotions — issue #68's runtime admin API."""

    def test_add_then_price_end_to_end(self) -> None:
        """Catches an added promotion not reaching the pricing engine.

        The admin form's whole point: POST a promotion, and the very next
        /price call must apply it — 201 with the GET-item shape, then exact
        cents with the new promotion in the trace.
        """
        response = client.post("/promotions", json=_MUG_FIXED_OFF)
        assert response.status_code == 201
        # Same serialized shape GET /promotions items use.
        assert response.json() == {
            "id": "A1",
            "name": "$2 off travel mug",
            "type": "FIXED_OFF_ITEM",
            "phase": "item",
            "target": {"kind": "sku", "sku": "MUG-TVL"},
            "params": {"amount_off_cents": 200},
        }
        priced = _price(
            [
                {
                    "sku": "MUG-TVL",
                    "category": "Drinkware",
                    "unit_price_cents": 2200,
                    "qty": 1,
                }
            ],
            ["A1"],
        )
        assert priced.status_code == 200
        body = priced.json()
        # 2200 - 200 off the mug + 1000 flat shipping.
        assert body["discount_total_cents"] == 200
        assert body["total_cents"] == 3000
        assert body["promotion_statuses"]["A1"] == "applied"
        assert body["adjustments"] == [
            {
                "promotion_id": "A1",
                "promotion_name": "$2 off travel mug",
                "phase": "item",
                "amount_cents": 200,
                "line_allocations": [{"sku": "MUG-TVL", "amount_cents": 200}],
            }
        ]

    def test_duplicate_seed_id_is_422(self) -> None:
        """Catches an addition silently shadowing (or duplicating) a seed.

        Reusing a seed id would break the engine's unique-id precondition,
        so the API must refuse it with the id named.
        """
        response = client.post("/promotions", json={**_MUG_FIXED_OFF, "id": "P1"})
        assert response.status_code == 422
        assert "P1" in response.json()["detail"]

    def test_duplicate_added_id_is_422_and_not_stored_twice(self) -> None:
        """Catches double-submitting the admin form storing two copies.

        The second POST of the same entry must 422, and the list must show
        exactly one copy.
        """
        assert client.post("/promotions", json=_MUG_FIXED_OFF).status_code == 201
        response = client.post("/promotions", json=_MUG_FIXED_OFF)
        assert response.status_code == 422
        assert "A1" in response.json()["detail"]
        listed = client.get("/promotions").json()
        assert [promo["id"] for promo in listed] == [*SEED_IDS, "A1"]

    def test_unknown_type_is_422(self) -> None:
        """Catches a bad `type` key crashing the server or storing garbage.

        The seed loader's unknown-kind rejection must surface as a 422
        naming the bad tag, and nothing may be stored.
        """
        response = client.post(
            "/promotions", json={**_MUG_FIXED_OFF, "type": "MYSTERY"}
        )
        assert response.status_code == 422
        assert "MYSTERY" in response.json()["detail"]
        assert [promo["id"] for promo in client.get("/promotions").json()] == SEED_IDS

    def test_mis_scoped_target_is_422(self) -> None:
        """Catches a mis-scoped target slipping past validation.

        A BXGY (item-phase) promotion with a cart target is a seed-authoring
        error the kinds reject at construction; the API must map that to a
        422, not a 500 mid-pricing later.
        """
        response = client.post(
            "/promotions",
            json={
                "type": "BXGY",
                "id": "A8",
                "name": "Broken: cart-scoped BXGY",
                "target": {"kind": "cart"},
                "min_qty": 2,
            },
        )
        assert response.status_code == 422
        assert "SKU or category target" in response.json()["detail"]


class TestAddedPromotionClusters:
    """Added promotions join conflict clusters with no engine changes."""

    def test_added_fixed_off_clusters_against_p4(self) -> None:
        """Catches an added promotion bypassing cluster derivation.

        A runtime FIXED_OFF_ITEM on BREW-V60 shares P4's target, so the two
        must form one conflict cluster: only one applies. If both applied,
        the dripper would be double-discounted (total 2600, not 3100).
        """
        response = client.post(
            "/promotions",
            json={
                "type": "FIXED_OFF_ITEM",
                "id": "A9",
                "name": "$7 off pour-over dripper",
                "target": {"kind": "sku", "sku": "BREW-V60"},
                "amount_off_cents": 700,
            },
        )
        assert response.status_code == 201
        priced = _price(
            [
                {
                    "sku": "BREW-V60",
                    "category": "Brew Gear",
                    "unit_price_cents": 2800,
                    "qty": 1,
                }
            ],
            ["P4", "A9"],
        )
        assert priced.status_code == 200
        body = priced.json()
        # The optimizer picks the cluster's better member: A9's 700 beats
        # P4's 500, so 2800 - 700 + 1000 shipping.
        assert body["total_cents"] == 3100
        assert [adj["promotion_id"] for adj in body["adjustments"]] == ["A9"]
        assert body["promotion_statuses"]["A9"] == "applied"
        assert body["promotion_statuses"]["P4"] == "claimed"


class TestPromotionsOrdering:
    """GET /promotions lists seeds then additions, in insertion order."""

    def test_additions_follow_seeds_in_insertion_order(self) -> None:
        """Catches additions reordering the toggle list (and the engine).

        Declaration order is the naive engine's cluster tie-break, so the
        list must stay seeds-first with additions appended in POST order,
        each serialized exactly as its 201 response was.
        """
        first = client.post("/promotions", json=_MUG_FIXED_OFF)
        second = client.post(
            "/promotions",
            json={
                "type": "PCT_OFF_CART",
                "id": "A2",
                "name": "5% off $20+",
                "target": {"kind": "cart"},
                "min_subtotal_cents": 2000,
                "percent_off": 5,
            },
        )
        assert first.status_code == 201
        assert second.status_code == 201
        listed = client.get("/promotions").json()
        assert [promo["id"] for promo in listed] == [*SEED_IDS, "A1", "A2"]
        assert listed[-2:] == [first.json(), second.json()]


_CART_PCT_OFF: dict[str, object] = {
    "type": "PCT_OFF_CART",
    "id": "A2",
    "name": "5% off $20+",
    "target": {"kind": "cart"},
    "min_subtotal_cents": 2000,
    "percent_off": 5,
}

_DB_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS promotions"
    " (id TEXT PRIMARY KEY, entry TEXT NOT NULL, created_at TEXT NOT NULL)"
)


def _insert_row(path: Path, row_id: str, entry_text: str) -> None:
    """Write one raw row straight into the SQLite file, bypassing the store."""
    conn = sqlite3.connect(path)
    try:
        with conn:  # commit on success
            conn.execute(_DB_SCHEMA)
            conn.execute(
                "INSERT INTO promotions (id, entry, created_at) VALUES (?, ?, ?)",
                (row_id, entry_text, "2026-01-01T00:00:00+00:00"),
            )
    finally:
        conn.close()


class TestPersistence:
    """Issue #75 — runtime additions survive a restart via SQLite."""

    def test_added_promotion_survives_restart(self, db_path: Path) -> None:
        """Catches an accepted promotion silently vanishing on restart.

        The whole point of #75: after a 201, a fresh store on the same
        database (a process restart) must still list the addition — with
        the same parsed shape the live store held.
        """
        assert client.post("/promotions", json=_MUG_FIXED_OFF).status_code == 201
        reloaded = _restarted_store(db_path)
        assert [promo.id for promo in reloaded.all()] == [*SEED_IDS, "A1"]
        assert reloaded.all()[-1] == app.main.PROMOTION_STORE.all()[-1]

    def test_reload_preserves_insertion_order(self, db_path: Path) -> None:
        """Catches a reload reordering additions (and the engine tie-break).

        Insertion order is the naive engine's cluster tie-break, so a
        restart must replay additions in the order they were POSTed, after
        every seed.
        """
        assert client.post("/promotions", json=_MUG_FIXED_OFF).status_code == 201
        assert client.post("/promotions", json=_CART_PCT_OFF).status_code == 201
        reloaded = _restarted_store(db_path)
        assert [promo.id for promo in reloaded.all()] == [*SEED_IDS, "A1", "A2"]

    def test_clear_additions_deletes_persisted_rows(self, db_path: Path) -> None:
        """Catches the test hook resetting memory but not disk.

        If `clear_additions()` left rows behind, a later "restart" would
        resurrect promotions a test believed cleared — cross-test leakage
        through the filesystem.
        """
        assert client.post("/promotions", json=_MUG_FIXED_OFF).status_code == 201
        app.main.PROMOTION_STORE.clear_additions()
        assert [promo.id for promo in _restarted_store(db_path).all()] == SEED_IDS

    def test_garbage_stored_row_fails_load_naming_id(self, db_path: Path) -> None:
        """Catches corrupt rows being skipped instead of failing loud.

        A stored row that no longer parses is schema drift or corruption;
        silently dropping it would price carts against a promotion set the
        admin believes still exists. Boot must raise and name the row.
        """
        _insert_row(db_path, "BAD1", "{not json")
        with pytest.raises(PromotionStoreLoadError, match="BAD1"):
            _restarted_store(db_path)

    def test_stored_row_colliding_with_seed_fails_load(self, db_path: Path) -> None:
        """Catches a persisted addition shadowing a seed after a seed edit.

        A row whose id now matches a seed breaks the engine's unique-id
        precondition; boot must refuse the whole store, naming the id,
        rather than pick a winner.
        """
        seed_entry = json.loads(PROMOTIONS_SEED_PATH.read_text(encoding="utf-8"))[0]
        assert seed_entry["id"] == "P1"
        _insert_row(db_path, "P1", json.dumps(seed_entry))
        with pytest.raises(PromotionStoreLoadError, match="P1"):
            _restarted_store(db_path)
