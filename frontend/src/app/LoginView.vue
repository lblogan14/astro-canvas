<script setup lang="ts">
/**
 * The sign-in page a `--auth users` server shows before the canvas (design §12).
 *
 * Only ever reached on a lab server: on a desktop install the auth store settles on
 * `mode === 'single'` and the router never routes here. The session is an httpOnly cookie set
 * by the server, so nothing here holds a credential after the request returns.
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { Loader, LogIn } from '@lucide/vue'

import { Button } from '@/components/ui/button'
import { useAuthStore } from '@/stores/auth'

const { t } = useI18n()
const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const email = ref('')
const password = ref('')
const displayName = ref('')
const signingUp = ref(false)

const canSubmit = computed(
  () => email.value.trim().length > 0 && password.value.length > 0 && !auth.busy,
)

async function submit(): Promise<void> {
  if (!canSubmit.value) return
  const ok = signingUp.value
    ? await auth.register(email.value.trim(), password.value, displayName.value.trim())
    : await auth.login(email.value.trim(), password.value)
  password.value = ''
  if (!ok) return
  // The guard sent us here with where the user was going; go back there.
  const back = route.query.redirect
  await router.replace(typeof back === 'string' && back.startsWith('/') ? back : '/')
}

const providerLabel = (provider: string): string =>
  provider.charAt(0).toUpperCase() + provider.slice(1)
</script>

<template>
  <div class="flex h-full items-center justify-center overflow-auto p-6">
    <form
      class="w-full max-w-sm space-y-4 rounded-lg border bg-card p-6 shadow-sm"
      data-testid="login-form"
      @submit.prevent="submit"
    >
      <div class="space-y-1">
        <h2 class="text-base font-semibold tracking-tight">{{ t('auth.title') }}</h2>
        <p class="text-xs text-muted-foreground">{{ t('auth.subtitle') }}</p>
      </div>

      <label class="block space-y-1">
        <span class="text-xs font-medium">{{ t('auth.email') }}</span>
        <input
          v-model="email"
          type="email"
          autocomplete="username"
          required
          class="h-8 w-full rounded-md border bg-background px-2 text-sm"
          data-testid="login-email"
        />
      </label>

      <label class="block space-y-1">
        <span class="text-xs font-medium">{{ t('auth.password') }}</span>
        <input
          v-model="password"
          type="password"
          :autocomplete="signingUp ? 'new-password' : 'current-password'"
          required
          class="h-8 w-full rounded-md border bg-background px-2 text-sm"
          data-testid="login-password"
        />
        <span v-if="signingUp" class="text-xs text-muted-foreground">
          {{ t('auth.password_hint') }}
        </span>
      </label>

      <label v-if="signingUp" class="block space-y-1">
        <span class="text-xs font-medium">{{ t('auth.display_name') }}</span>
        <input
          v-model="displayName"
          type="text"
          autocomplete="nickname"
          class="h-8 w-full rounded-md border bg-background px-2 text-sm"
          data-testid="login-display-name"
        />
        <span class="text-xs text-muted-foreground">{{ t('auth.display_name_hint') }}</span>
      </label>

      <p v-if="auth.error" class="text-xs text-destructive" role="alert" data-testid="login-error">
        {{ auth.error }}
      </p>

      <Button type="submit" class="w-full" :disabled="!canSubmit" data-testid="login-submit">
        <Loader v-if="auth.busy" class="animate-spin" />
        <LogIn v-else />
        {{ auth.busy ? t('auth.signing_in') : signingUp ? t('auth.sign_up') : t('auth.sign_in') }}
      </Button>

      <template v-if="auth.providers.length">
        <div class="flex items-center gap-2 text-xs text-muted-foreground">
          <span class="h-px flex-1 bg-border" aria-hidden="true" />
          {{ t('auth.or') }}
          <span class="h-px flex-1 bg-border" aria-hidden="true" />
        </div>
        <Button
          v-for="provider in auth.providers"
          :key="provider"
          type="button"
          variant="outline"
          class="w-full"
          :data-testid="`login-provider-${provider}`"
          @click="auth.startOauth(provider)"
        >
          {{ t('auth.with_provider', { provider: providerLabel(provider) }) }}
        </Button>
      </template>

      <p v-if="!auth.canRegister" class="text-xs text-muted-foreground">
        {{ t('auth.registration_closed') }}
      </p>
      <Button
        v-else
        type="button"
        variant="link"
        size="xs"
        class="w-full"
        data-testid="login-toggle"
        @click="signingUp = !signingUp"
      >
        {{ signingUp ? t('auth.to_sign_in') : t('auth.to_sign_up') }}
      </Button>
    </form>
  </div>
</template>
