import { useEffect, useState } from 'react'
import { fetchCatalog, fetchPromotions } from './api'
import type {
  CartItemInput,
  CatalogItem,
  DealToggleContext,
  PromotionInfo,
} from './types'
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
  // Deal state has two modes. `selection === null` is automatic: every deal
  // is claimed and the server picks the best allowed combination. The first
  // manual switch freezes whatever was applied into an explicit selection,
  // and every edit after that is a plain add/remove on that set. Freezing
  // is what stops a deal the shopper never turned on from promoting itself
  // into the receipt when they switch something else off — switching off is
  // purely subtractive.
  const [selection, setSelection] = useState<string[] | null>(null)
  // Deals the shopper explicitly switched ON. Subset of the selection, sent
  // as pins so the server forces them even when it would rather withhold
  // them for a better total elsewhere.
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
          // No claimed-set to seed: `selection === null` already means
          // "every deal claimed". There is no opting in — the server picks
          // the best allowed combination and which ones actually apply
          // stays response-driven.
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

  const toggleDeal = (id: string, on: boolean, context: DealToggleContext) => {
    // Declaration order keeps the request body stable across edits, so two
    // routes to the same selection produce the same array.
    const order = promotions ?? []
    const inOrder = (ids: Iterable<string>) => {
      const wanted = new Set(ids)
      return order
        .map((promo) => promo.id)
        .filter((promoId) => wanted.has(promoId))
    }
    // The first manual switch inherits whatever the server had applied;
    // after that the shopper's own set is the starting point.
    const base = new Set(selection ?? context.appliedIds)
    if (on) {
      // Drop the deals that cannot co-apply with this one before adding it,
      // so we never ask the server for a combination it has to resolve for
      // us. Dropping them from the *selection* (not just un-pinning) is what
      // keeps a later switch-off subtractive: un-pinning alone would leave
      // the rival lurking, ready to reappear.
      for (const conflicting of context.conflictsWith) {
        base.delete(conflicting)
      }
      base.add(id)
      setSelection(inOrder(base))
      setPinnedIds((ids) =>
        inOrder([
          ...ids.filter(
            (existing) => !context.conflictsWith.includes(existing),
          ),
          id,
        ]),
      )
      return
    }
    base.delete(id)
    setSelection(inOrder(base))
    setPinnedIds((ids) => ids.filter((existing) => existing !== id))
  }

  const resetDeals = () => {
    // Back to automatic: no explicit selection, no pins. Two updates, but
    // React batches them, so the debounced reprice still fires once.
    setSelection(null)
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
    setSelection((ids) =>
      ids === null ? null : ids.filter((existing) => existing !== id),
    )
    setPinnedIds((ids) => ids.filter((existing) => existing !== id))
  }

  const removePromotion = (id: string) => {
    // Drop it from signage/toggles and un-claim it, so the checkout's next
    // POST /price never references the deleted id (which would 422).
    setPromotions((existing) =>
      existing === null
        ? existing
        : existing.filter((promotion) => promotion.id !== id),
    )
    setClaimedIds((ids) => ids.filter((existing) => existing !== id))
  }

  const addPromotion = (promotion: PromotionInfo) => {
    // Append the 201 body — GET /promotions lists seeds then additions, so
    // this matches what a refetch would return. Shop signage and checkout
    // toggles read this state, so the new promotion appears immediately.
    // In automatic mode it competes for a slot straight away; under an
    // explicit selection it stays out until the shopper switches it on,
    // since adding it for them is exactly the surprise this mode removes.
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
            selection={selection}
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
