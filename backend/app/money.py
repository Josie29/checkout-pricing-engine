from collections.abc import Sequence


def percent_of_cents(base_cents: int, percent: int) -> int:
    """Whole-number percentage of an integer-cent amount, rounded half-up.

    The project-wide percentage rounding rule: a percentage discount is
    computed exactly once, at the promotion's aggregate base (the matched
    subtotal), rounded half-up to the cent (0.5 rounds away from zero, so
    20% of 1002 = 200.4 -> 200 and 15% of 30 = 4.5 -> 5). Per-line amounts
    then come from `allocate_proportionally`, never from re-rounding
    percentages per line — one rounding site keeps the split deterministic
    and drift-free.

    Half-up over bankers' rounding: it matches what a shopper computes by
    hand, and at the half-cent it favors the customer on a discount.

    Args:
        base_cents: Non-negative base amount in integer cents.
        percent: Whole-number percentage, 0-100 inclusive. Fractional
            percentages are deliberately unsupported — no seed needs them,
            and floats never touch money.

    Returns:
        `percent`% of `base_cents`, rounded half-up to an integer cent.

    Raises:
        ValueError: If `base_cents` is negative or `percent` is outside
            0-100.
    """
    if base_cents < 0:
        raise ValueError("base_cents must be non-negative")
    if not 0 <= percent <= 100:
        raise ValueError("percent must be between 0 and 100 inclusive")
    # +50 before floor-dividing by 100 implements round-half-up on the cent.
    return (base_cents * percent + 50) // 100


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
