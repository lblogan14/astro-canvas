<script setup lang="ts">
import { onMounted } from 'vue'
import { RouterView } from 'vue-router'
import { useI18n } from 'vue-i18n'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useUiStore } from '@/stores/ui'

const { t } = useI18n()
const ui = useUiStore()

onMounted(() => {
  ui.setTheme(ui.theme)
  void ui.connect()
})
</script>

<template>
  <div class="flex h-dvh flex-col bg-background text-foreground">
    <header class="flex h-12 shrink-0 items-center justify-between border-b px-4">
      <div class="flex items-baseline gap-3">
        <h1 class="text-sm font-semibold tracking-tight">{{ t('app.title') }}</h1>
        <span class="hidden text-xs text-muted-foreground sm:inline">{{ t('app.tagline') }}</span>
      </div>
      <div class="flex items-center gap-2">
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
          size="xs"
          :aria-label="t('theme.toggle', { theme: t(`theme.${ui.theme}`) })"
          @click="ui.cycleTheme()"
        >
          {{ t(`theme.${ui.theme}`) }}
        </Button>
      </div>
    </header>
    <main class="relative flex-1 overflow-hidden">
      <RouterView />
    </main>
  </div>
</template>
