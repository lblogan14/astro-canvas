<script setup lang="ts">
withDefaults(
  defineProps<{
    id: string
    modelValue: boolean
    disabled?: boolean
    invalid?: boolean
  }>(),
  { disabled: false, invalid: false },
)

const emit = defineEmits<{ 'update:modelValue': [value: unknown] }>()

function onChange(event: Event) {
  emit('update:modelValue', (event.target as HTMLInputElement).checked)
}
</script>

<template>
  <div class="flex h-6 items-center" data-widget="checkbox">
    <input
      :id="id"
      type="checkbox"
      class="h-3.5 w-3.5 rounded-sm border border-input accent-primary outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
      :checked="modelValue"
      :disabled="disabled"
      :aria-invalid="invalid || undefined"
      @change="onChange"
    />
  </div>
</template>
