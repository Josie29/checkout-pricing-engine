import type {
  PromotionAvailability,
  PromotionInfo,
  PromotionStatus,
} from '../types'
import { formatCents } from '../format'
import { gapLabel, scopeLabel } from '../promotionLabels'

interface PromotionTogglesProps {
  promotions: PromotionInfo[]
  /** Catalog sku -> display name, for readable SKU-targeted scope lines. */
  productNames: ReadonlyMap<string, string>
  /** Statuses from the latest `POST /price` response; null before any price. */
  statuses: Record<string, PromotionStatus> | null
  /** Eligibility, shortfall, and conflicts from the same response. */
  availability: Record<string, PromotionAvailability> | null
  /**
   * Cents saved per applied promotion id, straight from the latest
   * response's `adjustments`; null before any price. Display only — no
   * client-side pricing.
   */
  savedCents: Record<string, number> | null
  /** True when the shopper has overridden the automatic best combination. */
  overridden: boolean
  /**
   * Cents the override costs against the automatic best, when that best is
   * known for the current cart; null otherwise (so the reset control still
   * appears, just without a figure).
   */
  overrideCostCents: number | null
  /** Force a deal on (`on`) or exclude it (`!on`). */
  onToggle: (id: string, on: boolean) => void
  /** Drop every override and return to the automatic best combination. */
  onReset: () => void
  /** True while a `POST /price` is pending; controls are disabled. */
  pricePending: boolean
}

/** The three states a deal card can be in, derived from the server response. */
type DealState = 'applied' | 'available' | 'ineligible'

/**
 * Deal cards in three unambiguous states, all derived from the server:
 *
 * - `applied`   — switch on, highlighted, showing the cents it saved.
 * - `available` — the cart qualifies but a rival deal won this slot. Normal
 *                 colouring, switch off, clickable: turning it on pins it,
 *                 and the server drops whatever it displaces.
 * - `ineligible`— the cart does not qualify. Greyed and non-interactive,
 *                 with the shortfall that would unlock it.
 *
 * The switch reflects what actually *applied*, not what the shopper claimed,
 * so it can never disagree with the receipt beside it. Every deal is claimed
 * by default and the optimizer picks the best combination; the switches exist
 * for overriding that pick, and `Best deal` undoes every override at once.
 */
export function PromotionToggles({
  promotions,
  productNames,
  statuses,
  availability,
  savedCents,
  overridden,
  overrideCostCents,
  onToggle,
  onReset,
  pricePending,
}: PromotionTogglesProps) {
  return (
    <section aria-labelledby="promotions-heading">
      <div className="promo-head">
        <h2 id="promotions-heading">Deals</h2>
        {overridden && (
          <button
            type="button"
            className="reset-deals"
            disabled={pricePending}
            onClick={onReset}
          >
            {overrideCostCents === null
              ? 'Best deal'
              : `Best deal saves ${formatCents(overrideCostCents)}`}
          </button>
        )}
      </div>
      <p className="muted promo-intro">
        Every deal is claimed for you and the best allowed combination is
        applied automatically. Switch one on to take it instead.
      </p>
      <ul className="promotion-list">
        {promotions.map((promotion) => {
          const entry = availability?.[promotion.id]
          // Before the first response (and against a server too old to send
          // availability) assume eligible: a live card is recoverable by
          // clicking, a greyed one is a dead end.
          const eligible = entry?.eligible ?? true
          const applied = statuses?.[promotion.id] === 'applied'
          const state: DealState = applied
            ? 'applied'
            : eligible
              ? 'available'
              : 'ineligible'
          const saved = savedCents?.[promotion.id]
          const hint = gapLabel(entry?.gap, promotion.target)
          return (
            <li key={promotion.id} className={`coupon coupon--${state}`}>
              <label className="coupon-label">
                <input
                  type="checkbox"
                  className="coupon-input"
                  checked={applied}
                  disabled={state === 'ineligible' || pricePending}
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
                  {state === 'ineligible' && hint !== null && (
                    <span className="coupon-hint">{hint}</span>
                  )}
                </span>
              </label>
              {state === 'applied' && saved !== undefined && (
                <span className="coupon-saved">
                  &minus;{formatCents(saved)}
                </span>
              )}
              {state === 'available' && (
                <span className="coupon-status">qualifies</span>
              )}
              {state === 'ineligible' && hint === null && (
                <span className="coupon-status">not eligible</span>
              )}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
