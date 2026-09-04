/**
 * Resolves the widget kind for a parameter from its `ParamSpec` and JSON Schema (draft 2020-12).
 * Explicit `widget` / `x-widget` hints win; otherwise the schema shape decides.
 */
import type { ParamSpec } from '@/api/types'

export type WidgetKind =
  | 'number'
  | 'slider'
  | 'text'
  | 'code'
  | 'markdown'
  | 'select'
  | 'checkbox'
  | 'range'
  | 'list'
  | 'path'
  | 'ports'
  | 'color'
  | 'redshift'
  | 'wavelength'
  | 'json'

export type JsonSchema = Record<string, unknown>

export type SchemaType =
  'string' | 'number' | 'integer' | 'boolean' | 'array' | 'object' | 'null' | undefined

const KNOWN_KINDS: ReadonlySet<string> = new Set<WidgetKind>([
  'number',
  'slider',
  'text',
  'code',
  'markdown',
  'select',
  'checkbox',
  'range',
  'list',
  'path',
  'ports',
  'color',
  'redshift',
  'wavelength',
  'json',
])

const WIDGET_ALIASES: Readonly<Record<string, WidgetKind>> = {
  file: 'path',
  int: 'number',
  integer: 'number',
  float: 'number',
  textarea: 'code',
  enum: 'select',
  dropdown: 'select',
  bool: 'checkbox',
  boolean: 'checkbox',
}

function isRecord(value: unknown): value is JsonSchema {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isSchemaType(value: unknown): value is Exclude<SchemaType, undefined> {
  return (
    value === 'string' ||
    value === 'number' ||
    value === 'integer' ||
    value === 'boolean' ||
    value === 'array' ||
    value === 'object' ||
    value === 'null'
  )
}

/** The `anyOf`/`oneOf` branches of a schema, if any. */
function branches(schema: JsonSchema): JsonSchema[] | null {
  const raw = schema['anyOf'] ?? schema['oneOf']
  if (!Array.isArray(raw)) return null
  return raw.filter(isRecord)
}

/** True when the schema accepts `null` (type list, `anyOf` null branch, or `type: 'null'`). */
export function nullable(schema: JsonSchema): boolean {
  const type = schema['type']
  if (type === 'null') return true
  if (Array.isArray(type) && type.includes('null')) return true
  const alts = branches(schema)
  if (alts) return alts.some((alt) => nullable(alt))
  return false
}

/**
 * Strips nullability: `["number","null"]` becomes `number`, `anyOf: [{type:'number'},{type:'null'}]`
 * becomes the non-null branch (merged with the parent's remaining keywords). Multi-type schemas
 * with more than one non-null type are left as-is with `type` set to the first of them.
 */
export function unwrapNullable(schema: JsonSchema): JsonSchema {
  const type = schema['type']
  if (Array.isArray(type)) {
    const nonNull = type.filter((entry) => entry !== 'null')
    return { ...schema, type: nonNull[0] }
  }
  const alts = branches(schema)
  if (alts) {
    const nonNull = alts.filter((alt) => alt['type'] !== 'null')
    if (nonNull.length === 1 && nonNull[0]) {
      const rest: JsonSchema = { ...schema }
      delete rest['anyOf']
      delete rest['oneOf']
      return { ...rest, ...unwrapNullable(nonNull[0]) }
    }
  }
  return schema
}

/** The primary (non-null) JSON Schema type of a schema, or `undefined` when unspecified. */
export function schemaType(schema: JsonSchema): SchemaType {
  const type = unwrapNullable(schema)['type']
  return isSchemaType(type) ? type : undefined
}

function isNumericSchema(value: unknown): boolean {
  if (!isRecord(value)) return false
  const type = schemaType(value)
  return type === 'number' || type === 'integer'
}

/** True for a fixed pair of numbers: `prefixItems` of two numeric schemas or `minItems === maxItems === 2`. */
export function isRangeSchema(schema: JsonSchema): boolean {
  const inner = unwrapNullable(schema)
  if (schemaType(inner) !== 'array') return false
  const prefix = inner['prefixItems']
  if (Array.isArray(prefix)) {
    return prefix.length === 2 && prefix.every(isNumericSchema) && !inner['items']
  }
  return inner['minItems'] === 2 && inner['maxItems'] === 2 && isNumericSchema(inner['items'])
}

/** Item type of a list schema (`'number'` for number/integer items, else `'string'`). */
export function listItemType(schema: JsonSchema): 'number' | 'string' {
  const inner = unwrapNullable(schema)
  return isNumericSchema(inner['items']) ? 'number' : 'string'
}

function explicitWidget(spec: ParamSpec): WidgetKind | null {
  const hint = spec.widget ?? spec.json_schema['x-widget']
  if (typeof hint !== 'string') return null
  const key = hint.toLowerCase()
  if (KNOWN_KINDS.has(key)) return key as WidgetKind
  return WIDGET_ALIASES[key] ?? null
}

/** Picks the widget kind for a parameter. */
export function widgetFor(spec: ParamSpec): WidgetKind {
  const explicit = explicitWidget(spec)
  if (explicit) return explicit

  const schema = unwrapNullable(spec.json_schema)
  if (Array.isArray(schema['enum'])) return 'select'

  switch (schemaType(schema)) {
    case 'boolean':
      return 'checkbox'
    case 'number':
    case 'integer':
      return 'number'
    case 'string':
      return schema['format'] === 'color' ? 'color' : 'text'
    case 'array':
      return isRangeSchema(schema) ? 'range' : 'list'
    case 'object':
      return 'json'
    default:
      return 'json'
  }
}

export interface NumberBounds {
  min?: number
  max?: number
  step?: number
}

const EXCLUSIVE_NUDGE = 1e-9

function asFinite(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

/**
 * Numeric bounds for a number-like schema. Exclusive bounds are nudged inward by the step (or
 * 1e-9). Step priority: `spec.step`, `x-step`, `multipleOf`, then `1` for integers.
 */
export function schemaNumberBounds(
  schema: JsonSchema,
  spec?: Pick<ParamSpec, 'step'> | null,
): NumberBounds {
  const inner = unwrapNullable(schema)
  const bounds: NumberBounds = {}

  const step =
    asFinite(spec?.step) ??
    asFinite(inner['x-step']) ??
    asFinite(inner['multipleOf']) ??
    (schemaType(inner) === 'integer' ? 1 : undefined)
  if (step !== undefined && step > 0) bounds.step = step

  const nudge = bounds.step ?? EXCLUSIVE_NUDGE
  const min = asFinite(inner['minimum'])
  const exclusiveMin = asFinite(inner['exclusiveMinimum'])
  if (min !== undefined) bounds.min = min
  if (exclusiveMin !== undefined) {
    const nudged = exclusiveMin + nudge
    bounds.min = bounds.min === undefined ? nudged : Math.max(bounds.min, nudged)
  }

  const max = asFinite(inner['maximum'])
  const exclusiveMax = asFinite(inner['exclusiveMaximum'])
  if (max !== undefined) bounds.max = max
  if (exclusiveMax !== undefined) {
    const nudged = exclusiveMax - nudge
    bounds.max = bounds.max === undefined ? nudged : Math.min(bounds.max, nudged)
  }

  return bounds
}

/** Options for a `select` widget from `enum` (labels fall back to the stringified value). */
export function enumOptions(schema: JsonSchema): { value: unknown; label: string }[] {
  const inner = unwrapNullable(schema)
  const values = inner['enum']
  if (!Array.isArray(values)) return []
  const names = inner['x-enum-labels'] ?? inner['enumNames']
  return values.map((value, index) => {
    const name = Array.isArray(names) ? names[index] : undefined
    return { value, label: typeof name === 'string' ? name : String(value) }
  })
}
