import { useEffect, useRef } from 'react'
import type { CartItemInput } from '../types'
import { CartTable } from './CartTable'

interface CartDrawerProps {
  open: boolean
  items: CartItemInput[]
  /** Step a line's quantity by +1/-1; clamped to >= 1 by the owner. */
  onQtyStep: (sku: string, delta: 1 | -1) => void
  onPriceChange: (sku: string, unitPriceCents: number) => void
  onRemove: (sku: string) => void
  onClose: () => void
  /** Close the drawer and navigate to the checkout page. */
  onCheckout: () => void
}

/**
 * Slide-over cart panel, toggled from the header cart pill. Wraps the
 * existing `CartTable` (qty stepper, editable unit price, remove) and adds
 * the checkout call-to-action — so the shop page itself stays cart-free.
 * Closes on backdrop click, Escape, or the Close button. Still no pricing:
 * totals only exist on the checkout page.
 */
export function CartDrawer({
  open,
  items,
  onQtyStep,
  onPriceChange,
  onRemove,
  onClose,
  onCheckout,
}: CartDrawerProps) {
  const panelRef = useRef<HTMLElement>(null)

  // Move focus into the dialog when it opens so keyboard users land inside
  // and Escape works immediately.
  useEffect(() => {
    if (open) {
      panelRef.current?.focus()
    }
  }, [open])

  if (!open) {
    return null
  }

  const cartEmpty = items.length === 0
  return (
    <div>
      {/* Click-away scrim; the Close button is the accessible control. */}
      <div className="cart-drawer-backdrop" onClick={onClose} />
      <aside
        ref={panelRef}
        className="cart-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="Cart"
        tabIndex={-1}
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            onClose()
          }
        }}
      >
        <div className="cart-drawer-head">
          <button type="button" onClick={onClose}>
            Close
          </button>
        </div>
        <CartTable
          items={items}
          onQtyStep={onQtyStep}
          onPriceChange={onPriceChange}
          onRemove={onRemove}
        />
        <div className="checkout-cta">
          <button
            type="button"
            className="checkout-button"
            disabled={cartEmpty}
            onClick={onCheckout}
          >
            Go to checkout
          </button>
          {cartEmpty && (
            <p className="muted">Add items to the cart to check out.</p>
          )}
        </div>
      </aside>
    </div>
  )
}
