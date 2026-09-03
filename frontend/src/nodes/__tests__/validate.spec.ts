import { describe, expect, it } from 'vitest'

import type { ParamSpec } from '@/api/types'

import { coerceDefault, validateParam } from '../validate'

function spec(overrides: Partial<ParamSpec> & { json_schema: Record<string, unknown> }): ParamSpec {
  return {
    name: 'p',
    label: 'P',
    description: '',
    required: false,
    advanced: false,
    linkable: true,
    link_type: 'astro.Any',
    widget: null,
    unit: null,
    step: null,
    ...overrides,
  }
}

const keys = (messages: { key: string }[]) => messages.map((m) => m.key)

describe('validateParam', () => {
  it('flags required when empty', () => {
    const s = spec({ required: true, json_schema: { type: 'number' } })
    expect(keys(validateParam(s, undefined))).toEqual(['autoform.errors.required'])
    expect(keys(validateParam(s, null))).toEqual(['autoform.errors.required'])
    expect(keys(validateParam(s, ''))).toEqual(['autoform.errors.required'])
    expect(validateParam(s, 0)).toEqual([])
  })

  it('accepts empty optional values and null for nullable schemas', () => {
    expect(validateParam(spec({ json_schema: { type: 'number' } }), null)).toEqual([])
    expect(validateParam(spec({ json_schema: { type: ['number', 'null'] } }), null)).toEqual([])
    expect(validateParam(spec({ json_schema: { type: 'string' } }), undefined)).toEqual([])
  })

  it('still applies minLength to an empty optional string', () => {
    expect(
      keys(validateParam(spec({ json_schema: { type: 'string', minLength: 1 } }), '')),
    ).toEqual(['autoform.errors.min_length'])
  })

  it('reports type mismatches with the expected type', () => {
    expect(validateParam(spec({ json_schema: { type: 'number' } }), 'x')).toEqual([
      { key: 'autoform.errors.type', params: { expected: 'number' } },
    ])
    expect(validateParam(spec({ json_schema: { type: 'string' } }), 1)).toEqual([
      { key: 'autoform.errors.type', params: { expected: 'string' } },
    ])
    expect(keys(validateParam(spec({ json_schema: { type: 'boolean' } }), 'true'))).toEqual([
      'autoform.errors.type',
    ])
    expect(keys(validateParam(spec({ json_schema: { type: 'array' } }), {}))).toEqual([
      'autoform.errors.type',
    ])
    expect(keys(validateParam(spec({ json_schema: { type: 'object' } }), []))).toEqual([
      'autoform.errors.type',
    ])
    expect(keys(validateParam(spec({ json_schema: { type: 'integer' } }), NaN))).toEqual([
      'autoform.errors.type',
    ])
    expect(keys(validateParam(spec({ json_schema: { type: 'null' } }), 1))).toEqual([
      'autoform.errors.type',
    ])
    // Unknown type accepts anything.
    expect(validateParam(spec({ json_schema: {} }), { a: 1 })).toEqual([])
  })

  it('checks integers', () => {
    const s = spec({ json_schema: { type: 'integer' } })
    expect(keys(validateParam(s, 1.5))).toEqual(['autoform.errors.integer'])
    expect(validateParam(s, 2)).toEqual([])
  })

  it('checks numeric bounds', () => {
    const s = spec({ json_schema: { type: 'number', minimum: -0.1, maximum: 20 } })
    expect(validateParam(s, -1)).toEqual([{ key: 'autoform.errors.min', params: { limit: -0.1 } }])
    expect(validateParam(s, 21)).toEqual([{ key: 'autoform.errors.max', params: { limit: 20 } }])
    expect(validateParam(s, 20)).toEqual([])
    const ex = spec({ json_schema: { type: 'number', exclusiveMinimum: 0, exclusiveMaximum: 1 } })
    expect(validateParam(ex, 0)).toEqual([{ key: 'autoform.errors.min', params: { limit: 0 } }])
    expect(validateParam(ex, 1)).toEqual([{ key: 'autoform.errors.max', params: { limit: 1 } }])
    expect(validateParam(ex, 0.5)).toEqual([])
  })

  it('checks string length and pattern', () => {
    const s = spec({
      json_schema: { type: 'string', minLength: 2, maxLength: 4, pattern: '^[a-z]+$' },
    })
    expect(validateParam(s, 'a')).toEqual([
      { key: 'autoform.errors.min_length', params: { limit: 2 } },
    ])
    expect(validateParam(s, 'abcde')).toEqual([
      { key: 'autoform.errors.max_length', params: { limit: 4 } },
    ])
    expect(validateParam(s, 'AB')).toEqual([{ key: 'autoform.errors.pattern' }])
    expect(validateParam(s, 'abc')).toEqual([])
    // A broken pattern never blames the user.
    expect(validateParam(spec({ json_schema: { type: 'string', pattern: '(' } }), 'x')).toEqual([])
  })

  it('checks enum membership including structured values', () => {
    const s = spec({ json_schema: { enum: ['a', 'b', [1, 2]] } })
    expect(validateParam(s, 'c')).toEqual([{ key: 'autoform.errors.enum' }])
    expect(validateParam(s, 'a')).toEqual([])
    expect(validateParam(s, [1, 2])).toEqual([])
  })

  it('checks array item counts and range ordering', () => {
    const list = spec({
      json_schema: { type: 'array', items: { type: 'number' }, minItems: 1, maxItems: 2 },
    })
    expect(validateParam(list, [])).toEqual([
      { key: 'autoform.errors.min_items', params: { limit: 1 } },
    ])
    expect(validateParam(list, [1, 2, 3])).toEqual([
      { key: 'autoform.errors.max_items', params: { limit: 2 } },
    ])
    const range = spec({
      json_schema: { type: 'array', prefixItems: [{ type: 'number' }, { type: 'number' }] },
    })
    expect(validateParam(range, [5, 1])).toEqual([{ key: 'autoform.errors.range_order' }])
    expect(validateParam(range, [1, 5])).toEqual([])
    expect(validateParam(range, ['a', 5])).toEqual([])
  })

  it('unwraps nullable schemas before applying rules', () => {
    const s = spec({ json_schema: { anyOf: [{ type: 'integer', minimum: 0 }, { type: 'null' }] } })
    expect(keys(validateParam(s, -1))).toEqual(['autoform.errors.min'])
    expect(keys(validateParam(s, 0.5))).toEqual(['autoform.errors.integer'])
    expect(validateParam(s, null)).toEqual([])
  })
})

describe('coerceDefault', () => {
  it('prefers spec.default, then schema default', () => {
    expect(coerceDefault(spec({ default: 3, json_schema: { type: 'number', default: 1 } }))).toBe(3)
    expect(coerceDefault(spec({ json_schema: { type: 'number', default: 1 } }))).toBe(1)
    expect(
      coerceDefault(spec({ default: null, json_schema: { type: 'number', default: 1 } })),
    ).toBe(1)
    expect(coerceDefault(spec({ default: 'x', json_schema: { type: 'string' } }))).toBe('x')
  })

  it('returns null for nullable schemas without a default', () => {
    expect(coerceDefault(spec({ json_schema: { type: ['number', 'null'] } }))).toBeNull()
    expect(
      coerceDefault(spec({ json_schema: { anyOf: [{ type: 'string' }, { type: 'null' }] } })),
    ).toBeNull()
  })

  it('produces zero values per type', () => {
    expect(coerceDefault(spec({ json_schema: { type: 'number' } }))).toBe(0)
    expect(coerceDefault(spec({ json_schema: { type: 'integer' } }))).toBe(0)
    expect(coerceDefault(spec({ json_schema: { type: 'string' } }))).toBe('')
    expect(coerceDefault(spec({ json_schema: { type: 'boolean' } }))).toBe(false)
    expect(coerceDefault(spec({ json_schema: { type: 'array' } }))).toEqual([])
    expect(coerceDefault(spec({ json_schema: { type: 'object' } }))).toEqual({})
    expect(coerceDefault(spec({ json_schema: {} }))).toBeNull()
  })

  it('clamps numeric zero into the schema bounds', () => {
    expect(coerceDefault(spec({ json_schema: { type: 'number', minimum: 5 } }))).toBe(5)
    expect(coerceDefault(spec({ json_schema: { type: 'number', maximum: -2 } }))).toBe(-2)
  })

  it('picks the first enum value', () => {
    expect(coerceDefault(spec({ json_schema: { type: 'string', enum: ['lin', 'log'] } }))).toBe(
      'lin',
    )
  })

  it('builds a pair for range schemas from item bounds', () => {
    expect(
      coerceDefault(
        spec({
          json_schema: {
            type: 'array',
            items: { type: 'number', minimum: 1, maximum: 9 },
            minItems: 2,
            maxItems: 2,
          },
        }),
      ),
    ).toEqual([1, 9])
    expect(
      coerceDefault(
        spec({
          json_schema: { type: 'array', prefixItems: [{ type: 'number' }, { type: 'number' }] },
        }),
      ),
    ).toEqual([0, 0])
  })
})
