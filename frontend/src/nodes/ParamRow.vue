<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Star } from '@lucide/vue'

import type { NodeIssue, ParamSpec } from '@/api/types'

import { validateParam, type ValidationMessage } from './validate'
import {
  enumOptions,
  listItemType,
  schemaNumberBounds,
  schemaType,
  unwrapNullable,
  widgetFor,
  type WidgetKind,
} from './widgetFor'
import {
  CheckboxField,
  CodeField,
  ColorField,
  ListField,
  NumberField,
  PathField,
  PortsField,
  RangeField,
  RedshiftField,
  SelectField,
  SliderField,
  TextField,
  WavelengthField,
} from './widgets'

const props = withDefaults(
  defineProps<{
    param: ParamSpec
    value: unknown
    linked?: boolean
    issues?: NodeIssue[]
    compact?: boolean
    disabled?: boolean
    idPrefix: string
    /** Show the star that lifts this param into the App/Wizard/Dashboard layouts. */
    promotable?: boolean
    promoted?: boolean
  }>(),
  {
    linked: false,
    issues: () => [],
    compact: false,
    disabled: false,
    promotable: false,
    promoted: false,
  },
)

const emit = defineEmits<{
  update: [name: string, value: unknown]
  'toggle-link': [name: string]
  promote: [name: string]
}>()

const { t } = useI18n()

const inputId = computed(() => `${props.idPrefix}-${props.param.name}`)
const messageId = computed(() => `${inputId.value}-messages`)
const kind = computed<WidgetKind>(() => widgetFor(props.param))
const bounds = computed(() => schemaNumberBounds(props.param.json_schema, props.param))
const integer = computed(() => schemaType(props.param.json_schema) === 'integer')

const unit = computed<string | null>(() => {
  const raw = props.param.unit ?? props.param.json_schema['x-unit']
  return typeof raw === 'string' && raw !== '' ? raw : null
})

/** Units are rendered inside number-like widgets; other kinds get a trailing unit label. */
const widgetOwnsUnit = computed(
  () =>
    kind.value === 'number' ||
    kind.value === 'slider' ||
    kind.value === 'range' ||
    kind.value === 'wavelength' ||
    kind.value === 'redshift',
)

const sliderBounds = computed<{ min: number; max: number } | null>(() => {
  const { min, max } = bounds.value
  return min !== undefined && max !== undefined && max > min ? { min, max } : null
})

const numberValue = computed<number | null>(() =>
  typeof props.value === 'number' && Number.isFinite(props.value) ? props.value : null,
)

const stringValue = computed<string>(() => {
  if (typeof props.value === 'string') return props.value
  if (props.value === null || props.value === undefined) return ''
  return String(props.value)
})

const booleanValue = computed(() => props.value === true)
const arrayValue = computed<unknown[]>(() => (Array.isArray(props.value) ? props.value : []))

const rangeValue = computed<[number, number] | null>(() => {
  if (Array.isArray(props.value) && props.value.length === 2) {
    const [lo, hi] = props.value
    if (typeof lo === 'number' && typeof hi === 'number') return [lo, hi]
  }
  return null
})

const language = computed(() => {
  if (kind.value === 'json') return 'json'
  if (kind.value === 'markdown') return 'markdown'
  const lang = props.param.json_schema['x-language']
  return typeof lang === 'string' ? lang : 'code'
})

const placeholder = computed(() => {
  const raw = props.param.json_schema['x-placeholder']
  return typeof raw === 'string' ? raw : ''
})

const textMaxLength = computed(() => {
  const max = unwrapNullable(props.param.json_schema)['maxLength']
  return typeof max === 'number' ? max : undefined
})

// --- editing state -------------------------------------------------------------------------

const touched = ref(false)

/** Raw JSON text while the user is editing (may be unparsable). */
const jsonDraft = ref<string | null>(null)
const jsonError = ref(false)

function serialize(value: unknown): string {
  if (value === undefined) return ''
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return ''
  }
}

const jsonText = computed(() => jsonDraft.value ?? serialize(props.value))

// When an upstream value change lands (undo, load) and the draft already denotes it, drop it.
watch(
  () => props.value,
  (next) => {
    if (jsonDraft.value === null) return
    try {
      if (JSON.stringify(JSON.parse(jsonDraft.value)) === JSON.stringify(next))
        jsonDraft.value = null
    } catch {
      // keep an unparsable draft so the user can fix it
    }
  },
  { deep: true },
)

function update(value: unknown) {
  touched.value = true
  emit('update', props.param.name, value)
}

function updateJson(text: unknown) {
  const raw = typeof text === 'string' ? text : ''
  touched.value = true
  jsonDraft.value = raw
  if (raw.trim() === '') {
    jsonError.value = false
    emit('update', props.param.name, null)
    return
  }
  try {
    const parsed: unknown = JSON.parse(raw)
    jsonError.value = false
    emit('update', props.param.name, parsed)
  } catch {
    jsonError.value = true
  }
}

const clientMessages = computed<ValidationMessage[]>(() => {
  if (!touched.value) return []
  const messages = validateParam(props.param, props.value)
  if (jsonError.value) messages.unshift({ key: 'autoform.json_invalid' })
  return messages
})

const serverIssues = computed(() =>
  props.issues.filter((issue) => issue.param === props.param.name),
)
const invalid = computed(() => clientMessages.value.length > 0 || serverIssues.value.length > 0)
</script>

<template>
  <div
    class="autoform-row"
    :class="
      compact ? 'grid grid-cols-[minmax(4rem,35%)_1fr] items-start gap-x-2' : 'flex flex-col gap-1'
    "
    :data-param="param.name"
    :data-widget-kind="kind"
  >
    <div class="flex min-w-0 items-center gap-1" :class="compact ? 'h-6' : ''">
      <label
        :for="inputId"
        class="truncate text-xs leading-none text-muted-foreground"
        :title="param.description || param.label"
      >
        {{ param.label
        }}<span
          v-if="param.required"
          class="text-destructive"
          :title="t('autoform.required_marker')"
          >*</span
        >
      </label>
    </div>

    <div class="flex min-w-0 flex-col gap-1">
      <div class="flex min-w-0 items-center gap-1">
        <span
          v-if="linked"
          :id="inputId"
          class="inline-flex h-6 flex-1 items-center rounded-md border border-dashed border-input px-1.5 text-[11px] text-muted-foreground"
          role="status"
          data-linked
        >
          {{ t('autoform.linked') }}
        </span>

        <template v-else>
          <div class="min-w-0 flex-1">
            <NumberField
              v-if="kind === 'number' || (kind === 'slider' && !sliderBounds)"
              :id="inputId"
              :model-value="numberValue"
              :min="bounds.min"
              :max="bounds.max"
              :step="bounds.step"
              :unit="unit"
              :integer="integer"
              :disabled="disabled"
              :invalid="invalid"
              @update:model-value="update"
            />
            <SliderField
              v-else-if="kind === 'slider' && sliderBounds"
              :id="inputId"
              :model-value="numberValue"
              :min="sliderBounds.min"
              :max="sliderBounds.max"
              :step="bounds.step"
              :unit="unit"
              :integer="integer"
              :disabled="disabled"
              :invalid="invalid"
              :label="param.label"
              @update:model-value="update"
            />
            <RedshiftField
              v-else-if="kind === 'redshift'"
              :id="inputId"
              :model-value="numberValue"
              :min="bounds.min"
              :max="bounds.max"
              :step="bounds.step"
              :disabled="disabled"
              :invalid="invalid"
              @update:model-value="update"
            />
            <WavelengthField
              v-else-if="kind === 'wavelength'"
              :id="inputId"
              :model-value="numberValue"
              :min="bounds.min"
              :max="bounds.max"
              :step="bounds.step"
              :unit="unit"
              :disabled="disabled"
              :invalid="invalid"
              @update:model-value="update"
            />
            <TextField
              v-else-if="kind === 'text'"
              :id="inputId"
              :model-value="stringValue"
              :maxlength="textMaxLength"
              :placeholder="placeholder"
              :disabled="disabled"
              :invalid="invalid"
              @update:model-value="update"
            />
            <CodeField
              v-else-if="kind === 'code' || kind === 'markdown'"
              :id="inputId"
              :kind="kind"
              :model-value="stringValue"
              :language="language"
              :placeholder="placeholder"
              :disabled="disabled"
              :invalid="invalid"
              @update:model-value="update"
            />
            <CodeField
              v-else-if="kind === 'json'"
              :id="inputId"
              kind="json"
              :model-value="jsonText"
              language="json"
              :disabled="disabled"
              :invalid="invalid"
              @update:model-value="updateJson"
            />
            <SelectField
              v-else-if="kind === 'select'"
              :id="inputId"
              :model-value="value"
              :options="enumOptions(param.json_schema)"
              :disabled="disabled"
              :invalid="invalid"
              @update:model-value="update"
            />
            <CheckboxField
              v-else-if="kind === 'checkbox'"
              :id="inputId"
              :model-value="booleanValue"
              :disabled="disabled"
              :invalid="invalid"
              @update:model-value="update"
            />
            <RangeField
              v-else-if="kind === 'range'"
              :id="inputId"
              :model-value="rangeValue"
              :unit="unit"
              :min="bounds.min"
              :max="bounds.max"
              :step="bounds.step"
              :disabled="disabled"
              :invalid="invalid"
              :label="param.label"
              @update:model-value="update"
            />
            <ListField
              v-else-if="kind === 'list'"
              :id="inputId"
              :model-value="arrayValue"
              :item-type="listItemType(param.json_schema)"
              :disabled="disabled"
              :invalid="invalid"
              :label="param.label"
              @update:model-value="update"
            />
            <PortsField
              v-else-if="kind === 'ports'"
              :id="inputId"
              :model-value="arrayValue"
              :disabled="disabled"
              :invalid="invalid"
              :label="param.label"
              @update:model-value="update"
            />
            <PathField
              v-else-if="kind === 'path'"
              :id="inputId"
              :model-value="stringValue"
              :disabled="disabled"
              :invalid="invalid"
              @update:model-value="update"
            />
            <ColorField
              v-else-if="kind === 'color'"
              :id="inputId"
              :model-value="stringValue"
              :disabled="disabled"
              :invalid="invalid"
              :label="param.label"
              @update:model-value="update"
            />
          </div>
          <span
            v-if="unit && !widgetOwnsUnit"
            class="shrink-0 text-[11px] text-muted-foreground"
            aria-hidden="true"
          >
            {{ unit }}
          </span>
        </template>

        <button
          v-if="promotable"
          type="button"
          class="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md border text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          :class="
            promoted
              ? 'border-amber-500 bg-amber-500/10 text-amber-600'
              : 'border-input bg-background'
          "
          :aria-pressed="promoted"
          :aria-label="
            promoted
              ? t('promote.remove', { label: param.label })
              : t('promote.add', { label: param.label })
          "
          :title="promoted ? t('promote.remove_hint') : t('promote.add_hint')"
          data-promote-toggle
          :data-testid="`promote-${param.name}`"
          @click="emit('promote', param.name)"
        >
          <Star class="size-3" :fill="promoted ? 'currentColor' : 'none'" />
        </button>

        <button
          v-if="param.linkable"
          type="button"
          class="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md border text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
          :class="
            linked ? 'border-primary bg-primary/10 text-primary' : 'border-input bg-background'
          "
          :aria-pressed="linked"
          :aria-label="
            linked
              ? t('autoform.unlink', { label: param.label })
              : t('autoform.link', { label: param.label })
          "
          :disabled="disabled"
          data-link-toggle
          @click="emit('toggle-link', param.name)"
        >
          <svg
            aria-hidden="true"
            viewBox="0 0 16 16"
            class="h-3 w-3"
            fill="none"
            stroke="currentColor"
            stroke-width="1.6"
            stroke-linecap="round"
          >
            <path d="M6.5 9.5 9.5 6.5" />
            <path d="M7 4.5 8.5 3a2.5 2.5 0 0 1 3.5 3.5L10.5 8" />
            <path d="M9 11.5 7.5 13A2.5 2.5 0 0 1 4 9.5L5.5 8" />
          </svg>
        </button>
      </div>

      <p
        v-if="!compact && param.description"
        class="m-0 text-[11px] leading-snug text-muted-foreground"
      >
        {{ param.description }}
      </p>

      <ul
        v-if="invalid"
        :id="messageId"
        role="alert"
        class="m-0 flex list-none flex-col gap-0.5 p-0 text-[11px] leading-snug text-destructive"
      >
        <li v-for="(message, index) in clientMessages" :key="`c${index}`">
          {{ t(message.key, message.params ?? {}) }}
        </li>
        <li v-for="(issue, index) in serverIssues" :key="`s${index}`" :data-issue="issue.code">
          {{ issue.message }}
        </li>
      </ul>
    </div>
  </div>
</template>
