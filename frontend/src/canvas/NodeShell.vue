<script setup lang="ts">
/**
 * Node anatomy (design §8.2): header (icon, editable title, menu), typed ports, params via
 * AutoForm, preview slot, footer (timing, cache glyph), status stripe + badge, error popover.
 * Library-agnostic: the canvas implementation supplies the port handles through slots.
 */
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuPortal,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuRoot,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
  PopoverContent,
  PopoverPortal,
  PopoverRoot,
  PopoverTrigger,
} from 'reka-ui'
import {
  Ban,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  Copy,
  MoreHorizontal,
  Pencil,
  PencilRuler,
  Play,
  RefreshCw,
  Trash2,
  Unlink,
  Zap,
} from '@lucide/vue'

import type { NodeDoc, NodeIssue, NodeSpec, ParamSpec, PortSpec } from '@/api/types'
import { portStyle, typeLabel } from '@/canvas/ports'
import { AutoForm } from '@/nodes'
import type { NodeExecution } from '@/stores/execution'

export interface ShellPort {
  name: string
  type: string
  label: string
  /** True for params converted to input ports. */
  linked: boolean
  required: boolean
}

const props = defineProps<{
  nodeId: string
  node: NodeDoc
  spec: NodeSpec | undefined
  exec: NodeExecution
  issues: NodeIssue[]
  selected: boolean
  lod: boolean
}>()

const emit = defineEmits<{
  'update-param': [name: string, value: unknown]
  'toggle-link': [name: string]
  rename: [title: string | null]
  'set-disabled': [disabled: boolean]
  'set-cost': [cost: NodeDoc['cost']]
  'run-here': []
  duplicate: []
  delete: []
  'toggle-collapse': []
  'open-editor': []
}>()

defineSlots<{
  'input-handle'(props: { port: ShellPort }): unknown
  'output-handle'(props: { port: ShellPort }): unknown
  preview(props: { exec: NodeExecution; spec: NodeSpec | undefined }): unknown
}>()

const { t } = useI18n()

const title = computed(() => props.node.title ?? props.spec?.name ?? props.node.type)
const collapsed = computed(() => props.node.ui?.collapsed === true)
const linked = computed(() => props.node.linked ?? [])

const inputs = computed<ShellPort[]>(() => {
  const spec = props.spec
  if (!spec) return []
  const declared = spec.inputs.map((p: PortSpec) => ({
    name: p.name,
    type: p.type,
    label: p.name,
    linked: false,
    required: p.required,
  }))
  const fromParams = spec.params
    .filter((p: ParamSpec) => linked.value.includes(p.name))
    .map((p) => ({
      name: p.name,
      type: p.link_type,
      label: p.label,
      linked: true,
      required: false,
    }))
  return [...declared, ...fromParams]
})

const outputs = computed<ShellPort[]>(
  () =>
    props.spec?.outputs.map((p) => ({
      name: p.name,
      type: p.type,
      label: p.name,
      linked: false,
      required: false,
    })) ?? [],
)

const formParams = computed(
  () => props.spec?.params.filter((p) => !linked.value.includes(p.name)) ?? [],
)
const paramIssues = computed(() => props.issues.filter((i) => i.param))
const nodeIssues = computed(() => props.issues.filter((i) => !i.param))

const accentType = computed(() => outputs.value[0]?.type ?? inputs.value[0]?.type ?? 'astro.Any')
const accent = computed(() => portStyle(accentType.value))

const stateKey = computed(() => {
  if (props.node.disabled) return 'bypassed'
  if (props.exec.state === 'dirty' && props.exec.stale) return 'stale'
  return props.exec.state
})
const showBadge = computed(() => stateKey.value !== 'idle')
const hasIssues = computed(() => props.issues.length > 0)

const costLabel = computed(() => props.node.cost ?? 'default')

const summaryChips = computed(() => {
  const chips: { port: string; text: string }[] = []
  for (const [port, entry] of Object.entries(props.exec.summaries)) {
    // Scalar summaries are `{type, data: {value}}` (see `PortType.summary`).
    const data = (entry.summary as { data?: { value?: unknown } }).data
    const value = data?.value
    let text: string
    if (port === '$preview') text = JSON.stringify(entry.summary).slice(0, 60)
    else if (value !== undefined && (typeof value !== 'object' || value === null))
      text = formatScalar(value)
    else text = typeLabel(entry.typeId)
    chips.push({ port, text })
  }
  return chips
})

function formatScalar(value: unknown): string {
  if (typeof value === 'number') {
    return Number.isInteger(value) ? String(value) : value.toPrecision(6).replace(/\.?0+$/, '')
  }
  return String(value)
}

// --- title editing -----------------------------------------------------------------------------

const editing = ref(false)
const draft = ref('')
const titleInput = ref<HTMLInputElement | null>(null)

function startRename(): void {
  draft.value = props.node.title ?? ''
  editing.value = true
  void nextTick(() => titleInput.value?.select())
}

function commitRename(): void {
  if (!editing.value) return
  editing.value = false
  const next = draft.value.trim()
  if (next !== (props.node.title ?? '')) emit('rename', next || null)
}

function cancelRename(): void {
  editing.value = false
}

watch(
  () => props.selected,
  (selected) => {
    if (!selected) cancelRename()
  },
)

const errorOpen = ref(false)
</script>

<template>
  <div
    class="ac-node relative flex min-w-[200px] flex-col rounded-lg border bg-card text-card-foreground shadow-sm"
    :class="{ 'opacity-60': node.disabled }"
    :data-node-id="nodeId"
    :data-state="stateKey"
    :data-testid="`node-${nodeId}`"
  >
    <span class="ac-node__stripe" :data-state="stateKey" aria-hidden="true" />
    <span
      v-if="exec.state === 'running'"
      class="ac-node__progress"
      :style="{ width: `${Math.round((exec.progress?.frac ?? 0.15) * 100)}%` }"
      aria-hidden="true"
    />

    <header
      class="flex h-8 items-center gap-1.5 rounded-t-lg border-b bg-muted/40 pr-1 pl-3"
      @dblclick.stop="startRename"
    >
      <span
        class="size-2 shrink-0 rounded-full"
        :style="{ background: accent.color }"
        :title="typeLabel(accentType)"
        aria-hidden="true"
      />
      <input
        v-if="editing"
        ref="titleInput"
        v-model="draft"
        class="nodrag h-6 min-w-0 flex-1 rounded border bg-background px-1 text-xs"
        :aria-label="t('node.rename')"
        @keydown.enter.prevent="commitRename"
        @keydown.escape.prevent="cancelRename"
        @blur="commitRename"
      />
      <span v-else class="min-w-0 flex-1 truncate text-xs font-semibold" :title="node.type">
        {{ title }}
      </span>

      <button
        v-if="spec?.editor"
        type="button"
        class="nodrag inline-flex size-6 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-foreground"
        :title="t('node.open_editor')"
        :aria-label="t('node.open_editor')"
        data-testid="node-editor"
        @click.stop="emit('open-editor')"
      >
        <PencilRuler class="size-3.5" />
      </button>

      <span
        v-if="showBadge"
        class="ac-badge shrink-0 rounded px-1.5 py-px text-[10px] font-medium uppercase tracking-wide"
        :data-state="stateKey"
        data-testid="status-badge"
      >
        <RefreshCw
          v-if="exec.cacheHit && exec.state === 'done'"
          class="inline size-2.5"
          aria-hidden="true"
        />
        {{ t(`node.state.${stateKey}`) }}
      </span>

      <PopoverRoot v-if="exec.error || hasIssues" v-model:open="errorOpen">
        <PopoverTrigger
          class="nodrag inline-flex size-6 items-center justify-center rounded text-destructive hover:bg-destructive/10"
          :aria-label="t('node.show_error')"
          data-testid="error-trigger"
        >
          <CircleAlert class="size-3.5" />
        </PopoverTrigger>
        <PopoverPortal>
          <PopoverContent
            side="bottom"
            :side-offset="6"
            class="nodrag nowheel z-50 max-h-80 w-96 overflow-auto rounded-md border bg-popover p-3 text-xs text-popover-foreground shadow-md"
            data-testid="error-detail"
          >
            <ul v-if="issues.length" class="mb-2 space-y-1">
              <li v-for="(issue, i) in issues" :key="i" class="flex gap-2">
                <code class="shrink-0 rounded bg-muted px-1 text-[10px]">{{ issue.code }}</code>
                <span>{{ issue.message }}</span>
              </li>
            </ul>
            <template v-if="exec.error">
              <p class="font-medium text-destructive">{{ exec.error.message }}</p>
              <p v-if="exec.error.hint" class="mt-1 text-muted-foreground">
                {{ t('node.hint', { hint: exec.error.hint }) }}
              </p>
              <pre
                v-if="exec.error.traceback"
                class="mt-2 max-h-48 overflow-auto rounded bg-muted p-2 font-mono text-[10px] leading-snug whitespace-pre-wrap"
                >{{ exec.error.traceback }}</pre>
            </template>
          </PopoverContent>
        </PopoverPortal>
      </PopoverRoot>

      <DropdownMenuRoot>
        <DropdownMenuTrigger
          class="nodrag inline-flex size-6 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-foreground"
          :aria-label="t('node.menu')"
          data-testid="node-menu"
        >
          <MoreHorizontal class="size-3.5" />
        </DropdownMenuTrigger>
        <DropdownMenuPortal>
          <DropdownMenuContent
            side="bottom"
            align="end"
            :side-offset="4"
            class="ac-menu nodrag z-50 min-w-44 rounded-md border bg-popover p-1 text-xs text-popover-foreground shadow-md"
          >
            <DropdownMenuItem class="ac-menu-item" @select="startRename">
              <Pencil class="size-3.5" /> {{ t('node.rename') }}
            </DropdownMenuItem>
            <DropdownMenuItem
              v-if="spec?.editor"
              class="ac-menu-item"
              data-testid="node-menu-editor"
              @select="emit('open-editor')"
            >
              <PencilRuler class="size-3.5" /> {{ t('node.open_editor') }}
            </DropdownMenuItem>
            <DropdownMenuItem class="ac-menu-item" @select="emit('set-disabled', !node.disabled)">
              <Ban class="size-3.5" /> {{ node.disabled ? t('node.enable') : t('node.bypass') }}
            </DropdownMenuItem>
            <DropdownMenuSub>
              <DropdownMenuSubTrigger class="ac-menu-item">
                <Zap class="size-3.5" />
                {{ t('node.cost.label', { cost: t(`node.cost.${costLabel}`) }) }}
                <ChevronRight class="ml-auto size-3.5" />
              </DropdownMenuSubTrigger>
              <DropdownMenuPortal>
                <DropdownMenuSubContent
                  class="ac-menu nodrag z-50 min-w-36 rounded-md border bg-popover p-1 text-xs shadow-md"
                >
                  <DropdownMenuRadioGroup
                    :model-value="costLabel"
                    @update:model-value="
                      (value) =>
                        emit('set-cost', value === 'default' ? null : (value as NodeDoc['cost']))
                    "
                  >
                    <DropdownMenuRadioItem
                      v-for="option in ['default', 'cheap', 'expensive', 'auto']"
                      :key="option"
                      :value="option"
                      class="ac-menu-item data-[state=checked]:font-semibold"
                    >
                      {{ t(`node.cost.${option}`) }}
                    </DropdownMenuRadioItem>
                  </DropdownMenuRadioGroup>
                </DropdownMenuSubContent>
              </DropdownMenuPortal>
            </DropdownMenuSub>
            <DropdownMenuItem class="ac-menu-item" @select="emit('toggle-collapse')">
              <ChevronDown class="size-3.5" />
              {{ collapsed ? t('node.expand') : t('node.collapse') }}
            </DropdownMenuItem>
            <DropdownMenuSeparator class="my-1 h-px bg-border" />
            <DropdownMenuItem class="ac-menu-item" @select="emit('run-here')">
              <Play class="size-3.5" /> {{ t('node.run_here') }}
            </DropdownMenuItem>
            <DropdownMenuItem class="ac-menu-item" @select="emit('duplicate')">
              <Copy class="size-3.5" /> {{ t('node.duplicate') }}
            </DropdownMenuItem>
            <DropdownMenuSeparator class="my-1 h-px bg-border" />
            <DropdownMenuItem class="ac-menu-item text-destructive" @select="emit('delete')">
              <Trash2 class="size-3.5" /> {{ t('node.delete') }}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenuPortal>
      </DropdownMenuRoot>
    </header>

    <!-- Ports: handles live at the row edges (slots), labels inside. -->
    <div v-if="inputs.length || outputs.length" class="grid grid-cols-2 gap-x-2 py-1.5">
      <ul class="min-w-0 space-y-0.5">
        <li
          v-for="port in inputs"
          :key="port.name"
          class="relative flex h-5 items-center gap-1 pl-3 text-[11px]"
          :data-port="port.name"
        >
          <slot name="input-handle" :port="port" />
          <span class="truncate" :title="typeLabel(port.type)">{{ port.label }}</span>
          <span v-if="port.required" class="text-destructive" aria-hidden="true">*</span>
          <button
            v-if="port.linked"
            type="button"
            class="nodrag inline-flex size-4 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-foreground"
            :aria-label="t('node.unlink_param', { param: port.label })"
            @click="emit('toggle-link', port.name)"
          >
            <Unlink class="size-3" />
          </button>
        </li>
      </ul>
      <ul class="min-w-0 space-y-0.5">
        <li
          v-for="port in outputs"
          :key="port.name"
          class="relative flex h-5 items-center justify-end gap-1 pr-3 text-[11px]"
          :data-port="port.name"
        >
          <span class="truncate" :title="typeLabel(port.type)">{{ port.label }}</span>
          <slot name="output-handle" :port="port" />
        </li>
      </ul>
    </div>

    <template v-if="!lod && !collapsed">
      <div v-if="formParams.length" class="border-t px-2 py-1.5">
        <AutoForm
          :params="formParams"
          :values="node.params ?? {}"
          :issues="paramIssues"
          :id-prefix="`p-${nodeId}`"
          compact
          :disabled="node.disabled"
          @update="(name, value) => emit('update-param', name, value)"
          @toggle-link="(name) => emit('toggle-link', name)"
        />
      </div>

      <div v-if="nodeIssues.length" class="border-t px-3 py-1 text-[11px] text-destructive">
        <p v-for="(issue, i) in nodeIssues" :key="i">{{ issue.message }}</p>
      </div>

      <div class="ac-node__preview border-t px-2 py-1.5" data-testid="preview">
        <slot name="preview" :exec="exec" :spec="spec">
          <div v-if="summaryChips.length" class="flex flex-wrap gap-1">
            <span
              v-for="chip in summaryChips"
              :key="chip.port"
              class="inline-flex max-w-full items-center gap-1 rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]"
              :data-summary-port="chip.port"
            >
              <span class="text-muted-foreground">{{ chip.port }}</span>
              <span class="truncate">{{ chip.text }}</span>
            </span>
          </div>
          <p v-else class="text-[11px] text-muted-foreground">
            {{ t('node.preview_placeholder') }}
          </p>
        </slot>
      </div>

      <p
        v-if="node.notes"
        class="border-t px-3 py-1 text-[11px] whitespace-pre-wrap text-muted-foreground"
      >
        {{ node.notes }}
      </p>
    </template>

    <footer
      v-if="!lod"
      class="flex h-6 items-center gap-2 rounded-b-lg border-t px-2 text-[10px] text-muted-foreground"
    >
      <button
        type="button"
        class="nodrag inline-flex items-center gap-1 rounded px-1 hover:bg-muted hover:text-foreground"
        @click="emit('run-here')"
      >
        <Play class="size-3" /> {{ t('node.run_here') }}
      </button>
      <span class="ml-auto inline-flex items-center gap-1" data-testid="timing">
        <RefreshCw
          v-if="exec.cacheHit"
          class="size-3"
          :aria-label="t('node.cache_hit')"
          :title="t('node.cache_hit')"
        />
        <span v-if="exec.elapsedMs !== null">{{
          t('node.elapsed', { ms: Math.round(exec.elapsedMs) })
        }}</span>
        <span v-if="exec.costClass === 'expensive'" :title="t('node.cost.expensive')">
          <Zap class="size-3" />
        </span>
      </span>
    </footer>
  </div>
</template>

<style>
.ac-node__stripe {
  position: absolute;
  left: 0;
  top: 6px;
  bottom: 6px;
  width: 3px;
  border-radius: 2px;
  background: transparent;
}
.ac-node__stripe[data-state='dirty'],
.ac-node__stripe[data-state='stale'] {
  background: var(--ac-status-dirty);
}
.ac-node__stripe[data-state='queued'],
.ac-node__stripe[data-state='cancelled'] {
  background: var(--ac-status-queued);
}
.ac-node__stripe[data-state='running'] {
  background: var(--ac-status-running);
}
.ac-node__stripe[data-state='done'] {
  background: var(--ac-status-done);
}
.ac-node__stripe[data-state='error'] {
  background: var(--ac-status-error);
}
.ac-node__progress {
  position: absolute;
  left: 0;
  top: 0;
  height: 2px;
  background: var(--ac-status-running);
  border-top-left-radius: 8px;
  transition: width 200ms ease-out;
}
.ac-badge {
  background: var(--muted);
  color: var(--muted-foreground);
}
.ac-badge[data-state='dirty'],
.ac-badge[data-state='stale'] {
  background: color-mix(in oklab, var(--ac-status-dirty) 20%, transparent);
  color: var(--ac-status-dirty);
}
.ac-badge[data-state='running'] {
  background: color-mix(in oklab, var(--ac-status-running) 18%, transparent);
  color: var(--ac-status-running);
}
.ac-badge[data-state='done'] {
  background: color-mix(in oklab, var(--ac-status-done) 18%, transparent);
  color: var(--ac-status-done);
}
.ac-badge[data-state='error'] {
  background: color-mix(in oklab, var(--ac-status-error) 18%, transparent);
  color: var(--ac-status-error);
}
.ac-menu-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.3rem 0.5rem;
  border-radius: calc(var(--radius) - 4px);
  cursor: default;
  outline: none;
  user-select: none;
}
.ac-menu-item[data-highlighted] {
  background: var(--accent);
  color: var(--accent-foreground);
}
</style>
