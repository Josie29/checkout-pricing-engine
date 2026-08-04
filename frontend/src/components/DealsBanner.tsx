import type { PromotionInfo } from '../types'

interface DealsBannerProps {
  promotions: PromotionInfo[]
}

/**
 * Slim read-only strip above the catalog listing the cart- and
 * shipping-phase promotions by name. Pure signage: no eligibility checks,
 * no amounts computed — promotions are applied at checkout.
 */
export function DealsBanner({ promotions }: DealsBannerProps) {
  const deals = promotions.filter(
    (promo) => promo.phase === 'cart' || promo.phase === 'shipping',
  )
  if (deals.length === 0) {
    return null
  }
  return (
    <p className="deals-banner">
      <strong>Deals:</strong> {deals.map((promo) => promo.name).join(' · ')}
      {/* · is a middle-dot separator between deal names. */}
      <span className="deals-banner-hint">Promotions apply at checkout.</span>
    </p>
  )
}
