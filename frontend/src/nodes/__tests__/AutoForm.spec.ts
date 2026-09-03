import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import type { NodeIssue, ParamSpec } from '@/api/types'
import { i18n } from '@/i18n'

import AutoForm from '../AutoForm.vue'

function spec(
  overrides: Partial<ParamSpec> & { name: string; json_schema: Record<string, unknown> },
): ParamSpec {
  return {
    label: overrides.name,
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

// Real backend examples.
const value = spec({
  name: 'value',
  label: 'Value',
  json_schema: { default: 0.0, type: 'number', 'x-widget': 'number' },
  widget: 'number',
  default: 0.0,
  link_type: 'astro.Float',
  description: 'The number to output.',
})
const expression = spec({
  name: 'expression',
  label: 'Expression',
  json_schema: { default: 'x', type: 'string', 'x-widget': 'code' },
  widget: 'code',
  default: 'x',
})
const text = spec({
  name: 'text',
  label: 'Text',
  widget: 'markdown',
  json_schema: { type: 'string', 'x-widget': 'markdown' },
})
const z = spec({
  name: 'z',
  label: 'Redshift',
  widget: 'redshift',
  step: 0.0001,
  default: 0.0,
  json_schema: {
    default: 0.0,
    maximum: 20.0,
    minimum: -0.1,
    type: 'number',
    'x-step': 0.0001,
    'x-widget': 'redshift',
  },
})
const wrest = spec({
  name: 'wrest',
  label: 'Rest wavelength',
  widget: 'wavelength',
  unit: 'Angstrom',
  required: true,
  json_schema: { minimum: 0.0, type: 'number', 'x-unit': 'Angstrom', 'x-widget': 'wavelength' },
})

// Synthetic fixtures for the remaining kinds.
const gain = spec({
  name: 'gain',
  label: 'Gain',
  widget: 'slider',
  json_schema: { type: 'number', minimum: 0, maximum: 10, default: 2 },
  default: 2,
})
const scale = spec({
  name: 'scale',
  label: 'Scale',
  json_schema: { type: 'string', enum: ['lin', 'log'], default: 'lin' },
})
const flag = spec({ name: 'flag', label: 'Flag', json_schema: { type: 'boolean', default: false } })
const window_ = spec({
  name: 'window',
  label: 'Window',
  unit: 'px',
  json_schema: {
    type: 'array',
    prefixItems: [{ type: 'number' }, { type: 'number' }],
    default: [1, 5],
  },
})
const tags = spec({
  name: 'tags',
  label: 'Tags',
  json_schema: { type: 'array', items: { type: 'string' }, default: ['a'] },
})
const meta = spec({
  name: 'meta',
  label: 'Meta',
  json_schema: { type: 'object', default: { k: 1 } },
})
const tint = spec({
  name: 'tint',
  label: 'Tint',
  json_schema: { type: 'string', format: 'color', default: '#ff0000' },
})
const path = spec({ name: 'path', label: 'Path', widget: 'file', json_schema: { type: 'string' } })
const counter = spec({
  name: 'counter',
  label: 'Counter',
  json_schema: { type: 'integer', minimum: 0, maximum: 3 },
})
const secret = spec({
  name: 'secret',
  label: 'Secret',
  advanced: true,
  json_schema: { type: 'string', default: 's' },
})
const depth = spec({
  name: 'depth',
  label: 'Depth',
  advanced: true,
  json_schema: { type: 'integer', default: 1 },
})

const ALL = [
  value,
  expression,
  text,
  z,
  wrest,
  gain,
  scale,
  flag,
  window_,
  tags,
  meta,
  tint,
  path,
  counter,
  secret,
  depth,
]

function mountForm(
  props: Partial<InstanceType<typeof AutoForm>['$props']> & { params?: ParamSpec[] } = {},
) {
  return mount(AutoForm, {
    props: { params: ALL, values: {}, idPrefix: 'n1', ...props },
    global: { plugins: [i18n] },
  })
}

function row(wrapper: ReturnType<typeof mountForm>, name: string) {
  return wrapper.find(`[data-param="${name}"]`)
}

function last(wrapper: ReturnType<typeof mountForm>, event: 'update' | 'toggle-link') {
  const events = wrapper.emitted(event) ?? []
  return events[events.length - 1]
}

describe('AutoForm', () => {
  it('renders the right widget kind for each param', () => {
    const w = mountForm()
    const kinds: Record<string, string> = {
      value: 'number',
      expression: 'code',
      text: 'markdown',
      z: 'redshift',
      wrest: 'wavelength',
      gain: 'slider',
      scale: 'select',
      flag: 'checkbox',
      window: 'range',
      tags: 'list',
      meta: 'json',
      tint: 'color',
      path: 'path',
      counter: 'number',
    }
    for (const [name, kind] of Object.entries(kinds)) {
      const r = row(w, name)
      expect(r.exists()).toBe(true)
      expect(r.find(`[data-widget="${kind}"]`).exists()).toBe(true)
    }
    expect(w.classes()).toContain('nodrag')
    expect(w.classes()).toContain('nowheel')
  })

  it('labels every input and prefixes ids', () => {
    const w = mountForm()
    const input = row(w, 'value').find('input')
    expect(input.attributes('id')).toBe('n1-value')
    expect(row(w, 'value').find('label').attributes('for')).toBe('n1-value')
    expect(row(w, 'wrest').find('label').text()).toContain('*')
    // Angstrom renders as its symbol.
    expect(row(w, 'wrest').text()).toContain('Å')
    expect(row(w, 'z').text()).toContain('z')
  })

  it('uses coerced defaults when a value is missing and shows provided values', () => {
    const w = mountForm({ values: { value: 4.5 } })
    expect((row(w, 'value').find('input').element as HTMLInputElement).value).toBe('4.5')
    expect((row(w, 'expression').find('textarea').element as HTMLTextAreaElement).value).toBe('x')
    // Required with no default: the zero value clamped into [min, max].
    expect((row(w, 'wrest').find('input').element as HTMLInputElement).value).toBe('0')
    expect((row(w, 'meta').find('textarea').element as HTMLTextAreaElement).value).toBe(
      JSON.stringify({ k: 1 }, null, 2),
    )
  })

  it('emits numbers from number inputs and null when cleared', async () => {
    const w = mountForm()
    const input = row(w, 'value').find('input')
    await input.setValue('2.5')
    expect(w.emitted('update')).toEqual([['value', 2.5]])
    await input.setValue('')
    expect(last(w, 'update')).toEqual(['value', null])
    // Non-numeric text never produces a non-number (the browser sanitises it to '').
    await input.setValue('abc')
    for (const [, emitted] of w.emitted('update') ?? []) {
      expect(emitted === null || typeof emitted === 'number').toBe(true)
    }
  })

  it('clamps out-of-range numbers on blur', async () => {
    const w = mountForm()
    const input = row(w, 'counter').find('input')
    await input.setValue('7')
    await input.trigger('blur')
    expect(last(w, 'update')).toEqual(['counter', 3])
  })

  it('emits booleans from the checkbox and values from the select', async () => {
    const w = mountForm()
    await row(w, 'flag').find('input[type="checkbox"]').setValue(true)
    expect(last(w, 'update')).toEqual(['flag', true])
    await row(w, 'scale').find('select').setValue('1')
    expect(last(w, 'update')).toEqual(['scale', 'log'])
  })

  it('emits a pair from the range and a list from the list widget', async () => {
    const w = mountForm()
    const inputs = row(w, 'window').findAll('input')
    await inputs[1]!.setValue('9')
    expect(last(w, 'update')).toEqual(['window', [1, 9]])
    await inputs[0]!.setValue('12')
    expect(last(w, 'update')).toEqual(['window', [12, 5]])

    await row(w, 'tags').find('button[aria-label^="Add item"]').trigger('click')
    expect(last(w, 'update')).toEqual(['tags', ['a', '']])
    await row(w, 'tags').find('input').setValue('b')
    expect(last(w, 'update')).toEqual(['tags', ['b']])
    await row(w, 'tags').find('button[aria-label^="Remove item"]').trigger('click')
    expect(last(w, 'update')).toEqual(['tags', []])
  })

  it('emits from the slider, text, code, path and color widgets', async () => {
    const w = mountForm()
    await row(w, 'gain').find('input[type="range"]').setValue('7')
    expect(last(w, 'update')).toEqual(['gain', 7])
    await row(w, 'expression').find('textarea').setValue('x + 1')
    expect(last(w, 'update')).toEqual(['expression', 'x + 1'])
    await row(w, 'path').find('input[type="text"]').setValue('/data/a.fits')
    expect(last(w, 'update')).toEqual(['path', '/data/a.fits'])
    await row(w, 'tint').find('input[type="text"]').setValue('#ABC')
    expect(last(w, 'update')).toEqual(['tint', '#aabbcc'])
    await row(w, 'tint').find('input[type="text"]').setValue('#ab')
    expect(last(w, 'update')).toEqual(['tint', '#aabbcc'])
    await row(w, 'tint').find('input[type="color"]').setValue('#00ff00')
    expect(last(w, 'update')).toEqual(['tint', '#00ff00'])
  })

  it('only emits parsed JSON and flags invalid text', async () => {
    const w = mountForm()
    const area = row(w, 'meta').find('textarea')
    await area.setValue('{"k": 2')
    expect(w.emitted('update')).toBeUndefined()
    expect(row(w, 'meta').find('[role="alert"]').text()).toContain('Not valid JSON')
    expect(area.attributes('aria-invalid')).toBe('true')
    await area.setValue('{"k": 2}')
    expect(last(w, 'update')).toEqual(['meta', { k: 2 }])
    expect(row(w, 'meta').find('[role="alert"]').exists()).toBe(false)
    await area.setValue('')
    expect(last(w, 'update')).toEqual(['meta', null])
  })

  it('shows validation only after the user edits a field', async () => {
    const w = mountForm({ values: { wrest: null } })
    expect(row(w, 'wrest').find('[role="alert"]').exists()).toBe(false)
    const input = row(w, 'wrest').find('input')
    await input.setValue('5')
    await w.setProps({ values: { wrest: 5 } })
    expect(row(w, 'wrest').find('[role="alert"]').exists()).toBe(false)
    await input.setValue('')
    await w.setProps({ values: { wrest: null } })
    const alert = row(w, 'wrest').find('[role="alert"]')
    expect(alert.exists()).toBe(true)
    expect(alert.text()).toBe('Required')
    expect(input.attributes('aria-invalid')).toBe('true')
  })

  it('shows a range error for an invalid number after editing', async () => {
    const w = mountForm({ values: { z: 0 } })
    const input = row(w, 'z').find('input')
    await input.setValue('30')
    await w.setProps({ values: { z: 30 } })
    expect(row(w, 'z').find('[role="alert"]').text()).toBe('Must be at most 20')
  })

  it('renders server issues under the matching param', () => {
    const issues: NodeIssue[] = [
      { code: 'E_PARAM', message: 'Bad value', param: 'value' },
      { code: 'E_PORT', message: 'Port problem', port: 'in' },
    ]
    const w = mountForm({ issues })
    const alert = row(w, 'value').find('[role="alert"]')
    expect(alert.text()).toBe('Bad value')
    expect(alert.find('[data-issue="E_PARAM"]').exists()).toBe(true)
    expect(row(w, 'z').find('[role="alert"]').exists()).toBe(false)
  })

  it('renders linked params without a widget and toggles links', async () => {
    const w = mountForm({ linked: ['value'] })
    const linkedRow = row(w, 'value')
    expect(linkedRow.find('input').exists()).toBe(false)
    expect(linkedRow.find('[data-linked]').text()).toBe('linked')
    const unlink = linkedRow.find('button[data-link-toggle]')
    expect(unlink.attributes('aria-pressed')).toBe('true')
    expect(unlink.attributes('aria-label')).toBe('Unlink Value')
    await unlink.trigger('click')
    expect(w.emitted('toggle-link')).toEqual([['value']])

    const link = row(w, 'z').find('button[data-link-toggle]')
    expect(link.attributes('aria-pressed')).toBe('false')
    expect(link.attributes('aria-label')).toBe('Link Redshift as input')
    await link.trigger('click')
    expect(last(w, 'toggle-link')).toEqual(['z'])
  })

  it('hides the link toggle for non-linkable params', () => {
    const w = mountForm({ params: [{ ...value, linkable: false }] })
    expect(row(w, 'value').find('[data-link-toggle]').exists()).toBe(false)
  })

  it('collapses advanced params behind a toggle', async () => {
    const w = mountForm()
    const toggle = w.find('[data-advanced-toggle]')
    expect(toggle.text()).toContain('Advanced (2)')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    const section = w.find('[data-advanced]').element as HTMLElement
    expect(section.style.display).toBe('none')
    expect(row(w, 'secret').exists()).toBe(true)
    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(section.style.display).toBe('')
    await row(w, 'depth').find('input').setValue('4')
    expect(last(w, 'update')).toEqual(['depth', 4])
    // The prop drives the open state whenever it changes.
    await w.setProps({ showAdvanced: true })
    await w.setProps({ showAdvanced: false })
    expect(toggle.attributes('aria-expanded')).toBe('false')
  })

  it('opens advanced initially when showAdvanced is set and hides the section when empty', () => {
    const w = mountForm({ showAdvanced: true })
    expect(w.find('[data-advanced-toggle]').attributes('aria-expanded')).toBe('true')
    const none = mountForm({ params: [value] })
    expect(none.find('[data-advanced-toggle]').exists()).toBe(false)
  })

  it('marks compact layout and hides descriptions there', () => {
    const stacked = mountForm()
    expect(stacked.attributes('data-compact')).toBeUndefined()
    expect(row(stacked, 'value').text()).toContain('The number to output.')
    const compact = mountForm({ compact: true })
    expect(compact.attributes('data-compact')).toBe('true')
    expect(row(compact, 'value').text()).not.toContain('The number to output.')
  })

  it('disables every control when disabled', () => {
    const w = mountForm({ disabled: true })
    for (const control of w.findAll('input, select, textarea, button[data-link-toggle]')) {
      expect((control.element as HTMLInputElement).disabled).toBe(true)
    }
  })

  it('renders a plain number field for a slider without bounds and a trailing unit for other kinds', () => {
    const w = mountForm({
      params: [
        spec({ name: 'loose', widget: 'slider', json_schema: { type: 'number' } }),
        spec({ name: 'label', unit: 'deg', json_schema: { type: 'string' } }),
      ],
    })
    expect(row(w, 'loose').find('[data-widget="number"]').exists()).toBe(true)
    expect(row(w, 'label').text()).toContain('deg')
  })
})
