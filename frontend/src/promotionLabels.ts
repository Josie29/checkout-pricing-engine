import type { PromotionTarget } from './types'
import { formatCents } from './format'

/**
 * Scope line for a promotion, read directly off its target metadata (no
 * eligibility or amount logic). SKU targets resolve to the catalog product
 * name so shoppers never read raw SKUs. Shared by the checkout coupons and
 * the admin page's promotion list.
 *
 * @param target - The promotion's target.
 * @param productNames - Catalog sku -> display name lookup.
 * @returns A short human label like "item deal · Coffee Beans".
 */
export function scopeLabel(
  target: PromotionTarget,
  productNames: ReadonlyMap<string, string>,
): string {
  switch (target.kind) {
    case 'category':
      return `item deal · ${target.category}`
    case 'sku':
      return `item deal · ${productNames.get(target.sku) ?? target.sku}`
    case 'cart':
      return 'whole-cart deal'
    case 'shipping':
      return 'shipping deal'
  }
}

/**
 * Compact summary of a promotion's kind-specific parameters — effect first,
 * then condition — rendered verbatim from the `params` payload.
 *
 * @param params - The promotion's `params` from `GET /promotions`.
 * @returns E.g. "20% off, min 3" or "min subtotal $100.00"; '' when empty.
 */
export function paramsLabel(params: Record<string, number>): string {
  const parts: string[] = []
  if (params.percent_off !== undefined) {
    parts.push(`${params.percent_off}% off`)
  }
  if (params.amount_off_cents !== undefined) {
    parts.push(`${formatCents(params.amount_off_cents)} off`)
  }
  if (params.min_qty !== undefined) {
    parts.push(`min ${params.min_qty}`)
  }
  if (params.min_subtotal_cents !== undefined) {
    parts.push(`min subtotal ${formatCents(params.min_subtotal_cents)}`)
  }
  return parts.join(', ')
}
