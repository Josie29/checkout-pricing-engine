from pathlib import Path

# Imported for its side effect: registers the five seeded kinds.
import app.promotion_kinds  # noqa: F401  # pyright: ignore[reportUnusedImport]
from app.catalog import CatalogItem, load_catalog
from app.promotions import Promotion
from app.seed_loader import load_promotions

SEEDS_DIR = Path(__file__).resolve().parent
PROMOTIONS_SEED_PATH = SEEDS_DIR / "promotions.json"
CATALOG_SEED_PATH = SEEDS_DIR / "catalog.json"


def load_seed_promotions() -> list[Promotion]:
    """Load the packaged Roast & Co promotion seed (P1-P7).

    Importing this package registers the seeded kinds, so callers need no
    other wiring — this is the entry point the app boots through.

    Returns:
        The seed promotions in file order (the engine's declaration order).

    Raises:
        SeedLoadError: If the packaged seed file is missing or invalid.
    """
    return load_promotions(PROMOTIONS_SEED_PATH)


def load_seed_catalog() -> list[CatalogItem]:
    """Load the packaged eight-SKU Roast & Co catalog seed.

    Returns:
        The catalog items in file order.

    Raises:
        SeedLoadError: If the packaged seed file is missing or invalid.
    """
    return load_catalog(CATALOG_SEED_PATH)
