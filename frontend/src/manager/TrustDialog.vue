<script setup lang="ts">
/**
 * The trust gate's review step (design §7.2, §11): every Python snippet in the open workflow,
 * with its source, so the user reads what they are about to run before they enable it.
 *
 * Decisions are stored by snippet hash, not by node — trusting a snippet enables every node that
 * carries it, and editing one changes its hash, so the gate closes again on its own.
 */
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from 'reka-ui'
import { CircleCheck, ShieldAlert, ShieldX } from '@lucide/vue'

import { api } from '@/api/client'
import type { CodeSnippet, TrustReview } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { usePacksStore } from '@/stores/packs'
import { useSessionStore } from '@/stores/session'
import { useWorkflowStore } from '@/stores/workflow'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: [] }>()

const { t } = useI18n()
const workflow = useWorkflowStore()
const packs = usePacksStore()
const session = useSessionStore()

const review = ref<TrustReview | null>(null)
const busy = ref(false)

const snippets = computed<CodeSnippet[]>(() => review.value?.snippets ?? [])
const untrusted = computed(() => snippets.value.filter((s) => s.decision !== 'trusted'))

async function load(): Promise<void> {
  const id = workflow.id
  if (!id) return
  try {
    review.value = await api.getWorkflowTrust(id)
  } catch {
    review.value = null
  }
}

watch(
  () => [props.open, workflow.id],
  ([isOpen]) => {
    if (isOpen) void load()
  },
  { immediate: true },
)

async function decide(snippet: CodeSnippet, decision: 'trusted' | 'blocked'): Promise<void> {
  busy.value = true
  try {
    await packs.decide(snippet.hash, decision)
    await load()
    if (workflow.id) await session.refreshStatus(workflow.id)
  } finally {
    busy.value = false
  }
}

async function forget(snippet: CodeSnippet): Promise<void> {
  busy.value = true
  try {
    await packs.forget(snippet.hash)
    await load()
    if (workflow.id) await session.refreshStatus(workflow.id)
  } finally {
    busy.value = false
  }
}

async function trustAll(): Promise<void> {
  for (const snippet of untrusted.value) await decide(snippet, 'trusted')
}
</script>

<template>
  <DialogRoot :open="open" @update:open="(value) => !value && emit('close')">
    <DialogPortal>
      <DialogOverlay class="fixed inset-0 z-50 bg-black/50" />
      <DialogContent
        class="fixed top-1/2 left-1/2 z-50 flex max-h-[85vh] w-[min(46rem,94vw)] -translate-x-1/2 -translate-y-1/2 flex-col gap-3 rounded-lg border bg-background p-4 shadow-xl"
        data-testid="trust-dialog"
        @escape-key-down="emit('close')"
      >
        <DialogTitle class="flex items-center gap-2 text-sm font-semibold">
          <ShieldAlert class="size-4 text-amber-500" /> {{ t('trust.title') }}
        </DialogTitle>
        <DialogDescription class="text-xs text-muted-foreground">
          {{ t('trust.hint') }}
        </DialogDescription>

        <p
          v-if="snippets.length === 0"
          class="p-6 text-center text-xs text-muted-foreground"
          data-testid="trust-empty"
        >
          {{ t('trust.empty') }}
        </p>

        <ul v-else class="min-h-0 flex-1 space-y-3 overflow-auto" role="list">
          <li
            v-for="snippet in snippets"
            :key="snippet.node"
            class="rounded-lg border"
            :data-testid="`trust-snippet-${snippet.node}`"
            :data-decision="snippet.decision ?? 'none'"
          >
            <div class="flex items-center gap-2 border-b px-3 py-2 text-xs">
              <span class="font-medium">{{ snippet.title || snippet.node }}</span>
              <Badge variant="outline">{{ t('trust.lines', snippet.lines) }}</Badge>
              <Badge v-if="snippet.decision === 'trusted'" variant="secondary">
                {{ t('trust.trusted') }}
              </Badge>
              <Badge v-else-if="snippet.decision === 'blocked'" variant="destructive">
                {{ t('trust.blocked') }}
              </Badge>
              <Badge v-else variant="outline">{{ t('trust.untrusted') }}</Badge>
              <span class="flex-1" />
              <span class="font-mono text-[10px] text-muted-foreground">
                {{ snippet.hash.slice(0, 12) }}
              </span>
            </div>
            <pre
              class="max-h-56 overflow-auto px-3 py-2 text-[11px] whitespace-pre-wrap"
              :data-testid="`trust-source-${snippet.node}`"
              >{{ snippet.source }}</pre>
            <div class="flex gap-1 border-t px-3 py-2">
              <Button
                size="xs"
                :disabled="busy || snippet.decision === 'trusted'"
                :data-testid="`trust-accept-${snippet.node}`"
                @click="decide(snippet, 'trusted')"
              >
                <CircleCheck /> {{ t('trust.trust') }}
              </Button>
              <Button
                size="xs"
                variant="ghost"
                :disabled="busy || snippet.decision === 'blocked'"
                :data-testid="`trust-block-${snippet.node}`"
                @click="decide(snippet, 'blocked')"
              >
                <ShieldX /> {{ t('trust.block') }}
              </Button>
              <Button
                v-if="snippet.decision"
                size="xs"
                variant="ghost"
                :disabled="busy"
                :data-testid="`trust-forget-${snippet.node}`"
                @click="forget(snippet)"
              >
                {{ t('trust.forget') }}
              </Button>
            </div>
          </li>
        </ul>

        <div class="flex items-center gap-2">
          <p
            v-if="untrusted.length === 0 && snippets.length"
            class="flex-1 text-xs text-emerald-700 dark:text-emerald-400"
          >
            {{ t('trust.done') }}
          </p>
          <span v-else class="flex-1" />
          <Button
            v-if="untrusted.length > 1"
            size="sm"
            variant="ghost"
            :disabled="busy"
            data-testid="trust-all"
            @click="trustAll"
          >
            {{ t('trust.trust_all') }}
          </Button>
          <Button size="sm" data-testid="trust-close" @click="emit('close')">
            {{ t('common.close') }}
          </Button>
        </div>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>
