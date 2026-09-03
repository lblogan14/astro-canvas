import { describe, expect, it } from 'vitest'

import { formatCompact, formatKvValue } from '../formatValue'

describe('formatCompact', () => {
  it('keeps round numbers whole', () => {
    // Stripping trailing zeros without checking for a decimal point turns these into 1 and 498.
    expect(formatCompact(10000)).toBe('10000')
    expect(formatCompact(4980, 4)).toBe('4980')
    expect(formatCompact(100)).toBe('100')
  })

  it('trims the fraction and switches to exponential at the extremes', () => {
    expect(formatCompact(1.5)).toBe('1.5')
    expect(formatCompact(1.234567)).toBe('1.2346')
    expect(formatCompact(-120.5)).toBe('-120.5')
    expect(formatCompact(0)).toBe('0')
    expect(formatCompact(1.2e-6)).toBe('1.200e-6')
    expect(formatCompact(3.4e8)).toBe('3.400e+8')
    expect(formatCompact(Number.NaN)).toBe('NaN')
    expect(formatCompact(Number.POSITIVE_INFINITY)).toBe('NaN')
  })
})

describe('formatKvValue', () => {
  it('renders every JSON shape a key/value tile can hold', () => {
    expect(formatKvValue(null)).toBe('—')
    expect(formatKvValue(undefined)).toBe('—')
    expect(formatKvValue(7)).toBe('7')
    expect(formatKvValue(10000)).toBe('10000')
    expect(formatKvValue(1.23456789)).toBe('1.2346')
    expect(formatKvValue(Number.NaN)).toBe('NaN')
    expect(formatKvValue(true)).toBe('true')
    expect(formatKvValue('text')).toBe('text')
    expect(formatKvValue([1, 2])).toBe('[1, 2]')
    expect(formatKvValue([1, 2, 3, 4, 5])).toBe('[5 items]')
    expect(formatKvValue({ a: 1, b: 2 })).toBe('{2 keys}')
  })
})
