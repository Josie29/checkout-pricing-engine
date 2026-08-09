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
  // Deal state is two overrides on top of "everything is claimed": ids the
  // shopper excluded are absent from `claimedIds`, and ids they forced on
  // are in `pinnedIds`. With neither, the server picks the best allowed
  // combination on its own — the default the checkout resets back to.
  const [claimedIds, setClaimedIds] = useState<string[]>([])
  const [pinnedIds, setPinnedIds] = useState<string[]>([])
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
          // Every deal starts claimed: there is no opting in, the server
          // picks the best allowed combination, and which ones actually
          // apply stays response-driven. Overrides after this are the
          // shopper's — only a (re)seed resets them.
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
    // Stepping the last unit down removes the line: a cart line must carry
    // at least one unit (the server rejects qty 0), and the catalog card's
    // stepper collapsing back to "Add" is the standard way out. The drawer's
    // explicit Remove stays as a shortcut for multi-unit lines.
    setCartItems((items) =>
      items.flatMap((line) => {
        if (line.sku !== sku) {
          return [line]
        }
        const qty = line.qty + delta
        return qty < 1 ? [] : [{ ...line, qty }]
      }),
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

  const toggleDeal = (id: string, on: boolean) => {
    if (on) {
      // Pin it: the server constrains its search to combinations where this
      // deal actually applies and drops whatever it displaces, so the
      // mutually-exclusive rival switches itself off in the next response.
      // A pin implies a claim, but re-claiming keeps the two sets coherent
      // if the shopper had excluded this deal earlier.
      setPinnedIds((ids) => (ids.includes(id) ? ids : [...ids, id]))
      setClaimedIds((ids) => (ids.includes(id) ? ids : [...ids, id]))
      return
    }
    // Switching a deal off means "not this one" — drop both the pin and the
    // claim, or the server would just re-apply it.
    setPinnedIds((ids) => ids.filter((existing) => existing !== id))
    setClaimedIds((ids) => ids.filter((existing) => existing !== id))
  }

  const resetDeals = () => {
    // Back to the automatic best: claim everything, pin nothing. Two updates,
    // but React batches them, so the debounced reprice still fires once.
    setClaimedIds(
      promotions === null ? [] : promotions.map((promo) => promo.id),
    )
    setPinnedIds([])
  }

  const removePromotion = (id: string) => {
    // Drop it from signage/toggles and from both override sets, so the
    // checkout's next POST /price never references the deleted id (a 422).
    setPromotions((existing) =>
      existing === null
        ? existing
        : existing.filter((promotion) => promotion.id !== id),
    )
    setClaimedIds((ids) => ids.filter((existing) => existing !== id))
    setPinnedIds((ids) => ids.filter((existing) => existing !== id))
  }

  const addPromotion = (promotion: PromotionInfo) => {
    // Append the 201 body — GET /promotions lists seeds then additions, so
    // this matches what a refetch would return. Shop signage and checkout
    // toggles read this state, so the new promotion appears immediately.
    setPromotions((existing) =>
      existing === null ? [promotion] : [...existing, promotion],
    )
    // Claimed like every other deal, so it competes for a slot immediately
    // rather than sitting inert until the shopper finds and enables it.
    setClaimedIds((ids) => [...ids, promotion.id])
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
            promotions={promotions}
            onCreated={addPromotion}
            onDeleted={removePromotion}
            onBackToShop={() => navigate('shop')}
          />
        ) : route === 'checkout' ? (
          <CheckoutPage
            promotions={promotions}
            catalog={catalog}
            cartItems={cartItems}
            claimedIds={claimedIds}
            pinnedIds={pinnedIds}
            onToggle={toggleDeal}
            onReset={resetDeals}
            onBackToShop={() => navigate('shop')}
          />
        ) : (
          <ShopPage
            catalog={catalog}
            promotions={promotions}
            cartItems={cartItems}
            onAdd={addCatalogItem}
            onQtyStep={stepQty}
          />
        )}
      </main>
    </>
  )
}

export default App
