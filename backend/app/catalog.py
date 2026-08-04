import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from app.domain import NonBlankStr
from app.seed_loader import SeedLoadError


class CatalogItem(BaseModel):
    """One sellable product: the source of truth the cart builder picks from.

    Served to the frontend (via #22's API) so shoppers assemble carts from
    real SKUs at integer-cent prices — display formatting to `$D.CC` is the
    frontend's job; storage and computation stay integer cents.
    """

    model_config = ConfigDict(frozen=True)

    sku: NonBlankStr
    name: NonBlankStr
    category: NonBlankStr
    unit_price_cents: int = Field(ge=0)


_CATALOG_ADAPTER: TypeAdapter[list[CatalogItem]] = TypeAdapter(list[CatalogItem])


def parse_catalog(data: object) -> list[CatalogItem]:
    """Validate parsed catalog seed data into `CatalogItem` instances.

    Args:
        data: The parsed payload — must be a list of mappings with each
            item's sku, name, category, and unit_price_cents.

    Returns:
        One catalog item per entry, in seed order.

    Raises:
        SeedLoadError: If the payload is not a list, an entry fails
            validation, or two entries share a SKU — the loader fails loud
            rather than skipping bad entries.
    """
    try:
        items = _CATALOG_ADAPTER.validate_python(data)
    except ValidationError as exc:
        raise SeedLoadError(f"invalid catalog seed data: {exc}") from exc
    skus = [item.sku for item in items]
    if len(skus) != len(set(skus)):
        raise SeedLoadError("catalog seed entries must have unique SKUs")
    return items


def load_catalog(path: Path) -> list[CatalogItem]:
    """Load a JSON catalog seed file into `CatalogItem` instances.

    The file holds a top-level JSON array of catalog entries — same format
    choice (JSON, fail-loud) as the promotion seed loader.

    Args:
        path: Path to the catalog seed file.

    Returns:
        One catalog item per entry, in file order.

    Raises:
        SeedLoadError: If the file cannot be read, is not valid JSON, or
            its entries fail `parse_catalog` validation.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SeedLoadError(f"cannot read catalog seed file {path}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SeedLoadError(
            f"catalog seed file {path} is not valid JSON: {exc}"
        ) from exc
    try:
        return parse_catalog(data)
    except SeedLoadError as exc:
        raise SeedLoadError(f"catalog seed file {path}: {exc}") from exc
