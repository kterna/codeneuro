<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { TabId, TabItem } from '../../types/ledger'

const props = defineProps<{
  tabs: readonly TabItem[]
}>()

const emit = defineEmits<{
  (e: 'select-tab', id: TabId): void
}>()

const dialogRef = ref<HTMLDialogElement | null>(null)
const inputRef = ref<HTMLInputElement | null>(null)
const query = ref('')
const selectedIndex = ref(0)
let previousActiveElement: HTMLElement | null = null

const results = computed(() => {
  const text = query.value.toLocaleLowerCase().trim()
  return props.tabs.filter(item => !text || item.title.includes(text) || item.subtitle.includes(text))
})

watch(query, () => {
  selectedIndex.value = 0
})

function open() {
  previousActiveElement = document.activeElement as HTMLElement | null
  query.value = ''
  selectedIndex.value = 0
  dialogRef.value?.showModal()
  setTimeout(() => inputRef.value?.focus(), 50)
}

function close() {
  dialogRef.value?.close()
  if (previousActiveElement && typeof previousActiveElement.focus === 'function') {
    previousActiveElement.focus()
  }
}

function choose(id: TabId) {
  emit('select-tab', id)
  close()
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    if (results.value.length) {
      selectedIndex.value = (selectedIndex.value + 1) % results.value.length
    }
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    if (results.value.length) {
      selectedIndex.value = (selectedIndex.value - 1 + results.value.length) % results.value.length
    }
  } else if (event.key === 'Enter') {
    event.preventDefault()
    if (results.value.length > 0 && selectedIndex.value >= 0 && selectedIndex.value < results.value.length) {
      choose(results.value[selectedIndex.value].id)
    }
  } else if (event.key === 'Escape') {
    event.preventDefault()
    close()
  }
}

defineExpose({
  open,
  close,
})
</script>

<template>
  <dialog
    ref="dialogRef"
    id="palette"
    aria-label="搜索页面"
    role="dialog"
    aria-modal="true"
    @keydown="handleKeydown"
  >
    <div class="palette-search">
      <span aria-hidden="true">⌕</span>
      <input
        ref="inputRef"
        v-model="query"
        placeholder="搜索页面或功能…"
        aria-label="搜索页面或功能"
        autocomplete="off"
      />
      <kbd @click="close" style="cursor: pointer">Esc</kbd>
    </div>
    <div class="palette-results" role="listbox">
      <button
        v-for="(item, idx) in results"
        :key="item.id"
        class="command"
        :class="{ selected: idx === selectedIndex }"
        role="option"
        :aria-selected="idx === selectedIndex"
        @click="choose(item.id)"
        @mouseenter="selectedIndex = idx"
      >
        <span style="font-size: 16px; margin-right: 8px">{{ item.icon }}</span>
        <strong>{{ item.title }}</strong>
        <small>{{ item.subtitle }}</small>
      </button>
      <p v-if="!results.length" class="empty compact">没有找到匹配的页面</p>
    </div>
    <div class="palette-footer">↑ ↓ 选择 · Enter 执行 · Esc 关闭 · Ctrl / ⌘ K 随时唤出</div>
  </dialog>
</template>
