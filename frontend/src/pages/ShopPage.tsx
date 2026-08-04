import { useState } from 'react'
import type { CatalogItem, PromotionInfo } from '../types'
import { CatalogList } from '../components/CatalogList'
import { DealsBanner } from '../components/DealsBanner'

interface ShopPageProps {
  catalog: CatalogItem[]
  /** Seeded promotion list — rendered as read-only signage only. */
  promotions: PromotionInfo[]
  onAdd: (item: CatalogItem) => void
}

/**
 * The shop page: a full-width catalog card grid. It never calls
 * `POST /price` and never shows a total — unit prices come straight from
 * the catalog response, and all pricing happens on the checkout page.
 *
 * The cart lives in the header drawer (see `CartDrawer`), not on this
 * page. Cart/shipping deal signage is behind a toggle button instead of a
 * permanent banner; per-product deals still chip their catalog cards.
 */
export function ShopPage({ catalog, promotions, onAdd }: ShopPageProps) {
  const [dealsOpen, setDealsOpen] = useState(false)
  // Item-phase promos are chipped on cards by CatalogList; only cart- and
  // shipping-phase promos live behind the toggle (mirrors DealsBanner's
  // filter), so the button hides when there is nothing to reveal.
  const hasDeals = promotions.some(
    (promo) => promo.phase === 'cart' || promo.phase === 'shipping',
  )
  return (
    <div>
      <div className="shop-toolbar">
        <h2>Catalog</h2>
        {hasDeals && (
          <button
            type="button"
            aria-expanded={dealsOpen}
            onClick={() => setDealsOpen((open) => !open)}
          >
            {dealsOpen ? 'Hide deals' : 'View deals'}
          </button>
        )}
      </div>
      {dealsOpen && <DealsBanner promotions={promotions} />}
      <CatalogList catalog={catalog} promotions={promotions} onAdd={onAdd} />
    </div>
  )
}
