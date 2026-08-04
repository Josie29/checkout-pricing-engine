interface CartButtonProps {
  /** Total item count across cart lines (sum of quantities, not money). */
  count: number
  /** Navigate to the checkout page. */
  onClick: () => void
}

/**
 * Header cart button: a shopping-cart glyph with a live item-count badge.
 * Pure presentation — the count is summed by the owner from cart state;
 * no pricing happens here. The badge hides at zero, and the accessible
 * name always carries the count ("Cart, 4 items").
 */
export function CartButton({ count, onClick }: CartButtonProps) {
  const label = count === 1 ? 'Cart, 1 item' : `Cart, ${count} items`
  return (
    <button
      type="button"
      className="cart-button"
      aria-label={label}
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
      {count > 0 && (
        <span className="cart-badge" aria-hidden="true">
          {count}
        </span>
      )}
    </button>
  )
}
