import { useState } from 'react'
import type { Adjustment, Phase, PriceResponse } from '../types'
import { formatCents } from '../format'

interface DealsExplainerProps {
  /** Latest priced response; null hides the row (nothing to narrate yet). */
  price: PriceResponse | null
}

/**
 * "How deals work" — a dashed footnote row at the end of the coupon list
 * that expands in place into a three-round walkthrough (item -> cart ->
 * shipping) narrated with this cart's own numbers. Every amount is
 * rendered verbatim from the response (`adjustments` split by phase, plus
 * the cascade-boundary `phase_subtotals`) — no client-side pricing. The
 * row hides when the server doesn't send `phase_subtotals`.
 */
export function DealsExplainer({ price }: DealsExplainerProps) {
  const [open, setOpen] = useState(false)
  const subtotals = price?.phase_subtotals
  if (price === null || subtotals === null || subtotals === undefined) {
    return null
  }
  const ofPhase = (phase: Phase): Adjustment[] =>
    price.adjustments.filter((adjustment) => adjustment.phase === phase)
  const itemDeals = ofPhase('item')
  const cartDeals = ofPhase('cart')
  const shippingDeals = ofPhase('shipping')
  return (
    <div className="deals-explainer">
      <button
        type="button"
        className="deals-explainer-toggle"
        aria-expanded={open}
        onClick={() => setOpen((wasOpen) => !wasOpen)}
      >
        <span className="deals-explainer-i" aria-hidden="true">
          i
        </span>
        How deals work — 3 rounds, best combination wins
        <span className="deals-explainer-chevron" aria-hidden="true">
          {open ? '▴' : '▾' /* small up/down triangles */}
        </span>
      </button>
      {open && (
        <div className="how-steps">
          <div className="how-step">
            <span className="how-step-num" aria-hidden="true">
              1
            </span>
            <div>
              <p>
                {itemDeals.length > 0
                  ? 'Item deals came first, off original prices:'
                  : 'No item deals applied, so items kept their original prices.'}
              </p>
              {itemDeals.length > 0 && (
                <ul>
                  {itemDeals.map((deal) => (
                    <li key={deal.promotion_id}>
                      {`${deal.promotion_name} — ${formatCents(deal.amount_cents)} off`}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
          <div className="how-step">
            <span className="how-step-num" aria-hidden="true">
              2
            </span>
            <div>
              <p>
                {`Cart deals ran next, on the discounted items total of ${formatCents(subtotals.after_item_cents)}.`}
              </p>
              {cartDeals.length > 0 ? (
                <ul>
                  {cartDeals.map((deal) => (
                    <li key={deal.promotion_id}>
                      {`${deal.promotion_name} — ${formatCents(deal.amount_cents)} off`}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="how-quiet">No cart deal applied.</p>
              )}
            </div>
          </div>
          <div className="how-step">
            <span className="how-step-num" aria-hidden="true">
              3
            </span>
            <div>
              <p>
                {`Shipping came last, checked against the after-deals total of ${formatCents(subtotals.after_cart_cents)}.`}
              </p>
              {shippingDeals.length > 0 ? (
                <ul>
                  {shippingDeals.map((deal) => (
                    <li key={deal.promotion_id}>
                      {`${deal.promotion_name} — ${formatCents(deal.amount_cents)} off`}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="how-quiet">
                  {`Shipping charged: ${formatCents(price.shipping_cents)}.`}
                </p>
              )}
            </div>
          </div>
          <p className="how-rules">
            Deals that overlap on the same items never stack — at most one wins
            per item, plus one cart deal and one shipping deal. Deals on
            different items apply together. Every allowed combination of your
            switched-on deals was priced (even skipping some), and the cheapest
            total won.
          </p>
        </div>
      )}
    </div>
  )
}
