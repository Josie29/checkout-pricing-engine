/**
 * The single seam to the backend pricing API. Components never call `fetch`
 * directly — everything goes through these functions.
 */
import type {
  CatalogItem,
  PriceRequest,
  PriceResponse,
  PromotionCreateRequest,
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
 * Render a FastAPI `detail` field as a human-readable sentence. Plain-string
 * details pass through; Pydantic validation arrays become their joined `msg`
 * texts instead of raw JSON.
 *
 * @param detail - The `detail` value from an error response body.
 * @returns A readable message for the error region.
 */
function formatDetail(detail: unknown): string {
  if (typeof detail === 'string') {
    return detail
  }
  if (Array.isArray(detail)) {
    return detail
      .map((entry: unknown) =>
        entry !== null && typeof entry === 'object' && 'msg' in entry
          ? String((entry as { msg: unknown }).msg)
          : JSON.stringify(entry),
      )
      .join('; ')
  }
  return JSON.stringify(detail)
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
        detail = formatDetail((body as { detail: unknown }).detail)
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
 * Add one promotion at runtime (the unauthenticated admin page). The body is
 * a seed-entry object; the server validates it and stores it in memory only.
 *
 * @param entry - The seed-entry body for the new promotion.
 * @returns The stored promotion in the `GET /promotions` item shape.
 * @throws {ApiError} On any non-2xx response (422 for duplicate ids, unknown
 *   types, mis-scoped targets, or invalid fields, with the server's detail).
 */
export function createPromotion(
  entry: PromotionCreateRequest,
): Promise<PromotionInfo> {
  return request<PromotionInfo>('/promotions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(entry),
  })
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
