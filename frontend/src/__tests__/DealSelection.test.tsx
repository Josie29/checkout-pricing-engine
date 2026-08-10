/*
 * Removing this means nothing catches the checkout re-optimizing behind the
 * shopper's back. Switching a deal off must be purely subtractive: a rival
 * the shopper never turned on must not promote itself into the receipt, and
 * the switches must only ever move in response to a click. The App smoke
 * test cannot cover this — it seeds a single promotion, so there is no rival
 * to substitute in.
 */
import { afterEach, expect, test, vi } from 'vitest'
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import App from '../App'
import type {
  CatalogItem,
  PriceResponse,
  PromotionAvailability,
  PromotionInfo,
} from '../types'

const CATALOG: CatalogItem[] = [
  {
    sku: 'COF-ETH',
    name: 'Ethiopia Yirgacheffe, 12oz',
    category: 'Coffee Beans',
    unit_price_cents: 1600,
  },
]

// Two deals on the same category: mutually exclusive, P1 the better of the
// two on a three-bag cart (one free bag, 1600, beats 20% of 4800, 960).
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
    id: 'P6',
    name: 'Beans: 20% off',
    type: 'PCT_OFF_ITEM',
    phase: 'item',
    target: { kind: 'category', category: 'Coffee Beans' },
    params: { min_qty: 3, percent_off: 20 },
  },
]

/** Both deals qualify on a three-bag cart, and each blocks the other. */
const AVAILABILITY: Record<string, PromotionAvailability> = {
  P1: { eligible: true, gap: null, conflicts_with: ['P6'] },
  P6: { eligible: true, gap: null, conflicts_with: ['P1'] },
}

/**
 * Canned priced response for beans x3 with one deal applied (or none).
 *
 * @param applied - The winning deal id, or null for an undiscounted cart.
 * @param discount - Its discount in cents (0 when nothing applied).
 * @returns A self-consistent `POST /price` body.
 */
function priceBody(applied: string | null, discount: number): PriceResponse {
  const promotion = PROMOTIONS.find((promo) => promo.id === applied)
  return {
    lines: [
      {
        sku: 'COF-ETH',
        name: 'Ethiopia Yirgacheffe, 12oz',
        category: 'Coffee Beans',
        unit_price_cents: 1600,
        qty: 3,
        line_subtotal_cents: 4800,
        discount_cents: discount,
        line_total_cents: 4800 - discount,
      },
    ],
    adjustments:
      promotion === undefined
        ? []
        : [
            {
              promotion_id: promotion.id,
              promotion_name: promotion.name,
              phase: 'item',
              amount_cents: discount,
              line_allocations: [{ sku: 'COF-ETH', amount_cents: discount }],
            },
          ],
    subtotal_cents: 4800,
    discount_total_cents: discount,
    shipping_cents: 700,
    total_cents: 4800 - discount + 700,
    optimal: true,
    phase_subtotals: {
      after_item_cents: 4800 - discount,
      after_cart_cents: 4800 - discount,
    },
    promotion_statuses: {
      P1: applied === 'P1' ? 'applied' : 'claimed',
      P6: applied === 'P6' ? 'applied' : 'claimed',
    },
    promotion_availability: AVAILABILITY,
  }
}

/** Wrap a canned body in the minimal Response surface `api.ts` uses. */
function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: () => Promise.resolve(body),
  } as unknown as Response
}

/**
 * Stand-in for the optimizer: applies the best *claimed* deal, honouring a
 * pin over the automatic choice. Deliberately mirrors the server's rule that
 * only claimed deals can ever apply — which is exactly what the frontend
 * relies on to keep a switched-off deal's rival out of the receipt.
 */
function installFetchMock() {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
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
        pinned_promotion_ids: string[]
      }
      const claimed = new Set(body.claimed_promotion_ids)
      const pinned = body.pinned_promotion_ids
      if (pinned.includes('P6')) {
        return Promise.resolve(jsonResponse(priceBody('P6', 960)))
      }
      if (pinned.includes('P1') || claimed.has('P1')) {
        return Promise.resolve(jsonResponse(priceBody('P1', 1600)))
      }
      if (claimed.has('P6')) {
        return Promise.resolve(jsonResponse(priceBody('P6', 960)))
      }
      return Promise.resolve(jsonResponse(priceBody(null, 0)))
    }
    return Promise.reject(new Error(`Unexpected fetch: ${url}`))
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

/** Build a three-bag cart and land on the checkout page. */
async function goToCheckout() {
  render(<App />)
  fireEvent.click(
    await screen.findByRole('button', {
      name: 'Add Ethiopia Yirgacheffe, 12oz',
    }),
  )
  const plus = screen.getByRole('button', {
    name: 'Increase quantity of Ethiopia Yirgacheffe, 12oz',
  })
  fireEvent.click(plus)
  fireEvent.click(plus)
  fireEvent.click(screen.getByRole('button', { name: 'Cart, 3 items' }))
  fireEvent.click(screen.getByRole('button', { name: 'Go to checkout' }))
}

/** The checkbox for one deal, by its accessible name. */
function dealSwitch(name: string): HTMLInputElement {
  return screen.getByRole('checkbox', { name }) as HTMLInputElement
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  window.history.replaceState(null, '', '/')
})

test('switching a deal off does not promote its rival', async () => {
  installFetchMock()
  await goToCheckout()

  // Arrival: the optimizer took the better deal; its rival qualifies but is
  // off, which is the state the shopper is about to act on.
  expect(await screen.findByText('$39.00')).toBeDefined()
  expect(dealSwitch('Beans: buy 2 get 1 free').checked).toBe(true)
  expect(dealSwitch('Beans: 20% off').checked).toBe(false)

  fireEvent.click(dealSwitch('Beans: buy 2 get 1 free'))

  // The cart falls back to the undiscounted total — NOT to the rival's
  // $45.40. Switching off is subtractive; it must not hand the shopper a
  // deal they never asked for.
  expect(await screen.findByText('$55.00')).toBeDefined()
  expect(dealSwitch('Beans: buy 2 get 1 free').checked).toBe(false)
  expect(dealSwitch('Beans: 20% off').checked).toBe(false)
})

test('a rival left un-applied stays live rather than greying out', async () => {
  installFetchMock()
  await goToCheckout()
  expect(await screen.findByText('$39.00')).toBeDefined()

  fireEvent.click(dealSwitch('Beans: buy 2 get 1 free'))
  await screen.findByText('$55.00')

  // Still eligible, so it must stay switchable — greying it out here would
  // strand the shopper with no way to take the deal they can plainly have.
  const rival = dealSwitch('Beans: 20% off')
  expect(rival.disabled).toBe(false)
  expect(screen.getAllByText('qualifies').length).toBeGreaterThan(0)

  // And switching it on pins it, so it applies despite being the weaker deal.
  fireEvent.click(rival)
  expect(await screen.findByText('$45.40')).toBeDefined()
  expect(dealSwitch('Beans: 20% off').checked).toBe(true)
  expect(dealSwitch('Beans: buy 2 get 1 free').checked).toBe(false)
})

test('reset returns to the automatic best combination', async () => {
  installFetchMock()
  await goToCheckout()
  expect(await screen.findByText('$39.00')).toBeDefined()

  fireEvent.click(dealSwitch('Beans: buy 2 get 1 free'))
  expect(await screen.findByText('$55.00')).toBeDefined()

  // The reset control quotes what the override costs against the baseline
  // captured on arrival ($55.00 - $39.00).
  fireEvent.click(
    await screen.findByRole('button', { name: 'Best deal saves $16.00' }),
  )
  expect(await screen.findByText('$39.00')).toBeDefined()
  await waitFor(() => {
    expect(screen.queryByRole('button', { name: /^Best deal/ })).toBeNull()
  })
})
