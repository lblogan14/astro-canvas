<script setup lang="ts">
/**
 * Wizard mode (design 8.4, 8.5): the graph as ordered steps, which is how `launch_specgui`'s
 * tabs (Load → Redshift → Transition → Continuum → Measure → Save) read to an undergraduate who
 * should never have to see a canvas.
 *
 * *Next* opens once every node the step depends on is `done` and free of validation errors —
 * that is the whole gating rule, and it is why a step that has not run yet offers *Run step*
 * instead. Going back never discards anything: the values live in the document, so a step
 * revisited shows what was typed into it.
 *
 * The layout editor is in the same component behind an *Edit* toggle: step titles are text
 * inputs, and promoted params and views are dragged (or moved with buttons) between steps and
 * the unassigned tray. Edits stay in a local draft until *Save layout*.
 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  Ban,
  Check,
  ChevronLeft,
  ChevronRight,
  Download,
  FastForward,
  Play,
  Plus,
  Save,
  SquarePen,
  Trash2,
  TriangleAlert,
  Workflow,
} from '@lucide/vue'

import { Button } from '@/components/ui/button'
import { useUiStore } from '@/stores/ui'
import { useWorkflowStore } from '@/stores/workflow'
import PromotedField from './PromotedField.vue'
import ViewTile from './ViewTile.vue'
import {
  type WizardLayout,
  type WizardStep,
  defaultWizardLayout,
  parseItem,
  promotedItem,
  readWizardLayout,
  refOf,
  viewItem,
} from './layouts'
import { useMode } from './useMode'

const { t } = useI18n()
const workflow = useWorkflowStore()
const ui = useUiStore()
const mode = useMode()

const current = ref(0)
const editing = ref(false)
/** Layout being edited; `null` while the wizard shows the stored (or derived) one. */
const draft = ref<WizardLayout | null>(null)
const dragged = ref<string | null>(null)
const exported = ref<string | null>(null)

const stored = computed(() => readWizardLayout(workflow.layouts))
const layout = computed<WizardLayout>(
  () => draft.value ?? stored.value ?? defaultWizardLayout(workflow.promotedList, workflow.views),
)

interface Step {
  index: number
  title: string
  description: string | null
  items: ReturnType<typeof mode.resolve>['resolved']
  missing: string[]
  nodes: string[]
  state: ReturnType<typeof mode.groupState>
  problems: { node: string; message: string }[]
  optional: boolean
}

const steps = computed<Step[]>(() =>
  layout.value.steps.map((step, index) => {
    const { resolved, missing } = mode.resolve(step.items)
    const nodes = step.nodes?.length ? step.nodes : mode.nodesOf(resolved)
    return {
      index,
      title: step.title || t('wizard.step_n', { n: index + 1 }),
      description: step.description ?? null,
      items: resolved,
      missing,
      nodes,
      state: mode.groupState(nodes),
      problems: mode.problemsOf(nodes),
      optional: step.optional === true,
    }
  }),
)

const step = computed<Step | null>(() => steps.value[current.value] ?? null)
const fields = computed(() => step.value?.items.filter((item) => item.kind === 'promoted') ?? [])
const views = computed(() => step.value?.items.filter((item) => item.kind === 'view') ?? [])
const isLast = computed(() => current.value >= steps.value.length - 1)
/** Next is gated on the step's nodes: done, and nothing invalid. */
const canAdvance = computed(
  () => !!step.value && (step.value.state === 'done' || step.value.optional),
)
const resultsIndex = computed(() => Math.max(0, steps.value.length - 1))

/** Every promoted param and view that no step lists yet (the editor's tray). */
const unassigned = computed(() => {
  const used = new Set(layout.value.steps.flatMap((entry) => entry.items))
  const items = [
    ...workflow.promotedList.map((entry) => promotedItem(refOf(entry))),
    ...workflow.views.map((view) => viewItem(view.id)),
  ]
  return items.filter((item) => !used.has(item))
})

watch(
  () => steps.value.length,
  (length) => {
    if (current.value >= length) current.value = Math.max(0, length - 1)
  },
)

function go(index: number): void {
  // Backwards is always allowed; forwards only through a finished step.
  if (index <= current.value || canAdvance.value)
    current.value = Math.max(0, Math.min(index, steps.value.length - 1))
}

function labelOf(item: string): string {
  const parsed = parseItem(item)
  if (!parsed) return item
  if (parsed.kind === 'view') return workflow.views.find((v) => v.id === parsed.ref)?.port ?? item
  return workflow.promotedList.find((p) => refOf(p) === parsed.ref)?.label ?? parsed.ref
}

// --- layout editing ----------------------------------------------------------------------------

function beginEdit(): void {
  draft.value = {
    steps: layout.value.steps.map((entry) => ({ ...entry, items: [...entry.items] })),
  }
  editing.value = true
}

function mutate(change: (steps: WizardStep[]) => void): void {
  if (!draft.value) beginEdit()
  const next = draft.value?.steps.map((entry) => ({ ...entry, items: [...entry.items] })) ?? []
  change(next)
  draft.value = { steps: next }
}

function setTitle(index: number, title: string): void {
  mutate((entries) => {
    const entry = entries[index]
    if (entry) entry.title = title
  })
}

function addStep(): void {
  mutate((entries) => entries.push({ title: t('wizard.new_step'), items: [], nodes: [] }))
}

function removeStep(index: number): void {
  mutate((entries) => entries.splice(index, 1))
}

/** Move an item into `index`, or out of every step when `index` is `null` (the tray). */
function assign(item: string, index: number | null): void {
  mutate((entries) => {
    for (const entry of entries) entry.items = entry.items.filter((existing) => existing !== item)
    if (index !== null) entries[index]?.items.push(item)
  })
}

function onDrop(index: number | null): void {
  const item = dragged.value
  dragged.value = null
  if (item) assign(item, index)
}

function shiftStep(item: string, from: number, delta: number): void {
  const to = from + delta
  if (to < 0 || to >= layout.value.steps.length) return
  assign(item, to)
}

function saveLayout(): void {
  workflow.setLayout('wizard', layout.value, 'command.layout_wizard')
  workflow.scheduleSave()
  draft.value = null
  editing.value = false
  ui.notify(t('modes.layout_saved'))
}

function discard(): void {
  draft.value = null
  editing.value = false
}

async function exportResults(): Promise<void> {
  const dir = await mode.exportResults()
  exported.value = dir
  if (dir) ui.notify(t('modes.exported', { dir }))
}
</script>

<template>
  <div class="flex h-full min-h-0 flex-col bg-background" data-testid="wizard-mode">
    <!-- stepper -->
    <!-- The stepper is the list; the layout buttons are its siblings, because an `<ol>` may only
         contain `<li>` (axe `list`). -->
    <div class="flex shrink-0 flex-wrap items-center gap-1 border-b px-2 py-1.5 text-xs">
      <ol class="flex flex-wrap items-center gap-1" data-testid="wizard-stepper">
        <li v-for="entry in steps" :key="entry.index" class="flex items-center gap-1">
          <button
            type="button"
            class="inline-flex items-center gap-1 rounded-md border px-2 py-1"
            :class="[
              entry.index === current
                ? 'border-primary bg-primary/10 font-medium text-primary'
                : 'border-transparent',
              entry.index > current && !canAdvance ? 'text-muted-foreground' : '',
            ]"
            :aria-current="entry.index === current ? 'step' : undefined"
            :data-testid="`wizard-step-${entry.index}`"
            :data-state="entry.state"
            @click="go(entry.index)"
          >
            <Check v-if="entry.state === 'done'" class="size-3 text-emerald-600" />
            <TriangleAlert v-else-if="entry.state === 'error'" class="size-3 text-destructive" />
            <span
              v-else
              class="inline-block size-2 rounded-full"
              :class="
                entry.state === 'running' ? 'animate-pulse bg-blue-500' : 'bg-muted-foreground/40'
              "
              aria-hidden="true"
            />
            {{ entry.title }}
          </button>
          <ChevronRight
            v-if="entry.index < steps.length - 1"
            class="size-3 text-muted-foreground"
            aria-hidden="true"
          />
        </li>
      </ol>

      <span class="flex-1" />

      <Button
        size="sm"
        variant="ghost"
        :aria-pressed="editing"
        data-testid="wizard-edit"
        @click="editing ? discard() : beginEdit()"
      >
        <SquarePen /> {{ editing ? t('common.cancel') : t('wizard.edit_layout') }}
      </Button>
      <Button
        v-if="editing || draft"
        size="sm"
        variant="ghost"
        data-testid="wizard-save-layout"
        @click="saveLayout"
      >
        <Save /> {{ t('modes.save_layout') }}
      </Button>
      <Button
        size="sm"
        variant="ghost"
        data-testid="wizard-show-graph"
        @click="ui.setMode('canvas')"
      >
        <Workflow /> {{ t('modes.show_graph') }}
      </Button>
    </div>

    <p
      v-if="steps.length === 0"
      class="p-6 text-center text-xs text-muted-foreground"
      data-testid="wizard-empty"
    >
      {{ t('modes.empty') }}
    </p>

    <!-- layout editor -->
    <div v-else-if="editing" class="min-h-0 flex-1 overflow-auto p-3" data-testid="wizard-editor">
      <div class="grid gap-3 lg:grid-cols-[minmax(0,3fr)_minmax(0,1fr)]">
        <div class="flex flex-col gap-2">
          <section
            v-for="entry in layout.steps"
            :key="entry.title + steps.length"
            class="rounded-lg border bg-card p-2"
            :data-testid="`wizard-edit-step-${layout.steps.indexOf(entry)}`"
            @dragover.prevent
            @drop.prevent="onDrop(layout.steps.indexOf(entry))"
          >
            <div class="mb-1 flex items-center gap-1">
              <input
                class="h-7 min-w-0 flex-1 rounded border bg-background px-2 text-sm font-medium"
                :value="entry.title"
                :aria-label="t('wizard.step_title')"
                :data-testid="`wizard-title-${layout.steps.indexOf(entry)}`"
                @change="
                  setTitle(layout.steps.indexOf(entry), ($event.target as HTMLInputElement).value)
                "
              />
              <button
                type="button"
                class="inline-flex size-6 items-center justify-center rounded text-muted-foreground hover:text-destructive"
                :aria-label="t('wizard.remove_step', { title: entry.title })"
                :data-testid="`wizard-remove-step-${layout.steps.indexOf(entry)}`"
                @click="removeStep(layout.steps.indexOf(entry))"
              >
                <Trash2 class="size-3.5" />
              </button>
            </div>
            <ul class="flex flex-wrap gap-1" role="list">
              <li
                v-for="item in entry.items"
                :key="item"
                class="flex items-center gap-1 rounded-full border bg-background px-2 py-0.5 text-[11px]"
                draggable="true"
                :data-testid="`wizard-item-${item}`"
                @dragstart="dragged = item"
                @dragend="dragged = null"
              >
                {{ labelOf(item) }}
                <button
                  type="button"
                  class="text-muted-foreground hover:text-foreground"
                  :aria-label="t('wizard.move_earlier', { label: labelOf(item) })"
                  @click="shiftStep(item, layout.steps.indexOf(entry), -1)"
                >
                  <ChevronLeft class="size-3" />
                </button>
                <button
                  type="button"
                  class="text-muted-foreground hover:text-foreground"
                  :aria-label="t('wizard.move_later', { label: labelOf(item) })"
                  @click="shiftStep(item, layout.steps.indexOf(entry), 1)"
                >
                  <ChevronRight class="size-3" />
                </button>
              </li>
              <li v-if="entry.items.length === 0" class="text-[11px] text-muted-foreground">
                {{ t('wizard.drop_here') }}
              </li>
            </ul>
          </section>
          <Button size="sm" variant="outline" data-testid="wizard-add-step" @click="addStep">
            <Plus /> {{ t('wizard.add_step') }}
          </Button>
        </div>

        <section
          class="rounded-lg border border-dashed p-2"
          data-testid="wizard-tray"
          @dragover.prevent
          @drop.prevent="onDrop(null)"
        >
          <h2 class="mb-1 text-xs font-medium text-muted-foreground">{{ t('wizard.tray') }}</h2>
          <ul class="flex flex-wrap gap-1" role="list">
            <li
              v-for="item in unassigned"
              :key="item"
              class="rounded-full border bg-background px-2 py-0.5 text-[11px]"
              draggable="true"
              :data-testid="`wizard-tray-${item}`"
              @dragstart="dragged = item"
              @dragend="dragged = null"
            >
              {{ labelOf(item) }}
            </li>
            <li v-if="unassigned.length === 0" class="text-[11px] text-muted-foreground">
              {{ t('wizard.tray_empty') }}
            </li>
          </ul>
        </section>
      </div>
    </div>

    <!-- the step itself -->
    <template v-else-if="step">
      <div class="min-h-0 flex-1 overflow-auto p-3" :data-testid="`wizard-body-${step.index}`">
        <h2 class="text-sm font-semibold">{{ step.title }}</h2>
        <p v-if="step.description" class="mt-1 text-[11px] text-muted-foreground">
          {{ step.description }}
        </p>

        <div class="mt-3 grid gap-3 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
          <div class="flex min-w-0 flex-col gap-3">
            <PromotedField v-for="field in fields" :key="field.key" :item="field" />
            <p v-if="fields.length === 0" class="text-[11px] text-muted-foreground">
              {{ t('wizard.no_params') }}
            </p>
            <ul
              v-if="step.problems.length"
              class="space-y-0.5 rounded-lg border border-destructive/40 bg-destructive/5 p-2 text-[11px] text-destructive"
              data-testid="wizard-problems"
            >
              <li v-for="(problem, index) in step.problems" :key="index">
                {{ problem.node }}: {{ problem.message }}
              </li>
            </ul>
            <ul
              v-if="step.missing.length"
              class="space-y-0.5 rounded-lg border border-amber-500/40 bg-amber-500/5 p-2 text-[11px] text-amber-700"
              data-testid="wizard-missing"
            >
              <li v-for="ref in step.missing" :key="ref">{{ t('modes.missing_item', { ref }) }}</li>
            </ul>
          </div>
          <div v-if="views.length" class="grid min-w-0 gap-3 self-start" data-testid="wizard-views">
            <ViewTile
              v-for="view in views"
              :key="view.key"
              :view="view.view"
              :label="view.label"
              :height="280"
            />
          </div>
        </div>
      </div>

      <!-- controls -->
      <div class="flex shrink-0 items-center gap-1 border-t px-2 py-1.5">
        <Button
          size="sm"
          variant="ghost"
          :disabled="current === 0"
          data-testid="wizard-back"
          @click="go(current - 1)"
        >
          <ChevronLeft /> {{ t('wizard.back') }}
        </Button>
        <Button
          v-if="!mode.running.value"
          size="sm"
          variant="secondary"
          :disabled="step.nodes.length === 0"
          :title="t('wizard.run_step_hint')"
          data-testid="wizard-run-step"
          @click="mode.run(step.nodes)"
        >
          <Play /> {{ t('wizard.run_step') }}
        </Button>
        <Button
          v-else
          size="sm"
          variant="destructive"
          data-testid="wizard-cancel"
          @click="mode.cancel()"
        >
          <Ban /> {{ t('toolbar.cancel') }}
        </Button>

        <span class="text-[11px] text-muted-foreground" data-testid="wizard-state">
          {{ t(`wizard.state.${step.state}`) }}
        </span>

        <span class="flex-1" />

        <Button
          size="sm"
          variant="ghost"
          :disabled="isLast"
          :title="t('wizard.skip_hint')"
          data-testid="wizard-skip"
          @click="current = resultsIndex"
        >
          <FastForward /> {{ t('wizard.skip') }}
        </Button>
        <Button
          v-if="isLast"
          size="sm"
          :disabled="mode.exportRefs.value.length === 0"
          data-testid="wizard-export"
          @click="exportResults"
        >
          <Download /> {{ t('modes.export') }}
        </Button>
        <Button
          v-else
          size="sm"
          :disabled="!canAdvance"
          :title="canAdvance ? t('wizard.next') : t('wizard.next_blocked')"
          data-testid="wizard-next"
          @click="go(current + 1)"
        >
          {{ t('wizard.next') }} <ChevronRight />
        </Button>
      </div>
      <p
        v-if="exported"
        class="border-t px-2 py-1 text-[11px] text-muted-foreground"
        data-testid="wizard-exported"
      >
        {{ t('modes.exported', { dir: exported }) }}
      </p>
    </template>
  </div>
</template>
