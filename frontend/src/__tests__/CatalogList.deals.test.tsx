/*
 * Removing this means nothing catches the bug where deal-chip signage
 * mismatches its promotion targets — a category promo missing from some of
 * its category's products, a SKU promo leaking onto other products, or
 * cart/shipping promos wrongly chipping product cards.
 */
import { afterEach, expect, test } from 'vitest'
import { cleanup, render, screen, within } from '@testing-library/react'
import { CatalogList } from '../components/CatalogList'
import type { CatalogItem, PromotionInfo } from '../types'

afterEach(cleanup)

const CATALOG: CatalogItem[] = [
  {
    sku: 'COF-ETH',
    name: 'Ethiopia Yirgacheffe, 12oz',
    category: 'Coffee Beans',
    unit_price_cents: 1600,
  },
  {
    sku: 'COF-COL',
    name: 'Colombia Supremo, 12oz',
    category: 'Coffee Beans',
    unit_price_cents: 1400,
  },
  {
    sku: 'BREW-V60',
    name: 'Ceramic Pour-Over Dripper',
    category: 'Brew Gear',
    unit_price_cents: 2800,
  },
  {
    sku: 'BREW-GRD',
    name: 'Manual Burr Grinder',
    category: 'Brew Gear',
    unit_price_cents: 4500,
  },
]

const PROMOTIONS: PromotionInfo[] = [
  {
    id: 'P1',
    name: 'Beans: buy 2 get 1 free',
    type: 'BXGY',
    phase: 'item',
    target: { kind: 'category', category: 'Coffee Beans' },
    params: { min_qty: 3 },
  },
  {
    id: 'P4',
    name: '$5 off pour-over dripper',
    type: 'FIXED_OFF_ITEM',
    phase: 'item',
    target: { kind: 'sku', sku: 'BREW-V60' },
    params: { amount_off_cents: 500 },
  },
  {
    id: 'P2',
    name: '15% off $50+',
    type: 'PCT_OFF_CART',
    phase: 'cart',
    target: { kind: 'cart' },
    params: { min_subtotal_cents: 5000, percent_off: 15 },
  },
  {
    id: 'P7',
    name: 'Free shipping $100+',
    type: 'FREE_SHIPPING',
    phase: 'shipping',
    target: { kind: 'shipping' },
    params: { min_subtotal_cents: 10000 },
  },
]

/** Chip texts on one product's card, [] when the card has no chip list. */
function chipsOn(productName: string): string[] {
  const chipList = screen.queryByRole('list', {
    name: `Deals on ${productName}`,
  })
  if (chipList === null) {
    return []
  }
  return within(chipList)
    .getAllByRole('listitem')
    .map((chip) => chip.textContent ?? '')
}

test('chips match item promos by category or sku; cart/shipping never chip', () => {
  render(
    <CatalogList catalog={CATALOG} promotions={PROMOTIONS} onAdd={() => {}} />,
  )
  // Category promo appears on every member of its category.
  expect(chipsOn('Ethiopia Yirgacheffe, 12oz')).toEqual([
    'Beans: buy 2 get 1 free',
  ])
  expect(chipsOn('Colombia Supremo, 12oz')).toEqual(['Beans: buy 2 get 1 free'])
  // SKU promo appears only on its SKU.
  expect(chipsOn('Ceramic Pour-Over Dripper')).toEqual([
    '$5 off pour-over dripper',
  ])
  // Non-targeted product gets no chips — and cart/shipping promos (P2, P7)
  // chipped no card above either.
  expect(chipsOn('Manual Burr Grinder')).toEqual([])
})
