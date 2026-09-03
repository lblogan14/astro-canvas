import { describe, expect, it } from 'vitest'

import type { ParamSpec } from '@/api/types'

import {
  enumOptions,
  isRangeSchema,
  listItemType,
  nullable,
  schemaNumberBounds,
  schemaType,
  unwrapNullable,
  widgetFor,
} from '../widgetFor'

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

describe('widgetFor', () => {
  it('honours the explicit widget on the spec', () => {
    expect(widgetFor(spec({ widget: 'code', json_schema: { type: 'string' } }))).toBe('code')
    expect(widgetFor(spec({ widget: 'markdown', json_schema: { type: 'string' } }))).toBe(
      'markdown',
    )
    expect(widgetFor(spec({ widget: 'slider', json_schema: { type: 'number' } }))).toBe('slider')
    expect(widgetFor(spec({ widget: 'redshift', json_schema: { type: 'number' } }))).toBe(
      'redshift',
    )
    expect(widgetFor(spec({ widget: 'wavelength', json_schema: { type: 'number' } }))).toBe(
      'wavelength',
    )
  })

  it('honours x-widget from the schema when spec.widget is absent', () => {
    expect(widgetFor(spec({ json_schema: { type: 'string', 'x-widget': 'path' } }))).toBe('path')
    expect(widgetFor(spec({ json_schema: { type: 'string', 'x-widget': 'Code' } }))).toBe('code')
  })

  it('maps aliases to known kinds', () => {
    expect(widgetFor(spec({ widget: 'file', json_schema: { type: 'string' } }))).toBe('path')
    expect(widgetFor(spec({ widget: 'int', json_schema: { type: 'integer' } }))).toBe('number')
    expect(widgetFor(spec({ widget: 'integer', json_schema: {} }))).toBe('number')
    expect(widgetFor(spec({ widget: 'float', json_schema: {} }))).toBe('number')
    expect(widgetFor(spec({ widget: 'textarea', json_schema: { type: 'string' } }))).toBe('code')
    expect(widgetFor(spec({ widget: 'enum', json_schema: { enum: [1] } }))).toBe('select')
    expect(widgetFor(spec({ widget: 'dropdown', json_schema: { enum: [1] } }))).toBe('select')
    expect(widgetFor(spec({ widget: 'bool', json_schema: {} }))).toBe('checkbox')
    expect(widgetFor(spec({ widget: 'boolean', json_schema: {} }))).toBe('checkbox')
  })

  it('falls back to the schema when the widget hint is unknown', () => {
    expect(widgetFor(spec({ widget: 'mystery', json_schema: { type: 'boolean' } }))).toBe(
      'checkbox',
    )
  })

  it('infers select from enum', () => {
    expect(widgetFor(spec({ json_schema: { type: 'string', enum: ['a', 'b'] } }))).toBe('select')
  })

  it('infers checkbox, number, text and color', () => {
    expect(widgetFor(spec({ json_schema: { type: 'boolean' } }))).toBe('checkbox')
    expect(widgetFor(spec({ json_schema: { type: 'number' } }))).toBe('number')
    expect(widgetFor(spec({ json_schema: { type: 'integer' } }))).toBe('number')
    expect(widgetFor(spec({ json_schema: { type: 'string' } }))).toBe('text')
    expect(widgetFor(spec({ json_schema: { type: 'string', format: 'color' } }))).toBe('color')
  })

  it('infers range from a numeric pair and list from other arrays', () => {
    expect(
      widgetFor(
        spec({
          json_schema: { type: 'array', prefixItems: [{ type: 'number' }, { type: 'number' }] },
        }),
      ),
    ).toBe('range')
    expect(
      widgetFor(
        spec({
          json_schema: { type: 'array', items: { type: 'integer' }, minItems: 2, maxItems: 2 },
        }),
      ),
    ).toBe('range')
    expect(
      widgetFor(
        spec({
          json_schema: { type: 'array', prefixItems: [{ type: 'string' }, { type: 'number' }] },
        }),
      ),
    ).toBe('list')
    expect(widgetFor(spec({ json_schema: { type: 'array', items: { type: 'string' } } }))).toBe(
      'list',
    )
    expect(
      widgetFor(spec({ json_schema: { type: 'array', items: { type: 'number' }, minItems: 2 } })),
    ).toBe('list')
  })

  it('infers json for objects and unknown shapes', () => {
    expect(widgetFor(spec({ json_schema: { type: 'object' } }))).toBe('json')
    expect(widgetFor(spec({ json_schema: {} }))).toBe('json')
    expect(widgetFor(spec({ json_schema: { type: 'null' } }))).toBe('json')
  })

  it('unwraps nullable type lists and anyOf branches', () => {
    expect(widgetFor(spec({ json_schema: { type: ['number', 'null'] } }))).toBe('number')
    expect(
      widgetFor(spec({ json_schema: { anyOf: [{ type: 'string' }, { type: 'null' }] } })),
    ).toBe('text')
    expect(
      widgetFor(spec({ json_schema: { oneOf: [{ type: 'boolean' }, { type: 'null' }] } })),
    ).toBe('checkbox')
    expect(
      widgetFor(
        spec({ json_schema: { anyOf: [{ type: 'string', enum: ['x', 'y'] }, { type: 'null' }] } }),
      ),
    ).toBe('select')
  })
})

describe('nullable / unwrapNullable / schemaType', () => {
  it('detects nullability', () => {
    expect(nullable({ type: 'number' })).toBe(false)
    expect(nullable({ type: ['number', 'null'] })).toBe(true)
    expect(nullable({ type: 'null' })).toBe(true)
    expect(nullable({ anyOf: [{ type: 'string' }, { type: 'null' }] })).toBe(true)
    expect(nullable({ anyOf: [{ type: 'string' }, { type: 'number' }] })).toBe(false)
    expect(nullable({})).toBe(false)
  })

  it('unwraps and merges parent keywords', () => {
    expect(unwrapNullable({ type: ['integer', 'null'], minimum: 1 })).toEqual({
      type: 'integer',
      minimum: 1,
    })
    expect(
      unwrapNullable({ anyOf: [{ type: 'number', minimum: 2 }, { type: 'null' }], default: null }),
    ).toEqual({ type: 'number', minimum: 2, default: null })
    // Ambiguous unions are left alone.
    const union = { anyOf: [{ type: 'string' }, { type: 'number' }] }
    expect(unwrapNullable(union)).toBe(union)
    expect(unwrapNullable({ anyOf: 'nope' })).toEqual({ anyOf: 'nope' })
  })

  it('reports the schema type', () => {
    expect(schemaType({ type: 'string' })).toBe('string')
    expect(schemaType({ type: ['array', 'null'] })).toBe('array')
    expect(schemaType({ type: 'weird' })).toBeUndefined()
    expect(schemaType({})).toBeUndefined()
  })
})

describe('schemaNumberBounds', () => {
  it('reads minimum/maximum and step sources in priority order', () => {
    expect(
      schemaNumberBounds({ type: 'number', minimum: -0.1, maximum: 20, 'x-step': 1e-4 }),
    ).toEqual({ min: -0.1, max: 20, step: 1e-4 })
    expect(schemaNumberBounds({ type: 'number', 'x-step': 0.5 }, { step: 0.25 })).toEqual({
      step: 0.25,
    })
    expect(schemaNumberBounds({ type: 'number', multipleOf: 2 })).toEqual({ step: 2 })
    expect(schemaNumberBounds({ type: 'integer' })).toEqual({ step: 1 })
    expect(schemaNumberBounds({ type: 'number' })).toEqual({})
    expect(schemaNumberBounds({ type: 'number', 'x-step': -1 })).toEqual({})
  })

  it('nudges exclusive bounds inward', () => {
    expect(
      schemaNumberBounds({ type: 'integer', exclusiveMinimum: 0, exclusiveMaximum: 10 }),
    ).toEqual({ min: 1, max: 9, step: 1 })
    const bounds = schemaNumberBounds({ type: 'number', exclusiveMinimum: 0 })
    expect(bounds.min).toBeCloseTo(1e-9, 12)
    expect(bounds.max).toBeUndefined()
    const both = schemaNumberBounds({
      type: 'number',
      minimum: 5,
      exclusiveMinimum: 0,
      maximum: 5,
      exclusiveMaximum: 100,
    })
    expect(both).toEqual({ min: 5, max: 5 })
  })

  it('looks through nullable wrappers', () => {
    expect(schemaNumberBounds({ type: ['number', 'null'], minimum: 1 })).toEqual({ min: 1 })
  })
})

describe('isRangeSchema / listItemType / enumOptions', () => {
  it('recognises range schemas', () => {
    expect(
      isRangeSchema({ type: 'array', prefixItems: [{ type: 'number' }, { type: 'integer' }] }),
    ).toBe(true)
    expect(isRangeSchema({ type: 'array', prefixItems: [{ type: 'number' }] })).toBe(false)
    expect(
      isRangeSchema({
        type: 'array',
        prefixItems: [{ type: 'number' }, { type: 'number' }],
        items: { type: 'number' },
      }),
    ).toBe(false)
    expect(isRangeSchema({ type: 'string' })).toBe(false)
    expect(
      isRangeSchema({ type: 'array', items: { type: 'string' }, minItems: 2, maxItems: 2 }),
    ).toBe(false)
  })

  it('derives list item type', () => {
    expect(listItemType({ type: 'array', items: { type: 'number' } })).toBe('number')
    expect(listItemType({ type: 'array', items: { type: 'string' } })).toBe('string')
    expect(listItemType({ type: 'array' })).toBe('string')
  })

  it('builds select options with optional labels', () => {
    expect(enumOptions({ enum: ['a', 2, null] })).toEqual([
      { value: 'a', label: 'a' },
      { value: 2, label: '2' },
      { value: null, label: 'null' },
    ])
    expect(enumOptions({ enum: ['a', 'b'], 'x-enum-labels': ['Alpha'] })).toEqual([
      { value: 'a', label: 'Alpha' },
      { value: 'b', label: 'b' },
    ])
    expect(enumOptions({ type: 'string' })).toEqual([])
  })
})
