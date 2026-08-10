from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from app.domain import Cart, Phase, PricingResult
from app.engine import EngineConfig, price_combination_run
from app.promotions import EligibilityGap, Promotion, targets_can_overlap


class PromotionAvailability(BaseModel):
    """Why a promotion did or did not apply, for one priced cart.

    Splits the checkout's two visually distinct "not applied" cases, which
    `PromotionStatus` alone cannot tell apart once every promotion is
    claimed by default: `eligible: false` means the cart does not qualify
    (grey it out, show `gap`), while `eligible: true` on an unapplied
    promotion means it qualifies but lost its slot to a conflicting rival
    (leave it live — the shopper may force it on).
    """

    model_config = ConfigDict(frozen=True)

    eligible: bool
    gap: EligibilityGap | None = None
    conflicts_with: list[str] = Field(default_factory=list[str])
    """Ids that cannot apply alongside this one on this cart.

    Pairwise target overlap within a phase — the same `targets_can_overlap`
    the engine enforces, so the checkout's "toggling this one off toggles
    that one on" mirrors the engine's real exclusivity instead of guessing
    it from promotion metadata.
    """


def describe_availability(
    cart: Cart,
    promotions: Sequence[Promotion],
    result: PricingResult,
    config: EngineConfig | None = None,
) -> dict[str, PromotionAvailability]:
    """Explain every promotion's fate against an already-priced result.

    Eligibility is judged against the *winning* combination's cascade states,
    not the submitted cart: a cart-phase threshold reads the subtotal net of
    the item discounts that actually landed, so "free shipping over $100" on
    a $110 cart correctly reports itself unmet once $20 of item deals fire.
    That is the honest answer to "why didn't it apply", and the shortfall in
    `gap` is measured against the same state, so hint and verdict never
    disagree.

    Reconstructs those states by re-pricing the result's own applied set
    through `price_combination_run` — the identity `price_combination(cart,
    applied) == result` is pinned by tests/test_engine.py, so this observes
    the same cascade the caller already paid for rather than trusting a
    second implementation of it.

    Args:
        cart: The cart that was priced.
        promotions: The full promotion list, in declaration order.
        result: The priced result being explained; its adjustments name the
            combination that won.
        config: Engine configuration; defaults to `EngineConfig()`.

    Returns:
        One entry per promotion in `promotions`, keyed by id.

    Raises:
        EngineInvariantError: If the result's own applied set fails to
            re-price — meaning `result` did not come from this engine.
    """
    by_id = {promotion.id: promotion for promotion in promotions}
    applied_ids = [adjustment.promotion_id for adjustment in result.adjustments]
    applied = [by_id[pid] for pid in applied_ids if pid in by_id]
    phase_inputs = price_combination_run(cart, applied, config).phase_inputs

    conflicts = _conflicts(cart, promotions)
    availability: dict[str, PromotionAvailability] = {}
    for promotion in promotions:
        state = phase_inputs.get(promotion.phase, cart)
        eligible = promotion.is_eligible(state)
        availability[promotion.id] = PromotionAvailability(
            eligible=eligible,
            # An eligible promotion has no shortfall to report, whether or
            # not it won its slot.
            gap=None if eligible else promotion.gap(state),
            conflicts_with=conflicts[promotion.id],
        )
    return availability


def _conflicts(cart: Cart, promotions: Sequence[Promotion]) -> dict[str, list[str]]:
    """Map each promotion to the same-phase ids whose targets it overlaps.

    Symmetric by construction. Note this is pairwise exclusivity, not
    cluster membership: two per-SKU promotions chained into one conflict
    cluster by a category promotion do not conflict with *each other* and
    may both apply (app/clusters.py), so neither lists the other.

    Args:
        cart: The cart overlap is decided against.
        promotions: The full promotion list, in declaration order.

    Returns:
        One entry per promotion id; ids listed in declaration order.
    """
    by_phase: dict[Phase, list[Promotion]] = {phase: [] for phase in Phase}
    for promotion in promotions:
        by_phase[promotion.phase].append(promotion)
    return {
        promotion.id: [
            other.id
            for other in by_phase[promotion.phase]
            if other.id != promotion.id
            and targets_can_overlap(promotion.target, other.target, cart)
        ]
        for promotion in promotions
    }
