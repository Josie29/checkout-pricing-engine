import type { PromotionInfo, PromotionStatus } from '../types'

interface PromotionTogglesProps {
  promotions: PromotionInfo[]
  claimedIds: readonly string[]
  /** Statuses from the latest `POST /price` response; null before any price. */
  statuses: Record<string, PromotionStatus> | null
  onToggle: (id: string, claimed: boolean) => void
  /** Replace the claimed set wholesale — one update, one debounced reprice. */
  onSetAllClaimed: (ids: string[]) => void
  /** True while a `POST /price` is pending; bulk buttons are disabled. */
  pricePending: boolean
}

/**
 * Checkbox list of seeded promotions (seed order). Checked = claimed.
 * Reflects the latest response's statuses: applied promotions get a badge,
 * claimed-but-ineligible ones a "not applied" hint. Apply all / Clear all
 * replace the claimed set in a single update, so the checkout fires exactly
 * one reprice; which promotions actually apply stays response-driven.
 */
export function PromotionToggles({
  promotions,
  claimedIds,
  statuses,
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
      <h2 id="promotions-heading">Promotions</h2>
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
      <ul className="promotion-list">
        {promotions.map((promotion) => {
          const claimed = claimedIds.includes(promotion.id)
          const status = statuses?.[promotion.id]
          return (
            <li key={promotion.id} className="promotion-item">
              <label className="promotion-label">
                <input
                  type="checkbox"
                  checked={claimed}
                  onChange={(event) =>
                    onToggle(promotion.id, event.target.checked)
                  }
                />
                <span>{promotion.name}</span>
              </label>
              {claimed && status === 'applied' && (
                <span className="status-badge status-applied">applied</span>
              )}
              {claimed && status === 'claimed' && (
                <span className="status-badge status-not-applied">
                  not applied
                </span>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
