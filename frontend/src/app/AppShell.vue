<script setup lang="ts">
import { onMounted, watch } from 'vue'
import { RouterView, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { LogOut, Monitor, Moon, ShieldCheck, Sun, UserRound } from '@lucide/vue'

import ShellNotices from '@/app/ShellNotices.vue'
import BrandMark from '@/components/BrandMark.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useAuthStore } from '@/stores/auth'
import { useSessionStore } from '@/stores/session'
import { useUiStore } from '@/stores/ui'

const { t } = useI18n()
const ui = useUiStore()
const session = useSessionStore()
const auth = useAuthStore()
const router = useRouter()

onMounted(() => {
  ui.setTheme(ui.theme)
  if (!auth.requiresLogin) void ui.connect()
})

// On a users server the WebSocket handshake needs the session cookie, so connecting waits
// until somebody is actually logged in (and reconnects after a later sign-in).
watch(
  () => auth.requiresLogin,
  (blocked, was) => {
    if (!blocked && was) void ui.connect()
  },
)

async function signOut(): Promise<void> {
  await auth.logout()
  await router.push({ name: 'login' })
}
</script>

<template>
  <div class="flex h-dvh flex-col bg-background text-foreground">
    <header class="flex h-10 shrink-0 items-center justify-between border-b px-4">
      <div class="flex items-center gap-2">
        <BrandMark />
        <div class="flex items-baseline gap-3">
          <h1 class="text-sm font-semibold tracking-tight">{{ t('app.title') }}</h1>
          <span class="hidden text-xs text-muted-foreground sm:inline">{{ t('app.tagline') }}</span>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <Badge
          v-if="auth.user"
          data-testid="account"
          :data-admin="auth.user.is_superuser ? 'true' : 'false'"
          variant="outline"
          class="hidden sm:inline-flex"
          :title="auth.user.email"
        >
          <ShieldCheck v-if="auth.user.is_superuser" class="size-3" aria-hidden="true" />
          <UserRound v-else class="size-3" aria-hidden="true" />
          {{ auth.label }}
        </Badge>
        <Button
          v-if="auth.user"
          variant="ghost"
          size="xs"
          data-testid="sign-out"
          :title="t('auth.sign_out')"
          @click="signOut()"
        >
          <LogOut />
          <span class="hidden sm:inline">{{ t('auth.sign_out') }}</span>
        </Button>
        <Badge
          data-testid="ws-status"
          :data-status="session.wsStatus"
          variant="outline"
          class="hidden sm:inline-flex"
        >
          <span
            class="size-1.5 rounded-full"
            :class="session.isConnected ? 'bg-emerald-500' : 'bg-current opacity-60'"
            aria-hidden="true"
          />
          {{ t(`ws.${session.wsStatus}`) }}
        </Badge>
        <Badge
          data-testid="backend-status"
          :data-status="ui.backendStatus"
          :variant="ui.isOnline ? 'secondary' : 'destructive'"
          :title="ui.backendError ?? undefined"
        >
          <span
            class="size-1.5 rounded-full"
            :class="ui.isOnline ? 'bg-emerald-500' : 'bg-current opacity-60'"
            aria-hidden="true"
          />
          {{ t(`backend.status.${ui.backendStatus}`) }}
          <span v-if="ui.backendVersion">{{
            t('backend.version', { version: ui.backendVersion })
          }}</span>
        </Badge>
        <Button v-if="!ui.isOnline" variant="outline" size="xs" @click="ui.connect()">
          {{ t('backend.retry') }}
        </Button>
        <Button
          variant="ghost"
          size="icon-xs"
          :aria-label="t('theme.toggle', { theme: t(`theme.${ui.theme}`) })"
          :title="t('theme.toggle', { theme: t(`theme.${ui.theme}`) })"
          data-testid="theme-toggle"
          @click="ui.cycleTheme()"
        >
          <Sun v-if="ui.theme === 'light'" />
          <Moon v-else-if="ui.theme === 'dark'" />
          <Monitor v-else />
        </Button>
      </div>
    </header>
    <ShellNotices />
    <main class="relative min-h-0 flex-1 overflow-hidden">
      <RouterView />
      <!-- One toast for the whole shell: the Manager and the gallery notify from their own pages. -->
      <div
        v-if="ui.toast"
        class="pointer-events-none absolute bottom-4 left-1/2 z-50 -translate-x-1/2 rounded-md border px-3 py-2 text-xs shadow-md"
        :class="
          ui.toast.kind === 'error'
            ? 'border-destructive/40 bg-destructive/10 text-destructive'
            : 'bg-popover text-popover-foreground'
        "
        role="status"
        data-testid="toast"
      >
        {{ ui.toast.message }}
      </div>
    </main>
  </div>
</template>
