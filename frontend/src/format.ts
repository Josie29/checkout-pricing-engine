/**
 * Format integer cents as `$D.CC`. Render-time only — formatted strings are
 * never parsed back to numbers.
 *
 * @param cents - A non-negative amount in integer cents.
 * @returns The dollar string, e.g. `1600` -> `"$16.00"`.
 */
export function formatCents(cents: number): string {
  // Floor division / modulo split cents into dollar and cent parts.
  const dollars = Math.floor(cents / 100)
  const remainder = String(cents % 100).padStart(2, '0')
  return `$${dollars}.${remainder}`
}

/**
 * Format integer cents as a plain `D.CC` string (no `$`) for seeding the
 * editable price input.
 *
 * @param cents - A non-negative amount in integer cents.
 * @returns The plain dollar string, e.g. `1600` -> `"16.00"`.
 */
export function centsToDollarInput(cents: number): string {
  // Floor division / modulo split cents into dollar and cent parts.
  return `${Math.floor(cents / 100)}.${String(cents % 100).padStart(2, '0')}`
}

/**
 * Parse a user-typed dollar amount (e.g. "16", "16.5", "16.50") into integer
 * cents using string math — no floats, no locale surprises.
 *
 * @param input - The raw text from a price input.
 * @returns Integer cents, or null if the input is not a valid dollar amount.
 */
export function parseDollarsToCents(input: string): number | null {
  const match = /^\s*\$?\s*(\d+)(?:\.(\d{1,2}))?\s*$/.exec(input)
  if (!match || match[1] === undefined) {
    return null
  }
  // Pad "5" -> "50" so "$16.5" means 16 dollars 50 cents.
  const centsPart = (match[2] ?? '0').padEnd(2, '0')
  return Number(match[1]) * 100 + Number(centsPart)
}
