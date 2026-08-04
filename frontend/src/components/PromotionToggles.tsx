import type { PromotionInfo, PromotionStatus } from '../types'

interface PromotionTogglesProps {
  promotions: PromotionInfo[]
  claimedIds: readonly string[]
  /** Statuses from the latest `POST /price` response; null before any price. */
  statuses: Record<string, PromotionStatus> | null
  onToggle: (id: string, claimed: boolean) => void
}

/**
 * Checkbox list of seeded promotions (seed order). Checked = claimed.
 * Reflects the latest response's statuses: applied promotions get a badge,
 * claimed-but-ineligible ones a "not applied" hint.
 */
export function PromotionToggles({
  promotions,
  claimedIds,
  statuses,
  onToggle,
}: PromotionTogglesProps) {
  return (
    <section aria-labelledby="promotions-heading">
      <h2 id="promotions-heading">Promotions</h2>
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
