/**
 * Compact display of one number: exponential when it is very small or very large, otherwise five
 * significant digits with the trailing zeros of the *fraction* removed. Stripping zeros without
 * checking for a decimal point would turn 10000 into 1.
 */
export function formatCompact(value: number, digits = 5): string {
  if (!Number.isFinite(value)) return 'NaN'
  const abs = Math.abs(value)
  if (abs !== 0 && (abs < 1e-3 || abs >= 1e6)) return value.toExponential(3)
  const text = value.toPrecision(digits)
  return text.includes('.') ? text.replace(/\.?0+$/, '') : text
}

/** Compact display formatting shared by the key/value tile and chips. */
export function formatKvValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return String(value)
    if (Number.isInteger(value)) return String(value)
    return formatCompact(value)
  }
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (typeof value === 'string') return value
  if (Array.isArray(value)) {
    return value.length <= 4
      ? `[${value.map((v) => formatKvValue(v)).join(', ')}]`
      : `[${value.length} items]`
  }
  if (typeof value === 'object') return `{${Object.keys(value as object).length} keys}`
  return String(value)
}
