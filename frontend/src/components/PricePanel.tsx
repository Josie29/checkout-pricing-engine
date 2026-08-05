import type { Adjustment, Phase, PriceResponse } from '../types'
import { formatCents } from '../format'
import { ProductImage } from './ProductImage'

interface PricePanelProps {
  /** Latest priced result; null when the cart is empty or nothing priced yet. */
  price: PriceResponse | null
  cartEmpty: boolean
  loading: boolean
  /** Failure of the latest `POST /price`; null while healthy. */
  failure: { message: string; status: number | null } | null
  /** Re-fires the failed request; wired to the Retry button. */
  onRetry: () => void
}

/** Plain-language label for each pricing phase. */
const PHASE_LABELS: Record<Phase, string> = {
  item: 'item promotion',
  cart: 'cart promotion',
  shipping: 'shipping promotion',
}

interface ExplanationProps {
  adjustment: Adjustment
  /** Display name per sku, from the response's own lines. */
  lineNames: ReadonlyMap<string, string>
}

/**
 * One applied promotion's explanation: name, phase, total saved, and the
 * per-line amounts from `line_allocations`. Shipping adjustments carry no
 * allocations and are phrased as "off shipping" instead.
 */
function Explanation({ adjustment, lineNames }: ExplanationProps) {
  return (
    <li className="explanation">
      <p className="explanation-summary">
        {`${adjustment.promotion_name} (${PHASE_LABELS[adjustment.phase]}) — saved ${formatCents(adjustment.amount_cents)}`}
      </p>
      {adjustment.line_allocations.length === 0 ? (
        <ul className="explanation-lines">
          <li>{`${formatCents(adjustment.amount_cents)} off shipping`}</li>
        </ul>
      ) : (
        <ul className="explanation-lines">
          {adjustment.line_allocations.map((allocation) => (
            <li key={allocation.sku}>
              {`${formatCents(allocation.amount_cents)} off ${lineNames.get(allocation.sku) ?? allocation.sku}`}
            </li>
          ))}
        </ul>
      )}
    </li>
  )
}

/**
 * Receipt-card price breakdown rendered verbatim from the latest
 * `POST /price` response — every amount comes from the API's integer cents,
 * nothing is computed client-side. Lines carry thumbnails, struck-through
 * pre-discount subtotals, and green savings chips; the optimizer note is a
 * callout at the top. While a newer price is loading or the last request
 * failed, the panel is explicitly marked so stale numbers are never
 * presented as current; failures offer a Retry.
 */
export function PricePanel({
  price,
  cartEmpty,
  loading,
  failure,
  onRetry,
}: PricePanelProps) {
  const stale = loading || failure !== null
  // 422 means the request itself was rejected — retrying the same inputs
  // cannot succeed, so surface the server's detail without a Retry button.
  const rejected = failure !== null && failure.status === 422
  // Sku -> display name lookup from the response's own lines (no derivation).
  const lineNames = new Map(
    (price?.lines ?? []).map((line) => [line.sku, line.name ?? line.sku]),
  )
  return (
    <section aria-labelledby="price-heading" aria-busy={loading}>
      <h2 id="price-heading">Your order</h2>
      {loading && (
        <p className="muted" role="status">
          Updating&hellip;
        </p>
      )}
      {failure !== null && (
        <div role="alert">
          <p className="error">
            {rejected
              ? `The server rejected this cart: ${failure.message}`
              : `Something went wrong pricing the cart: ${failure.message}`}
          </p>
          {!rejected && (
            <p className="muted">
              Prices below are out of date until a retry succeeds.
            </p>
          )}
          {!rejected && (
            <button type="button" onClick={onRetry}>
              Retry
            </button>
          )}
        </div>
      )}
      {cartEmpty ? (
        <p className="muted">Add items to the cart to see a price.</p>
      ) : price === null ? null : (
        <div className={stale ? 'receipt price-stale' : 'receipt'}>
          {price.optimal && price.adjustments.length > 0 && (
            <p className="optimal-callout">
              <strong>Best combination applied</strong>
              {` — you save ${formatCents(price.discount_total_cents)}.`}
              {/* Echo the coupons' "not applied" hint so the two surfaces
                  read as one explanation. */}
              {Object.values(price.promotion_statuses).includes('claimed') &&
                ' Deals marked "not applied" would not save more.'}
            </p>
          )}
          <ul className="receipt-lines">
            {price.lines.map((line) => (
              <li key={line.sku} className="receipt-line">
                <ProductImage
                  sku={line.sku}
                  name={line.name ?? line.sku}
                  variant="thumb"
                />
                <span className="receipt-line-info">
                  <span className="receipt-line-top">
                    <span className="receipt-line-name">
                      {line.qty} &times; {line.name ?? line.sku}
                    </span>
                    {line.discount_cents > 0 && (
                      <span className="receipt-line-save">
                        &minus;{formatCents(line.discount_cents)}
                      </span>
                    )}
                  </span>
                  {/* Category under the name ties the line to category-
                      targeted deals like "Beans: buy 2 get 1 free". */}
                  <span className="receipt-line-cat">{line.category}</span>
                </span>
                <span className="receipt-line-amount">
                  {line.discount_cents > 0 && (
                    <s>{formatCents(line.line_subtotal_cents)}</s>
                  )}
                  {formatCents(line.line_total_cents)}
                </span>
              </li>
            ))}
          </ul>
          <div className="receipt-sums">
            <div className="receipt-sum">
              <span>Subtotal</span>
              <span className="amount">
                {formatCents(price.subtotal_cents)}
              </span>
            </div>
            {price.discount_total_cents > 0 && (
              <div className="receipt-sum receipt-sum--discount">
                <span>Deals</span>
                <span className="amount">
                  &minus;{formatCents(price.discount_total_cents)}
                </span>
              </div>
            )}
            <div className="receipt-sum">
              <span>Shipping</span>
              <span className="amount">
                {formatCents(price.shipping_cents)}
              </span>
            </div>
            <div className="receipt-sum receipt-sum--total">
              <span>Total</span>
              <span className="amount">{formatCents(price.total_cents)}</span>
            </div>
          </div>
          {price.adjustments.length > 0 && (
            <div className="explanations">
              <h3 id="explanations-heading">How your deals applied</h3>
              <ul aria-labelledby="explanations-heading">
                {price.adjustments.map((adjustment) => (
                  <Explanation
                    key={adjustment.promotion_id}
                    adjustment={adjustment}
                    lineNames={lineNames}
                  />
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </section>
  )
}
