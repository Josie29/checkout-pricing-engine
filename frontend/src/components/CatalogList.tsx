import type { CatalogItem, PromotionInfo } from '../types'
import { formatCents } from '../format'
import { ProductImage } from './ProductImage'

interface CatalogListProps {
  catalog: CatalogItem[]
  /** Full promotion list; item-phase entries become per-product deal chips. */
  promotions: PromotionInfo[]
  /** Quantity already in the cart per SKU; absent means not in the cart. */
  qtyBySku: ReadonlyMap<string, number>
  onAdd: (item: CatalogItem) => void
  onQtyStep: (sku: string, delta: 1 | -1) => void
}

/**
 * Item-phase promotions whose target matches the product, by metadata only:
 * category targets match on equal category, SKU targets on equal SKU.
 * No price or eligibility (qty) logic — chips are read-only signage.
 *
 * @param item - The catalog product being rendered.
 * @param promotions - The seeded promotion list.
 * @returns The promotions to chip on this product's card, in seed order.
 */
function itemPromotionsFor(
  item: CatalogItem,
  promotions: PromotionInfo[],
): PromotionInfo[] {
  return promotions.filter(
    (promo) =>
      promo.phase === 'item' &&
      ((promo.target.kind === 'category' &&
        promo.target.category === item.category) ||
        (promo.target.kind === 'sku' && promo.target.sku === item.sku)),
  )
}

/**
 * Seeded catalog as a grid of image-led cards: photo on top, name and
 * category below, deal chips, and a price + Add row pinned to the card
 * bottom. The heading lives in `ShopPage` (next to the deals toggle), so
 * the section labels itself.
 *
 * A card already in the cart swaps its Add button for a quantity stepper
 * showing the count, so the grid answers "how many of this do I have?"
 * without opening the drawer. Stepping the last unit down removes the line
 * and the stepper collapses back to Add.
 */
export function CatalogList({
  catalog,
  promotions,
  qtyBySku,
  onAdd,
  onQtyStep,
}: CatalogListProps) {
  return (
    <section aria-label="Catalog">
      <ul className="catalog-list">
        {catalog.map((item) => {
          const deals = itemPromotionsFor(item, promotions)
          const qty = qtyBySku.get(item.sku)
          return (
            <li key={item.sku} className="catalog-item">
              <ProductImage sku={item.sku} name={item.name} />
              <div className="catalog-item-info">
                <span className="catalog-item-name">{item.name}</span>
                <span className="muted">{item.category}</span>
                {deals.length > 0 && (
                  <ul
                    className="deal-chips"
                    aria-label={`Deals on ${item.name}`}
                  >
                    {deals.map((promo) => (
                      <li key={promo.id} className="deal-chip">
                        {promo.name}
                      </li>
                    ))}
                  </ul>
                )}
                <div className="catalog-item-buy">
                  <span className="catalog-item-price">
                    {formatCents(item.unit_price_cents)}
                  </span>
                  {qty === undefined ? (
                    <button
                      type="button"
                      className="add-button"
                      onClick={() => onAdd(item)}
                      aria-label={`Add ${item.name}`}
                    >
                      Add
                    </button>
                  ) : (
                    <div className="qty-stepper">
                      <button
                        type="button"
                        onClick={() => onQtyStep(item.sku, -1)}
                        aria-label={
                          qty === 1
                            ? `Remove ${item.name} from cart`
                            : `Decrease quantity of ${item.name}`
                        }
                      >
                        &minus;
                      </button>
                      {/* Live so a screen reader announces the new count
                          rather than silently re-rendering the button. */}
                      <output className="qty-stepper-count" aria-live="polite">
                        {qty}
                      </output>
                      <button
                        type="button"
                        onClick={() => onQtyStep(item.sku, 1)}
                        aria-label={`Increase quantity of ${item.name}`}
                      >
                        +
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
