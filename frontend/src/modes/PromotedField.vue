<script setup lang="ts">
/**
 * One promoted param as a form row, drawn with the same widget the Inspector uses (design 8.4:
 * "the same AutoForm widgets, larger"). The promoted `label` and `help` override the spec's, so
 * renaming a parameter in the Parameters panel is enough to relabel every mode.
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import type { ParamSpec } from '@/api/types'
import ParamRow from '@/nodes/ParamRow.vue'
import { useExecutionStore } from '@/stores/execution'
import { useWorkflowStore } from '@/stores/workflow'
import type { ResolvedPromoted } from './layouts'

const props = withDefaults(defineProps<{ item: ResolvedPromoted; compact?: boolean }>(), {
  compact: false,
})

const { t } = useI18n()
const workflow = useWorkflowStore()
const execution = useExecutionStore()

/** The spec with the promoted label and help text substituted in. */
const spec = computed<ParamSpec | null>(() => {
  const base = props.item.spec
  if (!base) return null
  return {
    ...base,
    label: props.item.label,
    description: props.compact ? '' : (props.item.help ?? ''),
  }
})

const issues = computed(() => execution.issuesFor(props.item.node))
</script>

<template>
  <div :data-testid="`field-${item.ref}`" :data-node="item.node">
    <ParamRow
      v-if="spec"
      :param="spec"
      :value="item.value"
      :linked="item.linked"
      :issues="issues"
      :compact="compact"
      :disabled="item.disabled"
      :id-prefix="`mode-${item.node}`"
      @update="(name, value) => workflow.setParam(item.node, name, value)"
      @toggle-link="(name) => workflow.toggleLink(item.node, name)"
    />
    <p v-else class="text-[11px] text-destructive">
      {{ t('modes.unknown_param', { ref: item.ref }) }}
    </p>
  </div>
</template>
