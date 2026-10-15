<script setup lang="ts">
import { ref, watch } from 'vue'
import { apiService } from '../../api/client'
import type { Ledger, Topic, TopicPage } from '../../types/ledger'

const props = defineProps<{ projectId: string; ledger: Ledger }>()
const emit = defineEmits<{ (e: 'refresh'): void }>()
const page = ref<TopicPage | null>(null)
const search = ref('')
const includeDeleted = ref(false)
const selected = ref<Topic | null>(null)
const key = ref('')
const name = ref('')
const description = ref('')
const reason = ref('')
const busy = ref(false)
const error = ref('')
let sequence = 0

async function load(cursor?: string | null) {
  const request = ++sequence
  try {
    const result = await apiService.getTopics(props.projectId, search.value, includeDeleted.value, cursor)
    if (request === sequence) page.value = result
  } catch (e) {
    if (request === sequence) error.value = e instanceof Error ? e.message : String(e)
  }
}
function reset() {
  selected.value = null
  key.value = name.value = description.value = reason.value = ''
}
watch(() => props.projectId, () => { reset(); error.value = ''; void load() }, { immediate: true })

async function inspect(topic: Topic) {
  busy.value = true
  error.value = ''
  try {
    selected.value = await apiService.getTopic(props.projectId, topic.key)
    key.value = selected.value.key
    name.value = selected.value.name
    description.value = selected.value.description
    reason.value = ''
  } catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}
async function action(kind: 'save' | 'delete' | 'enable') {
  if (!reason.value.trim()) { error.value = '请填写本次操作理由。'; return }
  busy.value = true
  error.value = ''
  try {
    if (kind === 'enable') {
      await apiService.enableTopics(props.projectId, page.value?.taxonomy_revision ?? props.ledger.taxonomy.taxonomy_revision, reason.value)
    } else if (kind === 'delete' && selected.value) {
      await apiService.deleteTopic(props.projectId, selected.value.key, selected.value.version, reason.value)
    } else if (selected.value) {
      await apiService.updateTopic(props.projectId, selected.value.key, {
        expected_version: selected.value.version, name: name.value,
        description: selected.value.definition_locked ? undefined : description.value, reason: reason.value,
      })
    } else {
      await apiService.createTopic(props.projectId, { key: key.value, name: name.value, description: description.value, reason: reason.value })
    }
    reset()
    await load()
    emit('refresh')
  } catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}
</script>

<template>
  <section class="panel topics-panel">
    <div class="section-head">
      <h3>业务主题管理</h3>
      <span class="tag">{{ page?.topic_query_enabled ? '主题查询已启用' : '待分类验收' }}</span>
    </div>
    <p class="caption">key 永久稳定；已使用的业务边界不可直接修改。删除不会级联修改规则，已删除 key 不可复用。</p>
    <div class="toolbar">
      <input v-model="search" aria-label="搜索业务主题" placeholder="主题 key 或名称" @keyup.enter="load()" />
      <label><input v-model="includeDeleted" type="checkbox" @change="load()" />含已删除</label>
      <button type="button" :disabled="busy" @click="load()">查询</button>
      <button type="button" :disabled="busy" @click="reset">新建主题</button>
    </div>
    <p v-if="error" class="error-box" role="alert">{{ error }}</p>
    <ul class="topic-list">
      <li v-for="topic in page?.items" :key="topic.key">
        <button type="button" :disabled="busy" @click="inspect(topic)">{{ topic.name }} · {{ topic.key }}</button>
        <span class="caption">v{{ topic.version }} · {{ topic.status }}</span>
      </li>
    </ul>
    <button v-if="page?.next_cursor" type="button" :disabled="busy" @click="load(page.next_cursor)">下一页</button>
    <form class="topic-form" @submit.prevent="action('save')">
      <label>稳定 key<input v-model="key" required maxlength="64" :disabled="!!selected || busy" placeholder="例如 esign-ca" /></label>
      <label>显示名称<input v-model="name" required maxlength="200" :disabled="busy || selected?.status === 'deleted'" /></label>
      <label>业务边界<textarea v-model="description" required maxlength="2000" :readonly="selected?.definition_locked" :disabled="busy || selected?.status === 'deleted'" /></label>
      <p v-if="selected?.definition_locked" class="caption">该定义已被引用；改变边界需要新建主题，并对知识逐项重新分类。</p>
      <p v-if="selected?.blocking_references" class="caption">阻断引用：规则 {{ selected.blocking_references.rules }}，便签 {{ selected.blocking_references.findings }}，提案 {{ selected.blocking_references.proposals }}。</p>
      <label>操作理由<textarea v-model="reason" required :disabled="busy" /></label>
      <div class="toolbar">
        <button class="primary" :disabled="busy || selected?.status === 'deleted'">{{ selected ? '保存修改' : '创建主题' }}</button>
        <button v-if="selected" type="button" :disabled="busy || !selected.can_delete" @click="action('delete')">删除无在用引用的主题</button>
      </div>
    </form>
    <div v-if="!page?.topic_query_enabled" class="panel">
      <p>未完成分类或验证依据/P0 理由：规则 {{ ledger.topic_coverage.rules.length }} 条，便签 {{ ledger.topic_coverage.findings.length }} 条。</p>
      <p class="caption">先在规则详情、开发便签中逐项完成分类与审阅，再填写理由并确认启用。系统不会自动猜测主题。</p>
      <button type="button" :disabled="busy || !!ledger.topic_coverage.rules.length || !!ledger.topic_coverage.findings.length" @click="action('enable')">确认分类完整，启用主题查询</button>
    </div>
  </section>
</template>

<style scoped>
.topics-panel, .topic-form { display: flex; flex-direction: column; gap: 12px; }
.toolbar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.topic-form label { display: flex; flex-direction: column; gap: 5px; }
.topic-list { max-height: 280px; overflow: auto; padding: 0; list-style: none; }
.topic-list li { display: flex; gap: 12px; align-items: center; margin: 6px 0; }
</style>
