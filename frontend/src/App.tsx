import { useEffect, useState } from 'react'
import { fetchCatalog, fetchPromotions } from './api'
import type { CartItemInput, CatalogItem, PromotionInfo } from './types'
import { useRoute } from './router'
import { ShopPage } from './pages/ShopPage'
import { CheckoutPage } from './pages/CheckoutPage'

/**
 * Two-page pricing UI: the shop (`/`) builds the cart without ever pricing;
 * the checkout (`/checkout`) owns every `POST /price`. Cart and toggle
 * state live here so they survive navigation between the pages — in-memory
 * only, so a full page refresh clears the cart by design.
 */
function App() {
  const { route, navigate } = useRoute()

  const [catalog, setCatalog] = useState<CatalogItem[] | null>(null)
  const [promotions, setPromotions] = useState<PromotionInfo[] | null>(null)
  const [seedError, setSeedError] = useState<string | null>(null)

  const [cartItems, setCartItems] = useState<CartItemInput[]>([])
  const [claimedIds, setClaimedIds] = useState<string[]>([])

  // Bumping the nonce re-runs the seed fetch effect — the retry button's
  // only job.
  const [seedAttempt, setSeedAttempt] = useState(0)

  // Load the seeded catalog and promotion list on mount (and on retry).
  useEffect(() => {
    let cancelled = false
    Promise.all([fetchCatalog(), fetchPromotions()])
      .then(([catalogItems, promotionInfos]) => {
        if (!cancelled) {
          setCatalog(catalogItems)
          setPromotions(promotionInfos)
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setSeedError(error instanceof Error ? error.message : String(error))
        }
      })
    return () => {
      cancelled = true
    }
  }, [seedAttempt])

  const addCatalogItem = (item: CatalogItem) => {
    setCartItems((items) => {
      const existing = items.find((line) => line.sku === item.sku)
      if (existing) {
        return items.map((line) =>
          line.sku === item.sku ? { ...line, qty: line.qty + 1 } : line,
        )
      }
      return [
        ...items,
        {
          sku: item.sku,
          name: item.name,
          category: item.category,
          unit_price_cents: item.unit_price_cents,
          qty: 1,
        },
      ]
    })
  }

  const stepQty = (sku: string, delta: 1 | -1) => {
    // Functional update so rapid clicks never read a stale quantity.
    setCartItems((items) =>
      items.map((line) =>
        line.sku === sku
          ? { ...line, qty: Math.max(1, line.qty + delta) }
          : line,
      ),
    )
  }

  const changePrice = (sku: string, unitPriceCents: number) => {
    setCartItems((items) =>
      items.map((line) =>
        line.sku === sku ? { ...line, unit_price_cents: unitPriceCents } : line,
      ),
    )
  }

  const removeItem = (sku: string) => {
    setCartItems((items) => items.filter((line) => line.sku !== sku))
  }

  const togglePromotion = (id: string, claimed: boolean) => {
    setClaimedIds((ids) =>
      claimed ? [...ids, id] : ids.filter((existing) => existing !== id),
    )
  }

  const retrySeed = () => {
    // Clearing the error returns the page to its loading state while the
    // re-fired fetches are in flight.
    setSeedError(null)
    setSeedAttempt((attempt) => attempt + 1)
  }

  return (
    <main className="app">
      <h1>Checkout Pricing Engine</h1>
      {seedError !== null ? (
        <div role="alert">
          <p className="error">
            Something went wrong loading the catalog and promotions: {seedError}
          </p>
          <button type="button" onClick={retrySeed}>
            Retry
          </button>
        </div>
      ) : catalog === null || promotions === null ? (
        <p className="muted" role="status">
          Loading&hellip;
        </p>
      ) : route === 'checkout' ? (
        <CheckoutPage
          promotions={promotions}
          cartItems={cartItems}
          claimedIds={claimedIds}
          onToggle={togglePromotion}
          onBackToShop={() => navigate('shop')}
        />
      ) : (
        <ShopPage
          catalog={catalog}
          cartItems={cartItems}
          onAdd={addCatalogItem}
          onQtyStep={stepQty}
          onPriceChange={changePrice}
          onRemove={removeItem}
          onCheckout={() => navigate('checkout')}
        />
      )}
    </main>
  )
}

export default App
