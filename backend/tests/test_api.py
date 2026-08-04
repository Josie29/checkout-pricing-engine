import importlib

import httpx
import pytest
from fastapi.testclient import TestClient

import app.main
from app.main import app as fastapi_app

client = TestClient(fastapi_app)


def _price(cart_items: list[dict[str, object]], claimed: list[str]) -> httpx.Response:
    """POST /price with the given cart lines and claimed promotion ids."""
    return client.post(
        "/price",
        json={"cart": {"items": cart_items}, "claimed_promotion_ids": claimed},
    )


class TestPrice:
    """POST /price — the contract the frontend's breakdown panel renders."""

    def test_multi_promotion_cart_exact_cents_and_trace(self) -> None:
        """Catches the API mangling the engine's result.

        A shopper stacking a BXGY, a fixed-off, and a cart-percent promo must
        see exact per-line discounts, a full explanation trace, and a total
        that ties out.
        """
        response = _price(
            [
                {
                    "sku": "COF-ETH",
                    "name": "Ethiopia Yirgacheffe, 12oz",
                    "category": "Coffee Beans",
                    "unit_price_cents": 1600,
                    "qty": 3,
                },
                {
                    "sku": "BREW-V60",
                    "category": "Brew Gear",
                    "unit_price_cents": 2800,
                    "qty": 1,
                },
            ],
            ["P1", "P4", "P2", "P7"],
        )
        assert response.status_code == 200
        body = response.json()
        # Item phase: P1 frees the cheapest bean (1600), P4 takes 500 off the
        # dripper. Cart phase: 15% of the post-item 5500 = 825, split 480/345.
        assert body["subtotal_cents"] == 7600
        assert body["discount_total_cents"] == 2925
        assert body["shipping_cents"] == 1000
        assert body["total_cents"] == 5675
        assert body["optimal"] is False
        assert body["lines"] == [
            {
                "sku": "COF-ETH",
                "name": "Ethiopia Yirgacheffe, 12oz",
                "category": "Coffee Beans",
                "unit_price_cents": 1600,
                "qty": 3,
                "line_subtotal_cents": 4800,
                "discount_cents": 2080,
                "line_total_cents": 2720,
            },
            {
                "sku": "BREW-V60",
                "name": None,
                "category": "Brew Gear",
                "unit_price_cents": 2800,
                "qty": 1,
                "line_subtotal_cents": 2800,
                "discount_cents": 845,
                "line_total_cents": 1955,
            },
        ]
        assert body["adjustments"] == [
            {
                "promotion_id": "P1",
                "promotion_name": "Beans: buy 2 get 1 free",
                "phase": "item",
                "amount_cents": 1600,
                "line_allocations": [{"sku": "COF-ETH", "amount_cents": 1600}],
            },
            {
                "promotion_id": "P4",
                "promotion_name": "$5 off pour-over dripper",
                "phase": "item",
                "amount_cents": 500,
                "line_allocations": [{"sku": "BREW-V60", "amount_cents": 500}],
            },
            {
                "promotion_id": "P2",
                "promotion_name": "15% off $50+",
                "phase": "cart",
                "amount_cents": 825,
                "line_allocations": [
                    {"sku": "COF-ETH", "amount_cents": 480},
                    {"sku": "BREW-V60", "amount_cents": 345},
                ],
            },
        ]
        # P7 was toggled on but the post-cart subtotal (4675) misses its
        # $100 threshold: claimed, never applied, no error.
        assert body["promotion_statuses"] == {
            "P1": "applied",
            "P6": "available",
            "P4": "applied",
            "P2": "applied",
            "P5": "available",
            "P7": "claimed",
        }

    def test_claimed_but_ineligible_promotion_stays_claimed(self) -> None:
        """Catches toggling an ineligible promo erroring or showing as applied.

        The UI must render it as claimed-not-applied with an undiscounted total.
        """
        response = _price(
            [
                {
                    "sku": "SNK-BSC",
                    "category": "Snacks",
                    "unit_price_cents": 900,
                    "qty": 1,
                }
            ],
            ["P2"],  # needs a $50 subtotal; this cart is $9
        )
        assert response.status_code == 200
        body = response.json()
        assert body["promotion_statuses"]["P2"] == "claimed"
        assert body["adjustments"] == []
        assert body["discount_total_cents"] == 0
        assert body["total_cents"] == 900 + 1000  # subtotal + flat shipping

    def test_unknown_claimed_id_is_422_not_500(self) -> None:
        """Catches a stale/garbage promotion id crashing the server.

        The engine's ValueError must surface as a 422 with the bad id named.
        """
        response = _price(
            [
                {
                    "sku": "SNK-BSC",
                    "category": "Snacks",
                    "unit_price_cents": 900,
                    "qty": 1,
                }
            ],
            ["P1", "NOPE"],
        )
        assert response.status_code == 422
        assert "NOPE" in response.json()["detail"]

    def test_empty_cart_is_422(self) -> None:
        """Catches the empty-cart contract drifting.

        The domain model rejects zero-line carts, so the API must answer 422,
        not price or 500.
        """
        response = _price([], ["P1"])
        assert response.status_code == 422


class TestPromotions:
    """GET /promotions — the toggle list's data source."""

    def test_lists_seeded_promotions_with_display_metadata(self) -> None:
        """Catches the toggle list losing promotions or their metadata.

        The UI needs each promotion's type, phase, target, and thresholds to
        describe it next to its checkbox.
        """
        response = client.get("/promotions")
        assert response.status_code == 200
        body = response.json()
        assert [promo["id"] for promo in body] == ["P1", "P6", "P4", "P2", "P5", "P7"]
        assert body[0] == {
            "id": "P1",
            "name": "Beans: buy 2 get 1 free",
            "type": "BXGY",
            "phase": "item",
            "target": {"kind": "category", "category": "Coffee Beans"},
            "params": {"min_qty": 3},
        }
        # Engine-injected mechanics (the shipping baseline) are not promotion
        # display data and must not leak into the list.
        assert body[-1] == {
            "id": "P7",
            "name": "Free shipping $100+",
            "type": "FREE_SHIPPING",
            "phase": "shipping",
            "target": {"kind": "shipping"},
            "params": {"min_subtotal_cents": 10000},
        }


class TestCatalog:
    """GET /catalog — the cart builder's data source."""

    def test_lists_the_eight_seeded_skus(self) -> None:
        """Catches the cart builder losing SKUs or price/category fields.

        It needs all eight seeded items to add real lines at integer-cent
        prices.
        """
        response = client.get("/catalog")
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 8
        assert body[0] == {
            "sku": "COF-ETH",
            "name": "Ethiopia Yirgacheffe, 12oz",
            "category": "Coffee Beans",
            "unit_price_cents": 1600,
        }


def test_cors_origins_env_var_enables_cors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Catches the deployed frontend being blocked by missing CORS headers.

    Setting CORS_ORIGINS must allow that origin; unset must add no header.
    """
    # Middleware is wired at import time, so exercise it via a reload.
    monkeypatch.setenv("CORS_ORIGINS", "https://web.example")
    try:
        reloaded = importlib.reload(app.main)
        with TestClient(reloaded.app) as cors_client:
            response = cors_client.get(
                "/health", headers={"Origin": "https://web.example"}
            )
        assert response.headers["access-control-allow-origin"] == "https://web.example"
    finally:
        monkeypatch.delenv("CORS_ORIGINS")
        importlib.reload(app.main)

    with TestClient(app.main.app) as plain_client:
        response = plain_client.get(
            "/health", headers={"Origin": "https://web.example"}
        )
    assert "access-control-allow-origin" not in response.headers
