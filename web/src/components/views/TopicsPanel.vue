<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { apiService } from '../../api/client'
import type { Ledger, Topic, TopicPage } from '../../types/ledger'
import GhTag from '../ui/GhTag.vue'

const props = defineProps<{ projectId: string; ledger: Ledger }>()
const emit = defineEmits<{ (e: 'refresh'): void }>()
const page = ref<TopicPage | null>(null)
const search = ref('')
const includeDeleted = ref(false)
const selected = ref<Topic | null>(null)
const mode = ref<'none' | 'create' | 'edit'>('none')
const key = ref('')
const name = ref('')
const description = ref('')
const reason = ref('')
const enableReason = ref('')
const busy = ref(false)
const error = ref('')
let sequence = 0

const isClassificationComplete = computed(() => {
  return !props.ledger.topic_coverage.rules.length && !props.ledger.topic_coverage.findings.length
})

const hasBlockingReferences = computed(() => {
  if (!selected.value || selected.value.status === 'deleted') return false
  const refs = selected.value.blocking_references
  return Boolean(refs && (refs.rules > 0 || refs.findings > 0 || refs.proposals > 0))
})

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
  mode.value = 'none'
}

function startCreate() {
  selected.value = null
  key.value = name.value = description.value = reason.value = ''
  mode.value = 'create'
  error.value = ''
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
    mode.value = 'edit'
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}

async function action(kind: 'save' | 'delete' | 'enable') {
  if (kind === 'enable') {
    if (!enableReason.value.trim()) {
      error.value = '请填写启用理由。'
      return
    }
  } else {
    if (!reason.value.trim()) {
      error.value = '请填写本次操作理由。'
      return
    }
  }

  busy.value = true
  error.value = ''
  try {
    if (kind === 'enable') {
      await apiService.enableTopics(
        props.projectId,
        page.value?.taxonomy_revision ?? props.ledger.taxonomy.taxonomy_revision,
        enableReason.value
      )
      enableReason.value = ''
      reset()
      await load()
      emit('refresh')
    } else if (kind === 'delete' && selected.value) {
      await apiService.deleteTopic(props.projectId, selected.value.key, selected.value.version, reason.value)
      reset()
      await load()
      emit('refresh')
    } else if (selected.value) {
      await apiService.updateTopic(props.projectId, selected.value.key, {
        expected_version: selected.value.version,
        name: name.value,
        description: selected.value.definition_locked ? undefined : description.value,
        reason: reason.value,
      })
      reset()
      await load()
      emit('refresh')
    } else {
      await apiService.createTopic(props.projectId, {
        key: key.value,
        name: name.value,
        description: description.value,
        reason: reason.value,
      })
      reset()
      await load()
      emit('refresh')
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="panel topics-panel">
    <!-- 顶部状态栏与核心约束声明 -->
    <header class="topics-header">
      <div class="topics-header-title-row">
        <div class="topics-title-group">
          <span class="topics-icon-badge" aria-hidden="true">🏷️</span>
          <div>
            <h3 class="topics-title">业务主题管理</h3>
            <span class="topics-subtitle">领域知识分类体系 (Topics Taxonomy)</span>
          </div>
        </div>
        <div class="topics-status-badge">
          <GhTag :variant="page?.topic_query_enabled ? 'success' : 'amber'">
            {{ page?.topic_query_enabled ? '主题查询已启用' : '待分类验收' }}
          </GhTag>
        </div>
      </div>
      <p class="caption topics-notice-text">
        key 永久稳定；已使用的业务边界不可直接修改。删除不会级联修改规则，已删除 key 不可复用。
      </p>
    </header>

    <!-- 准入验收卡片：当主题查询未启用时展示 -->
    <div v-if="!page?.topic_query_enabled" class="cutover-callout-card">
      <div class="cutover-card-header">
        <div class="cutover-indicator">
          <span class="cutover-dot" :class="{ ready: isClassificationComplete }"></span>
          <strong>主题检索准入验收</strong>
        </div>
        <span class="cutover-stats-pill">
          规则 {{ ledger.topic_coverage.rules.length }} 条 · 便签 {{ ledger.topic_coverage.findings.length }} 条
        </span>
      </div>

      <div class="cutover-body">
        <p class="cutover-desc">
          未完成分类或验证依据/P0 理由：规则 {{ ledger.topic_coverage.rules.length }} 条，便签 {{ ledger.topic_coverage.findings.length }} 条。
        </p>
        <p class="caption cutover-instruction">
          先在规则详情、开发便签中逐项完成分类与审阅，再填写理由并确认启用。系统不会自动猜测主题。
        </p>
      </div>

      <!-- 独立启用理由输入区：分类完整后支持填写理由并启用 -->
      <div class="cutover-reason-box">
        <label class="form-field-group">
          <span class="field-title">
            <span>启用理由</span>
            <span class="field-required">* 必须登记全量主题查询启用审计理由</span>
          </span>
          <textarea
            v-model="enableReason"
            :disabled="busy || !isClassificationComplete"
            rows="2"
            placeholder="请确认存量规则与便签分类均已完成，并详实填写启用主题检索的审计理由…"
            class="gh-textarea cutover-reason-textarea"
          />
        </label>
      </div>

      <div class="cutover-action-row">
        <button
          type="button"
          class="primary btn-enable-topics"
          :disabled="busy || !isClassificationComplete || !enableReason.trim()"
          @click="action('enable')"
        >
          确认分类完整，启用主题查询
        </button>
      </div>
    </div>

    <!-- 错误反馈浮条 -->
    <p v-if="error" class="error-box" role="alert">{{ error }}</p>

    <!-- 工作台双栏布局：左侧主题目录与搜索，右侧检视与编辑 -->
    <div class="topics-workbench-grid">
      <!-- 左列：主题索引目录 -->
      <div class="topics-sidebar-column">
        <!-- 搜索与操作过滤栏 -->
        <div class="toolbar topics-toolbar">
          <div class="search-input-wrap">
            <span class="search-icon" aria-hidden="true">🔍</span>
            <input
              v-model="search"
              aria-label="搜索业务主题"
              placeholder="主题 key 或名称…"
              class="topics-search-input"
              @keyup.enter="load()"
            />
          </div>
          <div class="toolbar-actions-row">
            <label class="deleted-checkbox-label">
              <input v-model="includeDeleted" type="checkbox" @change="load()" />
              <span>含已删除</span>
            </label>
            <div class="toolbar-btn-group">
              <button type="button" class="subtle btn-search" :disabled="busy" @click="load()">查询</button>
              <button type="button" class="primary btn-create-new" :disabled="busy" @click="startCreate">
                ＋ 新建主题
              </button>
            </div>
          </div>
        </div>

        <!-- 主题条目列表 -->
        <div class="topics-list-container">
          <div v-if="!page?.items?.length" class="topics-empty-state">
            <span class="empty-icon">📭</span>
            <span>暂无符合条件的主题</span>
          </div>
          <ul v-else class="topic-list">
            <li
              v-for="topic in page?.items"
              :key="topic.key"
              class="topic-list-row"
              :class="{
                'is-selected': selected?.key === topic.key,
                'is-deleted': topic.status === 'deleted',
              }"
            >
              <div class="topic-item-card">
                <button
                  type="button"
                  class="topic-inspect-btn"
                  :disabled="busy"
                  @click="inspect(topic)"
                >{{ topic.name }} · {{ topic.key }}</button>
                <div class="topic-item-meta">
                  <span v-if="topic.definition_locked" class="topic-lock-pill" title="已锁定边界">🔒 边界锁定</span>
                  <span class="caption topic-meta-tags">v{{ topic.version }} · {{ topic.status }}</span>
                </div>
              </div>
            </li>
          </ul>

          <div v-if="page?.next_cursor" class="topics-pagination-wrap">
            <button type="button" class="subtle btn-next-page" :disabled="busy" @click="load(page.next_cursor)">
              加载下一页 ↓
            </button>
          </div>
        </div>
      </div>

      <!-- 右列：检视与编辑卡片 (或默认克制空态) -->
      <div class="topics-editor-column">
        <!-- 未选择主题时的克制空态展示 -->
        <div v-if="mode === 'none'" class="topics-empty-selection">
          <span class="empty-icon" aria-hidden="true">📋</span>
          <h4 class="empty-title">未选择业务主题</h4>
          <p class="caption empty-desc">
            请在左侧列表中点击主题条目查看详情与引用状态，或点击下方按钮登记新的业务边界。
          </p>
          <button type="button" class="primary btn-start-create" :disabled="busy" @click="startCreate">
            ＋ 新建主题
          </button>
        </div>

        <!-- 新建或详情修改表单卡片 -->
        <div v-else class="topic-editor-card">
          <div class="editor-card-header">
            <div class="editor-header-left">
              <h4 class="editor-heading">
                {{ selected ? '主题详情与定义修改' : '新建业务主题' }}
              </h4>
              <span v-if="selected" class="editor-key-pill">
                <code>{{ selected.key }}</code>
              </span>
            </div>
            <div v-if="selected" class="editor-header-tags">
              <GhTag :variant="selected.status === 'deleted' ? 'danger' : 'neutral'">
                {{ selected.status === 'deleted' ? '已标记删除' : '生效中' }}
              </GhTag>
              <GhTag v-if="selected.definition_locked" variant="amber">
                定义已锁定
              </GhTag>
            </div>
          </div>

          <form class="topic-form" @submit.prevent="action('save')">
            <!-- 稳定 key -->
            <label class="form-field-group">
              <span class="field-title">
                <span>稳定 key</span>
                <span class="field-help-inline">项目内唯一，创建后永久不可变</span>
              </span>
              <input
                v-model="key"
                required
                maxlength="64"
                :disabled="!!selected || busy"
                placeholder="例如 esign-ca、frontend-layout"
                class="gh-input font-mono"
              />
            </label>

            <!-- 显示名称 -->
            <label class="form-field-group">
              <span class="field-title">
                <span>显示名称</span>
                <span class="field-help-inline">业务人员与开发者可读的规范名称</span>
              </span>
              <input
                v-model="name"
                required
                maxlength="200"
                :disabled="busy || selected?.status === 'deleted'"
                placeholder="例如 电子签章核心"
                class="gh-input"
              />
            </label>

            <!-- 业务边界 -->
            <label class="form-field-group">
              <span class="field-title">
                <span>业务边界</span>
                <span class="field-help-inline">该主题管辖的职责范畴与排他边界 (引用后锁定)</span>
              </span>
              <textarea
                v-model="description"
                required
                maxlength="2000"
                :readonly="selected?.definition_locked"
                :disabled="busy || selected?.status === 'deleted'"
                rows="4"
                placeholder="详细描述此业务主题覆盖的系统模块、业务语义与排他边界…"
                class="gh-textarea font-body"
              />
            </label>

            <!-- 边界锁定警告提示 -->
            <div v-if="selected?.definition_locked" class="definition-lock-callout">
              <span class="lock-icon" aria-hidden="true">🔒</span>
              <div class="lock-text">
                <strong>该定义已被引用；改变边界需要新建主题，并对知识逐项重新分类。</strong>
                <p class="caption lock-subtext">保护历史知识库审计一致性，防止边界漂移导致归属规则失效。</p>
              </div>
            </div>

            <!-- 阻断引用提示：仅在存在在用引用计数时展示，删除态不借 can_delete=false 冒充引用阻断 -->
            <div v-if="hasBlockingReferences && selected?.blocking_references" class="blocking-refs-callout">
              <span class="ref-icon" aria-hidden="true">🛡️</span>
              <div class="ref-text">
                <strong>阻断引用：规则 {{ selected.blocking_references.rules }}，便签 {{ selected.blocking_references.findings }}，提案 {{ selected.blocking_references.proposals }}。</strong>
                <p class="caption ref-subtext">存在在用引用的主题无法删除，必须先将关联规则/便签重新分类。</p>
              </div>
            </div>

            <!-- 操作理由 (审计必须) -->
            <label class="form-field-group">
              <span class="field-title">
                <span>操作理由</span>
                <span class="field-required">* 必须登记操作审计原因</span>
              </span>
              <textarea
                v-model="reason"
                required
                :disabled="busy"
                rows="3"
                placeholder="请如实记录本次新建、修改或删除此主题的业务背景与理由…"
                class="gh-textarea"
              />
            </label>

            <!-- 底部操作按钮栏 -->
            <div class="toolbar form-actions-toolbar">
              <button
                class="primary btn-submit-topic"
                type="submit"
                :disabled="busy || selected?.status === 'deleted'"
              >
                {{ selected ? '保存修改' : '创建主题' }}
              </button>

              <button
                v-if="selected"
                type="button"
                class="danger btn-delete-topic"
                :disabled="busy || !selected.can_delete"
                @click="action('delete')"
              >
                删除无在用引用的主题
              </button>

              <button
                type="button"
                class="subtle btn-cancel"
                :disabled="busy"
                @click="reset"
              >
                {{ selected ? '取消选中' : '取消' }}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.topics-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
  background: var(--gh-canvas-subtle);
  border: 1px solid var(--gh-border-default);
  border-radius: 8px;
  padding: 20px;
  min-width: 0;
  max-width: 100%;
  box-sizing: border-box;
}

/* 顶部标题栏 */
.topics-header {
  display: flex;
  flex-direction: column;
  gap: 8px;
  border-bottom: 1px solid var(--gh-border-muted);
  padding-bottom: 14px;
}

.topics-header-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.topics-title-group {
  display: flex;
  align-items: center;
  gap: 10px;
}

.topics-icon-badge {
  font-size: 20px;
  line-height: 1;
}

.topics-title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--gh-fg-default);
}

.topics-subtitle {
  font-size: 12px;
  color: var(--gh-fg-muted);
}

.topics-notice-text {
  margin: 0;
  color: var(--gh-fg-muted);
  font-size: 12px;
  line-height: 1.5;
}

/* 准入卡片 */
.cutover-callout-card {
  background: var(--gh-canvas-default);
  border: 1px solid var(--gh-attention-fg);
  border-left: 4px solid var(--gh-attention-fg);
  border-radius: 6px;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
}

.cutover-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.cutover-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--gh-fg-default);
}

.cutover-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--gh-attention-fg);
  display: inline-block;
}

.cutover-dot.ready {
  background: var(--gh-success-fg);
}

.cutover-stats-pill {
  font-size: 11px;
  font-family: var(--font-mono);
  background: var(--gh-attention-subtle);
  color: var(--gh-attention-fg);
  padding: 2px 8px;
  border-radius: 12px;
  font-weight: 600;
}

.cutover-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.cutover-desc {
  margin: 0;
  font-size: 12px;
  color: var(--gh-fg-default);
  font-weight: 500;
}

.cutover-instruction {
  margin: 0;
  font-size: 11px;
  color: var(--gh-fg-muted);
  line-height: 1.4;
}

.cutover-reason-box {
  margin-top: 4px;
  padding-top: 8px;
  border-top: 1px solid var(--gh-border-muted);
}

.cutover-reason-textarea {
  min-width: 0;
  width: 100%;
}

.cutover-action-row {
  display: flex;
  justify-content: flex-end;
  padding-top: 4px;
}

/* 双栏工作台：在1080px以下平滑退化为单列，避免900/1024等宽度横向溢出 */
.topics-workbench-grid {
  display: grid;
  grid-template-columns: minmax(260px, 1fr) minmax(340px, 1.4fr);
  gap: 16px;
  align-items: start;
  min-width: 0;
}

@media (max-width: 1080px) {
  .topics-workbench-grid {
    grid-template-columns: 1fr;
  }
}

/* 左侧目录栏 */
.topics-sidebar-column {
  display: flex;
  flex-direction: column;
  gap: 10px;
  background: var(--gh-canvas-default);
  border: 1px solid var(--gh-border-default);
  border-radius: 6px;
  padding: 12px;
  min-width: 0;
}

.topics-toolbar {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.search-input-wrap {
  position: relative;
  width: 100%;
}

.search-icon {
  position: absolute;
  left: 8px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 11px;
  color: var(--gh-fg-muted);
  pointer-events: none;
}

.topics-search-input {
  width: 100%;
  padding-left: 26px !important;
  font-size: 12px;
  box-sizing: border-box;
}

.toolbar-actions-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.deleted-checkbox-label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--gh-fg-muted);
  cursor: pointer;
  user-select: none;
  white-space: nowrap;
}

.toolbar-btn-group {
  display: flex;
  align-items: center;
  gap: 6px;
}

.btn-search {
  padding: 4px 10px;
}

.btn-create-new {
  padding: 4px 12px;
  white-space: nowrap;
}

/* 主题列表 */
.topics-list-container {
  display: flex;
  flex-direction: column;
  min-height: 200px;
  min-width: 0;
}

.topics-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 32px 16px;
  color: var(--gh-fg-muted);
  font-size: 12px;
  gap: 8px;
}

.empty-icon {
  font-size: 24px;
}

.topic-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 380px;
  overflow-y: auto;
  min-width: 0;
}

.topic-list-row {
  margin: 0;
  padding: 0;
  min-width: 0;
}

.topic-item-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  background: var(--gh-canvas-subtle);
  border: 1px solid var(--gh-border-muted);
  border-radius: 6px;
  padding: 8px 10px;
  transition: all 0.12s ease;
  min-width: 0;
}

.topic-item-card:hover {
  background: var(--gh-surface-card-hover);
  border-color: var(--gh-border-default);
}

.topic-list-row.is-selected .topic-item-card {
  background: var(--gh-surface-card);
  border-color: var(--gh-accent-fg);
  border-left: 3px solid var(--gh-accent-fg);
  box-shadow: inset 0 0 0 1px var(--gh-accent-subtle);
}

.topic-list-row.is-deleted .topic-item-card {
  opacity: 0.65;
  border-style: dashed;
}

.topic-inspect-btn {
  width: 100%;
  text-align: left;
  background: transparent;
  border: none;
  padding: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--gh-fg-default);
  cursor: pointer;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.topic-inspect-btn:hover {
  color: var(--gh-accent-fg);
}

.topic-item-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 11px;
}

.topic-lock-pill {
  font-size: 10px;
  color: var(--gh-attention-fg);
}

.topic-meta-tags {
  font-size: 10px;
  color: var(--gh-fg-muted);
}

.topics-pagination-wrap {
  margin-top: 8px;
  text-align: center;
}

.btn-next-page {
  width: 100%;
  font-size: 11px;
}

/* 右侧表单编辑卡片 / 克制空态展示 */
.topics-editor-column {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.topics-empty-selection {
  background: var(--gh-canvas-default);
  border: 1px dashed var(--gh-border-default);
  border-radius: 6px;
  padding: 36px 24px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  gap: 10px;
  color: var(--gh-fg-muted);
}

.empty-title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--gh-fg-default);
}

.empty-desc {
  margin: 0;
  font-size: 12px;
  max-width: 320px;
  line-height: 1.5;
}

.btn-start-create {
  margin-top: 6px;
}

.topic-editor-card {
  background: var(--gh-canvas-default);
  border: 1px solid var(--gh-border-default);
  border-radius: 6px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-width: 0;
}

.editor-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid var(--gh-border-muted);
  padding-bottom: 10px;
  gap: 8px;
  flex-wrap: wrap;
}

.editor-header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.editor-heading {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--gh-fg-default);
}

.editor-key-pill code {
  font-size: 11px;
  padding: 1px 6px;
  background: var(--gh-canvas-inset);
  border: 1px solid var(--gh-border-default);
  border-radius: 4px;
}

.editor-header-tags {
  display: flex;
  gap: 6px;
}

/* 表单内部元素 */
.topic-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-width: 0;
}

.form-field-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.field-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--gh-fg-default);
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 4px;
}

.field-help-inline {
  font-size: 11px;
  font-weight: normal;
  color: var(--gh-fg-muted);
  word-break: break-word;
}

.field-required {
  font-size: 11px;
  font-weight: normal;
  color: var(--gh-danger-fg);
  word-break: break-word;
}

.gh-input,
.gh-textarea {
  width: 100%;
  box-sizing: border-box;
  min-width: 0;
}

.font-mono {
  font-family: var(--font-mono);
}

.font-body {
  line-height: 1.5;
}

/* 提示卡片 */
.definition-lock-callout,
.blocking-refs-callout {
  border-radius: 6px;
  padding: 10px 12px;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  font-size: 12px;
  min-width: 0;
}

.definition-lock-callout {
  background: var(--gh-attention-subtle);
  border: 1px solid rgba(187, 128, 9, 0.35);
  color: var(--gh-attention-fg);
}

.blocking-refs-callout {
  background: var(--gh-accent-subtle);
  border: 1px solid rgba(56, 139, 253, 0.35);
  color: var(--gh-accent-fg);
}

.lock-icon,
.ref-icon {
  font-size: 14px;
  line-height: 1.4;
}

.lock-text,
.ref-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.lock-subtext,
.ref-subtext {
  margin: 0;
  font-size: 11px;
  opacity: 0.85;
}

/* 操作按钮工具条 */
.form-actions-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
  padding-top: 10px;
  border-top: 1px solid var(--gh-border-muted);
}

.btn-submit-topic {
  min-width: 90px;
}

.btn-delete-topic {
  border-color: rgba(248, 81, 73, 0.4);
}

.btn-cancel {
  margin-left: auto;
}
</style>
