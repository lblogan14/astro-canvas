<script setup lang="ts">
import { onMounted } from 'vue'
import { RouterView } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Monitor, Moon, Sun } from '@lucide/vue'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useSessionStore } from '@/stores/session'
import { useUiStore } from '@/stores/ui'

const { t } = useI18n()
const ui = useUiStore()
const session = useSessionStore()

onMounted(() => {
  ui.setTheme(ui.theme)
  void ui.connect()
})
</script>

<template>
  <div class="flex h-dvh flex-col bg-background text-foreground">
    <header class="flex h-10 shrink-0 items-center justify-between border-b px-4">
      <div class="flex items-baseline gap-3">
        <h1 class="text-sm font-semibold tracking-tight">{{ t('app.title') }}</h1>
        <span class="hidden text-xs text-muted-foreground sm:inline">{{ t('app.tagline') }}</span>
      </div>
      <div class="flex items-center gap-2">
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
