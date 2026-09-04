<script setup lang="ts">
/**
 * Export the open workflow as a `.acw` bundle (design §7.2).
 *
 * The three choices that actually change what travels: how big an input file may be before it is
 * carried as a hash instead of a copy, which outputs to include, and whether to render preview
 * images. The result stays in the workspace (`bundles/…`) so it sits next to the data it
 * describes; the download link is for sending it somewhere else.
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from 'reka-ui'
import { Download, Loader, Package } from '@lucide/vue'

import { api } from '@/api/client'
import type { BundleManifest } from '@/api/types'
import { Button } from '@/components/ui/button'
import { useUiStore } from '@/stores/ui'
import { useWorkflowStore } from '@/stores/workflow'

defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: [] }>()

const { t } = useI18n()
const workflow = useWorkflowStore()
const ui = useUiStore()

const embedMb = ref(200)
const includeOutputs = ref<'leaves' | 'all' | 'none'>('leaves')
const includeFigures = ref(true)
const busy = ref(false)
const manifest = ref<BundleManifest | null>(null)

const OUTPUT_CHOICES = ['leaves', 'all', 'none'] as const

/** "3 inputs · 2 outputs · 4 figures", without leaning on optional wire fields. */
const counts = computed(() => ({
  inputs: t('bundle.count_inputs', manifest.value?.inputs?.length ?? 0),
  outputs: t('bundle.count_outputs', manifest.value?.outputs?.length ?? 0),
  figures: t('bundle.count_figures', manifest.value?.figures?.length ?? 0),
}))

const size = computed(() => {
  const bytes = manifest.value?.bytes ?? 0
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} kB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
})

async function run(): Promise<void> {
  const id = workflow.id
  if (!id) return
  busy.value = true
  manifest.value = null
  try {
    manifest.value = await api.exportBundle({
      workflow_id: id,
      embed_inputs_max_mb: Math.max(0, Math.round(embedMb.value)),
      include_outputs: includeOutputs.value,
      include_figures: includeFigures.value,
    })
    ui.notify(t('bundle.exported', { path: manifest.value.path, size: size.value }))
  } catch (error) {
    ui.notify(error instanceof Error ? error.message : String(error), 'error')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <DialogRoot :open="open" @update:open="(value) => !value && emit('close')">
    <DialogPortal>
      <DialogOverlay class="fixed inset-0 z-50 bg-black/50" />
      <DialogContent
        class="fixed top-1/2 left-1/2 z-50 flex w-[min(32rem,92vw)] -translate-x-1/2 -translate-y-1/2 flex-col gap-3 rounded-lg border bg-background p-4 shadow-xl"
        data-testid="bundle-dialog"
        @escape-key-down="emit('close')"
      >
        <DialogTitle class="flex items-center gap-2 text-sm font-semibold">
          <Package class="size-4" /> {{ t('bundle.export_title') }}
        </DialogTitle>
        <DialogDescription class="text-xs text-muted-foreground">
          {{ t('bundle.export_hint') }}
        </DialogDescription>

        <label class="flex items-center gap-2 text-xs">
          <span class="flex-1">{{ t('bundle.embed_inputs') }}</span>
          <input
            v-model.number="embedMb"
            type="number"
            min="0"
            step="10"
            class="h-7 w-24 rounded-md border bg-background px-2 text-right text-xs"
            data-testid="bundle-embed-mb"
          />
          <span class="text-muted-foreground">{{ t('bundle.megabytes') }}</span>
        </label>

        <fieldset class="text-xs">
          <legend class="mb-1">{{ t('bundle.outputs') }}</legend>
          <div class="flex gap-1">
            <Button
              v-for="choice in OUTPUT_CHOICES"
              :key="choice"
              size="xs"
              :variant="includeOutputs === choice ? 'secondary' : 'ghost'"
              :aria-pressed="includeOutputs === choice"
              :data-testid="`bundle-outputs-${choice}`"
              @click="includeOutputs = choice"
            >
              {{ t(`bundle.outputs_${choice}`) }}
            </Button>
          </div>
        </fieldset>

        <label class="flex items-center gap-2 text-xs">
          <input v-model="includeFigures" type="checkbox" data-testid="bundle-figures" />
          {{ t('bundle.figures') }}
        </label>

        <div
          v-if="manifest"
          class="rounded-md border bg-muted/40 p-2 text-[11px]"
          data-testid="bundle-result"
        >
          <p class="font-mono break-all">{{ manifest.path }} · {{ size }}</p>
          <p class="mt-1 text-muted-foreground">
            {{ counts.inputs }} · {{ counts.outputs }} · {{ counts.figures }}
          </p>
          <a
            class="mt-1 inline-flex items-center gap-1 underline"
            :href="api.bundleUrl(manifest.path)"
            :download="manifest.path.split('/').pop()"
            data-testid="bundle-download"
          >
            <Download class="size-3" /> {{ t('bundle.download') }}
          </a>
        </div>

        <div class="flex justify-end gap-2">
          <Button variant="ghost" size="sm" data-testid="bundle-close" @click="emit('close')">
            {{ t('common.close') }}
          </Button>
          <Button
            size="sm"
            :disabled="busy || !workflow.isOpen"
            data-testid="bundle-export"
            @click="run"
          >
            <Loader v-if="busy" class="animate-spin" />
            <Package v-else />
            {{ t('bundle.export') }}
          </Button>
        </div>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>
