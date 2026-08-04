/*
 * Removing these means nothing catches the bug where a product without a
 * matching /products/<SKU>.jpg shows the browser's broken-image icon in the
 * catalog instead of the neutral placeholder box, or where images stop
 * lazy-loading / lose their product-name alt text.
 */
import { afterEach, expect, test } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { ProductImage } from '../components/ProductImage'

afterEach(cleanup)

test('resolves the image from the sku with lazy loading and name alt', () => {
  render(<ProductImage sku="COF-ETH" name="Ethiopia Yirgacheffe, 12oz" />)
  const img = screen.getByAltText('Ethiopia Yirgacheffe, 12oz')
  expect(img.getAttribute('src')).toBe('/products/COF-ETH.jpg')
  expect(img.getAttribute('loading')).toBe('lazy')
})

test('a failed load swaps the img for a neutral placeholder box', () => {
  const { container } = render(<ProductImage sku="BOGUS" name="Bogus item" />)
  fireEvent.error(screen.getByAltText('Bogus item'))
  // The img is gone (no broken-image icon) but the fixed-aspect wrapper
  // remains as the placeholder, hidden from assistive tech.
  expect(container.querySelector('img')).toBeNull()
  const placeholder = container.querySelector('.product-image')
  expect(placeholder).not.toBeNull()
  expect(placeholder?.getAttribute('aria-hidden')).toBe('true')
})
