<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { FileText } from '@lucide/vue'

import type { PreviewProps } from '@/previews/registry'

const props = defineProps<PreviewProps>()
const { t } = useI18n()

const data = computed(
  () => (props.summary['data'] as Record<string, unknown> | undefined) ?? props.summary,
)
const path = computed(() => (typeof data.value['path'] === 'string' ? data.value['path'] : ''))
const size = computed(() => (typeof data.value['size'] === 'number' ? data.value['size'] : 0))
const mime = computed(() => (typeof data.value['mime'] === 'string' ? data.value['mime'] : '—'))

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`
}
</script>

<template>
  <div
    class="flex items-center gap-2 rounded bg-muted px-2 py-1 text-[11px]"
    data-preview="file-chip"
  >
    <FileText class="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
    <div class="min-w-0">
      <p class="truncate font-mono" :title="path">{{ path }}</p>
      <p class="text-[10px] text-muted-foreground">
        {{ t('preview.file', { size: formatSize(size), mime }) }}
      </p>
    </div>
  </div>
</template>
