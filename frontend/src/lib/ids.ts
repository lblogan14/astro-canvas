const ALPHABET = 'abcdefghijklmnopqrstuvwxyz0123456789'

function randomChunk(length: number): string {
  const values = new Uint8Array(length)
  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
    crypto.getRandomValues(values)
  } else {
    for (let i = 0; i < length; i += 1) values[i] = Math.floor(Math.random() * 256)
  }
  let out = ''
  for (const value of values) out += ALPHABET[value % ALPHABET.length]
  return out
}

/**
 * Short random identifier. Node ids must not contain `/` (sub-graph inlining uses `inst/inner`),
 * so only lowercase letters and digits are used.
 */
export function newId(prefix = 'n'): string {
  return `${prefix}_${randomChunk(8)}`
}

/** A unique id for `taken`, derived from `base` (`base`, `base_2`, `base_3`, …). */
export function uniqueId(base: string, taken: (id: string) => boolean): string {
  if (!taken(base)) return base
  for (let n = 2; ; n += 1) {
    const candidate = `${base}_${n}`
    if (!taken(candidate)) return candidate
  }
}
