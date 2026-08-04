import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from app.catalog import CatalogItem
from app.domain import Adjustment, Cart, Phase, PricedLine
from app.engine import EngineInvariantError, PromotionStatus, price_naive
from app.promotions import PROMOTION_REGISTRY, Promotion, PromotionTarget
from app.seeds import load_seed_catalog, load_seed_promotions

# Seed data is loaded once at import time (the app has no lifespan hooks);
# requests never re-read the seed files.
PROMOTIONS: list[Promotion] = load_seed_promotions()
CATALOG: list[CatalogItem] = load_seed_catalog()

app = FastAPI(title="Pricing Engine")

# Comma-separated allowed origins for the separately-hosted frontend
# (docs/deployment-plan.md's CORS_ORIGINS variable). Unset/empty leaves the
# Cross-Origin Resource Sharing (CORS) middleware off entirely.
_cors_origins = [
    origin.strip()
    for origin in os.environ.get("CORS_ORIGINS", "").split(",")
    if origin.strip()
]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )


class PriceRequest(BaseModel):
    """`POST /price` payload: the cart plus the shopper's claimed promotions."""

    model_config = ConfigDict(frozen=True)

    cart: Cart
    claimed_promotion_ids: list[str] = Field(default_factory=list[str])


class PriceResponse(BaseModel):
    """`POST /price` response: the priced result plus per-promotion statuses.

    Carries `PricingResult`'s fields verbatim at the top level (this shape is
    frozen — #25 swaps in the optimizer's numbers and flips `optimal` without
    changing it) plus `promotion_statuses`, one entry per seeded promotion, so
    the UI can distinguish claimed-but-ineligible from applied.
    """

    model_config = ConfigDict(frozen=True)

    lines: list[PricedLine]
    adjustments: list[Adjustment]
    subtotal_cents: int
    discount_total_cents: int
    shipping_cents: int
    total_cents: int
    optimal: bool
    promotion_statuses: dict[str, PromotionStatus]


class PromotionInfo(BaseModel):
    """One `GET /promotions` entry: identity plus display metadata.

    `params` carries the kind-specific condition/effect fields (`min_qty`,
    `percent_off`, ...) so the toggle list can describe each promotion
    without hardcoding kinds.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    type: str
    phase: Phase
    target: PromotionTarget
    params: dict[str, int]


# Fields every kind shares (or that are engine-injected mechanics, like
# FreeShipping's shipping_baseline_cents) — everything else is a
# kind-specific condition/effect parameter worth displaying.
_NON_PARAM_FIELDS = frozenset({"id", "name", "target", "shipping_baseline_cents"})

_TYPE_BY_CLASS: dict[type[Promotion], str] = {
    cls: type_key for type_key, cls in PROMOTION_REGISTRY.items()
}


def _promotion_info(promotion: Promotion) -> PromotionInfo:
    """Project one seeded promotion into its `GET /promotions` entry.

    Args:
        promotion: A seeded promotion instance.

    Returns:
        The promotion's identity, type key, phase, target, and kind-specific
        display parameters.
    """
    params = {
        field: value
        for field, value in promotion.model_dump().items()
        if field not in _NON_PARAM_FIELDS and isinstance(value, int)
    }
    return PromotionInfo(
        id=promotion.id,
        name=promotion.name,
        type=_TYPE_BY_CLASS[type(promotion)],
        phase=promotion.phase,
        target=promotion.target,
        params=params,
    )


@app.get("/health")
def health() -> dict[str, str]:
    """Report service liveness for deployment healthchecks.

    Returns:
        A minimal status payload.
    """
    return {"status": "ok"}


@app.post("/price")
def price(request: PriceRequest) -> PriceResponse:
    """Price a cart with the naive engine against the seeded promotions.

    Args:
        request: The cart and the ids of the promotions the shopper toggled
            on.

    Returns:
        The itemized result, explanation trace, totals, and one status per
        seeded promotion. `optimal` stays False until the optimizer (#25)
        lands.

    Raises:
        HTTPException: 422 if a claimed id names no seeded promotion.
        EngineInvariantError: If a pricing invariant is violated — a server
            bug, surfaced as a 500 rather than mapped to a client error.
    """
    try:
        outcome = price_naive(request.cart, PROMOTIONS, request.claimed_promotion_ids)
    except EngineInvariantError:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result = outcome.result
    return PriceResponse(
        lines=result.lines,
        adjustments=result.adjustments,
        subtotal_cents=result.subtotal_cents,
        discount_total_cents=result.discount_total_cents,
        shipping_cents=result.shipping_cents,
        total_cents=result.total_cents,
        optimal=result.optimal,
        promotion_statuses=outcome.statuses,
    )


@app.get("/promotions")
def promotions() -> list[PromotionInfo]:
    """List the seeded promotions for the UI's toggle list.

    Returns:
        Every seeded promotion, in seed (declaration) order.
    """
    return [_promotion_info(promotion) for promotion in PROMOTIONS]


@app.get("/catalog")
def catalog() -> list[CatalogItem]:
    """List the seeded catalog for the UI's cart builder.

    Returns:
        Every catalog item, in seed order.
    """
    return CATALOG
