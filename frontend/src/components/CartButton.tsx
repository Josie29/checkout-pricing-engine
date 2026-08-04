interface CartButtonProps {
  /** Total item count across cart lines (sum of quantities, not money). */
  count: number
  /** Whether the cart drawer is open — mirrored onto aria-expanded. */
  expanded: boolean
  /** Toggle the cart drawer. */
  onClick: () => void
}

/**
 * Header cart pill: a shopping-cart glyph plus a live "N items" count.
 * Pure presentation — the count is summed by the owner from cart state;
 * no pricing happens here. Clicking toggles the cart drawer (it no longer
 * navigates). The accessible name always carries the count ("Cart, 4
 * items").
 */
export function CartButton({ count, expanded, onClick }: CartButtonProps) {
  const noun = count === 1 ? 'item' : 'items'
  return (
    <button
      type="button"
      className="cart-button"
      aria-label={`Cart, ${count} ${noun}`}
      aria-expanded={expanded}
      onClick={onClick}
    >
      <svg
        className="cart-icon"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
        focusable="false"
      >
        <path d="M2.5 3.5h2.2l2.1 10.4a1.5 1.5 0 0 0 1.47 1.2h9.1a1.5 1.5 0 0 0 1.45-1.13L20.9 6.7H5.3" />
        <circle cx="9" cy="19.5" r="1.5" />
        <circle cx="17.5" cy="19.5" r="1.5" />
      </svg>
      <span className="cart-count" aria-hidden="true">
        <b>{count}</b> {noun}
      </span>
    </button>
  )
}
