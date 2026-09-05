<script setup lang="ts">
/**
 * The four things a user has to be told about, wherever they are in the app (phase 13, item 4).
 *
 * A toast is the wrong shape for any of them: they are *states*, not events, and three of the
 * four have an action attached. So they sit under the header as a strip of banners that stay
 * until the state clears, ordered by how much they stop you doing:
 *
 * 1. the connection dropped — nothing will update until it comes back;
 * 2. the workspace folder is gone — no file will open;
 * 3. a node pack failed to load — its nodes are missing from the library;
 * 4. this document could not be read and a version was restored — saving accepts it.
 *
 * Only the two that a user can legitimately live with are dismissible; the connection banner
 * clears itself, and a lost workspace is not something to hide.
 */
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { CircleAlert, HardDriveDownload, PackageX, PlugZap, WifiOff, X } from '@lucide/vue'

import { Button } from '@/components/ui/button'
import { useAuthStore } from '@/stores/auth'
import { useNodesSchemaStore } from '@/stores/nodesSchema'
import { useSessionStore } from '@/stores/session'
import { useUiStore } from '@/stores/ui'
import { useWorkflowStore } from '@/stores/workflow'
import { useWorkspaceStore } from '@/stores/workspace'

const { t, d } = useI18n()
const router = useRouter()
const ui = useUiStore()
const auth = useAuthStore()
const schema = useNodesSchemaStore()
const session = useSessionStore()
const workflow = useWorkflowStore()
const workspace = useWorkspaceStore()

/** Offline is either half of the connection: the REST probe or the event socket. */
const offline = computed(
  () =>
    ui.backendStatus === 'offline' ||
    session.wsStatus === 'reconnecting' ||
    session.wsStatus === 'closed',
)
const reconnecting = computed(() => session.wsStatus === 'reconnecting')

const failedPacks = computed(() => schema.packs.filter((pack) => pack.error))
const packsDismissed = ref(false)
const recoveryDismissed = ref(false)

// A different set of failures, or a different document, is worth saying again.
watch(
  () => failedPacks.value.map((pack) => pack.name).join(','),
  () => {
    packsDismissed.value = false
  },
)
watch(
  () => workflow.id,
  () => {
    recoveryDismissed.value = false
  },
)

const showPacks = computed(() => failedPacks.value.length > 0 && !packsDismissed.value)
const showRecovery = computed(() => workflow.recovered !== null && !recoveryDismissed.value)

function restoredAt(iso: string): string {
  const parsed = new Date(iso)
  return Number.isNaN(parsed.getTime()) ? iso : d(parsed, 'short')
}

async function retry(): Promise<void> {
  await ui.connect()
  session.connect()
}
</script>

<template>
  <div
    v-if="offline || !workspace.available || showPacks || showRecovery"
    class="shrink-0 border-b"
    data-testid="shell-notices"
  >
    <!-- 1. the connection -->
    <div
      v-if="offline"
      class="flex items-center gap-2 bg-destructive/10 px-3 py-1.5 text-xs text-destructive"
      role="status"
      data-testid="notice-offline"
      :data-reconnecting="reconnecting ? 'true' : 'false'"
    >
      <WifiOff class="size-3.5 shrink-0" aria-hidden="true" />
      <span class="min-w-0 flex-1">
        {{
          reconnecting
            ? t('notice.reconnecting', { attempt: session.wsAttempt })
            : t('notice.offline')
        }}
      </span>
      <Button variant="outline" size="xs" data-testid="notice-retry" @click="retry()">
        <PlugZap /> {{ t('backend.retry') }}
      </Button>
    </div>

    <!-- 2. the workspace -->
    <div
      v-if="!workspace.available"
      class="flex items-center gap-2 bg-destructive/10 px-3 py-1.5 text-xs text-destructive"
      role="alert"
      data-testid="notice-workspace"
    >
      <HardDriveDownload class="size-3.5 shrink-0" aria-hidden="true" />
      <span class="min-w-0 flex-1">
        {{ t('notice.workspace_gone', { root: workspace.root ?? '' }) }}
      </span>
      <Button
        variant="outline"
        size="xs"
        data-testid="notice-workspace-switch"
        @click="ui.showSidebar('workspace')"
      >
        {{ t('workspace.switch') }}
      </Button>
    </div>

    <!-- 3. packs that did not load -->
    <div
      v-if="showPacks"
      class="flex items-center gap-2 bg-amber-500/10 px-3 py-1.5 text-xs text-amber-700 dark:text-amber-400"
      role="status"
      data-testid="notice-packs"
      :data-count="failedPacks.length"
    >
      <PackageX class="size-3.5 shrink-0" aria-hidden="true" />
      <span class="min-w-0 flex-1">
        {{
          t(
            'notice.packs_failed',
            { count: failedPacks.length, named: failedPacks.map((pack) => pack.name).join(', ') },
            failedPacks.length,
          )
        }}
      </span>
      <Button
        v-if="auth.canManagePacks"
        variant="outline"
        size="xs"
        data-testid="notice-packs-manager"
        @click="router.push({ name: 'manager' })"
      >
        {{ t('notice.open_manager') }}
      </Button>
      <Button
        variant="ghost"
        size="icon-xs"
        :aria-label="t('common.dismiss')"
        data-testid="notice-packs-dismiss"
        @click="packsDismissed = true"
      >
        <X />
      </Button>
    </div>

    <!-- 4. a document that had to be recovered -->
    <div
      v-if="showRecovery && workflow.recovered"
      class="flex items-center gap-2 bg-amber-500/10 px-3 py-1.5 text-xs text-amber-700 dark:text-amber-400"
      role="alert"
      data-testid="notice-recovered"
      :data-version="workflow.recovered.version"
    >
      <CircleAlert class="size-3.5 shrink-0" aria-hidden="true" />
      <span class="min-w-0 flex-1">
        {{
          t('notice.recovered', {
            version: workflow.recovered.version,
            when: restoredAt(workflow.recovered.created),
          })
        }}
      </span>
      <Button
        variant="outline"
        size="xs"
        data-testid="notice-recovered-save"
        @click="workflow.saveNow()"
      >
        {{ t('notice.keep_it') }}
      </Button>
      <Button
        variant="ghost"
        size="icon-xs"
        :aria-label="t('common.dismiss')"
        data-testid="notice-recovered-dismiss"
        @click="recoveryDismissed = true"
      >
        <X />
      </Button>
    </div>
  </div>
</template>
