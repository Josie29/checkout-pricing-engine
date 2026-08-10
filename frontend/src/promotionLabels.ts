import type { EligibilityGap, PromotionTarget } from './types'
import { formatCents } from './format'

/**
 * What a shopper would have to do to unlock a deal their cart misses.
 *
 * The server measures the shortfall against the cascade state the deal
 * actually tests — i.e. after the deals that already applied — so this can
 * legitimately name a bigger number than the visible subtotal implies. The
 * copy says "after deals" rather than pretending otherwise.
 *
 * @param gap - The shortfall from `promotion_availability`, or null.
 * @param target - The deal's target, so quantity copy can name its scope.
 * @returns A short actionable line, or null when there is nothing to say.
 */
export function gapLabel(
  gap: EligibilityGap | null | undefined,
  target: PromotionTarget,
): string | null {
  if (!gap) {
    return null
  }
  if (gap.subtotal_short_cents !== null) {
    return `Spend ${formatCents(gap.subtotal_short_cents)} more after deals to unlock`
  }
  if (gap.qty_short !== null) {
    // SKU-targeted deals already name their product in the deal title, so
    // only a category needs spelling out here.
    const scope = target.kind === 'category' ? ` from ${target.category}` : ''
    const unit = gap.qty_short === 1 ? 'item' : 'items'
    return `Add ${gap.qty_short} more ${unit}${scope} to unlock`
  }
  return null
}

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
  if (params.free_qty !== undefined) {
    parts.push(`${params.free_qty} free`)
  }
  if (params.min_qty !== undefined) {
    parts.push(`min ${params.min_qty}`)
  }
  if (params.min_subtotal_cents !== undefined) {
    parts.push(`min subtotal ${formatCents(params.min_subtotal_cents)}`)
  }
  return parts.join(', ')
}
