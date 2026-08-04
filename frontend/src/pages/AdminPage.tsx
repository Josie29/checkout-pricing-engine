import { useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { createPromotion } from '../api'
import { parseDollarsToCents } from '../format'
import type {
  CatalogItem,
  PromotionCreateRequest,
  PromotionInfo,
  PromotionKind,
  PromotionTarget,
} from '../types'

/** Human labels for the five registered promotion kinds, in menu order. */
const KIND_LABELS: Record<PromotionKind, string> = {
  BXGY: 'Buy N, get one free',
  PCT_OFF_ITEM: 'Percent off an item',
  FIXED_OFF_ITEM: 'Fixed amount off an item',
  PCT_OFF_CART: 'Percent off the cart',
  FREE_SHIPPING: 'Free shipping',
}

const KINDS = Object.keys(KIND_LABELS) as PromotionKind[]

/** Kinds whose promotions target a SKU or category (item phase). */
const ITEM_KINDS: readonly PromotionKind[] = [
  'BXGY',
  'PCT_OFF_ITEM',
  'FIXED_OFF_ITEM',
]

/**
 * Parse a whole-number input value within an inclusive range.
 *
 * @param raw - The raw input text.
 * @param min - Smallest accepted value.
 * @param max - Largest accepted value.
 * @returns The integer, or null if the text is not an integer in range.
 */
function parseIntInRange(raw: string, min: number, max: number): number | null {
  const value = Number(raw)
  if (!Number.isInteger(value) || value < min || value > max) {
    return null
  }
  return value
}

interface AdminPageProps {
  /** The already-fetched catalog — source of the target dropdowns. */
  catalog: CatalogItem[]
  /** Called with the 201 body so the owner can append it to its list. */
  onCreated: (promotion: PromotionInfo) => void
  /** Navigate back to the shop page. */
  onBackToShop: () => void
}

/**
 * The admin page (`/admin`): an add-promotion form posting one seed-entry
 * body to `POST /promotions`. Client-side checks are the cheap ones only
 * (fields present, numeric ranges); real validation — duplicate ids, target
 * scoping — is the server's 422, surfaced inline. Additions are in-memory
 * only and the page is unauthenticated by scope.
 */
export function AdminPage({
  catalog,
  onCreated,
  onBackToShop,
}: AdminPageProps) {
  // Distinct categories present in the catalog (Set spread dedupes).
  const categories = useMemo(
    () => [...new Set(catalog.map((item) => item.category))],
    [catalog],
  )

  const [kind, setKind] = useState<PromotionKind>('BXGY')
  const [id, setId] = useState('')
  const [name, setName] = useState('')
  const [targetKind, setTargetKind] = useState<'category' | 'sku'>('category')
  const [category, setCategory] = useState(() => categories[0] ?? '')
  const [sku, setSku] = useState(() => catalog[0]?.sku ?? '')
  const [minQty, setMinQty] = useState('')
  const [percentOff, setPercentOff] = useState('')
  const [amountOff, setAmountOff] = useState('')
  const [minSubtotal, setMinSubtotal] = useState('')

  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  const isItemKind = ITEM_KINDS.includes(kind)

  /**
   * Assemble the seed-entry body for the current form state. Dollar inputs
   * convert to integer cents with string math — never floats.
   *
   * @returns The request body, or a message describing the first problem.
   */
  const buildEntry = (): PromotionCreateRequest | string => {
    const trimmedId = id.trim()
    const trimmedName = name.trim()
    if (trimmedId === '' || trimmedName === '') {
      return 'Id and name are required.'
    }

    let target: PromotionTarget
    if (!isItemKind) {
      // Cart/shipping kinds have exactly one valid target — no picker.
      target = kind === 'PCT_OFF_CART' ? { kind: 'cart' } : { kind: 'shipping' }
    } else if (targetKind === 'category') {
      if (category === '') {
        return 'Pick a target category.'
      }
      target = { kind: 'category', category }
    } else {
      if (sku === '') {
        return 'Pick a target product.'
      }
      target = { kind: 'sku', sku }
    }

    const entry: PromotionCreateRequest = {
      type: kind,
      id: trimmedId,
      name: trimmedName,
      target,
    }

    if (kind === 'BXGY' || kind === 'PCT_OFF_ITEM') {
      const qty = parseIntInRange(minQty, 1, Number.MAX_SAFE_INTEGER)
      if (qty === null) {
        return 'Min quantity must be a whole number of at least 1.'
      }
      entry.min_qty = qty
    }
    if (kind === 'PCT_OFF_ITEM' || kind === 'PCT_OFF_CART') {
      const percent = parseIntInRange(percentOff, 1, 100)
      if (percent === null) {
        return 'Percent off must be a whole number from 1 to 100.'
      }
      entry.percent_off = percent
    }
    if (kind === 'FIXED_OFF_ITEM') {
      const cents = parseDollarsToCents(amountOff)
      if (cents === null || cents === 0) {
        return 'Amount off must be a dollar amount like 2 or 2.50.'
      }
      entry.amount_off_cents = cents
    }
    if (kind === 'PCT_OFF_CART' || kind === 'FREE_SHIPPING') {
      const cents = parseDollarsToCents(minSubtotal)
      if (cents === null) {
        return 'Min subtotal must be a dollar amount like 50 or 50.00.'
      }
      entry.min_subtotal_cents = cents
    }
    return entry
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const built = buildEntry()
    if (typeof built === 'string') {
      setError(built)
      setSuccess(null)
      return
    }
    setPending(true)
    setError(null)
    setSuccess(null)
    createPromotion(built)
      .then((promotion) => {
        onCreated(promotion)
        setSuccess(
          `Added "${promotion.name}" — it now appears in the shop and checkout.`,
        )
        setId('')
        setName('')
        setMinQty('')
        setPercentOff('')
        setAmountOff('')
        setMinSubtotal('')
      })
      .catch((cause: unknown) => {
        setError(cause instanceof Error ? cause.message : String(cause))
      })
      .finally(() => {
        setPending(false)
      })
  }

  return (
    <section aria-labelledby="admin-heading">
      <a
        href="/"
        className="back-link"
        onClick={(event) => {
          event.preventDefault()
          onBackToShop()
        }}
      >
        &larr; Back to shop
      </a>
      <h2 id="admin-heading">Add a promotion</h2>
      <p className="muted admin-note">
        Runtime-only: promotions added here reset when the server restarts. This
        page is unauthenticated by scope.
      </p>
      <form className="admin-form" onSubmit={handleSubmit}>
        <label className="admin-field">
          <span>Type</span>
          <select
            value={kind}
            onChange={(event) => setKind(event.target.value as PromotionKind)}
          >
            {KINDS.map((value) => (
              <option key={value} value={value}>
                {KIND_LABELS[value]}
              </option>
            ))}
          </select>
        </label>

        <label className="admin-field">
          <span>Id</span>
          <input
            value={id}
            required
            onChange={(event) => setId(event.target.value)}
          />
        </label>

        <label className="admin-field">
          <span>Name</span>
          <input
            value={name}
            required
            onChange={(event) => setName(event.target.value)}
          />
        </label>

        {isItemKind && (
          <fieldset className="admin-target">
            <legend>Target</legend>
            <div className="admin-radios">
              <label>
                <input
                  type="radio"
                  name="target-kind"
                  checked={targetKind === 'category'}
                  onChange={() => setTargetKind('category')}
                />
                <span>By category</span>
              </label>
              <label>
                <input
                  type="radio"
                  name="target-kind"
                  checked={targetKind === 'sku'}
                  onChange={() => setTargetKind('sku')}
                />
                <span>By SKU</span>
              </label>
            </div>
            {targetKind === 'category' ? (
              <label className="admin-field">
                <span>Category</span>
                <select
                  value={category}
                  onChange={(event) => setCategory(event.target.value)}
                >
                  {categories.map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              <label className="admin-field">
                <span>Product</span>
                <select
                  value={sku}
                  onChange={(event) => setSku(event.target.value)}
                >
                  {catalog.map((item) => (
                    <option key={item.sku} value={item.sku}>
                      {item.name} ({item.sku})
                    </option>
                  ))}
                </select>
              </label>
            )}
          </fieldset>
        )}

        {!isItemKind && (
          <p className="muted">
            {kind === 'PCT_OFF_CART'
              ? 'Applies to the whole cart — no target to pick.'
              : 'Applies to shipping — no target to pick.'}
          </p>
        )}

        {(kind === 'BXGY' || kind === 'PCT_OFF_ITEM') && (
          <label className="admin-field">
            <span>Min quantity</span>
            <input
              type="number"
              min={1}
              step={1}
              required
              value={minQty}
              onChange={(event) => setMinQty(event.target.value)}
            />
          </label>
        )}

        {(kind === 'PCT_OFF_ITEM' || kind === 'PCT_OFF_CART') && (
          <label className="admin-field">
            <span>Percent off</span>
            <input
              type="number"
              min={1}
              max={100}
              step={1}
              required
              value={percentOff}
              onChange={(event) => setPercentOff(event.target.value)}
            />
          </label>
        )}

        {kind === 'FIXED_OFF_ITEM' && (
          <label className="admin-field">
            <span>Amount off ($)</span>
            <input
              inputMode="decimal"
              placeholder="2.50"
              required
              value={amountOff}
              onChange={(event) => setAmountOff(event.target.value)}
            />
          </label>
        )}

        {(kind === 'PCT_OFF_CART' || kind === 'FREE_SHIPPING') && (
          <label className="admin-field">
            <span>Min subtotal ($)</span>
            <input
              inputMode="decimal"
              placeholder="50.00"
              required
              value={minSubtotal}
              onChange={(event) => setMinSubtotal(event.target.value)}
            />
          </label>
        )}

        <div>
          <button type="submit" className="checkout-button" disabled={pending}>
            {pending ? 'Adding…' : 'Add promotion'}
          </button>
        </div>

        {error !== null && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {success !== null && (
          <p className="admin-success" role="status">
            {success}
          </p>
        )}
      </form>
    </section>
  )
}
