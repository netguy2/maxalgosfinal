import { describe, expect, it } from 'vitest'
import { formatIndianNumber } from './utils'

describe('formatIndianNumber', () => {
  it('formats plain numbers with two decimals and Indian grouping', () => {
    expect(formatIndianNumber(0)).toBe('0.00')
    expect(formatIndianNumber(1234.5)).toBe('1,234.50')
    expect(formatIndianNumber('99999')).toBe('99,999.00')
  })

  it('abbreviates lakhs and crores', () => {
    expect(formatIndianNumber(482915.4)).toBe('4.83L')
    expect(formatIndianNumber('12345678')).toBe('1.23Cr')
  })

  it('keeps the sign on negatives', () => {
    expect(formatIndianNumber(-1234.5)).toBe('-1,234.50')
    expect(formatIndianNumber('-482915.40')).toBe('-4.83L')
  })

  // The regression this function was consolidated to fix: the three copies
  // that previously lived in the dashboard components each guarded with
  // `Number.isNaN(value)`, which is FALSE for undefined -- it matches only
  // the NaN value itself. An absent field therefore fell through to
  // Math.abs(undefined) -> NaN -> toLocaleString() and returned the literal
  // string "NaN", so the dashboard rendered "₹NaN" whenever a broker's funds
  // payload omitted a field.
  it('returns 0.00 for absent or unparseable values rather than "NaN"', () => {
    expect(formatIndianNumber(undefined)).toBe('0.00')
    expect(formatIndianNumber(null)).toBe('0.00')
    expect(formatIndianNumber('')).toBe('0.00')
    expect(formatIndianNumber('not-a-number')).toBe('0.00')
    expect(formatIndianNumber(Number.NaN)).toBe('0.00')
    expect(formatIndianNumber(Number.POSITIVE_INFINITY)).toBe('0.00')
  })
})
