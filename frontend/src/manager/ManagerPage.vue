<script setup lang="ts">
/**
 * The pack manager (design §9): Installed, Registry, Snapshots and Settings.
 *
 * Everything that changes the environment goes through the same two steps — resolve, then act on
 * a plan the user confirmed in `PlanDialog` — so the diff and any conflicts are always seen
 * first. A change that Python cannot apply in place (replacing already-imported code, a
 * rollback) raises the restart banner rather than pretending it took effect.
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import {
  ArrowLeft,
  Boxes,
  CircleCheck,
  Download,
  History,
  Loader,
  Package,
  RefreshCw,
  RotateCcw,
  Settings,
  Trash2,
  TriangleAlert,
} from '@lucide/vue'

import type { PackDetail, RegistryEntry, SecurityLevel } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { type ManagerTab, usePacksStore } from '@/stores/packs'
import { useUiStore } from '@/stores/ui'
import PlanDialog from './PlanDialog.vue'

const { t } = useI18n()
const router = useRouter()
const packs = usePacksStore()
const ui = useUiStore()

const TABS: readonly ManagerTab[] = ['installed', 'registry', 'snapshots', 'settings']

const source = ref('')
const snapshotLabel = ref('')
const uvPath = ref('')
const registryUrl = ref('')
const expanded = ref<string | null>(null)
/** What the confirmed plan will do once the dialog says yes. */
const pending = ref<string | null>(null)

const installing = computed(() => packs.busy?.kind === 'install')
const loading = computed(() => packs.busy !== null)

onMounted(async () => {
  await packs.refresh()
  uvPath.value = packs.settings?.uv_path ?? ''
  registryUrl.value = packs.settings?.registry_url ?? ''
  if (packs.tab !== 'installed') packs.setTab(packs.tab)
})

async function planFor(candidate: string): Promise<void> {
  if (!candidate.trim()) return
  pending.value = candidate.trim()
  await packs.resolve(candidate.trim())
}

async function confirmPlan(): Promise<void> {
  const target = pending.value
  if (!target) return
  const result = await packs.install(target)
  pending.value = null
  source.value = ''
  if (result?.ok) ui.notify(result.message || t('manager.installed', { name: target }))
  else if (packs.error) ui.notify(packs.error, 'error')
}

function cancelPlan(): void {
  pending.value = null
  packs.clearPlan()
}

async function removePack(pack: PackDetail): Promise<void> {
  const result = await packs.uninstall(pack.name)
  if (result?.ok) ui.notify(result.message)
  else if (packs.error) ui.notify(packs.error, 'error')
}

async function updatePack(pack: PackDetail): Promise<void> {
  const result = await packs.update(pack.name)
  if (result?.ok) ui.notify(result.message)
  else if (packs.error) ui.notify(packs.error, 'error')
}

async function rollback(id: number): Promise<void> {
  const result = await packs.rollback(id)
  if (result?.ok) ui.notify(result.message)
  else if (packs.error) ui.notify(packs.error, 'error')
}

async function saveSettings(patch: { security?: SecurityLevel }): Promise<void> {
  await packs.updateSettings({
    ...patch,
    uv_path: uvPath.value.trim(),
    registry_url: registryUrl.value.trim(),
  })
  ui.notify(t('manager.settings_saved'))
}

function installFromRegistry(entry: RegistryEntry): void {
  void planFor(entry.source)
}
</script>

<template>
  <div class="flex h-full flex-col bg-background" data-testid="manager-page">
    <header class="flex h-11 shrink-0 items-center gap-2 border-b px-3">
      <Button variant="ghost" size="sm" data-testid="manager-back" @click="router.back()">
        <ArrowLeft /> {{ t('gallery.back') }}
      </Button>
      <h1 class="flex items-center gap-2 text-sm font-semibold">
        <Boxes class="size-4" /> {{ t('manager.title') }}
      </h1>
      <span class="flex-1" />
      <Button
        variant="ghost"
        size="sm"
        :disabled="loading"
        data-testid="manager-refresh"
        @click="packs.refresh()"
      >
        <RefreshCw :class="loading ? 'animate-spin' : ''" /> {{ t('manager.refresh') }}
      </Button>
    </header>

    <div
      v-if="packs.restartRequired"
      class="flex items-center gap-2 border-b border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-600 dark:text-amber-400"
      data-testid="manager-restart"
      role="status"
    >
      <TriangleAlert class="size-3.5" /> {{ t('manager.restart_required') }}
    </div>

    <nav class="flex shrink-0 gap-1 border-b px-3 py-1.5" :aria-label="t('manager.title')">
      <Button
        v-for="entry in TABS"
        :key="entry"
        size="sm"
        :variant="packs.tab === entry ? 'secondary' : 'ghost'"
        :aria-pressed="packs.tab === entry"
        :data-testid="`manager-tab-${entry}`"
        @click="packs.setTab(entry)"
      >
        <Package v-if="entry === 'installed'" />
        <Download v-else-if="entry === 'registry'" />
        <History v-else-if="entry === 'snapshots'" />
        <Settings v-else />
        {{ t(`manager.tab.${entry}`) }}
      </Button>
    </nav>

    <p
      v-if="!packs.available"
      class="p-6 text-center text-xs text-muted-foreground"
      data-testid="manager-unavailable"
    >
      {{ t('manager.unavailable') }}
    </p>

    <div v-else class="min-h-0 flex-1 overflow-auto p-3">
      <p v-if="packs.error" class="mb-3 text-xs text-destructive" data-testid="manager-error">
        {{ packs.error }}
      </p>

      <!-- Installed --------------------------------------------------------------------- -->
      <section v-if="packs.tab === 'installed'" class="space-y-2">
        <div class="flex gap-2">
          <input
            v-model="source"
            class="h-7 flex-1 rounded-md border bg-background px-2 font-mono text-xs"
            :placeholder="t('manager.source_placeholder')"
            :aria-label="t('manager.source_label')"
            data-testid="manager-source"
            @keydown.enter.prevent="planFor(source)"
          />
          <Button
            size="sm"
            :disabled="loading || !source.trim()"
            data-testid="manager-install"
            @click="planFor(source)"
          >
            <Loader v-if="packs.busy?.kind === 'resolve'" class="animate-spin" />
            <Download v-else />
            {{ t('manager.install') }}
          </Button>
        </div>
        <p class="text-[11px] text-muted-foreground">
          {{ t(`manager.security_hint.${packs.security}`) }}
        </p>

        <ul class="space-y-2" role="list">
          <li
            v-for="pack in packs.installed"
            :key="pack.name"
            class="rounded-lg border p-3"
            :data-testid="`pack-${pack.name}`"
            :data-enabled="pack.enabled ? 'true' : 'false'"
            :data-error="pack.error ? 'true' : 'false'"
          >
            <div class="flex items-center gap-2">
              <span class="text-sm font-medium">{{ pack.name }}</span>
              <Badge variant="outline">{{ pack.version }}</Badge>
              <Badge v-if="!pack.enabled" variant="secondary">{{ t('manager.disabled') }}</Badge>
              <Badge v-if="pack.error" variant="destructive">{{ t('manager.failed') }}</Badge>
              <span class="flex-1" />
              <span class="text-[11px] text-muted-foreground">
                {{ t('manager.node_count', pack.node_count) }}
              </span>
            </div>
            <p class="mt-1 font-mono text-[11px] text-muted-foreground">
              {{ pack.distribution ?? pack.name }} · {{ pack.entry_point }}
            </p>

            <div class="mt-2 flex flex-wrap gap-1">
              <Button
                size="xs"
                variant="ghost"
                :disabled="loading"
                :data-testid="`pack-toggle-${pack.name}`"
                @click="packs.setEnabled(pack.name, !pack.enabled)"
              >
                {{ pack.enabled ? t('manager.disable') : t('manager.enable') }}
              </Button>
              <Button
                size="xs"
                variant="ghost"
                :disabled="loading"
                :data-testid="`pack-update-${pack.name}`"
                @click="updatePack(pack)"
              >
                <RefreshCw /> {{ t('manager.update') }}
              </Button>
              <Button
                size="xs"
                variant="ghost"
                :disabled="loading"
                :data-testid="`pack-uninstall-${pack.name}`"
                @click="removePack(pack)"
              >
                <Trash2 /> {{ t('manager.uninstall') }}
              </Button>
              <Button
                v-if="pack.traceback"
                size="xs"
                variant="ghost"
                :data-testid="`pack-traceback-${pack.name}`"
                @click="expanded = expanded === pack.name ? null : pack.name"
              >
                <TriangleAlert /> {{ t('manager.show_error') }}
              </Button>
            </div>

            <pre
              v-if="expanded === pack.name && pack.traceback"
              class="mt-2 max-h-56 overflow-auto rounded bg-muted p-2 text-[10px] whitespace-pre-wrap"
              :data-testid="`pack-error-${pack.name}`"
              >{{ pack.traceback }}</pre>
          </li>
        </ul>
      </section>

      <!-- Registry ---------------------------------------------------------------------- -->
      <section v-else-if="packs.tab === 'registry'" class="space-y-3">
        <div class="flex items-center gap-2">
          <input
            v-model="packs.query"
            class="h-7 w-56 rounded-md border bg-background px-2 text-xs"
            :placeholder="t('manager.registry_search')"
            :aria-label="t('manager.registry_search')"
            data-testid="registry-search"
          />
          <Button
            size="sm"
            variant="ghost"
            :disabled="loading"
            data-testid="registry-refresh"
            @click="packs.loadRegistry(true)"
          >
            <RefreshCw /> {{ t('manager.refresh') }}
          </Button>
          <span v-if="packs.registry?.stale" class="text-[11px] text-amber-500">
            {{ t('manager.registry_stale') }}
          </span>
        </div>

        <ul class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" role="list">
          <li
            v-for="entry in packs.registryResults"
            :key="entry.name"
            class="flex flex-col gap-2 rounded-lg border p-3"
            :data-testid="`registry-card-${entry.name}`"
          >
            <h2 class="text-sm font-semibold">{{ entry.display_name || entry.name }}</h2>
            <p class="line-clamp-4 text-[11px] text-muted-foreground">{{ entry.description }}</p>
            <div class="flex flex-wrap gap-1 text-[10px]">
              <span v-if="entry.publisher" class="rounded bg-muted px-1.5 py-0.5">
                {{ entry.publisher }}
              </span>
              <span v-if="entry.latest" class="rounded bg-muted px-1.5 py-0.5 font-mono">
                {{ entry.latest }}
              </span>
              <span
                v-for="category in entry.categories"
                :key="category"
                class="rounded bg-muted px-1.5 py-0.5"
              >
                {{ category }}
              </span>
            </div>
            <p v-if="entry.templates?.length" class="text-[11px] text-muted-foreground">
              {{ t('manager.templates_count', entry.templates.length) }}
            </p>
            <div class="mt-auto">
              <span
                v-if="packs.isInstalled(entry)"
                class="flex items-center gap-1 text-[11px] text-emerald-500"
                :data-testid="`registry-installed-${entry.name}`"
              >
                <CircleCheck class="size-3.5" /> {{ t('manager.already_installed') }}
              </span>
              <Button
                v-else
                size="sm"
                class="w-full"
                :disabled="loading"
                :data-testid="`registry-install-${entry.name}`"
                @click="installFromRegistry(entry)"
              >
                <Download /> {{ t('manager.install') }}
              </Button>
            </div>
          </li>
        </ul>
        <p
          v-if="packs.registryResults.length === 0"
          class="p-6 text-center text-xs text-muted-foreground"
          data-testid="registry-empty"
        >
          {{ packs.registry?.error ?? t('manager.registry_empty') }}
        </p>
      </section>

      <!-- Snapshots --------------------------------------------------------------------- -->
      <section v-else-if="packs.tab === 'snapshots'" class="space-y-3">
        <div class="flex gap-2">
          <input
            v-model="snapshotLabel"
            class="h-7 flex-1 rounded-md border bg-background px-2 text-xs"
            :placeholder="t('manager.snapshot_placeholder')"
            :aria-label="t('manager.snapshot_placeholder')"
            data-testid="snapshot-label"
          />
          <Button
            size="sm"
            :disabled="loading"
            data-testid="snapshot-create"
            @click="packs.snapshot(snapshotLabel).then(() => (snapshotLabel = ''))"
          >
            {{ t('manager.snapshot_create') }}
          </Button>
        </div>
        <p class="text-[11px] text-muted-foreground">{{ t('manager.snapshot_hint') }}</p>

        <ul class="space-y-2" role="list">
          <li
            v-for="snap in packs.snapshots"
            :key="snap.id"
            class="flex items-center gap-2 rounded-md border p-2 text-xs"
            :data-testid="`snapshot-${snap.id}`"
          >
            <span class="font-mono">#{{ snap.id }}</span>
            <span class="text-muted-foreground">{{
              snap.created.replace('T', ' ').slice(0, 19)
            }}</span>
            <span class="flex-1 truncate">{{ snap.label }}</span>
            <span class="text-muted-foreground">
              {{ t('manager.snapshot_packages', snap.packages) }}
            </span>
            <Button
              size="xs"
              variant="ghost"
              :disabled="loading"
              :data-testid="`snapshot-rollback-${snap.id}`"
              @click="rollback(snap.id)"
            >
              <RotateCcw /> {{ t('manager.rollback') }}
            </Button>
          </li>
        </ul>
        <p
          v-if="packs.snapshots.length === 0"
          class="p-6 text-center text-xs text-muted-foreground"
          data-testid="snapshots-empty"
        >
          {{ t('manager.snapshots_empty') }}
        </p>
      </section>

      <!-- Settings ---------------------------------------------------------------------- -->
      <section v-else class="max-w-xl space-y-4 text-xs">
        <div>
          <h2 class="mb-1 text-sm font-semibold">{{ t('manager.security') }}</h2>
          <div class="flex flex-col gap-1">
            <label
              v-for="level in packs.status?.security_levels ?? []"
              :key="level"
              class="flex items-start gap-2 rounded-md border p-2"
              :data-testid="`security-${level}`"
            >
              <input
                type="radio"
                name="security"
                class="mt-0.5"
                :value="level"
                :checked="packs.security === level"
                @change="saveSettings({ security: level as SecurityLevel })"
              />
              <span>
                <span class="font-medium">{{ t(`manager.security_level.${level}`) }}</span>
                <span class="block text-[11px] text-muted-foreground">
                  {{ packs.status?.security_help?.[level] }}
                </span>
              </span>
            </label>
          </div>
        </div>

        <div>
          <h2 class="mb-1 text-sm font-semibold">{{ t('manager.uv') }}</h2>
          <p class="font-mono text-[11px] text-muted-foreground" data-testid="manager-uv">
            {{ packs.status?.uv_path ?? t('manager.uv_missing') }}
            <span v-if="packs.status?.uv_version"> · {{ packs.status.uv_version }}</span>
          </p>
          <p class="mt-1 font-mono text-[11px] text-muted-foreground">
            {{ packs.status?.python }}
          </p>
          <input
            v-model="uvPath"
            class="mt-2 h-7 w-full rounded-md border bg-background px-2 font-mono text-xs"
            :placeholder="t('manager.uv_placeholder')"
            :aria-label="t('manager.uv_placeholder')"
            data-testid="manager-uv-path"
          />
        </div>

        <div>
          <h2 class="mb-1 text-sm font-semibold">{{ t('manager.registry_url') }}</h2>
          <input
            v-model="registryUrl"
            class="h-7 w-full rounded-md border bg-background px-2 font-mono text-xs"
            :placeholder="t('manager.registry_url_placeholder')"
            :aria-label="t('manager.registry_url')"
            data-testid="manager-registry-url"
          />
        </div>

        <Button
          size="sm"
          :disabled="loading"
          data-testid="manager-save-settings"
          @click="saveSettings({})"
        >
          {{ t('manager.save_settings') }}
        </Button>
      </section>
    </div>

    <PlanDialog :plan="packs.plan" :busy="installing" @confirm="confirmPlan" @cancel="cancelPlan" />
  </div>
</template>
