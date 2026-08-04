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

/** `POST /price` 200 response body. */
export interface PriceResponse {
  lines: PricedLine[]
  adjustments: Adjustment[]
  subtotal_cents: number
  discount_total_cents: number
  shipping_cents: number
  total_cents: number
  optimal: boolean
  promotion_statuses: Record<string, PromotionStatus>
}

/** What a promotion acts on (discriminated on `kind`). */
export type PromotionTarget =
  | { kind: 'sku'; sku: string }
  | { kind: 'category'; category: string }
  | { kind: 'cart' }
  | { kind: 'shipping' }

/** One `GET /promotions` entry, in seed order. */
export interface PromotionInfo {
  id: string
  name: string
  type: string
  phase: Phase
  target: PromotionTarget
  params: Record<string, number>
}
