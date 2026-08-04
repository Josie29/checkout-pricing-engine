import type { PriceResponse } from '../types'
import { formatCents } from '../format'

interface PricePanelProps {
  /** Latest priced result; null when the cart is empty or nothing priced yet. */
  price: PriceResponse | null
  cartEmpty: boolean
  loading: boolean
  error: string | null
}

/**
 * Itemized price breakdown rendered verbatim from the latest `POST /price`
 * response — every amount comes from the API's integer cents, nothing is
 * computed client-side. While a newer price is loading the panel is marked
 * pending so stale numbers are never presented as current.
 */
export function PricePanel({
  price,
  cartEmpty,
  loading,
  error,
}: PricePanelProps) {
  return (
    <section aria-labelledby="price-heading" aria-busy={loading}>
      <h2 id="price-heading">Price</h2>
      {loading && (
        <p className="muted" role="status">
          Updating&hellip;
        </p>
      )}
      {error !== null && (
        <p className="error" role="alert">
          Something went wrong pricing the cart: {error}
        </p>
      )}
      {cartEmpty ? (
        <p className="muted">Add items to the cart to see a price.</p>
      ) : price === null ? null : (
        <div className={loading || error !== null ? 'price-stale' : undefined}>
          <table className="price-table">
            <tbody>
              {price.lines.map((line) => (
                <tr key={line.sku}>
                  <th scope="row">
                    {line.qty} &times; {line.name ?? line.sku}
                    {line.discount_cents > 0 && (
                      <span className="line-discount">
                        {' '}
                        &minus;{formatCents(line.discount_cents)} off{' '}
                        {formatCents(line.line_subtotal_cents)}
                      </span>
                    )}
                  </th>
                  <td className="amount">
                    {formatCents(line.line_total_cents)}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th scope="row">Subtotal</th>
                <td className="amount">{formatCents(price.subtotal_cents)}</td>
              </tr>
              {price.discount_total_cents > 0 && (
                <tr>
                  <th scope="row">Discounts</th>
                  <td className="amount discount">
                    &minus;{formatCents(price.discount_total_cents)}
                  </td>
                </tr>
              )}
              <tr>
                <th scope="row">Shipping</th>
                <td className="amount">{formatCents(price.shipping_cents)}</td>
              </tr>
              <tr className="total-row">
                <th scope="row">Total</th>
                <td className="amount">{formatCents(price.total_cents)}</td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </section>
  )
}
