<script setup lang="ts">
/**
 * The red banner an imported workflow with unreviewed Python opens under (design §7.2).
 *
 * It reads the same `quarantined` compile issues the nodes show, so it appears and disappears
 * with the gate itself: trusting the last snippet clears it, editing one brings it back.
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ShieldAlert } from '@lucide/vue'

import { Button } from '@/components/ui/button'
import { useExecutionStore } from '@/stores/execution'
import TrustDialog from './TrustDialog.vue'

const { t } = useI18n()
const execution = useExecutionStore()

const dialogOpen = ref(false)

/** Node ids the compiler reported a `quarantined` issue for. */
const blocked = computed(() =>
  Object.entries(execution.issues)
    .filter(([, issues]) => issues.some((issue) => issue.code === 'quarantined'))
    .map(([nodeId]) => nodeId),
)
</script>

<template>
  <div
    v-if="blocked.length"
    class="flex items-center gap-2 border-b border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive"
    role="alert"
    data-testid="quarantine-banner"
    :data-nodes="blocked.length"
  >
    <ShieldAlert class="size-4 shrink-0" />
    <span class="flex-1">{{ t('trust.banner') }}</span>
    <Button size="xs" data-testid="quarantine-review" @click="dialogOpen = true">
      {{ t('trust.review') }}
    </Button>
  </div>
  <TrustDialog :open="dialogOpen" @close="dialogOpen = false" />
</template>
