import os
import re
from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from app.catalog import CatalogItem
from app.domain import Adjustment, Cart, Phase, PhaseSubtotals, PricedLine
from app.engine import EngineInvariantError, PromotionStatus, price_naive
from app.optimizer import optimize
from app.promotion_store import DuplicatePromotionIdError, PromotionStore
from app.promotions import PROMOTION_REGISTRY, Promotion, PromotionTarget
from app.seed_loader import SeedLoadError, parse_promotions
from app.seeds import load_seed_catalog, load_seed_promotions


def _resolve_promotions_db_path() -> Path:
    """Resolve where runtime promotion additions persist (issue #75).

    Returns:
        The `PROMOTIONS_DB_PATH` environment variable if set, else
        `data/promotions.db` under `backend/` (this file's grandparent).
        The file need not exist yet — the store creates it on first write.
    """
    env_path = os.environ.get("PROMOTIONS_DB_PATH", "").strip()
    if env_path:
        return Path(env_path)
    return Path(__file__).resolve().parent.parent / "data" / "promotions.db"


# Seed data is loaded once at import time (the app has no lifespan hooks);
# requests never re-read the seed files. `POST /promotions` appends runtime
# additions to the store, which persists them to SQLite (issue #75) and
# replays them at boot — seeds themselves stay file-based, and there is
# still no database for the catalog or carts (docs/scope.md).
PROMOTION_STORE = PromotionStore(
    load_seed_promotions(), db_path=_resolve_promotions_db_path()
)
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
    frozen for existing fields — #25 swaps in the optimizer's numbers and
    flips `optimal` without changing it; `phase_subtotals` is an additive
    field for the checkout deals explainer) plus `promotion_statuses`, one
    entry per stored promotion (seeds and runtime additions alike), so the
    UI can distinguish claimed-but-ineligible from applied.
    """

    model_config = ConfigDict(frozen=True)

    lines: list[PricedLine]
    adjustments: list[Adjustment]
    subtotal_cents: int
    discount_total_cents: int
    shipping_cents: int
    total_cents: int
    optimal: bool
    phase_subtotals: PhaseSubtotals | None
    promotion_statuses: dict[str, PromotionStatus]


class PromotionSource(StrEnum):
    """Where a stored promotion came from — file seeds or the admin API."""

    SEED = "seed"
    RUNTIME = "runtime"


class PromotionInfo(BaseModel):
    """One `GET /promotions` entry: identity plus display metadata.

    `params` carries the kind-specific condition/effect fields (`min_qty`,
    `percent_off`, ...) so the toggle list can describe each promotion
    without hardcoding kinds. `source` (additive) lets the admin page badge
    seeds vs runtime additions.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    type: str
    phase: Phase
    target: PromotionTarget
    params: dict[str, int]
    source: PromotionSource


# Fields every kind shares (or that are engine-injected mechanics, like
# FreeShipping's shipping_baseline_cents) — everything else is a
# kind-specific condition/effect parameter worth displaying.
_NON_PARAM_FIELDS = frozenset({"id", "name", "target", "shipping_baseline_cents"})

_TYPE_BY_CLASS: dict[type[Promotion], str] = {
    cls: type_key for type_key, cls in PROMOTION_REGISTRY.items()
}


def _promotion_info(promotion: Promotion, source: PromotionSource) -> PromotionInfo:
    """Project one stored promotion into its `GET /promotions` entry.

    Args:
        promotion: A stored (seed or runtime-added) promotion instance.
        source: Whether the promotion is a file seed or a runtime addition.

    Returns:
        The promotion's identity, type key, phase, target, source, and
        kind-specific display parameters.
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
        source=source,
    )


def _next_promotion_id(existing_ids: set[str]) -> str:
    """Next free auto-assigned promotion id: one past the highest P-number.

    Ids that don't match `P<digits>` (custom ids callers chose themselves)
    are ignored — they can never collide with the generated sequence's next
    value unless they are themselves P-numbered.

    Args:
        existing_ids: Every stored promotion id, seeds and additions.

    Returns:
        The id `P<n+1>` where `n` is the highest existing P-number (0 when
        there is none).
    """
    highest = 0
    for existing in existing_ids:
        match = re.fullmatch(r"P(\d+)", existing)
        if match is not None:
            highest = max(highest, int(match.group(1)))
    return f"P{highest + 1}"


def _find_structural_duplicate(
    candidate: Promotion, existing: Sequence[Promotion]
) -> Promotion | None:
    """Find a stored promotion with the candidate's exact type and terms.

    Identity fields (`id`, `name`) are ignored — two promotions are
    duplicates when the same kind targets the same thing with the same
    parameters, which is shopper-facing noise (they share a conflict
    cluster, so only one could ever apply). Enforced only on new adds:
    boot replay never runs this, so any pre-existing duplicate keeps
    loading.

    Args:
        candidate: The promotion being added.
        existing: Every stored promotion, seeds and additions.

    Returns:
        The first structural duplicate, or None.
    """
    key = candidate.model_dump(exclude={"id", "name"})
    for promotion in existing:
        if (
            type(promotion) is type(candidate)
            and promotion.model_dump(exclude={"id", "name"}) == key
        ):
            return promotion
    return None


@app.get("/health")
def health() -> dict[str, str]:
    """Report service liveness for deployment healthchecks.

    Returns:
        A minimal status payload.
    """
    return {"status": "ok"}


@app.post("/price")
def price(request: PriceRequest) -> PriceResponse:
    """Price a cart with both engines, returning the sanity-checked best.

    Every request computes the naive engine and the optimizer
    (docs/optimizer-spec.md's API surface — no opt-in flag). The runtime
    sanity check gates the optimized result: it is returned only if
    `0 < optimized_total <= naive_total`; otherwise (or when the optimizer
    already fell back on its cluster-product cap) the naive outcome is
    returned with `optimal: False`. Statuses reflect whichever result is
    returned; a claimed promotion the optimizer withheld stays `claimed`.

    Args:
        request: The cart and the ids of the promotions the shopper toggled
            on.

    Returns:
        The itemized result, explanation trace, totals, `optimal`, and one
        status per stored promotion.

    Raises:
        HTTPException: 422 if a claimed id names no seeded promotion.
        EngineInvariantError: If a pricing invariant is violated — a server
            bug, surfaced as a 500 rather than mapped to a client error.
    """
    promotions = PROMOTION_STORE.all()
    try:
        naive = price_naive(request.cart, promotions, request.claimed_promotion_ids)
        optimized = optimize(request.cart, promotions, request.claimed_promotion_ids)
    except EngineInvariantError:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # Runtime sanity check (docs/optimizer-spec.md): a live guard, not just
    # an offline property test. A legitimately-zero optimized total also
    # falls back — naive would be zero too, so nothing is lost.
    if 0 < optimized.result.total_cents <= naive.result.total_cents:
        outcome = optimized
    else:
        outcome = naive
    result = outcome.result
    return PriceResponse(
        lines=result.lines,
        adjustments=result.adjustments,
        subtotal_cents=result.subtotal_cents,
        discount_total_cents=result.discount_total_cents,
        shipping_cents=result.shipping_cents,
        total_cents=result.total_cents,
        optimal=result.optimal,
        phase_subtotals=result.phase_subtotals,
        promotion_statuses=outcome.statuses,
    )


@app.get("/promotions")
def promotions() -> list[PromotionInfo]:
    """List every promotion for the UI's toggle list.

    Returns:
        Seeds first, then runtime additions, in insertion (declaration)
        order — the same order the naive engine breaks cluster ties in.
    """
    addition_ids = PROMOTION_STORE.addition_ids()
    return [
        _promotion_info(
            promotion,
            PromotionSource.RUNTIME
            if promotion.id in addition_ids
            else PromotionSource.SEED,
        )
        for promotion in PROMOTION_STORE.all()
    ]


@app.post("/promotions", status_code=201)
def add_promotion(entry: dict[str, object]) -> PromotionInfo:
    """Add one promotion at runtime (issue #68's unauthenticated admin API).

    The body is one seed-entry object — the same shape as an
    `app/seeds/promotions.json` entry: a `type` registry key, `name`,
    `target`, the kind's own fields, and optionally an `id` (omitted or
    null, the server assigns the next free `P<n>` and returns it). It is
    validated through the seed loader, so every seed rule applies
    (registered kind, correctly-scoped target, kind field constraints).
    The addition is persisted to the store's SQLite file (issue #75) and
    survives restarts; `POST /price` picks it up immediately with no
    engine changes, since clusters and the optimizer derive everything
    from the promotion list.

    Args:
        entry: One raw seed-entry mapping.

    Returns:
        The stored promotion, serialized exactly as `GET /promotions` lists
        it, with a 201 status.

    Raises:
        HTTPException: 422 if the entry fails seed validation, reuses an
            existing promotion id (seed or prior addition), or structurally
            duplicates an existing promotion (same kind, target, and
            parameters — only id/name differing).
    """
    stored_entry = dict(entry)
    if stored_entry.get("id") is None:
        # Auto-assign the next free P<n> (additive: explicit ids still
        # accepted). The assigned id is written into the persisted entry so
        # a restart replays exactly what was validated. A concurrent add
        # racing to the same number loses in the store and 422s — at admin
        # rates that is acceptable over holding a lock across validation.
        stored_entry["id"] = _next_promotion_id(
            {promotion.id for promotion in PROMOTION_STORE.all()}
        )
    try:
        promotion = parse_promotions([stored_entry])[0]
    except SeedLoadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    duplicate = _find_structural_duplicate(promotion, PROMOTION_STORE.all())
    if duplicate is not None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"duplicates existing promotion {duplicate.id!r}"
                f" ({duplicate.name}) — same type, target, and terms"
            ),
        )
    try:
        PROMOTION_STORE.add(promotion, stored_entry)
    except DuplicatePromotionIdError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _promotion_info(promotion, PromotionSource.RUNTIME)


@app.get("/catalog")
def catalog() -> list[CatalogItem]:
    """List the seeded catalog for the UI's cart builder.

    Returns:
        Every catalog item, in seed order.
    """
    return CATALOG
