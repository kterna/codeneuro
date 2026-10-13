<script setup lang="ts">
import { ref } from 'vue'

const props = withDefaults(
  defineProps<{
    variant?: 'default' | 'primary' | 'danger' | 'subtle'
    type?: 'button' | 'submit' | 'reset'
    disabled?: boolean
    loading?: boolean
    ariaLabel?: string
  }>(),
  {
    variant: 'default',
    type: 'button',
    disabled: false,
    loading: false,
    ariaLabel: undefined,
  }
)

const emit = defineEmits<{
  (e: 'click', event: MouseEvent): void
}>()

function handleClick(e: MouseEvent) {
  if (props.disabled || props.loading) {
    e.preventDefault()
    return
  }
  emit('click', e)
}
</script>

<template>
  <button
    :type="type"
    :class="[variant !== 'default' ? variant : '', { 'is-loading': loading }]"
    :disabled="disabled || loading"
    :aria-label="ariaLabel"
    :aria-busy="loading"
    @click="handleClick"
  >
    <span v-if="loading" class="spinner" aria-hidden="true">⏳</span>
    <slot />
  </button>
</template>

<style scoped>
.spinner {
  display: inline-block;
  font-size: 11px;
  animation: pulse 1s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
