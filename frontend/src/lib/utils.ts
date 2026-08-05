import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Sanitize a value for CSV export to prevent formula injection.
 * Prefixes dangerous characters (=, +, -, @) with a single quote.
 */
export function sanitizeCSV(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return ''
  const str = String(value)
  // Prefix dangerous formula characters with a single quote
  if (/^[=+\-@]/.test(str)) {
    return `'${str}`
  }
  // Escape quotes and wrap in quotes if contains comma
  if (str.includes(',') || str.includes('"') || str.includes('\n')) {
    return `"${str.replace(/"/g, '""')}"`
  }
  return str
}

/**
 * Returns a currency formatter bound to the active broker.
 * - deltaexchange → USD ($)
 * - all other brokers  → INR (₹)
 */
export function makeFormatCurrency(
  broker?: string | null
): (value: number | string | null | undefined) => string {
  const isUSD = broker === 'deltaexchange'
  const fmt = new Intl.NumberFormat(isUSD ? 'en-US' : 'en-IN', {
    style: 'currency',
    currency: isUSD ? 'USD' : 'INR',
    minimumFractionDigits: 2,
  })
  return (value) => {
    // Intl.NumberFormat.format(undefined) returns the string "₹NaN" (and so
    // does format(NaN)), which is how order rows rendered "₹NaN" in the
    // Trigger column for order types that carry no trigger price. Broker
    // payloads legitimately omit fields per order type, so coercing here is
    // the fix -- 66 call sites should not each remember to guard.
    const num = typeof value === 'string' ? parseFloat(value) : value
    return fmt.format(typeof num === 'number' && Number.isFinite(num) ? num : 0)
  }
}

/**
 * Compact Indian-notation number: 12,34,567.89 -> "12.35L", 1.2e7 -> "1.20Cr".
 *
 * Three dashboard components each carried their own copy of this, and all
 * three shared the same hole: `Number.isNaN(undefined)` is FALSE (it matches
 * only the NaN value, not "not a number"), so an absent field slipped past
 * the guard into Math.abs(undefined) -> NaN -> toLocaleString() and rendered
 * the literal string "NaN" -- the dashboard showed "₹NaN" whenever a broker's
 * funds payload omitted a field. One implementation, one correct guard.
 *
 * Returns "0.00" for anything not finite, so callers can pass raw API values.
 */
export function formatIndianNumber(value: string | number | null | undefined): string {
  const num = typeof value === 'string' ? parseFloat(value) : value
  if (typeof num !== 'number' || !Number.isFinite(num)) return '0.00'

  const absNum = Math.abs(num)
  let formatted: string
  if (absNum >= 10000000) {
    formatted = `${(absNum / 10000000).toFixed(2)}Cr`
  } else if (absNum >= 100000) {
    formatted = `${(absNum / 100000).toFixed(2)}L`
  } else {
    formatted = absNum.toLocaleString('en-IN', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })
  }
  return num < 0 ? `-${formatted}` : formatted
}
