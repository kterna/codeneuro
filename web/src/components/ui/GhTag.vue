<script setup lang="ts">
withDefaults(
  defineProps<{
    variant?: 'default' | 'accent' | 'green' | 'success' | 'amber' | 'warning' | 'red' | 'danger' | 'purple' | 'neutral'
  }>(),
  {
    variant: 'default',
  }
)
</script>

<template>
  <span class="tag" :class="variant !== 'default' ? variant : ''">
    <slot />
  </span>
</template>
