import type { CartItemInput, CatalogItem } from '../types'
import { CatalogList } from '../components/CatalogList'
import { CartTable } from '../components/CartTable'

interface ShopPageProps {
  catalog: CatalogItem[]
  cartItems: CartItemInput[]
  onAdd: (item: CatalogItem) => void
  /** Step a line's quantity by +1/-1; clamped to >= 1 by the owner. */
  onQtyStep: (sku: string, delta: 1 | -1) => void
  onPriceChange: (sku: string, unitPriceCents: number) => void
  onRemove: (sku: string) => void
  /** Navigate to the checkout page. */
  onCheckout: () => void
}

/**
 * The shop page: catalog and cart building only. It never calls
 * `POST /price` and never shows a total — unit prices come straight from
 * the catalog response, and all pricing happens on the checkout page.
 */
export function ShopPage({
  catalog,
  cartItems,
  onAdd,
  onQtyStep,
  onPriceChange,
  onRemove,
  onCheckout,
}: ShopPageProps) {
  const cartEmpty = cartItems.length === 0
  return (
    <div className="layout">
      <div>
        <CatalogList catalog={catalog} onAdd={onAdd} />
      </div>
      <div>
        <CartTable
          items={cartItems}
          onQtyStep={onQtyStep}
          onPriceChange={onPriceChange}
          onRemove={onRemove}
        />
        <div className="checkout-cta">
          <button
            type="button"
            className="checkout-button"
            disabled={cartEmpty}
            onClick={onCheckout}
          >
            Go to checkout
          </button>
          {cartEmpty && (
            <p className="muted">Add items to the cart to check out.</p>
          )}
        </div>
      </div>
    </div>
  )
}
