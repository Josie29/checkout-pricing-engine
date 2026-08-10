from collections.abc import Sequence

from app.domain import Cart
from app.promotions import Promotion, targets_can_overlap


def assert_no_overlapping_pair(applied: Sequence[Promotion], cart: Cart) -> None:
    """Assert the legality rule: no two applied promotions share a resource.

    The exclusivity rule (docs/seed-promotions.md) is pairwise — at most one
    Item-phase promo *per line item* — not one per conflict cluster. Asserting
    per-cluster instead would wrongly forbid two promotions that share a
    cluster only through a third (the bug where `$1 off Ethiopia` and `$1 off
    Colombia` were chained by a Coffee Beans promotion and only one applied),
    while still missing a genuine double-discount on a cart whose clustering
    was mis-derived.

    Args:
        applied: The promotions the result actually applied.
        cart: The cart overlap is decided against.

    Raises:
        AssertionError: If two applied promotions of one phase have targets
            that overlap on `cart`.
    """
    for index, first in enumerate(applied):
        for second in applied[index + 1 :]:
            assert first.phase is not second.phase or not targets_can_overlap(
                first.target, second.target, cart
            ), f"{first.id} and {second.id} both discount the same resource"
