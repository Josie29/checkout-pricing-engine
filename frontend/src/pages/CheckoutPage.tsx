import { useEffect, useRef, useState } from 'react'
import { ApiError, postPrice } from '../api'
import type { CartItemInput, PriceResponse, PromotionInfo } from '../types'
import { PromotionToggles } from '../components/PromotionToggles'
import { PricePanel } from '../components/PricePanel'

/** Debounce window for `POST /price` so rapid toggle clicks fire one request. */
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

interface CheckoutPageProps {
  promotions: PromotionInfo[]
  cartItems: CartItemInput[]
  claimedIds: string[]
  onToggle: (id: string, claimed: boolean) => void
  /** Navigate back to the shop page. */
  onBackToShop: () => void
}

/** "Back to shop" as a real link so it reads as navigation; the click is
 * intercepted to route through `history.pushState` instead of a reload. */
function BackToShopLink({ onBackToShop }: { onBackToShop: () => void }) {
  return (
    <a
      href="/"
      className="back-link"
      onClick={(event) => {
        event.preventDefault()
        onBackToShop()
      }}
    >
      &larr; Back to shop
    </a>
  )
}

/**
 * The checkout page: the only surface that prices. It fires one debounced
 * `POST /price` on arrival and one per promotion toggle, and renders the
 * response verbatim in the price panel — the shop page never prices. An
 * empty cart (e.g. direct navigation to /checkout) renders an empty state
 * and makes no API call.
 */
export function CheckoutPage({
  promotions,
  cartItems,
  claimedIds,
  onToggle,
  onBackToShop,
}: CheckoutPageProps) {
  const [priced, setPriced] = useState<PricedResult | null>(null)
  const [failure, setFailure] = useState<PriceFailure | null>(null)

  // Bumping the nonce re-runs the price effect — the Retry button's only job.
  const [priceAttempt, setPriceAttempt] = useState(0)

  // Monotonic sequence guarding against out-of-order responses: only the
  // newest in-flight request may commit its result.
  const priceRequestSeq = useRef(0)

  // Price on mount and on every promotion toggle: one debounced POST /price
  // per change; stale responses are aborted and ignored. (Cart edits live on
  // the shop page, so cartItems is stable while this page is mounted.)
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

  const retryPrice = () => {
    // Clearing the failure returns the panel to its pending state while the
    // re-fired request is in flight.
    setFailure(null)
    setPriceAttempt((attempt) => attempt + 1)
  }

  if (cartItems.length === 0) {
    return (
      <section aria-labelledby="checkout-empty-heading">
        <h2 id="checkout-empty-heading">Checkout</h2>
        <p className="muted">
          Your cart is empty — nothing to price yet. Add items in the shop
          first.
        </p>
        <BackToShopLink onBackToShop={onBackToShop} />
      </section>
    )
  }

  const priceCurrent =
    priced !== null &&
    priced.cartItems === cartItems &&
    priced.claimedIds === claimedIds
  const failureCurrent =
    failure !== null &&
    failure.cartItems === cartItems &&
    failure.claimedIds === claimedIds
  const priceLoading = !priceCurrent && !failureCurrent

  return (
    <>
      <BackToShopLink onBackToShop={onBackToShop} />
      <div className="layout">
        <div>
          <PromotionToggles
            promotions={promotions}
            claimedIds={claimedIds}
            statuses={priced?.response.promotion_statuses ?? null}
            onToggle={onToggle}
          />
        </div>
        <div>
          <PricePanel
            price={priced?.response ?? null}
            cartEmpty={false}
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
    </>
  )
}
