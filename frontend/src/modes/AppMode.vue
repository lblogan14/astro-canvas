<script setup lang="ts">
/**
 * App mode (design 8.4): the promoted params as one scrolling form of sections with the pinned
 * views beside them — ComfyUI's App Mode analogue, and the layout a template opens into when it
 * wants a form rather than a wizard.
 *
 * With no `layouts.app` section the layout is derived from the promoted groups, so promoting
 * three params is all it takes to get a working app. *Save layout* writes what is on screen into
 * the document (one undoable command); until then the mode never dirties the workflow.
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { Ban, Download, Play, Save, Workflow, Zap } from '@lucide/vue'

import { Button } from '@/components/ui/button'
import { useUiStore } from '@/stores/ui'
import { useWorkflowStore } from '@/stores/workflow'
import PromotedField from './PromotedField.vue'
import ViewTile from './ViewTile.vue'
import { type ResolvedView, defaultAppLayout, readAppLayout } from './layouts'
import { useMode } from './useMode'

const { t } = useI18n()
const workflow = useWorkflowStore()
const ui = useUiStore()
const mode = useMode()

const exported = ref<string | null>(null)

/** The document's App layout, or the one derived from the promoted groups. */
const layout = computed(
  () => readAppLayout(workflow.layouts) ?? defaultAppLayout(workflow.promotedList, workflow.views),
)
const isDerived = computed(() => readAppLayout(workflow.layouts) === null)

/** Sections keep their promoted fields; views are hoisted into the right-hand column. */
const sections = computed(() =>
  layout.value.sections.map((section) => {
    const { resolved, missing } = mode.resolve(section.items)
    return {
      title: section.title,
      description: section.description,
      fields: resolved.filter((item) => item.kind === 'promoted'),
      missing,
    }
  }),
)

const views = computed<ResolvedView[]>(() => {
  const out: ResolvedView[] = []
  for (const section of layout.value.sections) {
    for (const item of mode.resolve(section.items).resolved) {
      if (item.kind === 'view') out.push(item)
    }
  }
  return out
})

const nodeIds = computed(() => [
  ...new Set([
    ...sections.value.flatMap((section) => section.fields.map((field) => field.node)),
    ...views.value.map((view) => view.node),
  ]),
])
const problems = computed(() => mode.problemsOf(nodeIds.value))
const missing = computed(() => sections.value.flatMap((section) => section.missing))
const isEmpty = computed(() => nodeIds.value.length === 0)

function saveLayout(): void {
  workflow.setLayout('app', layout.value, 'command.layout_app')
  workflow.scheduleSave()
  ui.notify(t('modes.layout_saved'))
}

async function exportResults(): Promise<void> {
  const dir = await mode.exportResults()
  exported.value = dir
  if (dir) ui.notify(t('modes.exported', { dir }))
}
</script>

<template>
  <div class="flex h-full min-h-0 flex-col bg-background" data-testid="app-mode">
    <div class="flex shrink-0 flex-wrap items-center gap-1 border-b px-2 py-1.5">
      <Button
        v-if="!mode.running.value"
        size="sm"
        :disabled="!workflow.isOpen"
        data-testid="app-run"
        @click="mode.run()"
      >
        <Play /> {{ t('modes.run') }}
      </Button>
      <Button
        v-else
        size="sm"
        variant="destructive"
        data-testid="app-cancel"
        @click="mode.cancel()"
      >
        <Ban /> {{ t('toolbar.cancel') }}
      </Button>
      <span
        class="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px]"
        :class="mode.autoRun.value ? 'bg-amber-500/10 text-amber-600' : 'text-muted-foreground'"
        data-testid="app-autorun"
        :data-on="mode.autoRun.value ? 'true' : 'false'"
      >
        <Zap class="size-3" />
        {{ mode.autoRun.value ? t('modes.auto_on') : t('modes.auto_off') }}
      </span>

      <span class="flex-1" />

      <Button
        size="sm"
        variant="ghost"
        :disabled="mode.exportRefs.value.length === 0"
        :title="t('modes.export_hint', { n: mode.exportRefs.value.length })"
        data-testid="app-export"
        @click="exportResults"
      >
        <Download /> {{ t('modes.export') }}
      </Button>
      <Button
        size="sm"
        variant="ghost"
        :disabled="isEmpty"
        :title="isDerived ? t('modes.save_layout_hint') : t('modes.save_layout_update')"
        data-testid="app-save-layout"
        @click="saveLayout"
      >
        <Save /> {{ t('modes.save_layout') }}
      </Button>
      <Button size="sm" variant="ghost" data-testid="app-show-graph" @click="ui.setMode('canvas')">
        <Workflow /> {{ t('modes.show_graph') }}
      </Button>
    </div>

    <p v-if="isEmpty" class="p-6 text-center text-xs text-muted-foreground" data-testid="app-empty">
      {{ t('modes.empty') }}
    </p>

    <div
      v-else
      class="grid min-h-0 flex-1 gap-3 overflow-auto p-3 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]"
    >
      <div class="flex min-w-0 flex-col gap-3">
        <section
          v-for="section in sections"
          :key="section.title"
          class="rounded-lg border bg-card p-3"
          :data-testid="`app-section-${section.title}`"
        >
          <h2 class="mb-2 text-sm font-semibold">{{ section.title }}</h2>
          <p v-if="section.description" class="mb-2 text-[11px] text-muted-foreground">
            {{ section.description }}
          </p>
          <div class="flex flex-col gap-3">
            <PromotedField v-for="field in section.fields" :key="field.key" :item="field" />
            <p v-if="section.fields.length === 0" class="text-[11px] text-muted-foreground">
              {{ t('modes.section_empty') }}
            </p>
          </div>
        </section>

        <ul
          v-if="problems.length"
          class="space-y-0.5 rounded-lg border border-destructive/40 bg-destructive/5 p-2 text-[11px] text-destructive"
          data-testid="app-problems"
        >
          <li v-for="(problem, index) in problems" :key="index">
            {{ problem.node }}: {{ problem.message }}
          </li>
        </ul>
        <ul
          v-if="missing.length"
          class="space-y-0.5 rounded-lg border border-amber-500/40 bg-amber-500/5 p-2 text-[11px] text-amber-700"
          data-testid="app-missing"
        >
          <li v-for="ref in missing" :key="ref">{{ t('modes.missing_item', { ref }) }}</li>
        </ul>
        <p v-if="exported" class="text-[11px] text-muted-foreground" data-testid="app-exported">
          {{ t('modes.exported', { dir: exported }) }}
        </p>
      </div>

      <div class="grid min-w-0 gap-3 self-start" data-testid="app-views">
        <ViewTile
          v-for="view in views"
          :key="view.key"
          :view="view.view"
          :label="view.label"
          :height="260"
        />
        <p v-if="views.length === 0" class="text-[11px] text-muted-foreground">
          {{ t('modes.no_views') }}
        </p>
      </div>
    </div>
  </div>
</template>
