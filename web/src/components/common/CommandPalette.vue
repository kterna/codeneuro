<script setup lang="ts">
import { computed, ref } from 'vue'
import type { TabId, TabItem } from '../../types/ledger'

const props = defineProps<{
  tabs: readonly TabItem[]
}>()

const emit = defineEmits<{
  (e: 'select-tab', id: TabId): void
}>()

const dialogRef = ref<HTMLDialogElement | null>(null)
const query = ref('')

const results = computed(() => {
  const text = query.value.toLocaleLowerCase().trim()
  return props.tabs.filter(item => !text || item.title.includes(text) || item.subtitle.includes(text))
})

function open() {
  query.value = ''
  dialogRef.value?.showModal()
}

function close() {
  dialogRef.value?.close()
}

function choose(id: TabId) {
  emit('select-tab', id)
  close()
}

defineExpose({
  open,
  close,
})
</script>

<template>
  <dialog ref="dialogRef" id="palette" aria-label="搜索与命令">
    <div class="palette-search">
      <span aria-hidden="true">⌕</span>
      <input
        v-model="query"
        placeholder="搜索工作台页面与核心模块…"
        aria-label="搜索命令"
        autocomplete="off"
        @keydown.enter.prevent="results.length && choose(results[0].id)"
      />
      <kbd>Esc</kbd>
    </div>
    <div class="palette-results">
      <button
        v-for="item in results"
        :key="item.id"
        class="command"
        @click="choose(item.id)"
      >
        <span style="font-size: 16px; margin-right: 8px">{{ item.icon }}</span>
        <strong>{{ item.title }}</strong>
        <small>{{ item.subtitle }}</small>
      </button>
      <p v-if="!results.length" class="empty compact">无匹配的页面或命令</p>
    </div>
    <div class="palette-footer">↑ ↓ 选择 · Enter 打开 · Ctrl / ⌘ K 随时唤出全局面板</div>
  </dialog>
</template>
