import { useState } from 'react'

interface ProductImageProps {
  sku: string
  /** Product name — becomes the image's alt text. */
  name: string
  /** `card` for catalog cards, `thumb` for small cart thumbnails. */
  variant?: 'card' | 'thumb'
  /** Extra class on the wrapper (e.g. responsive show/hide hooks). */
  className?: string
}

/**
 * Product photo resolved by convention from the SKU: `/products/<SKU>.jpg`
 * under `frontend/public/` — no per-SKU list, no backend involvement.
 * Image attribution lives in `frontend/public/products/CREDITS.md`.
 *
 * If the file is missing or fails to load, the `img` unmounts and the
 * fixed-aspect wrapper stays as a neutral placeholder box, so the browser's
 * broken-image icon never appears.
 */
export function ProductImage({
  sku,
  name,
  variant = 'card',
  className,
}: ProductImageProps) {
  const [failed, setFailed] = useState(false)
  const classes = ['product-image', `product-image--${variant}`]
  if (className !== undefined) {
    classes.push(className)
  }
  return (
    // The empty placeholder box carries no information — hide it from
    // assistive tech; the product name is always adjacent text.
    <div className={classes.join(' ')} aria-hidden={failed || undefined}>
      {!failed && (
        <img
          src={`/products/${encodeURIComponent(sku)}.jpg`}
          alt={name}
          loading="lazy"
          onError={() => setFailed(true)}
        />
      )}
    </div>
  )
}
