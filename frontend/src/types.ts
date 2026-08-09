/**
 * Server contract types — mirror backend/app (domain.py, main.py) verbatim.
 * Money fields are integer cents; the UI formats them at render time only.
 */

export type Phase = 'item' | 'cart' | 'shipping'

export type PromotionStatus = 'available' | 'claimed' | 'applied'

/** One `GET /catalog` entry. */
export interface CatalogItem {
  sku: string
  name: string
  category: string
  unit_price_cents: number
}

/** One cart line in the `POST /price` request payload. */
export interface CartItemInput {
  sku: string
  name?: string
  category: string
  unit_price_cents: number
  qty: number
}

/** `POST /price` request body. */
export interface PriceRequest {
  cart: { items: CartItemInput[] }
  claimed_promotion_ids: string[]
  /**
   * Deals the shopper forced on, overriding the optimizer's pick. A pin
   * implies a claim, and constrains the search to combinations where the
   * pinned deal actually applies — the only way to take a deal the search
   * withheld for a better total elsewhere.
   */
  pinned_promotion_ids: string[]
}

/** One line of the itemized breakdown after discounts. */
export interface PricedLine {
  sku: string
  name: string | null
  category: string
  unit_price_cents: number
  qty: number
  line_subtotal_cents: number
  discount_cents: number
  line_total_cents: number
}

/** The portion of one adjustment's discount attributed to one line. */
export interface LineAllocation {
  sku: string
  amount_cents: number
}

/** Explanation-trace record: one applied promotion's effect. */
export interface Adjustment {
  promotion_id: string
  promotion_name: string
  phase: Phase
  amount_cents: number
  line_allocations: LineAllocation[]
}

/**
 * Items subtotal at each cascade boundary — what the items summed to after
 * item-phase deals (the base cart deals compute on) and after cart-phase
 * deals (the base free-shipping thresholds check). Additive field; older
 * servers omit it.
 */
export interface PhaseSubtotals {
  after_item_cents: number
  after_cart_cents: number
}

/**
 * How far a cart falls short of a deal's condition, in the deal's own units.
 * Exactly one field is set; the UI formats it ("add $10.00" / "add 2 more").
 */
export interface EligibilityGap {
  subtotal_short_cents: number | null
  qty_short: number | null
}

/**
 * Why a deal did or did not apply — the "why" behind `promotion_statuses`.
 *
 * `eligible` is judged against the winning combination's cascade state, so a
 * cart-level threshold reads the subtotal net of the item deals that actually
 * landed. That makes `eligible: false` the honest reason a deal did not fire,
 * and `eligible: true` on an unapplied deal mean "qualifies, but a rival won"
 * — the state the checkout keeps live and lets the shopper pin.
 */
export interface PromotionAvailability {
  eligible: boolean
  gap: EligibilityGap | null
  /** Ids that cannot apply alongside this one on this cart. */
  conflicts_with: string[]
}

/** `POST /price` 200 response body. */
export interface PriceResponse {
  lines: PricedLine[]
  adjustments: Adjustment[]
  subtotal_cents: number
  discount_total_cents: number
  shipping_cents: number
  total_cents: number
  optimal: boolean
  phase_subtotals?: PhaseSubtotals | null
  promotion_statuses: Record<string, PromotionStatus>
  /** Additive field; older servers omit it. */
  promotion_availability?: Record<string, PromotionAvailability>
}

/**
 * What the checkout knows at the moment a deal switch is clicked, handed to
 * the app-level handler that owns the selection.
 *
 * Both facts come from the latest price response, so the handler never has
 * to re-derive server logic: `appliedIds` is what the first manual switch
 * inherits as its starting selection, and `conflictsWith` is the exact
 * pairwise exclusivity the engine enforces on this cart.
 */
export interface DealToggleContext {
  appliedIds: string[]
  conflictsWith: string[]
}

/** What a promotion acts on (discriminated on `kind`). */
export type PromotionTarget =
  | { kind: 'sku'; sku: string }
  | { kind: 'category'; category: string }
  | { kind: 'cart' }
  | { kind: 'shipping' }

/** The five registered promotion kinds `POST /promotions` accepts. */
export type PromotionKind =
  'BXGY' | 'PCT_OFF_ITEM' | 'FIXED_OFF_ITEM' | 'PCT_OFF_CART' | 'FREE_SHIPPING'

/**
 * `POST /promotions` request body — one seed-entry object. The kind-specific
 * fields are optional here because each type takes a different subset; the
 * server validates the exact set (422 otherwise).
 */
export interface PromotionCreateRequest {
  type: PromotionKind
  /** Omitted, the server assigns the next free P<n> and returns it. */
  id?: string
  name: string
  target: PromotionTarget
  min_qty?: number
  free_qty?: number
  percent_off?: number
  amount_off_cents?: number
  min_subtotal_cents?: number
}

/** Where a stored promotion came from — file seeds or the admin API. */
export type PromotionSource = 'seed' | 'runtime'

/** One `GET /promotions` entry, in seed order. */
export interface PromotionInfo {
  id: string
  name: string
  type: string
  phase: Phase
  target: PromotionTarget
  params: Record<string, number>
  /** Additive field; older servers omit it. */
  source?: PromotionSource
}
