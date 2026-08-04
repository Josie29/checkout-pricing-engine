/*
 * The single frontend smoke test (docs/testing-strategy.md). Removing it
 * means nothing catches the bug where the wired-together page stops turning
 * cart edits and promotion toggles into a `POST /price` and rendering the
 * server's total and explanation — e.g. a broken fetch seam, a debounce
 * regression that never fires, or a panel that ignores the response.
 */
import { afterEach, expect, test, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import App from '../App'
import type { CatalogItem, PriceResponse, PromotionInfo } from '../types'

const CATALOG: CatalogItem[] = [
  {
    sku: 'COF-ETH',
    name: 'Ethiopia Yirgacheffe, 12oz',
    category: 'Coffee Beans',
    unit_price_cents: 1600,
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
]

/** Canned `POST /price` result for beans x3 with no promotions claimed. */
const BASE_PRICE: PriceResponse = {
  lines: [
    {
      sku: 'COF-ETH',
      name: 'Ethiopia Yirgacheffe, 12oz',
      category: 'Coffee Beans',
      unit_price_cents: 1600,
      qty: 3,
      line_subtotal_cents: 4800,
      discount_cents: 0,
      line_total_cents: 4800,
    },
  ],
  adjustments: [],
  subtotal_cents: 4800,
  discount_total_cents: 0,
  shipping_cents: 700,
  total_cents: 5500,
  optimal: true,
  promotion_statuses: { P1: 'available' },
}

/** Canned result for beans x3 with P1 claimed: one unit free. */
const DISCOUNTED_PRICE: PriceResponse = {
  lines: [
    {
      sku: 'COF-ETH',
      name: 'Ethiopia Yirgacheffe, 12oz',
      category: 'Coffee Beans',
      unit_price_cents: 1600,
      qty: 3,
      line_subtotal_cents: 4800,
      discount_cents: 1600,
      line_total_cents: 3200,
    },
  ],
  adjustments: [
    {
      promotion_id: 'P1',
      promotion_name: 'Beans: buy 2 get 1 free',
      phase: 'item',
      amount_cents: 1600,
      line_allocations: [{ sku: 'COF-ETH', amount_cents: 1600 }],
    },
  ],
  subtotal_cents: 4800,
  discount_total_cents: 1600,
  shipping_cents: 700,
  total_cents: 3900,
  optimal: true,
  promotion_statuses: { P1: 'applied' },
}

/** Wrap a canned body in the minimal Response surface `api.ts` uses. */
function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: () => Promise.resolve(body),
  } as unknown as Response
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

test('cart edit and promotion toggle render the priced response', async () => {
  // Mock fetch at the api.ts seam: canned catalog/promotions, and a /price
  // that answers from the claimed promotion ids in the request body.
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/catalog')) {
        return Promise.resolve(jsonResponse(CATALOG))
      }
      if (url.endsWith('/promotions')) {
        return Promise.resolve(jsonResponse(PROMOTIONS))
      }
      if (url.endsWith('/price')) {
        const body = JSON.parse(String(init?.body)) as {
          claimed_promotion_ids: string[]
        }
        return Promise.resolve(
          jsonResponse(
            body.claimed_promotion_ids.includes('P1')
              ? DISCOUNTED_PRICE
              : BASE_PRICE,
          ),
        )
      }
      return Promise.reject(new Error(`Unexpected fetch: ${url}`))
    }),
  )

  render(<App />)

  // Add beans x3 once the catalog has loaded; the debounced POST /price
  // fires and the base total renders.
  const addButton = await screen.findByRole('button', {
    name: 'Add Ethiopia Yirgacheffe, 12oz',
  })
  fireEvent.click(addButton)
  fireEvent.click(addButton)
  fireEvent.click(addButton)
  expect(await screen.findByText('$55.00')).toBeDefined()

  // Toggle P1: the repriced total and its explanation come straight from
  // the canned response.
  fireEvent.click(
    screen.getByRole('checkbox', { name: 'Beans: buy 2 get 1 free' }),
  )
  expect(await screen.findByText('$39.00')).toBeDefined()
  expect(
    screen.getByText('Beans: buy 2 get 1 free (item promotion) — saved $16.00'),
  ).toBeDefined()
  expect(
    screen.getByText('$16.00 off Ethiopia Yirgacheffe, 12oz'),
  ).toBeDefined()
})
