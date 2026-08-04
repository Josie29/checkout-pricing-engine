import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.money import allocate_proportionally


def test_even_three_way_split_sums_exactly() -> None:
    """An even three-way split loses no cents.

    Catches the classic drift bug: $1.00 split across 3 equal lines showing
    33+33+33=99 — the receipt's line discounts wouldn't sum to the advertised
    discount. Leftover cent goes to the earliest line.
    """
    assert allocate_proportionally(100, [1, 1, 1]) == [34, 33, 33]


def test_one_cent_across_two_lines() -> None:
    """One indivisible cent lands on exactly one line.

    Catches the cent vanishing or doubling: 1 cent over two equal lines must
    land on the earlier line, deterministically.
    """
    assert allocate_proportionally(1, [1, 1]) == [1, 0]


def test_zero_amount_allocates_zeros() -> None:
    """A zero amount allocates zero to every line.

    Catches a zero-value promotion producing phantom per-line discounts.
    """
    assert allocate_proportionally(0, [500, 300]) == [0, 0]


def test_single_line_gets_full_amount() -> None:
    """A single line receives the full amount.

    Catches a one-line cart receiving less than the full promised discount.
    """
    assert allocate_proportionally(250, [999]) == [250]


def test_split_is_proportional_to_weights() -> None:
    """Shares follow the weights, not a uniform split.

    Catches uniform splitting where an expensive line and a cheap line get
    the same discount share — a $3 line must absorb 3x what a $1 line does.
    """
    assert allocate_proportionally(100, [300, 100]) == [75, 25]


def test_zero_weight_line_gets_nothing() -> None:
    """A zero-weight line gets a zero share.

    Catches a free (zero-subtotal) line absorbing discount that belongs to
    paid lines — its share must be exactly zero.
    """
    assert allocate_proportionally(90, [0, 60, 30]) == [0, 60, 30]


def test_ties_break_toward_earlier_lines() -> None:
    """Equal remainders resolve toward earlier lines.

    Catches nondeterministic leftover placement: equal remainders must
    resolve the same way every request, or repricing the same cart flips
    which line shows the extra cent.
    """
    assert allocate_proportionally(2, [1, 1, 1]) == [1, 1, 0]


def test_all_zero_weights_with_zero_amount_returns_zeros() -> None:
    """All-zero weights are fine when there is nothing to allocate.

    Catches a cart of all-free lines erroring on a zero-value adjustment
    instead of allocating nothing.
    """
    assert allocate_proportionally(0, [0, 0]) == [0, 0]


@pytest.mark.parametrize(
    ("amount", "weights"),
    [
        (-1, [1]),  # negative amount
        (10, []),  # nothing to allocate across
        (10, [5, -1]),  # negative weight
        (10, [0, 0]),  # positive amount, no proportion to split by
    ],
)
def test_invalid_inputs_raise(amount: int, weights: list[int]) -> None:
    """Unallocatable inputs are rejected up front.

    Catches the helper silently returning garbage (or crashing later in the
    engine) on inputs that can't be allocated — it must raise ValueError.
    """
    with pytest.raises(ValueError):
        allocate_proportionally(amount, weights)


@given(
    amount=st.integers(min_value=0, max_value=10**7),
    weights=st.lists(
        st.integers(min_value=0, max_value=10**6), min_size=1, max_size=25
    ),
)
def test_allocation_always_sums_exactly(amount: int, weights: list[int]) -> None:
    """Property: shares always sum to exactly the amount.

    The no-rounding-drift invariant itself: for any amount and any weights,
    shares are non-negative, one per line, and sum to exactly the amount — a
    single cent of drift here becomes a receipt that doesn't add up.
    """
    if sum(weights) == 0 and amount > 0:
        with pytest.raises(ValueError):
            allocate_proportionally(amount, weights)
        return
    shares = allocate_proportionally(amount, weights)
    assert len(shares) == len(weights)
    assert all(share >= 0 for share in shares)
    assert sum(shares) == amount
