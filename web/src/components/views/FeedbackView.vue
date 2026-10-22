<script setup lang="ts">
import { onMounted, ref } from 'vue'
import type { Finding, Ledger } from '../../types/ledger'
import { apiService } from '../../api/client'
import GhTag from '../ui/GhTag.vue'

const props = defineProps<{
  ledger: Ledger
  projectId: string
  loading?: boolean
}>()
const emit = defineEmits<{ (e: 'refresh'): void }>()

// 进入反馈页时先刷新账本，避免用旧版本提交处置
onMounted(() => emit('refresh'))
const selected = ref<Finding | null>(null)
const topicText = ref('')
const reason = ref('')
const busy = ref(false)
const error = ref('')

function editFinding(finding: Finding) {
  selected.value = finding
  topicText.value = finding.topics.join(', ')
  reason.value = error.value = ''
}

async function saveFinding(resolve: boolean) {
  if (!selected.value || !reason.value.trim()) {
    error.value = '请选择便签并填写理由。'
    return
  }
  busy.value = true
  error.value = ''
  try {
    await apiService.updateFinding(
      props.projectId,
      selected.value.id,
      selected.value.version,
      topicText.value.split(',').map(s => s.trim()).filter(Boolean),
      resolve,
      reason.value
    )
    selected.value = null
    emit('refresh')
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}

function formatFindingStatus(status: string): string {
  const map: Record<string, string> = {
    pending_review: '待审阅',
    active: '生效中',
    archived: '已归档',
    resolved: '已处理',
  }
  return map[status] || '未知状态'
}

const expandedFindings = ref<Set<string>>(new Set())
function toggleExpandFinding(id: string) {
  if (expandedFindings.value.has(id)) {
    expandedFindings.value.delete(id)
  } else {
    expandedFindings.value.add(id)
  }
}
</script>

<template>
  <div class="feedback-view-root">
    <div class="feedback-dual-grid">
      <!-- 左列：规则评分反馈矩阵 (GitHub 表格清单) -->
      <section class="feedback-card-panel">
        <div class="panel-header-line">
          <div class="panel-header-left">
            <span class="panel-icon" aria-hidden="true">📊</span>
            <h2>规则评分（0~5 分）</h2>
          </div>
          <span class="muted font-mono">{{ ledger.rules.length }} 条规则</span>
        </div>

        <div class="panel-scroll-table">
          <div v-if="!ledger.rules.length" class="empty compact">暂无规则评分数据。</div>
          <table v-else class="feedback-table">
            <thead>
              <tr>
                <th>规则 / 适用文件</th>
                <th style="width: 80px; text-align: center">平均分</th>
                <th style="width: 150px; text-align: right">使用情况</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="rule in ledger.rules" :key="rule.id">
                <td>
                  <div class="rule-title-row">
                    <strong class="font-title">{{ rule.title }}</strong>
                    <GhTag v-if="rule.status === 'deprecated'" variant="neutral">已停用</GhTag>
                    <GhTag v-else-if="rule.status === 'revoked'" variant="neutral">已撤销</GhTag>
                  </div>
                  <code class="font-sub-code">
                    {{ rule.is_global ? '全局适用' : rule.patterns[0] || rule.topics.join(', ') || '待分类' }}
                  </code>
                </td>
                <td style="text-align: center">
                  <span class="score-badge" :class="{ 'has-score': rule.avg_score !== null }">
                    {{ rule.avg_score !== null ? rule.avg_score : '—' }}
                  </span>
                </td>
                <td class="feedback-stats-cell">
                  <span class="font-mono stat-line">{{ rule.eval_count }} 次评分</span>
                  <span class="stat-sub-line">推送 {{ rule.delivery_count ?? 0 }} 次</span>
                  <span class="stat-sub-line">已知 {{ rule.known_count }} 次</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- 右列：开发便签 -->
      <section class="feedback-card-panel">
        <div class="panel-header-line">
          <div class="panel-header-left">
            <span class="panel-icon" aria-hidden="true">💡</span>
            <h2>开发便签</h2>
          </div>
          <span class="muted font-mono">{{ ledger.findings?.length ?? 0 }} 条便签</span>
        </div>

        <!-- 便签重新分类 / 处理抽屉卡片 -->
        <div v-if="selected" class="panel finding-triage-panel">
          <div class="triage-panel-header">
            <div class="triage-title-group">
              <span class="triage-badge">处理便签</span>
              <strong class="triage-target">{{ selected.text }} · v{{ selected.version }}</strong>
            </div>
            <button type="button" class="subtle btn-close-triage" aria-label="关闭处置面板" @click="selected = null">✕</button>
          </div>

          <div class="triage-form">
            <label class="form-field-group">
              <span class="field-label-text">
                所属主题
                <span class="field-help">多个主题用逗号分隔</span>
              </span>
              <input v-model="topicText" :disabled="busy" placeholder="例如 frontend-layout" class="gh-input font-mono" />
            </label>

            <label class="form-field-group">
              <span class="field-label-text">
                操作理由
                <span class="field-required">* 必填</span>
              </span>
              <textarea
                v-model="reason"
                :disabled="busy"
                rows="2"
                placeholder="详细说明本次分类调整或标记已处理的原因…"
                class="gh-textarea"
              />
            </label>

            <div class="triage-actions-toolbar">
              <button type="button" class="primary" :disabled="busy || loading" @click="saveFinding(false)">更新分类</button>
              <button type="button" class="success" :disabled="busy || loading" @click="saveFinding(true)">标记已处理</button>
              <button type="button" class="subtle" :disabled="busy" @click="selected = null">取消</button>
            </div>
            <p v-if="error" class="error-box" role="alert">{{ error }}</p>
          </div>
        </div>

        <!-- 便签流清单 -->
        <div class="panel-scroll-cards">
          <div v-if="!ledger.findings?.length" class="empty compact">
            暂无开发便签。
          </div>
          <div v-else class="findings-cards-flow">
            <article
              v-for="f in ledger.findings"
              :key="f.id"
              class="gotcha-article"
              :class="{
                'is-resolved': f.status === 'resolved',
                'is-editing': selected?.id === f.id,
              }"
            >
              <div class="gotcha-header">
                <span class="tag warning">经验</span>
                <code class="gotcha-path">{{ f.target_path || '未关联具体文件' }} · {{ f.topics.join(', ') || '待分类' }}</code>
              </div>
              <p class="gotcha-body-text" :class="{ 'is-clamped': !expandedFindings.has(f.id) && f.text.length > 90 }">
                {{ f.text }}
              </p>
              <button
                v-if="f.text.length > 90"
                type="button"
                class="btn-text-toggle"
                @click="toggleExpandFinding(f.id)"
              >
                {{ expandedFindings.has(f.id) ? '收起详情 ▴' : '展开全文 ▾' }}
              </button>
              <div class="gotcha-footer">
                <span class="muted font-mono">关联任务：{{ f.task_id }}</span>
                <div class="gotcha-footer-actions">
                  <GhTag
                    :variant="f.status === 'resolved' ? 'success' : (f.status === 'pending_review' ? 'amber' : 'neutral')"
                  >
                    {{ formatFindingStatus(f.status) }}
                  </GhTag>
                  <button
                    v-if="f.status === 'pending_review'"
                    type="button"
                    class="subtle btn-triage-trigger"
                    :disabled="busy || loading"
                    @click="editFinding(f)"
                  >
                    重新分类 / 处理
                  </button>
                </div>
              </div>
            </article>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.feedback-view-root {
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.head-title-wrap {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.feedback-view-root .section-head {
  margin-bottom: 0;
}

.feedback-dual-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 16px;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}

.feedback-card-panel {
  background: var(--gh-canvas-subtle);
  border: 1px solid var(--gh-border-default);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

/* 窄屏：上下排列后由整页统一滚动，不再嵌套内部滚轮 */
@media (max-width: 1280px) {
  .feedback-view-root {
    flex: 0 0 auto;
    min-height: 100%;
    overflow: visible;
  }

  .feedback-dual-grid {
    display: flex;
    flex-direction: column;
    flex: 0 0 auto;
    overflow: visible;
  }

  .feedback-card-panel .panel-scroll-table,
  .feedback-card-panel .panel-scroll-cards {
    flex: 0 0 auto;
    overflow: visible;
  }
}

.panel-header-line {
  padding: 12px 16px;
  border-bottom: 1px solid var(--gh-border-default);
  background: var(--gh-canvas-subtle);
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-shrink: 0;
}

.panel-header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.panel-icon {
  font-size: 15px;
}

.panel-header-line h2 {
  font-size: 13px;
  margin: 0;
  font-weight: 600;
  color: var(--gh-fg-default);
}

.panel-scroll-table,
.panel-scroll-cards {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
}

.panel-scroll-table {
  padding: 0 12px 12px;
}

.panel-scroll-cards {
  padding: 12px;
}

/* 规则评分表格 */
.feedback-table {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
}

.feedback-table th {
  position: sticky;
  top: 0;
  z-index: 2;
  padding: 10px 10px;
  font-size: 11px;
  font-weight: 600;
  color: var(--gh-fg-muted);
  background: var(--gh-canvas-subtle);
  border-bottom: 1px solid var(--gh-border-default);
  text-align: left;
}

.feedback-table td {
  padding: 10px 10px;
  border-bottom: 1px solid var(--gh-border-muted);
  vertical-align: middle;
  word-break: break-word;
}

.rule-title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 4px 6px;
}

.rule-title-row .tag {
  flex-shrink: 0;
  margin-top: 1px;
}

.feedback-stats-cell {
  text-align: right;
  white-space: nowrap;
}

.stat-line {
  display: block;
  font-size: 12px;
  font-weight: 500;
  color: var(--gh-fg-default);
  white-space: nowrap;
}

.stat-sub-line {
  display: block;
  font-size: 11px;
  color: var(--gh-fg-muted);
  white-space: nowrap;
}

.font-title {
  display: block;
  font-size: 12px;
  color: var(--gh-fg-default);
  line-height: 1.4;
}

.font-sub-code {
  display: block;
  margin-top: 2px;
  font-size: 11px;
  color: var(--gh-accent-fg);
  font-family: var(--font-mono);
  overflow-wrap: anywhere;
}

.score-badge {
  display: inline-block;
  padding: 3px 8px;
  border-radius: 12px;
  background: var(--gh-canvas-inset);
  color: var(--gh-fg-subtle);
  font-weight: 600;
  font-size: 12px;
  font-family: var(--font-mono);
  border: 1px solid var(--gh-border-muted);
}

.score-badge.has-score {
  background: var(--gh-success-subtle);
  color: var(--gh-success-fg);
  border-color: rgba(46, 160, 67, 0.4);
}

/* 便签处置面板 */
.finding-triage-panel {
  margin: 12px;
  background: var(--gh-canvas-default);
  border: 1px solid var(--gh-accent-fg);
  border-left: 3px solid var(--gh-accent-fg);
  border-radius: 6px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex-shrink: 0;
  box-shadow: 0 4px 12px rgba(1, 4, 9, 0.15);
}

.triage-panel-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 10px;
}

.triage-title-group {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.triage-badge {
  font-size: 11px;
  font-weight: 600;
  background: var(--gh-accent-subtle);
  color: var(--gh-accent-fg);
  padding: 2px 6px;
  border-radius: 4px;
}

.triage-target {
  font-size: 12px;
  color: var(--gh-fg-default);
}

.btn-close-triage {
  padding: 2px 6px;
  font-size: 11px;
}

.triage-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.form-field-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.field-label-text {
  font-size: 12px;
  font-weight: 600;
  color: var(--gh-fg-default);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.field-help {
  font-size: 11px;
  font-weight: normal;
  color: var(--gh-fg-muted);
}

.field-required {
  font-size: 11px;
  font-weight: normal;
  color: var(--gh-danger-fg);
}

.triage-actions-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-top: 4px;
}

/* 便签卡片流 */
.findings-cards-flow {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.gotcha-article {
  background: var(--gh-canvas-default);
  border: 1px solid var(--gh-border-muted);
  border-left: 3px solid var(--gh-attention-fg);
  border-radius: 6px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
  transition: all 0.12s ease;
}

.gotcha-article:hover {
  background: var(--gh-surface-card-hover);
  border-color: var(--gh-border-default);
}

.gotcha-article.is-resolved {
  border-left-color: var(--gh-success-fg);
  opacity: 0.85;
}

.gotcha-article.is-editing {
  border-color: var(--gh-accent-fg);
  background: var(--gh-surface-card);
}

.gotcha-header {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.gotcha-header .tag {
  flex-shrink: 0;
}

.gotcha-path {
  flex: 1 1 auto;
  min-width: 0;
  font-size: 11px;
  line-height: 1.5;
  color: var(--gh-fg-default);
  background: var(--gh-canvas-inset);
  padding: 2px 8px;
  border-radius: 4px;
  border: 1px solid var(--gh-border-muted);
  font-family: var(--font-mono);
  overflow-wrap: anywhere;
  word-break: break-word;
}

.gotcha-body-text {
  font-size: 12px;
  line-height: 1.6;
  color: var(--gh-fg-default);
  margin: 0;
  word-break: break-word;
}

.gotcha-body-text.is-clamped {
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-overflow: ellipsis;
}

.btn-text-toggle {
  align-self: flex-start;
  background: transparent;
  border: 0;
  color: var(--gh-accent-fg);
  font-size: 11px;
  cursor: pointer;
  padding: 0;
  margin: -2px 0 2px;
}
.btn-text-toggle:hover {
  text-decoration: underline;
}

.gotcha-footer {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  font-size: 11px;
  border-top: 1px solid var(--gh-border-muted);
  padding-top: 8px;
  gap: 6px 8px;
  min-width: 0;
}

.gotcha-footer > .muted {
  min-width: 0;
  overflow-wrap: anywhere;
}

.gotcha-footer-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.btn-triage-trigger {
  font-size: 11px;
  padding: 2px 8px;
}

.font-mono {
  font-family: var(--font-mono);
}
</style>
