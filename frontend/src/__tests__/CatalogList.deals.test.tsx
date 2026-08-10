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

/** Render the grid with an optional cart, defaulting to an empty one. */
function renderCatalog(qtyBySku: ReadonlyMap<string, number> = new Map()) {
  render(
    <CatalogList
      catalog={CATALOG}
      promotions={PROMOTIONS}
      qtyBySku={qtyBySku}
      onAdd={() => {}}
      onQtyStep={() => {}}
    />,
  )
}

test('chips match item promos by category or sku; cart/shipping never chip', () => {
  renderCatalog()
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

/*
 * Removing this means nothing catches the catalog card losing track of what
 * is already in the cart — a shopper would click Add repeatedly with no
 * feedback on the card, which is the confusion the stepper exists to fix.
 */
test('a card in the cart shows its quantity and swaps Add for a stepper', () => {
  renderCatalog(new Map([['COF-ETH', 3]]))
  // The in-cart product shows its count and no longer offers a bare Add.
  expect(
    screen.queryByRole('button', { name: 'Add Ethiopia Yirgacheffe, 12oz' }),
  ).toBeNull()
  expect(screen.getByText('3')).toBeTruthy()
  expect(
    screen.getByRole('button', {
      name: 'Increase quantity of Ethiopia Yirgacheffe, 12oz',
    }),
  ).toBeTruthy()
  // Every other card is untouched and still addable.
  expect(
    screen.getByRole('button', { name: 'Add Colombia Supremo, 12oz' }),
  ).toBeTruthy()
})

/*
 * Removing this means nothing catches the minus button silently doing
 * nothing (or stranding a qty-1 line) on the last unit — the shopper would
 * have no way to undo an accidental Add from the card they added it on.
 */
test('the last unit reads as remove, not decrease', () => {
  renderCatalog(new Map([['COF-ETH', 1]]))
  expect(
    screen.getByRole('button', {
      name: 'Remove Ethiopia Yirgacheffe, 12oz from cart',
    }),
  ).toBeTruthy()
})
