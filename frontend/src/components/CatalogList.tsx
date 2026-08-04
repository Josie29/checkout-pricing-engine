import type { CatalogItem } from '../types'
import { formatCents } from '../format'

interface CatalogListProps {
  catalog: CatalogItem[]
  onAdd: (item: CatalogItem) => void
}

/** Seeded catalog with an add button per product. */
export function CatalogList({ catalog, onAdd }: CatalogListProps) {
  return (
    <section aria-labelledby="catalog-heading">
      <h2 id="catalog-heading">Catalog</h2>
      <ul className="catalog-list">
        {catalog.map((item) => (
          <li key={item.sku} className="catalog-item">
            <div className="catalog-item-info">
              <span>{item.name}</span>
              <span className="muted">
                {item.category} · {formatCents(item.unit_price_cents)}
              </span>
            </div>
            <button
              type="button"
              onClick={() => onAdd(item)}
              aria-label={`Add ${item.name}`}
            >
              Add
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
