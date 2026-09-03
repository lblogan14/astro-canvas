<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { NodeIssue, ParamSpec } from '@/api/types'

import ParamRow from './ParamRow.vue'
import { coerceDefault } from './validate'

const props = withDefaults(
  defineProps<{
    params: ParamSpec[]
    values: Record<string, unknown>
    linked?: string[]
    issues?: NodeIssue[]
    compact?: boolean
    disabled?: boolean
    idPrefix: string
    showAdvanced?: boolean
  }>(),
  {
    linked: () => [],
    issues: () => [],
    compact: false,
    disabled: false,
    showAdvanced: false,
  },
)

const emit = defineEmits<{
  update: [name: string, value: unknown]
  'toggle-link': [name: string]
}>()

const { t } = useI18n()

const basicParams = computed(() => props.params.filter((param) => !param.advanced))
const advancedParams = computed(() => props.params.filter((param) => param.advanced))

const advancedOpen = ref(props.showAdvanced)
watch(
  () => props.showAdvanced,
  (next) => {
    advancedOpen.value = next
  },
)

const linkedSet = computed(() => new Set(props.linked))

function valueOf(param: ParamSpec): unknown {
  return param.name in props.values ? props.values[param.name] : coerceDefault(param)
}

const advancedId = computed(() => `${props.idPrefix}-advanced`)
const gap = computed(() => (props.compact ? 'gap-0.5' : 'gap-2'))
</script>

<template>
  <div
    class="nodrag nowheel flex flex-col text-xs text-foreground"
    :class="gap"
    :data-compact="compact ? 'true' : undefined"
    data-autoform
  >
    <ParamRow
      v-for="param in basicParams"
      :key="param.name"
      :param="param"
      :value="valueOf(param)"
      :linked="linkedSet.has(param.name)"
      :issues="issues"
      :compact="compact"
      :disabled="disabled"
      :id-prefix="idPrefix"
      @update="(name, value) => emit('update', name, value)"
      @toggle-link="(name) => emit('toggle-link', name)"
    />

    <div v-if="advancedParams.length > 0" class="flex flex-col" :class="gap" data-advanced-section>
      <button
        type="button"
        class="inline-flex h-6 items-center gap-1 self-start rounded-md px-1 text-[11px] text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        :aria-expanded="advancedOpen"
        :aria-controls="advancedId"
        data-advanced-toggle
        @click="advancedOpen = !advancedOpen"
      >
        <span
          aria-hidden="true"
          class="inline-block transition-transform"
          :class="advancedOpen ? 'rotate-90' : ''"
          >▸</span
        >
        {{ t('autoform.advanced', { count: advancedParams.length }) }}
      </button>
      <div v-show="advancedOpen" :id="advancedId" class="flex flex-col" :class="gap" data-advanced>
        <ParamRow
          v-for="param in advancedParams"
          :key="param.name"
          :param="param"
          :value="valueOf(param)"
          :linked="linkedSet.has(param.name)"
          :issues="issues"
          :compact="compact"
          :disabled="disabled"
          :id-prefix="idPrefix"
          @update="(name, value) => emit('update', name, value)"
          @toggle-link="(name) => emit('toggle-link', name)"
        />
      </div>
    </div>
  </div>
</template>
