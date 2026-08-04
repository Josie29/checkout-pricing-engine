import threading
from collections.abc import Sequence

from app.promotions import Promotion


class DuplicatePromotionIdError(ValueError):
    """A promotion was added under an id the store already holds."""


class PromotionStore:
    """In-memory promotion list: the seed set plus runtime additions.

    Deliberately not persisted — this project has no database
    (docs/scope.md), so promotions added at runtime last only until the
    process restarts, at which point the store reboots with just the seeds.
    `all()` returns seeds then additions in insertion order, which is the
    engine's declaration order — added promotions extend the naive engine's
    first-eligible-per-cluster ordering after every seed.

    The lock documents intent more than it defends anything: uvicorn runs a
    single process and the two guarded operations are tiny, but interleaving
    a duplicate-id check with an append would still be a bug worth making
    impossible.
    """

    def __init__(self, seeds: Sequence[Promotion]) -> None:
        """Initialize the store with the seed promotions.

        Args:
            seeds: The seed promotions, in declaration order. Assumed to
                already have unique ids (the seed loader enforces this).
        """
        self._lock = threading.Lock()
        self._seeds: list[Promotion] = list(seeds)
        self._additions: list[Promotion] = []

    def all(self) -> list[Promotion]:
        """Every promotion, seeds first, then additions in insertion order.

        Returns:
            A fresh list — callers may not mutate store state through it.
        """
        with self._lock:
            return [*self._seeds, *self._additions]

    def add(self, promotion: Promotion) -> None:
        """Add a runtime promotion after the seeds and prior additions.

        Args:
            promotion: A validated promotion instance to append.

        Raises:
            DuplicatePromotionIdError: If a seed or a prior addition already
                uses `promotion.id`.
        """
        with self._lock:
            if any(
                existing.id == promotion.id
                for existing in (*self._seeds, *self._additions)
            ):
                raise DuplicatePromotionIdError(
                    f"promotion id {promotion.id!r} already exists"
                )
            self._additions.append(promotion)

    def clear_additions(self) -> None:
        """Drop every runtime addition, keeping the seeds (testing hook).

        Tests that add promotions call this to restore the boot state; the
        app itself never does.
        """
        with self._lock:
            self._additions.clear()
