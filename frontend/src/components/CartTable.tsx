import { useState } from 'react'
import type { CartItemInput } from '../types'
import { centsToDollarInput, parseDollarsToCents } from '../format'
import { ProductImage } from './ProductImage'

interface CartTableProps {
  items: CartItemInput[]
  /** Step a line's quantity by +1/-1; clamped to >= 1 by the owner. */
  onQtyStep: (sku: string, delta: 1 | -1) => void
  onPriceChange: (sku: string, unitPriceCents: number) => void
  onRemove: (sku: string) => void
}

interface PriceInputProps {
  sku: string
  unitPriceCents: number
  onCommit: (cents: number) => void
}

/**
 * Editable unit price. Holds the draft text locally and commits integer
 * cents on blur/Enter; an invalid draft reverts to the current price. The
 * edited price only changes the `POST /price` payload — no local math.
 */
function PriceInput({ sku, unitPriceCents, onCommit }: PriceInputProps) {
  const [draft, setDraft] = useState(() => centsToDollarInput(unitPriceCents))

  const commit = () => {
    const cents = parseDollarsToCents(draft)
    if (cents === null || cents === unitPriceCents) {
      setDraft(centsToDollarInput(unitPriceCents))
      return
    }
    onCommit(cents)
  }

  return (
    <input
      className="price-input"
      type="text"
      inputMode="decimal"
      value={draft}
      aria-label={`Unit price for ${sku} in dollars`}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === 'Enter') {
          event.currentTarget.blur()
        }
      }}
    />
  )
}

/** Cart rows with qty stepper, editable unit price, and remove. */
export function CartTable({
  items,
  onQtyStep,
  onPriceChange,
  onRemove,
}: CartTableProps) {
  return (
    <section aria-labelledby="cart-heading">
      <h2 id="cart-heading">Cart</h2>
      {items.length === 0 ? (
        <p className="muted">Cart is empty — add items from the catalog.</p>
      ) : (
        <table className="cart-table">
          <thead>
            <tr>
              <th scope="col">Item</th>
              <th scope="col">Unit price</th>
              <th scope="col">Qty</th>
              <th scope="col">
                <span className="visually-hidden">Remove</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.sku}>
                <td>
                  <div className="cart-item-cell">
                    {/* Thumbnail is desktop-only (.cart-thumb) so the
                        four-column table stays uncrowded on mobile. */}
                    <ProductImage
                      sku={item.sku}
                      name={item.name ?? item.sku}
                      variant="thumb"
                      className="cart-thumb"
                    />
                    <span>{item.name ?? item.sku}</span>
                  </div>
                </td>
                <td>
                  <PriceInput
                    // Remount on committed price so the draft resyncs.
                    key={item.unit_price_cents}
                    sku={item.sku}
                    unitPriceCents={item.unit_price_cents}
                    onCommit={(cents) => onPriceChange(item.sku, cents)}
                  />
                </td>
                <td>
                  <div className="qty-stepper">
                    <button
                      type="button"
                      aria-label={`Decrease quantity of ${item.name ?? item.sku}`}
                      disabled={item.qty <= 1}
                      onClick={() => onQtyStep(item.sku, -1)}
                    >
                      &minus;
                    </button>
                    <span aria-label={`Quantity of ${item.name ?? item.sku}`}>
                      {item.qty}
                    </span>
                    <button
                      type="button"
                      aria-label={`Increase quantity of ${item.name ?? item.sku}`}
                      onClick={() => onQtyStep(item.sku, 1)}
                    >
                      +
                    </button>
                  </div>
                </td>
                <td>
                  <button
                    type="button"
                    className="remove-button"
                    onClick={() => onRemove(item.sku)}
                    aria-label={`Remove ${item.name ?? item.sku}`}
                  >
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}
