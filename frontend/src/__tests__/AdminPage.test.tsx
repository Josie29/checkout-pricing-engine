/*
 * Removing this means nothing catches the bug where the admin form posts a
 * malformed seed entry — above all a dollars input sent as a float (2.0)
 * instead of integer cents (200) — or swallows the 201 instead of surfacing
 * the success note and handing the created promotion to its owner.
 */
import { afterEach, expect, test, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { AdminPage } from '../pages/AdminPage'
import type { CatalogItem, PromotionInfo } from '../types'

const CATALOG: CatalogItem[] = [
  {
    sku: 'MUG-TVL',
    name: 'Travel Tumbler',
    category: 'Drinkware',
    unit_price_cents: 2200,
  },
  {
    sku: 'COF-ETH',
    name: 'Ethiopia Yirgacheffe, 12oz',
    category: 'Coffee Beans',
    unit_price_cents: 1600,
  },
]

/** Canned 201 body in the `GET /promotions` item shape. */
const CREATED: PromotionInfo = {
  id: 'A1',
  name: '$2 off travel mug',
  type: 'FIXED_OFF_ITEM',
  phase: 'item',
  target: { kind: 'sku', sku: 'MUG-TVL' },
  params: { amount_off_cents: 200 },
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

test('form posts the seed entry with dollars as integer cents and reports success', async () => {
  const fetchMock = vi.fn<
    (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>
  >(() =>
    Promise.resolve({
      ok: true,
      status: 201,
      json: () => Promise.resolve(CREATED),
    } as unknown as Response),
  )
  vi.stubGlobal('fetch', fetchMock)
  const onCreated = vi.fn()

  render(
    <AdminPage
      catalog={CATALOG}
      onCreated={onCreated}
      onBackToShop={() => {}}
    />,
  )

  fireEvent.change(screen.getByLabelText('Type'), {
    target: { value: 'FIXED_OFF_ITEM' },
  })
  fireEvent.change(screen.getByLabelText('Id'), { target: { value: 'A1' } })
  fireEvent.change(screen.getByLabelText('Name'), {
    target: { value: '$2 off travel mug' },
  })
  fireEvent.click(screen.getByLabelText('By SKU'))
  fireEvent.change(screen.getByLabelText('Product'), {
    target: { value: 'MUG-TVL' },
  })
  fireEvent.change(screen.getByLabelText('Amount off ($)'), {
    target: { value: '2' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Add promotion' }))

  // Success note names the promotion, and the 201 body goes to the owner so
  // shop signage and checkout toggles pick it up immediately.
  expect(await screen.findByText(/Added "\$2 off travel mug"/)).toBeDefined()
  expect(onCreated).toHaveBeenCalledWith(CREATED)

  // Exactly one POST /promotions, body in the seed-entry shape with the
  // dollars input converted to integer cents.
  expect(fetchMock).toHaveBeenCalledTimes(1)
  const [url, init] = fetchMock.mock.calls[0] ?? []
  expect(String(url).endsWith('/promotions')).toBe(true)
  expect(init?.method).toBe('POST')
  expect(JSON.parse(String(init?.body))).toEqual({
    type: 'FIXED_OFF_ITEM',
    id: 'A1',
    name: '$2 off travel mug',
    target: { kind: 'sku', sku: 'MUG-TVL' },
    amount_off_cents: 200,
  })

  // Submitting cleared the identity fields for the next entry.
  expect((screen.getByLabelText('Id') as HTMLInputElement).value).toBe('')
})
