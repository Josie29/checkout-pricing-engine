import { useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, postPrice } from '../api'
import type {
  CartItemInput,
  CatalogItem,
  DealToggleContext,
  PriceResponse,
  PromotionInfo,
} from '../types'
import { PromotionToggles } from '../components/PromotionToggles'
import { DealsExplainer } from '../components/DealsExplainer'
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
  pinnedIds: string[]
}

/** A failed `POST /price`, tagged with its inputs like `PricedResult`. */
interface PriceFailure {
  message: string
  /** HTTP status of the failure; null for network-level errors. */
  status: number | null
  cartItems: CartItemInput[]
  claimedIds: string[]
  pinnedIds: string[]
}

/** The automatic best total, remembered for the cart it was computed on.
 * Only responses with no overrides in play qualify, so this is always the
 * unconstrained optimum — what an override is measured against. */
interface BestKnown {
  cartItems: CartItemInput[]
  totalCents: number
}

interface CheckoutPageProps {
  promotions: PromotionInfo[]
  /** Seeded catalog — sku -> name lookup for readable coupon scope lines. */
  catalog: CatalogItem[]
  cartItems: CartItemInput[]
  /**
   * The shopper's explicit deal set, or null for automatic (every deal
   * claimed, server picks the best combination).
   */
  selection: string[] | null
  /** Deals the shopper forced on, overriding the optimizer's pick. */
  pinnedIds: string[]
  onToggle: (id: string, on: boolean, context: DealToggleContext) => void
  /** Drop every override, back to the automatic best combination. */
  onReset: () => void
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
  catalog,
  cartItems,
  selection,
  pinnedIds,
  onToggle,
  onReset,
  onBackToShop,
}: CheckoutPageProps) {
  // Automatic mode claims everything; an explicit selection claims exactly
  // itself, which is what keeps a deal the shopper never switched on out of
  // the search — and so out of the receipt — when they switch another off.
  const claimedIds = useMemo(
    () => selection ?? promotions.map((promo) => promo.id),
    [selection, promotions],
  )
  const overridden = selection !== null
  const [priced, setPriced] = useState<PricedResult | null>(null)
  const [failure, setFailure] = useState<PriceFailure | null>(null)
  // State, not a ref: the reset control's savings figure is rendered from
  // this, so a new baseline has to trigger a re-render.
  const [bestKnown, setBestKnown] = useState<BestKnown | null>(null)

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
    const overriding = selection !== null
    const timer = setTimeout(() => {
      postPrice(
        {
          cart: { items: cartItems },
          claimed_promotion_ids: claimedIds,
          pinned_promotion_ids: pinnedIds,
        },
        controller.signal,
      )
        .then((response) => {
          if (seq === priceRequestSeq.current) {
            if (!overriding) {
              // No overrides were in play, so this total *is* the automatic
              // best for this cart — the baseline an override is measured
              // against. Recorded against the cart identity so a later cart
              // edit invalidates it rather than quoting a stale saving.
              setBestKnown({ cartItems, totalCents: response.total_cents })
            }
            setPriced({ response, cartItems, claimedIds, pinnedIds })
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
            pinnedIds,
          })
        })
    }, PRICE_DEBOUNCE_MS)
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [cartItems, claimedIds, pinnedIds, priceAttempt, selection])

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
    priced.claimedIds === claimedIds &&
    priced.pinnedIds === pinnedIds
  const failureCurrent =
    failure !== null &&
    failure.cartItems === cartItems &&
    failure.claimedIds === claimedIds &&
    failure.pinnedIds === pinnedIds
  const priceLoading = !priceCurrent && !failureCurrent

  // What the override costs, but only when the automatic best is known for
  // *this* cart — editing the cart while overridden leaves us without a
  // baseline, and quoting a saving from the previous cart would be a lie.
  const overrideCostCents =
    overridden &&
    priceCurrent &&
    bestKnown !== null &&
    bestKnown.cartItems === cartItems &&
    priced.response.total_cents > bestKnown.totalCents
      ? priced.response.total_cents - bestKnown.totalCents
      : null

  // What the latest response actually applied, in trace order — the set the
  // first manual switch inherits as its explicit selection.
  const appliedIds =
    priced?.response.adjustments.map((adjustment) => adjustment.promotion_id) ??
    []

  // Cents saved per applied promotion, read off the response's adjustments
  // (like statuses, may briefly lag the toggles while a reprice is in
  // flight — the panel's stale marking covers both).
  const savedCents =
    priced === null
      ? null
      : Object.fromEntries(
          priced.response.adjustments.map((adjustment) => [
            adjustment.promotion_id,
            adjustment.amount_cents,
          ]),
        )

  return (
    <>
      <BackToShopLink onBackToShop={onBackToShop} />
      <div className="layout">
        <div>
          <PromotionToggles
            promotions={promotions}
            productNames={new Map(catalog.map((item) => [item.sku, item.name]))}
            statuses={priced?.response.promotion_statuses ?? null}
            availability={priced?.response.promotion_availability ?? null}
            savedCents={savedCents}
            overridden={overridden}
            overrideCostCents={overrideCostCents}
            appliedIds={appliedIds}
            onToggle={onToggle}
            onReset={onReset}
            pricePending={priceLoading}
          />
          <DealsExplainer price={priced?.response ?? null} />
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
