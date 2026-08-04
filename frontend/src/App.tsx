import { useEffect, useRef, useState } from 'react'
import { ApiError, fetchCatalog, fetchPromotions, postPrice } from './api'
import type {
  CartItemInput,
  CatalogItem,
  PriceResponse,
  PromotionInfo,
} from './types'
import { CatalogList } from './components/CatalogList'
import { CartTable } from './components/CartTable'
import { PromotionToggles } from './components/PromotionToggles'
import { PricePanel } from './components/PricePanel'

/** Debounce window for `POST /price` so rapid qty clicks fire one request. */
const PRICE_DEBOUNCE_MS = 250

/** A `POST /price` outcome tagged with the exact inputs it was computed for.
 * Comparing those inputs (by identity — every edit replaces the arrays) to
 * the current ones derives loading/stale state without extra flags. */
interface PricedResult {
  response: PriceResponse
  cartItems: CartItemInput[]
  claimedIds: string[]
}

/** A failed `POST /price`, tagged with its inputs like `PricedResult`. */
interface PriceFailure {
  message: string
  /** HTTP status of the failure; null for network-level errors. */
  status: number | null
  cartItems: CartItemInput[]
  claimedIds: string[]
}

/**
 * Single-page pricing UI: cart builder, promotion toggles, live price panel.
 * All pricing lives server-side — every cart edit or toggle fires one
 * debounced `POST /price` and the response is rendered verbatim.
 */
function App() {
  const [catalog, setCatalog] = useState<CatalogItem[] | null>(null)
  const [promotions, setPromotions] = useState<PromotionInfo[] | null>(null)
  const [seedError, setSeedError] = useState<string | null>(null)

  const [cartItems, setCartItems] = useState<CartItemInput[]>([])
  const [claimedIds, setClaimedIds] = useState<string[]>([])

  const [priced, setPriced] = useState<PricedResult | null>(null)
  const [failure, setFailure] = useState<PriceFailure | null>(null)

  // Bumping either nonce re-runs the matching fetch effect — the retry
  // buttons' only job.
  const [seedAttempt, setSeedAttempt] = useState(0)
  const [priceAttempt, setPriceAttempt] = useState(0)

  // Monotonic sequence guarding against out-of-order responses: only the
  // newest in-flight request may commit its result.
  const priceRequestSeq = useRef(0)

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

  // Reprice on every cart edit or promotion toggle: one debounced
  // POST /price per change; stale responses are aborted and ignored.
  useEffect(() => {
    if (cartItems.length === 0) {
      // Empty carts are a 422 by design — no call; the UI derives its
      // empty state from cartItems directly.
      return
    }
    const seq = ++priceRequestSeq.current
    const controller = new AbortController()
    const timer = setTimeout(() => {
      postPrice(
        { cart: { items: cartItems }, claimed_promotion_ids: claimedIds },
        controller.signal,
      )
        .then((response) => {
          if (seq === priceRequestSeq.current) {
            setPriced({ response, cartItems, claimedIds })
            setFailure(null)
          }
        })
        .catch((error: unknown) => {
          if (controller.signal.aborted || seq !== priceRequestSeq.current) {
            return
          }
          setFailure({
            message: error instanceof Error ? error.message : String(error),
            status: error instanceof ApiError ? error.status : null,
            cartItems,
            claimedIds,
          })
        })
    }, PRICE_DEBOUNCE_MS)
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [cartItems, claimedIds, priceAttempt])

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

  const retryPrice = () => {
    // Clearing the failure returns the panel to its pending state while the
    // re-fired request is in flight.
    setFailure(null)
    setPriceAttempt((attempt) => attempt + 1)
  }

  const cartEmpty = cartItems.length === 0
  const priceCurrent =
    priced !== null &&
    priced.cartItems === cartItems &&
    priced.claimedIds === claimedIds
  const failureCurrent =
    failure !== null &&
    failure.cartItems === cartItems &&
    failure.claimedIds === claimedIds
  const priceLoading = !cartEmpty && !priceCurrent && !failureCurrent

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
      ) : (
        <div className="layout">
          <div className="layout-build">
            <CatalogList catalog={catalog} onAdd={addCatalogItem} />
            <CartTable
              items={cartItems}
              onQtyStep={stepQty}
              onPriceChange={changePrice}
              onRemove={removeItem}
            />
            <PromotionToggles
              promotions={promotions}
              claimedIds={claimedIds}
              statuses={
                !cartEmpty && priced !== null
                  ? priced.response.promotion_statuses
                  : null
              }
              onToggle={togglePromotion}
            />
          </div>
          <div className="layout-price">
            <PricePanel
              price={priced?.response ?? null}
              cartEmpty={cartEmpty}
              loading={priceLoading}
              failure={
                failureCurrent
                  ? { message: failure.message, status: failure.status }
                  : null
              }
              onRetry={retryPrice}
            />
          </div>
        </div>
      )}
    </main>
  )
}

export default App
