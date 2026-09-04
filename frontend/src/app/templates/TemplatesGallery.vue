<script setup lang="ts">
/**
 * Templates gallery (design 7.3, brief item 5): the full-page view of what the installed packs
 * ship — a card per template with its figure, description, required packs and the layout it
 * opens into.
 *
 * *Open* instantiates the bundle into the workspace and lands in that layout; *Show graph* does
 * the same but opens the canvas, so "what does this actually do?" is always one click away. The
 * sample files a template points at are copied into `samples/` by the instantiate call, so a
 * fresh workspace runs the template without any further setup.
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { ArrowLeft, LayoutTemplate, Loader, Play, Workflow } from '@lucide/vue'

import { getToken } from '@/api/client'
import type { TemplateInfo } from '@/api/types'
import { Button } from '@/components/ui/button'
import { isAppMode, useUiStore } from '@/stores/ui'
import { useWorkflowsStore } from '@/stores/workflows'

const { t } = useI18n()
const router = useRouter()
const workflows = useWorkflowsStore()
const ui = useUiStore()

const busy = ref<string | null>(null)
const query = ref('')

const templates = computed(() => {
  const needle = query.value.trim().toLowerCase()
  if (!needle) return workflows.templates
  return workflows.templates.filter((template) =>
    [template.name, template.description, template.pack, ...(template.tags ?? [])]
      .join(' ')
      .toLowerCase()
      .includes(needle),
  )
})

onMounted(() => {
  void workflows.loadTemplates()
})

/** Figure URL with the bearer token as a query parameter (an `<img>` sends no headers). */
function figureUrl(template: TemplateInfo): string | null {
  if (!template.figure) return null
  const token = getToken()
  const base = `/api/templates/${encodeURIComponent(template.id)}/figure`
  return token ? `${base}?token=${encodeURIComponent(token)}` : base
}

/** A stable colour per template so a card without a figure is still recognisable. */
function hue(template: TemplateInfo): number {
  let total = 0
  for (const char of template.id) total = (total * 31 + char.charCodeAt(0)) % 360
  return total
}

function initials(template: TemplateInfo): string {
  return template.name
    .split(/\s+/)
    .slice(0, 2)
    .map((word) => word[0]?.toUpperCase() ?? '')
    .join('')
}

async function open(template: TemplateInfo, graph = false): Promise<void> {
  busy.value = template.id
  try {
    const id = await workflows.instantiate(template.id)
    const mode = graph ? 'canvas' : (template.default_layout ?? 'canvas')
    ui.setMode(isAppMode(mode) ? mode : 'canvas')
    ui.notify(t('workflows.template_created', { name: template.name }))
    await router.push(
      mode === 'canvas' || !isAppMode(mode)
        ? { name: 'workflow', params: { id } }
        : { name: 'workflow-mode', params: { id, mode } },
    )
  } catch (error) {
    ui.notify(error instanceof Error ? error.message : String(error), 'error')
  } finally {
    busy.value = null
  }
}
</script>

<template>
  <div class="flex h-full flex-col bg-background" data-testid="templates-gallery">
    <header class="flex h-11 shrink-0 items-center gap-2 border-b px-3">
      <Button variant="ghost" size="sm" data-testid="gallery-back" @click="router.back()">
        <ArrowLeft /> {{ t('gallery.back') }}
      </Button>
      <h1 class="flex items-center gap-2 text-sm font-semibold">
        <LayoutTemplate class="size-4" /> {{ t('gallery.title') }}
      </h1>
      <span class="flex-1" />
      <input
        v-model="query"
        class="h-7 w-56 rounded-md border bg-background px-2 text-xs"
        :placeholder="t('gallery.search')"
        :aria-label="t('gallery.search')"
        data-testid="gallery-search"
      />
    </header>

    <div class="min-h-0 flex-1 overflow-auto p-4">
      <p v-if="workflows.error" class="text-xs text-destructive">{{ workflows.error }}</p>
      <p
        v-else-if="templates.length === 0"
        class="p-6 text-center text-xs text-muted-foreground"
        data-testid="gallery-empty"
      >
        {{ t('gallery.empty') }}
      </p>

      <ul
        class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"
        role="list"
        data-testid="gallery-list"
      >
        <li
          v-for="template in templates"
          :key="template.id"
          class="flex flex-col overflow-hidden rounded-lg border bg-card"
          :data-testid="`gallery-card-${template.id}`"
          :data-layout="template.default_layout"
        >
          <img
            v-if="figureUrl(template)"
            :src="figureUrl(template) ?? undefined"
            :alt="t('gallery.figure_alt', { name: template.name })"
            class="h-32 w-full object-cover"
          />
          <div
            v-else
            class="flex h-32 items-center justify-center text-2xl font-semibold text-white"
            :style="{
              background: `linear-gradient(135deg, hsl(${hue(template)} 55% 45%), hsl(${(hue(template) + 40) % 360} 55% 30%))`,
            }"
            aria-hidden="true"
          >
            {{ initials(template) }}
          </div>

          <div class="flex min-h-0 flex-1 flex-col gap-2 p-3">
            <h2 class="text-sm font-semibold">{{ template.name }}</h2>
            <p class="line-clamp-4 text-[11px] text-muted-foreground">
              {{ template.description }}
            </p>
            <div class="mt-auto flex flex-wrap gap-1 text-[10px]">
              <span class="rounded bg-muted px-1.5 py-0.5">
                {{ t(`toolbar.layout_${template.default_layout}`) }}
              </span>
              <span class="rounded bg-muted px-1.5 py-0.5">
                {{ t('workflows.template_nodes', template.node_count) }}
              </span>
              <span
                v-for="(spec, pack) in template.packs"
                :key="pack"
                class="rounded bg-muted px-1.5 py-0.5 font-mono"
                :title="`${pack} ${spec}`"
              >
                {{ pack }}
              </span>
            </div>
            <div class="flex gap-1">
              <Button
                size="sm"
                class="flex-1"
                :disabled="busy !== null"
                :data-testid="`gallery-open-${template.id}`"
                @click="open(template)"
              >
                <Loader v-if="busy === template.id" class="animate-spin" />
                <Play v-else />
                {{ t('gallery.open') }}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                :disabled="busy !== null"
                :title="t('gallery.show_graph_hint')"
                :data-testid="`gallery-graph-${template.id}`"
                @click="open(template, true)"
              >
                <Workflow /> {{ t('modes.show_graph') }}
              </Button>
            </div>
          </div>
        </li>
      </ul>

      <p class="mt-4 text-[11px] text-muted-foreground">{{ t('gallery.samples_hint') }}</p>
    </div>
  </div>
</template>
