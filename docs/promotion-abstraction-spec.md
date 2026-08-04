# Spec — Promotion Abstraction (Contained-Change Interface)

Closes issue #8, per docs/scope.md's "Promotion abstraction" line. Goal: adding a new promotion kind is one new class + one registration call — no edits to the stacking engine, the seed loader, or other promotion classes.

## Interface

```python
class Promotion(BaseModel, ABC):
    id: str
    name: str
    target: PromotionTarget          # SkuTarget | CategoryTarget | CartTarget | ShippingTarget
    phase: ClassVar[Phase]           # set per subclass, not a field — see "Phase" below

    @abstractmethod
    def is_eligible(self, cart: Cart) -> bool: ...

    @abstractmethod
    def apply(self, cart: Cart) -> Adjustment: ...
```

`Cart` here is the phase-cascade state at that point, not necessarily the original request payload — per docs/seed-promotions.md's phase table, Item phase checks the original cart, Cart phase checks the post-Item subtotal, Shipping phase checks the post-Cart state. `Adjustment` is docs/scope.md's existing domain object (what applied, to which lines, in what amount) — this spec doesn't introduce a new explanation-trace type.

**Phase is a `ClassVar`, not a field.** docs/seed-promotions.md: "Phase is a property of Type, not authored per promotion instance." Making it a field would let a seed file author a `BXGY` instance into the Cart phase, silently breaking the cascade; a `ClassVar` set once per subclass makes that impossible by construction.

**Target is a discriminated union**, not a free-form string, because docs/optimizer-spec.md's cluster derivation depends on comparing it: "two promotions share a cluster if their targets can overlap on a given cart." `SkuTarget`/`CategoryTarget` carry the SKU or category string; `CartTarget`/`ShippingTarget` are singleton markers (nothing to overlap on beyond phase itself). The engine and optimizer only ever need to ask "can these two targets overlap on some cart" — the union exists to answer that question, not to hold display text.

**Condition and effect are not separate generic objects.** Each concrete class declares whatever typed fields its own condition/effect need (`min_qty: int`, `discount_pct: float`, `fixed_amount_cents: int`, `min_subtotal_cents: int`, ...) and encodes both directly in `is_eligible`/`apply`. The five kinds in docs/seed-promotions.md (BXGY, PCT_OFF_ITEM, FIXED_OFF_ITEM, PCT_OFF_CART, FREE_SHIPPING) each need a different, non-overlapping combination of inputs — there's nothing shared to factor into a generic Condition/Effect graph, and building one now would be indirection with no reuse behind it. Matches docs/optimizer-spec.md's stated bias: "the simple option, not a fallback from a more complex one."

## Registration

A module-level registry populated by a class decorator:

```python
PROMOTION_REGISTRY: dict[str, type[Promotion]] = {}

def register_promotion(type_key: str):
    def decorator(cls: type[Promotion]) -> type[Promotion]:
        PROMOTION_REGISTRY[type_key] = cls
        return cls
    return decorator

@register_promotion("BXGY")
class BuyXGetYFree(Promotion):
    phase: ClassVar[Phase] = Phase.ITEM
    min_qty: int
    ...
```

The seed loader builds its Pydantic discriminated union from `PROMOTION_REGISTRY` at import time (keyed on each seed entry's `type` field, already present in docs/seed-promotions.md's table) rather than a hand-maintained `Union[...]` type. A new kind registering itself is sufficient — no edit to the loader, the union type, or the stacking engine.

New-kind checklist:
1. Subclass `Promotion`; set `phase: ClassVar[Phase]`.
2. Implement `is_eligible` and `apply`.
3. Decorate with `@register_promotion("<TYPE>")`.
4. Add seed instances under that `type` string (docs/seed-promotions.md).

## Exclusivity — already resolved, not an interface concern

Issue #8 asked where the exclusivity-group tie-break fits in this interface. It doesn't need to: docs/seed-promotions.md ("How exclusivity works") and docs/optimizer-spec.md's cluster derivation already settled it structurally — two promotions conflict iff they share a `phase` and their `target`s can overlap on some cart. Both `phase` and `target` are interface fields above; no separate `exclusivity_group` field is added. An authored field would let a promotion declare exclusivity inconsistent with its actual target overlap — something the structural derivation can't do wrong, because it isn't authored per instance.

## Contract between `is_eligible` and `apply`

`apply` is only ever called by the engine after `is_eligible` has returned `True` for the same `Cart` (docs/core-engine-spec.md's Claimed → Applied transition). `apply` may assume eligibility and must not re-check it or mutate its input `Cart`.

## Test contract (docs/testing-strategy.md's "Unit, per promotion kind")

Generic, run once and parametrized across every entry in `PROMOTION_REGISTRY` — a new kind gets this coverage for free, no new test file required:

- Registers under a unique `type` string; round-trips through the seed loader (seed JSON/YAML in → correct subclass instance out).
- `phase` is a `ClassVar`, not a field.
- `is_eligible` is a pure predicate over `Cart` — false just below its condition, true at/above it (boundary-tested, e.g. qty-1 vs. qty, subtotal_cents-1 vs. subtotal_cents).
- `apply`, given an eligible `Cart`, returns an `Adjustment` whose amount is deterministic and does not mutate the input `Cart`.

Per-kind unit tests then only cover kind-specific condition/effect math (e.g., BXGY's "cheapest unit free" line selection) — the generic contract above is what the stacking engine and optimizer actually depend on to treat every kind uniformly.

## Non-goals

- Generic Condition/Effect object model — no reuse benefit across today's five kinds; add only if a future kind shares structure with an existing one.
- `exclusivity_group` field — superseded by the phase + target derivation above.
- Plugin discovery via entry points or filesystem scanning — a decorator registry is sufficient at this scale; entry points solve external packages registering into an app, which this project doesn't have.
