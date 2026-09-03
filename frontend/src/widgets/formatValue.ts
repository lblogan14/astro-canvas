/** Compact display formatting shared by the key/value tile and chips. */
export function formatKvValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return String(value)
    if (Number.isInteger(value)) return String(value)
    const abs = Math.abs(value)
    return abs !== 0 && (abs < 1e-3 || abs >= 1e6)
      ? value.toExponential(3)
      : value.toPrecision(5).replace(/\.?0+$/, '')
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
