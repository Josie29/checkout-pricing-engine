import type { PromotionInfo, PromotionStatus } from '../types'
import { formatCents } from '../format'
import { scopeLabel } from '../promotionLabels'

interface PromotionTogglesProps {
  promotions: PromotionInfo[]
  /** Catalog sku -> display name, for readable SKU-targeted scope lines. */
  productNames: ReadonlyMap<string, string>
  claimedIds: readonly string[]
  /** Statuses from the latest `POST /price` response; null before any price. */
  statuses: Record<string, PromotionStatus> | null
  /**
   * Cents saved per applied promotion id, straight from the latest
   * response's `adjustments`; null before any price. Display only — no
   * client-side pricing.
   */
  savedCents: Record<string, number> | null
  onToggle: (id: string, claimed: boolean) => void
  /** Replace the claimed set wholesale — one update, one debounced reprice. */
  onSetAllClaimed: (ids: string[]) => void
  /** True while a `POST /price` is pending; bulk buttons are disabled. */
  pricePending: boolean
}

/**
 * Coupon-card list of promotions (seed order). Each card is a labelled
 * switch: on = claimed. Statuses stay response-driven — an applied coupon
 * shows the cents it saved (from the response's adjustments), a
 * claimed-but-ineligible one dims with a "not applied" hint. Apply all /
 * Clear all replace the claimed set in a single update, so the checkout
 * fires exactly one reprice.
 */
export function PromotionToggles({
  promotions,
  productNames,
  claimedIds,
  statuses,
  savedCents,
  onToggle,
  onSetAllClaimed,
  pricePending,
}: PromotionTogglesProps) {
  const allClaimed = promotions.every((promotion) =>
    claimedIds.includes(promotion.id),
  )
  const noneClaimed = claimedIds.length === 0
  return (
    <section aria-labelledby="promotions-heading">
      <div className="promo-head">
        <h2 id="promotions-heading">Deals</h2>
        <div className="promotion-bulk-actions">
          <button
            type="button"
            disabled={allClaimed || pricePending}
            onClick={() =>
              onSetAllClaimed(promotions.map((promotion) => promotion.id))
            }
          >
            Apply all
          </button>
          <button
            type="button"
            disabled={noneClaimed || pricePending}
            onClick={() => onSetAllClaimed([])}
          >
            Clear all
          </button>
        </div>
      </div>
      <ul className="promotion-list">
        {promotions.map((promotion) => {
          const claimed = claimedIds.includes(promotion.id)
          const status = statuses?.[promotion.id]
          const applied = claimed && status === 'applied'
          const inert = claimed && status === 'claimed'
          const saved = savedCents?.[promotion.id]
          const classes = ['coupon']
          if (applied) {
            classes.push('coupon--applied')
          }
          if (inert) {
            classes.push('coupon--inert')
          }
          return (
            <li key={promotion.id} className={classes.join(' ')}>
              <label className="coupon-label">
                <input
                  type="checkbox"
                  className="coupon-input"
                  checked={claimed}
                  // Explicit name: the label's visible text also carries the
                  // scope line, which would otherwise concatenate into the
                  // accessible name.
                  aria-label={promotion.name}
                  onChange={(event) =>
                    onToggle(promotion.id, event.target.checked)
                  }
                />
                {/* Purely visual switch; state lives on the checkbox. */}
                <span className="coupon-switch" aria-hidden="true" />
                <span className="coupon-info">
                  <span className="coupon-name">{promotion.name}</span>
                  <span className="coupon-scope">
                    {scopeLabel(promotion.target, productNames)}
                  </span>
                </span>
              </label>
              {applied && saved !== undefined && (
                <span className="coupon-saved">
                  &minus;{formatCents(saved)}
                </span>
              )}
              {inert && <span className="coupon-status">not applied</span>}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
