<script setup lang="ts">
/**
 * The confirmation step of every environment change (design §9): nothing is installed before the
 * resolution diff — what is added, upgraded, downgraded, removed — and any conflicts have been
 * shown. A plan with conflicts renders the resolver's reason and offers no confirm button at all.
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  DialogContent,
  DialogDescription,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
} from 'reka-ui'
import { ArrowDown, ArrowUp, Loader, Minus, Plus, TriangleAlert } from '@lucide/vue'

import type { ChangeAction, InstallPlan } from '@/api/types'
import { Button } from '@/components/ui/button'

const props = defineProps<{
  plan: InstallPlan | null
  busy?: boolean
}>()

const emit = defineEmits<{ confirm: []; cancel: [] }>()

const { t } = useI18n()

const open = computed(() => props.plan !== null)
const blocked = computed(() => props.plan !== null && !props.plan.ok)
const changes = computed(() => props.plan?.changes ?? [])
const empty = computed(() => props.plan?.ok === true && changes.value.length === 0)

/** Order the diff the way it reads: additions, upgrades, then anything that goes backwards. */
const ORDER: Record<ChangeAction, number> = {
  add: 0,
  upgrade: 1,
  reinstall: 2,
  downgrade: 3,
  remove: 4,
}
const sorted = computed(() =>
  [...changes.value].sort(
    (a, b) => ORDER[a.action] - ORDER[b.action] || a.name.localeCompare(b.name),
  ),
)

const counts = computed(() => {
  const out: Partial<Record<ChangeAction, number>> = {}
  for (const change of changes.value) out[change.action] = (out[change.action] ?? 0) + 1
  return out
})

/** Downgrades and removals are the ones worth a second look before confirming. */
const risky = computed(() =>
  changes.value.some((change) => change.action === 'downgrade' || change.action === 'remove'),
)
</script>

<template>
  <DialogRoot :open="open" @update:open="(value) => !value && emit('cancel')">
    <DialogPortal>
      <DialogOverlay class="fixed inset-0 z-50 bg-black/50" />
      <DialogContent
        class="fixed top-1/2 left-1/2 z-50 flex max-h-[80vh] w-[min(38rem,92vw)] -translate-x-1/2 -translate-y-1/2 flex-col gap-3 rounded-lg border bg-background p-4 shadow-xl"
        data-testid="plan-dialog"
        :data-blocked="blocked ? 'true' : 'false'"
        @escape-key-down="emit('cancel')"
      >
        <DialogTitle class="text-sm font-semibold">
          {{ blocked ? t('manager.plan.blocked_title') : t('manager.plan.title') }}
        </DialogTitle>
        <DialogDescription class="font-mono text-xs break-all text-muted-foreground">
          {{ plan?.source }}
        </DialogDescription>

        <div
          v-if="blocked"
          class="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-xs text-destructive"
          data-testid="plan-conflicts"
        >
          <p class="flex items-center gap-1 font-medium">
            <TriangleAlert class="size-3.5" /> {{ plan?.message }}
          </p>
          <ul v-if="plan?.conflicts?.length" class="mt-2 list-disc space-y-1 pl-4 font-mono">
            <li v-for="(conflict, index) in plan.conflicts" :key="index">{{ conflict }}</li>
          </ul>
          <p class="mt-2 text-muted-foreground">{{ t('manager.plan.blocked_hint') }}</p>
        </div>

        <p v-else-if="empty" class="text-xs text-muted-foreground" data-testid="plan-empty">
          {{ plan?.message || t('manager.plan.no_changes') }}
        </p>

        <template v-else>
          <div class="flex flex-wrap gap-2 text-[11px]" data-testid="plan-summary">
            <span
              v-if="counts.add"
              class="rounded bg-emerald-500/15 px-1.5 py-0.5 text-emerald-500"
            >
              {{ t('manager.plan.count_add', counts.add) }}
            </span>
            <span v-if="counts.upgrade" class="rounded bg-sky-500/15 px-1.5 py-0.5 text-sky-500">
              {{ t('manager.plan.count_upgrade', counts.upgrade) }}
            </span>
            <span
              v-if="counts.downgrade"
              class="rounded bg-amber-500/15 px-1.5 py-0.5 text-amber-500"
            >
              {{ t('manager.plan.count_downgrade', counts.downgrade) }}
            </span>
            <span
              v-if="counts.remove"
              class="rounded bg-destructive/15 px-1.5 py-0.5 text-destructive"
            >
              {{ t('manager.plan.count_remove', counts.remove) }}
            </span>
          </div>

          <ul class="min-h-0 flex-1 overflow-auto rounded-md border font-mono text-xs">
            <li
              v-for="change in sorted"
              :key="change.name"
              class="flex items-center gap-2 border-b px-2 py-1 last:border-b-0"
              :data-testid="`plan-change-${change.name}`"
              :data-action="change.action"
            >
              <Plus v-if="change.action === 'add'" class="size-3 text-emerald-500" />
              <ArrowUp v-else-if="change.action === 'upgrade'" class="size-3 text-sky-500" />
              <ArrowDown v-else-if="change.action === 'downgrade'" class="size-3 text-amber-500" />
              <Minus v-else class="size-3 text-destructive" />
              <span class="flex-1">{{ change.name }}</span>
              <span v-if="change.from_version" class="text-muted-foreground line-through">
                {{ change.from_version }}
              </span>
              <span v-if="change.to_version">{{ change.to_version }}</span>
            </li>
          </ul>

          <p v-if="risky" class="text-[11px] text-amber-500" data-testid="plan-risky">
            {{ t('manager.plan.risky_hint') }}
          </p>
        </template>

        <details v-if="plan?.output" class="text-[11px] text-muted-foreground">
          <summary class="cursor-pointer">{{ t('manager.plan.details') }}</summary>
          <pre class="mt-1 max-h-40 overflow-auto rounded bg-muted p-2 whitespace-pre-wrap">{{
            plan.output
          }}</pre>
        </details>

        <div class="flex justify-end gap-2">
          <Button variant="ghost" size="sm" data-testid="plan-cancel" @click="emit('cancel')">
            {{ t('common.cancel') }}
          </Button>
          <Button
            v-if="!blocked && !empty"
            size="sm"
            :disabled="busy"
            data-testid="plan-confirm"
            @click="emit('confirm')"
          >
            <Loader v-if="busy" class="animate-spin" />
            {{ t('manager.plan.confirm') }}
          </Button>
        </div>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>
