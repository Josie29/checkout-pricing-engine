import { useEffect, useState } from 'react'
import { fetchCatalog, fetchPromotions } from './api'
import type { CartItemInput, CatalogItem, PromotionInfo } from './types'
import { useRoute } from './router'
import { ShopPage } from './pages/ShopPage'
import { CheckoutPage } from './pages/CheckoutPage'
import { AdminPage } from './pages/AdminPage'
import { CartButton } from './components/CartButton'
import { CartDrawer } from './components/CartDrawer'

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
  // The header cart pill toggles this slide-over; adding items never opens
  // it — the pill's live count is the feedback.
  const [cartOpen, setCartOpen] = useState(false)

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
          // Every deal starts claimed, so checkout arrives as apply-all;
          // which ones actually apply stays response-driven. Toggling after
          // this is the user's choice — only a (re)seed resets it.
          setClaimedIds(promotionInfos.map((promo) => promo.id))
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

  const setAllClaimed = (ids: string[]) => {
    // One state update replacing the array identity, so the checkout page's
    // debounced price effect fires exactly once for a bulk apply/clear.
    setClaimedIds(ids)
  }

  const addPromotion = (promotion: PromotionInfo) => {
    // Append the 201 body — GET /promotions lists seeds then additions, so
    // this matches what a refetch would return. Shop signage and checkout
    // toggles read this state, so the new promotion appears immediately.
    setPromotions((existing) =>
      existing === null ? [promotion] : [...existing, promotion],
    )
  }

  const retrySeed = () => {
    // Clearing the error returns the page to its loading state while the
    // re-fired fetches are in flight.
    setSeedError(null)
    setSeedAttempt((attempt) => attempt + 1)
  }

  // Header badge count: sum of cart quantities — a count, never money.
  const cartCount = cartItems.reduce((sum, line) => sum + line.qty, 0)

  return (
    <>
      <header className="site-header">
        <div className="site-header-inner">
          <div className="brand">
            <h1 className="wordmark">Roast &amp; Co</h1>
            <p className="tagline">coffee &amp; kitchenware</p>
          </div>
          <a
            href="/admin"
            className="admin-link"
            onClick={(event) => {
              event.preventDefault()
              navigate('admin')
            }}
          >
            Admin
          </a>
          <CartButton
            count={cartCount}
            expanded={cartOpen}
            onClick={() => setCartOpen((open) => !open)}
          />
        </div>
      </header>
      <CartDrawer
        open={cartOpen}
        items={cartItems}
        onQtyStep={stepQty}
        onPriceChange={changePrice}
        onRemove={removeItem}
        onClose={() => setCartOpen(false)}
        onCheckout={() => {
          setCartOpen(false)
          navigate('checkout')
        }}
      />
      <main className="app">
        {seedError !== null ? (
          <div role="alert">
            <p className="error">
              Something went wrong loading the catalog and promotions:{' '}
              {seedError}
            </p>
            <button type="button" onClick={retrySeed}>
              Retry
            </button>
          </div>
        ) : catalog === null || promotions === null ? (
          <p className="muted" role="status">
            Loading&hellip;
          </p>
        ) : route === 'admin' ? (
          <AdminPage
            catalog={catalog}
            onCreated={addPromotion}
            onBackToShop={() => navigate('shop')}
          />
        ) : route === 'checkout' ? (
          <CheckoutPage
            promotions={promotions}
            cartItems={cartItems}
            claimedIds={claimedIds}
            onToggle={togglePromotion}
            onSetAllClaimed={setAllClaimed}
            onBackToShop={() => navigate('shop')}
          />
        ) : (
          <ShopPage
            catalog={catalog}
            promotions={promotions}
            onAdd={addCatalogItem}
          />
        )}
      </main>
    </>
  )
}

export default App
