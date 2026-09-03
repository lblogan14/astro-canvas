/** Structural equality for JSON-like values (objects, arrays, primitives). */
export function deepEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true
  if (typeof a !== typeof b || a === null || b === null) return false
  if (typeof a !== 'object') return Number.isNaN(a as number) && Number.isNaN(b as number)
  if (Array.isArray(a)) {
    if (!Array.isArray(b) || a.length !== b.length) return false
    return a.every((item, index) => deepEqual(item, b[index]))
  }
  if (Array.isArray(b)) return false
  const left = a as Record<string, unknown>
  const right = b as Record<string, unknown>
  const keys = Object.keys(left)
  if (keys.length !== Object.keys(right).length) return false
  return keys.every((key) => key in right && deepEqual(left[key], right[key]))
}

/**
 * Deep copy of a JSON-like value. Uses a JSON round-trip on purpose: documents are plain JSON and
 * `structuredClone` refuses Vue reactive proxies.
 */
export function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}
