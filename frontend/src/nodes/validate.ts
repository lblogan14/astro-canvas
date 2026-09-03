/**
 * Client-side validation of parameter values against their JSON Schema, plus default coercion.
 * Messages are i18n keys under `autoform.errors.*` with interpolation params.
 */
import type { ParamSpec } from '@/api/types'
import {
  isRangeSchema,
  nullable,
  schemaNumberBounds,
  schemaType,
  unwrapNullable,
  type JsonSchema,
  type SchemaType,
} from './widgetFor'

export interface ValidationMessage {
  key: string
  params?: Record<string, unknown>
}

function isEmpty(value: unknown): boolean {
  return value === undefined || value === null || value === ''
}

function typeMatches(type: SchemaType, value: unknown): boolean {
  switch (type) {
    case 'string':
      return typeof value === 'string'
    case 'number':
      return typeof value === 'number' && Number.isFinite(value)
    case 'integer':
      return typeof value === 'number' && Number.isFinite(value)
    case 'boolean':
      return typeof value === 'boolean'
    case 'array':
      return Array.isArray(value)
    case 'object':
      return typeof value === 'object' && value !== null && !Array.isArray(value)
    case 'null':
      return value === null
    default:
      return true
  }
}

function numberRules(schema: JsonSchema, value: number, out: ValidationMessage[]): void {
  const min = schema['minimum']
  const max = schema['maximum']
  const exclusiveMin = schema['exclusiveMinimum']
  const exclusiveMax = schema['exclusiveMaximum']
  if (typeof min === 'number' && value < min)
    out.push({ key: 'autoform.errors.min', params: { limit: min } })
  if (typeof exclusiveMin === 'number' && value <= exclusiveMin)
    out.push({ key: 'autoform.errors.min', params: { limit: exclusiveMin } })
  if (typeof max === 'number' && value > max)
    out.push({ key: 'autoform.errors.max', params: { limit: max } })
  if (typeof exclusiveMax === 'number' && value >= exclusiveMax)
    out.push({ key: 'autoform.errors.max', params: { limit: exclusiveMax } })
}

function stringRules(schema: JsonSchema, value: string, out: ValidationMessage[]): void {
  const minLength = schema['minLength']
  const maxLength = schema['maxLength']
  const pattern = schema['pattern']
  if (typeof minLength === 'number' && value.length < minLength)
    out.push({ key: 'autoform.errors.min_length', params: { limit: minLength } })
  if (typeof maxLength === 'number' && value.length > maxLength)
    out.push({ key: 'autoform.errors.max_length', params: { limit: maxLength } })
  if (typeof pattern === 'string') {
    let ok = true
    try {
      ok = new RegExp(pattern, 'u').test(value)
    } catch {
      ok = true // an unparseable pattern is the schema's fault, not the user's
    }
    if (!ok) out.push({ key: 'autoform.errors.pattern' })
  }
}

function arrayRules(schema: JsonSchema, value: unknown[], out: ValidationMessage[]): void {
  const minItems = schema['minItems']
  const maxItems = schema['maxItems']
  if (typeof minItems === 'number' && value.length < minItems)
    out.push({ key: 'autoform.errors.min_items', params: { limit: minItems } })
  if (typeof maxItems === 'number' && value.length > maxItems)
    out.push({ key: 'autoform.errors.max_items', params: { limit: maxItems } })
  if (isRangeSchema(schema) && value.length === 2) {
    const [lo, hi] = value
    if (typeof lo === 'number' && typeof hi === 'number' && lo > hi)
      out.push({ key: 'autoform.errors.range_order' })
  }
}

function enumRule(schema: JsonSchema, value: unknown, out: ValidationMessage[]): void {
  const allowed = schema['enum']
  if (!Array.isArray(allowed)) return
  const found = allowed.some(
    (entry) => entry === value || JSON.stringify(entry) === JSON.stringify(value),
  )
  if (!found) out.push({ key: 'autoform.errors.enum' })
}

/** Validates `value` against `spec`; an empty list means the value is acceptable. */
export function validateParam(spec: ParamSpec, value: unknown): ValidationMessage[] {
  const out: ValidationMessage[] = []
  const schema = unwrapNullable(spec.json_schema)
  const type = schemaType(schema)

  if (isEmpty(value)) {
    if (spec.required) out.push({ key: 'autoform.errors.required' })
    // Empty string is a legitimate string value; null/undefined pass when nullable or optional.
    if (value === '' && type === 'string' && !spec.required) stringRules(schema, value, out)
    return out
  }

  if (!typeMatches(type, value)) {
    out.push({ key: 'autoform.errors.type', params: { expected: type ?? 'value' } })
    return out
  }

  if (type === 'integer' && typeof value === 'number' && !Number.isInteger(value))
    out.push({ key: 'autoform.errors.integer' })

  if (typeof value === 'number') numberRules(schema, value, out)
  else if (typeof value === 'string') stringRules(schema, value, out)
  else if (Array.isArray(value)) arrayRules(schema, value, out)

  enumRule(schema, value, out)
  return out
}

/** Zero value for a schema type: 0, '', false, [], {} — or `undefined` when the type is unknown. */
function zeroValue(type: SchemaType): unknown {
  switch (type) {
    case 'number':
    case 'integer':
      return 0
    case 'string':
      return ''
    case 'boolean':
      return false
    case 'array':
      return []
    case 'object':
      return {}
    default:
      return undefined
  }
}

/**
 * Initial value for a parameter: `spec.default`, then `json_schema.default`, then `null` for a
 * nullable schema, then a zero value per type. The bounds are respected for numbers (a zero
 * outside `[min, max]` is clamped).
 */
export function coerceDefault(spec: ParamSpec): unknown {
  if (spec.default !== undefined && spec.default !== null) return spec.default
  const explicit = spec.json_schema['default']
  if (explicit !== undefined && explicit !== null) return explicit
  if (nullable(spec.json_schema)) return null

  const schema = unwrapNullable(spec.json_schema)
  const type = schemaType(schema)
  const enumValues = schema['enum']
  if (Array.isArray(enumValues) && enumValues.length > 0) return enumValues[0]

  if (type === 'number' || type === 'integer') {
    const { min, max } = schemaNumberBounds(schema, spec)
    let value = 0
    if (min !== undefined && value < min) value = min
    if (max !== undefined && value > max) value = max
    return value
  }
  if (type === 'array' && isRangeSchema(schema)) {
    const items = schema['items']
    const itemSchema: JsonSchema =
      typeof items === 'object' && items !== null && !Array.isArray(items)
        ? (items as JsonSchema)
        : {}
    const { min, max } = schemaNumberBounds(itemSchema, null)
    return [min ?? 0, max ?? min ?? 0]
  }
  return zeroValue(type) ?? null
}
