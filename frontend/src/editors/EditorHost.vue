<script setup lang="ts">
/**
 * Mounts the expandable editor of the node in `ui.editor` (design §8.3). Editors open in a
 * centred modal by default; a setting persisted in localStorage docks them as a sheet on the
 * right instead. Every editor writes back through the workflow store only.
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from 'reka-ui'
import { PanelRight, Square, X } from '@lucide/vue'

import { useNodesSchemaStore } from '@/stores/nodesSchema'
import { useUiStore } from '@/stores/ui'
import { useWorkflowStore } from '@/stores/workflow'

import { editorComponent, editorFor } from './registry'

const { t } = useI18n()
const ui = useUiStore()
const schema = useNodesSchemaStore()
const workflow = useWorkflowStore()

const target = computed(() => ui.editor)
const node = computed(() => (target.value ? workflow.nodes[target.value.nodeId] : undefined))
const spec = computed(() => (node.value ? schema.byId[node.value.type] : undefined))
const editorId = computed(() => editorFor(spec.value))
const open = computed(
  () => target.value !== null && editorId.value !== null && spec.value !== undefined,
)
const title = computed(() =>
  target.value
    ? t('editor.title', {
        node: node.value?.title ?? spec.value?.name ?? target.value.nodeId,
        editor: editorId.value ? t(`editor.names.${editorId.value}`) : '',
      })
    : '',
)
const sheet = computed(() => ui.editorPlacement === 'sheet')

function close(): void {
  ui.closeEditor()
}

function togglePlacement(): void {
  ui.setEditorPlacement(sheet.value ? 'modal' : 'sheet')
}
</script>

<template>
  <DialogRoot :open="open" @update:open="(value) => !value && close()">
    <DialogPortal>
      <DialogOverlay v-if="!sheet" class="fixed inset-0 z-40 bg-black/40" />
      <DialogContent
        class="fixed z-50 flex flex-col rounded-lg border bg-background shadow-xl focus:outline-none"
        :class="
          sheet ? 'inset-y-2 right-2 w-[min(960px,92vw)]' : 'inset-4 md:inset-x-16 md:inset-y-10'
        "
        data-testid="editor"
        :data-editor="editorId ?? undefined"
        :data-placement="ui.editorPlacement"
        @escape-key-down="close"
      >
        <header class="flex h-10 items-center gap-2 border-b px-3">
          <DialogTitle class="min-w-0 flex-1 truncate text-sm font-semibold">{{
            title
          }}</DialogTitle>
          <DialogDescription class="sr-only">{{ spec?.description }}</DialogDescription>
          <button
            type="button"
            class="inline-flex h-7 items-center gap-1 rounded border px-2 text-xs hover:bg-muted"
            :title="sheet ? t('editor.placement.modal') : t('editor.placement.sheet')"
            data-testid="editor-placement"
            @click="togglePlacement"
          >
            <Square v-if="sheet" class="size-3.5" />
            <PanelRight v-else class="size-3.5" />
            {{ sheet ? t('editor.placement.modal') : t('editor.placement.sheet') }}
          </button>
          <DialogClose
            class="inline-flex size-7 items-center justify-center rounded hover:bg-muted"
            :aria-label="t('editor.close')"
            data-testid="editor-close"
          >
            <X class="size-4" />
          </DialogClose>
        </header>
        <div class="min-h-0 flex-1 p-3">
          <component
            :is="editorComponent(editorId)"
            v-if="editorId && spec && target"
            :key="target.nodeId"
            :node-id="target.nodeId"
            :spec="spec"
            @close="close"
          />
        </div>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>
