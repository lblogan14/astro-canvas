<script setup lang="ts">
/**
 * The Astro Canvas mark: a node card holding a spectrum, with an input port on the left edge
 * and an output port on the right, in the canvas's own Okabe-Ito port colours.
 *
 * Decorative by default — the shell renders it beside the `app.title` heading, so announcing it
 * again would only repeat the name. Pass `label` where the mark stands alone.
 *
 * Geometry mirrors `scripts/make_icons.py`, which generates `public/favicon.svg`,
 * `public/favicon.ico` and `public/apple-touch-icon.png` from the same numbers. Change it there
 * and here together.
 */
withDefaults(defineProps<{ label?: string }>(), { label: undefined })
</script>

<template>
  <svg
    viewBox="0 0 32 32"
    class="size-5 shrink-0"
    :role="label ? 'img' : undefined"
    :aria-label="label"
    :aria-hidden="label ? undefined : 'true'"
    focusable="false"
  >
    <rect x="5" y="5" width="22" height="22" rx="4" fill="#0072B2" />
    <path
      d="M8.2 21 L13.4 21 L16 10.2 L18.6 21 L23.8 21"
      fill="none"
      stroke="#FFFFFF"
      stroke-width="2.6"
      stroke-linecap="round"
      stroke-linejoin="round"
    />
    <circle cx="5" cy="16" r="2.8" fill="#E69F00" />
    <circle cx="27" cy="16" r="2.8" fill="#009E73" />
  </svg>
</template>
