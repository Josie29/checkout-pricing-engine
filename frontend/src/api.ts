/**
 * The single seam to the backend pricing API. Components never call `fetch`
 * directly — everything goes through these functions.
 */
import type {
  CatalogItem,
  PriceRequest,
  PriceResponse,
  PromotionInfo,
} from './types'

const BASE_URL: string =
  import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

/** A non-2xx response from the pricing API, carrying its `detail` message. */
export class ApiError extends Error {
  readonly status: number

  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
  }
}

/**
 * Perform one API request and parse the JSON body.
 *
 * @param path - Path relative to the API base URL (e.g. `/price`).
 * @param init - Fetch options (method, body, signal).
 * @returns The parsed response body.
 * @throws {ApiError} On any non-2xx response, with the server's `detail`.
 */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, init)
  if (!response.ok) {
    let detail = `Request failed (${response.status})`
    try {
      const body: unknown = await response.json()
      if (body !== null && typeof body === 'object' && 'detail' in body) {
        detail = JSON.stringify((body as { detail: unknown }).detail)
      }
    } catch {
      // Non-JSON error body — keep the generic status message.
    }
    throw new ApiError(response.status, detail)
  }
  return (await response.json()) as T
}

/**
 * Fetch the seeded catalog for the cart builder.
 *
 * @returns Catalog items in seed order.
 * @throws {ApiError} On any non-2xx response.
 */
export function fetchCatalog(): Promise<CatalogItem[]> {
  return request<CatalogItem[]>('/catalog')
}

/**
 * Fetch the seeded promotions for the toggle list.
 *
 * @returns Promotions in seed order.
 * @throws {ApiError} On any non-2xx response.
 */
export function fetchPromotions(): Promise<PromotionInfo[]> {
  return request<PromotionInfo[]>('/promotions')
}

/**
 * Price a cart with the claimed promotions. The backend is the only pricing
 * engine — the caller renders this response verbatim.
 *
 * @param body - The cart and claimed promotion ids.
 * @param signal - Abort signal so stale in-flight requests can be cancelled.
 * @returns The itemized pricing result.
 * @throws {ApiError} On any non-2xx response (422 for invalid carts/ids).
 */
export function postPrice(
  body: PriceRequest,
  signal?: AbortSignal,
): Promise<PriceResponse> {
  return request<PriceResponse>('/price', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
}
