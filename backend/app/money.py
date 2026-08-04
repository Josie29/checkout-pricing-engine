from collections.abc import Sequence


def allocate_proportionally(amount_cents: int, weights: Sequence[int]) -> list[int]:
    """Split an integer-cent amount across weights, summing exactly.

    Largest-remainder method: each position gets the floor of its proportional
    share, then the leftover cents go one each to the positions with the
    largest fractional remainders. Ties break toward the earlier position, so
    the split is deterministic. This is the "no rounding drift" invariant —
    the returned shares always sum to exactly `amount_cents`.

    The helper does not cap shares at the weights; a caller allocating a
    discount larger than the amounts being discounted must cap before calling.

    Args:
        amount_cents: Non-negative amount to split, in integer cents.
        weights: One non-negative integer weight per position (typically line
            subtotals in cents). Must be non-empty.

    Returns:
        One non-negative share per weight, in order, summing to `amount_cents`.

    Raises:
        ValueError: If `amount_cents` is negative, `weights` is empty, any
            weight is negative, or all weights are zero while `amount_cents`
            is positive (there is no proportion to split by).
    """
    if amount_cents < 0:
        raise ValueError("amount_cents must be non-negative")
    if not weights:
        raise ValueError("weights must be non-empty")
    if any(weight < 0 for weight in weights):
        raise ValueError("weights must be non-negative")
    total_weight = sum(weights)
    if total_weight == 0:
        if amount_cents == 0:
            return [0] * len(weights)
        raise ValueError("cannot split a positive amount across all-zero weights")

    # Floor division for the guaranteed whole-cent share per position.
    shares = [amount_cents * weight // total_weight for weight in weights]
    leftover = amount_cents - sum(shares)
    # Rank positions by fractional remainder (amount*weight mod total), largest
    # first; equal remainders break toward the earlier index for determinism.
    by_remainder = sorted(
        range(len(weights)),
        key=lambda i: (-(amount_cents * weights[i] % total_weight), i),
    )
    for i in by_remainder[:leftover]:
        shares[i] += 1
    return shares
