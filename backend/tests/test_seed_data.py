from pathlib import Path

import pytest

from app.catalog import CatalogItem, load_catalog, parse_catalog
from app.promotion_kinds import (
    BuyXGetYFree,
    FixedOffItem,
    FreeShipping,
    PercentOffCart,
    PercentOffItem,
)
from app.promotions import CategoryTarget, SkuTarget
from app.seed_loader import SeedLoadError
from app.seeds import load_seed_catalog, load_seed_promotions


class TestPromotionSeed:
    """The packaged seed must match docs/seed-promotions.md's tables."""

    def test_seed_loads_all_promotions_in_table_order(self) -> None:
        """P1/P6/P4/P2/P5/P7 load as the right classes, in doc order.

        Catches the shipped seed drifting from the seed doc — a promotion
        the business expects live would be missing, mistyped, or reordered
        (order is the naive engine's declaration-order tie-break).
        """
        promotions = load_seed_promotions()
        assert [(p.id, type(p)) for p in promotions] == [
            ("P1", BuyXGetYFree),
            ("P6", PercentOffItem),
            ("P4", FixedOffItem),
            ("P2", PercentOffCart),
            ("P5", PercentOffCart),
            ("P7", FreeShipping),
        ]

    def test_seed_conditions_and_effects_match_the_doc(self) -> None:
        """Each seeded promotion carries the doc's exact numbers.

        Catches a fat-fingered threshold or percentage — e.g. 15% off at
        $50 becoming $500, silently denying every real-world cart.
        """
        by_id = {p.id: p for p in load_seed_promotions()}
        p1 = by_id["P1"]
        assert isinstance(p1, BuyXGetYFree)
        assert p1.target == CategoryTarget(category="Coffee Beans")
        assert p1.min_qty == 3
        p6 = by_id["P6"]
        assert isinstance(p6, PercentOffItem)
        assert p6.target == CategoryTarget(category="Coffee Beans")
        assert (p6.min_qty, p6.percent_off) == (3, 20)
        p4 = by_id["P4"]
        assert isinstance(p4, FixedOffItem)
        assert p4.target == SkuTarget(sku="BREW-V60")
        assert p4.amount_off_cents == 500
        p2 = by_id["P2"]
        assert isinstance(p2, PercentOffCart)
        assert (p2.min_subtotal_cents, p2.percent_off) == (5000, 15)
        p5 = by_id["P5"]
        assert isinstance(p5, PercentOffCart)
        assert (p5.min_subtotal_cents, p5.percent_off) == (10000, 20)
        p7 = by_id["P7"]
        assert isinstance(p7, FreeShipping)
        assert p7.min_subtotal_cents == 10000
        # Baseline stays engine config: the seed relies on the default.
        assert p7.shipping_baseline_cents == 1000


class TestCatalogSeed:
    """The packaged catalog must match docs/seed-promotions.md's table."""

    def test_catalog_has_the_eight_skus_with_table_prices(self) -> None:
        """All 8 SKUs load with the doc's exact categories and cent prices.

        Catches catalog drift — a renamed category would detach P1/P6 from
        the bean lines, and a wrong price misprices every cart built from
        the frontend's catalog picker.
        """
        items = load_seed_catalog()
        assert [(i.sku, i.category, i.unit_price_cents) for i in items] == [
            ("COF-ETH", "Coffee Beans", 1600),
            ("COF-COL", "Coffee Beans", 1400),
            ("COF-DEC", "Coffee Beans", 1500),
            ("BREW-V60", "Brew Gear", 2800),
            ("BREW-GRD", "Brew Gear", 4500),
            ("MUG-CLS", "Drinkware", 1200),
            ("MUG-TVL", "Drinkware", 2200),
            ("SNK-BSC", "Snacks", 900),
        ]
        assert all(i.name for i in items)


class TestCatalogLoader:
    """Catalog loading fails loud on anything it does not fully understand."""

    @staticmethod
    def entry() -> dict[str, object]:
        """One valid raw catalog entry."""
        return {
            "sku": "COF-ETH",
            "name": "Ethiopia Yirgacheffe, 12oz",
            "category": "Coffee Beans",
            "unit_price_cents": 1600,
        }

    def test_duplicate_skus_fail_loud(self) -> None:
        """Two entries sharing a SKU raise.

        Catches a copy-pasted catalog row — duplicate SKUs would make cart
        lines (keyed by SKU) ambiguous about which product they price.
        """
        with pytest.raises(SeedLoadError, match="unique SKUs"):
            parse_catalog([self.entry(), dict(self.entry(), name="Same SKU again")])

    def test_invalid_entry_fails_loud(self) -> None:
        """A malformed entry (non-integer price) raises, never coerces.

        Catches a bad price sneaking into the catalog as 0 or garbage —
        every cart containing that SKU would be mispriced.
        """
        with pytest.raises(SeedLoadError, match="invalid catalog"):
            parse_catalog([dict(self.entry(), unit_price_cents="cheap")])

    def test_non_list_payload_fails_loud(self) -> None:
        """A payload that is not a top-level list raises.

        Catches format drift (entries wrapped in an object) silently
        loading an empty catalog.
        """
        with pytest.raises(SeedLoadError):
            parse_catalog({"catalog": [self.entry()]})

    def test_file_round_trip(self, tmp_path: Path) -> None:
        """A JSON catalog file on disk loads into `CatalogItem`s.

        Catches file-level plumbing breaking (encoding, parsing) even when
        in-memory validation works — the boot path goes through a file.
        """
        path = tmp_path / "catalog.json"
        path.write_text(
            '[{"sku": "X", "name": "X", "category": "C", "unit_price_cents": 1}]',
            encoding="utf-8",
        )
        assert load_catalog(path) == [
            CatalogItem(sku="X", name="X", category="C", unit_price_cents=1)
        ]

    def test_missing_file_fails_loud(self, tmp_path: Path) -> None:
        """A nonexistent catalog path raises SeedLoadError, not bare OSError.

        Catches a misconfigured seed path surfacing as an unhandled crash
        with no hint it is a seed-loading problem.
        """
        with pytest.raises(SeedLoadError, match="cannot read"):
            load_catalog(tmp_path / "nope.json")
