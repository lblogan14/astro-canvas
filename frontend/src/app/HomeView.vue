<script setup lang="ts">
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
</script>

<template>
  <section
    class="canvas-placeholder flex h-full w-full items-center justify-center bg-background"
    aria-label="canvas"
  >
    <div class="rounded-lg border bg-card px-6 py-4 text-center shadow-sm">
      <p class="text-sm font-medium">{{ t('canvas.placeholder') }}</p>
      <p class="mt-1 text-xs text-muted-foreground">{{ t('canvas.hint') }}</p>
    </div>
  </section>
</template>

<style scoped>
.canvas-placeholder {
  background-image: radial-gradient(var(--color-border) 1px, transparent 1px);
  background-size: 20px 20px;
}
</style>
