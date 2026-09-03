<script setup lang="ts">
/** Vue Flow node wrapper: typed handles, resizer and toolbar around the library-free NodeShell. */
import { computed, inject, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Handle, type NodeProps, Position } from '@vue-flow/core'
import { NodeResizer, type OnResizeStart } from '@vue-flow/node-resizer'
import { NodeToolbar } from '@vue-flow/node-toolbar'
import { Ban, Copy, Play, Trash2 } from '@lucide/vue'

import { CANVAS_LOD_KEY } from '@/canvas/CanvasAdapter'
import NodeShell, { type ShellPort } from '@/canvas/NodeShell.vue'
import { portStyle } from '@/canvas/ports'
import { useExecutionStore } from '@/stores/execution'
import { useNodesSchemaStore } from '@/stores/nodesSchema'
import { useSelectionStore } from '@/stores/selection'
import { useSessionStore } from '@/stores/session'
import { useWorkflowStore } from '@/stores/workflow'
import type { AstroNodeData } from './toFlow'

const props = defineProps<NodeProps<AstroNodeData>>()
// The node wrapper owns the DOM root; Vue Flow's slot listeners must not leak onto a fragment.
defineOptions({ inheritAttrs: false })

const { t } = useI18n()
const workflow = useWorkflowStore()
const schema = useNodesSchemaStore()
const execution = useExecutionStore()
const session = useSessionStore()
const selection = useSelectionStore()
const lod = inject(CANVAS_LOD_KEY, ref(false))

const node = computed(() => workflow.nodes[props.id])
const spec = computed(() => (node.value ? schema.byId[node.value.type] : undefined))
const exec = computed(() => execution.node(props.id))
const issues = computed(() => execution.issuesFor(props.id))
const singleSelected = computed(() => props.selected && selection.nodeIds.length === 1)

// Reconnecting clients get status snapshots but no summaries: ask for the done node's previews.
watch(
  () => [exec.value.state, spec.value?.id] as const,
  ([state]) => {
    if (state !== 'done' || !spec.value) return
    for (const port of spec.value.outputs) {
      if (!exec.value.summaries[port.name]) session.requestPreview(props.id, port.name)
    }
  },
  { immediate: true },
)

function handleStyle(port: ShellPort) {
  const style = portStyle(port.type)
  return { class: `ac-handle ac-glyph-${style.glyph}`, style: { '--ac-port': style.color } }
}

function onResizeEnd(event: OnResizeStart): void {
  const { x, y, width, height } = event.params
  const gid = workflow.groupOf(props.id)
  const [gx, gy] = (gid ? workflow.groups[gid]?.pos : undefined) ?? [0, 0]
  workflow.resizeNode(props.id, [Math.round(width), Math.round(height)], [x + gx, y + gy])
}

function runHere(): void {
  void session.run([props.id])
}

function duplicate(): void {
  const ids = workflow.duplicate([props.id])
  if (ids.length) selection.set(ids)
}

function remove(): void {
  workflow.removeNodes([props.id])
}

function toggleCollapse(): void {
  workflow.setUi(props.id, { collapsed: !(node.value?.ui?.collapsed === true) })
}
</script>

<template>
  <template v-if="node">
    <NodeResizer
      :is-visible="singleSelected && !lod"
      :min-width="200"
      :min-height="60"
      @resize-end="onResizeEnd"
    />
    <NodeToolbar :is-visible="singleSelected && !lod" :position="Position.Top" :offset="8">
      <div class="flex items-center gap-0.5 rounded-md border bg-popover p-0.5 shadow-sm">
        <button type="button" class="ac-toolbar-btn" :title="t('node.run_here')" @click="runHere">
          <Play class="size-3.5" />
        </button>
        <button
          type="button"
          class="ac-toolbar-btn"
          :title="node.disabled ? t('node.enable') : t('node.bypass')"
          :aria-pressed="node.disabled"
          @click="workflow.setDisabled(id, !node.disabled)"
        >
          <Ban class="size-3.5" />
        </button>
        <button
          type="button"
          class="ac-toolbar-btn"
          :title="t('node.duplicate')"
          @click="duplicate"
        >
          <Copy class="size-3.5" />
        </button>
        <button
          type="button"
          class="ac-toolbar-btn text-destructive"
          :title="t('node.delete')"
          @click="remove"
        >
          <Trash2 class="size-3.5" />
        </button>
      </div>
    </NodeToolbar>
    <NodeShell
      :node-id="id"
      :node="node"
      :spec="spec"
      :exec="exec"
      :issues="issues"
      :selected="selected"
      :lod="lod"
      @update-param="(name, value) => workflow.setParam(id, name, value)"
      @toggle-link="(name) => workflow.toggleLink(id, name)"
      @rename="(title) => workflow.setTitle(id, title)"
      @set-disabled="(disabled) => workflow.setDisabled(id, disabled)"
      @set-cost="(cost) => workflow.setCost(id, cost)"
      @run-here="runHere"
      @duplicate="duplicate"
      @delete="remove"
      @toggle-collapse="toggleCollapse"
    >
      <template #input-handle="{ port }">
        <Handle
          :id="port.name"
          type="target"
          :position="Position.Left"
          :connectable="connectable"
          v-bind="handleStyle(port)"
          :data-port-type="port.type"
        />
      </template>
      <template #output-handle="{ port }">
        <Handle
          :id="port.name"
          type="source"
          :position="Position.Right"
          :connectable="connectable"
          v-bind="handleStyle(port)"
          :data-port-type="port.type"
        />
      </template>
    </NodeShell>
  </template>
</template>

<style>
.ac-toolbar-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.5rem;
  height: 1.5rem;
  border-radius: calc(var(--radius) - 4px);
  color: var(--muted-foreground);
}
.ac-toolbar-btn:hover {
  background: var(--muted);
  color: var(--foreground);
}
</style>
