<script setup lang="ts">
import { ref } from 'vue'
import type { Finding, Ledger } from '../../types/ledger'
import { apiService } from '../../api/client'
import GhTag from '../ui/GhTag.vue'

const props = defineProps<{
  ledger: Ledger
  projectId: string
}>()
const emit = defineEmits<{ (e: 'refresh'): void }>()
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
  return map[status] || status
}
</script>

<template>
  <div class="feedback-view-root">
    <div class="section-head">
      <div class="head-title-wrap">
        <h2>规则效用反馈与开发便签</h2>
        <span class="caption">查看编码助手对规则的效用评分与实践中记录的开发便签</span>
      </div>
    </div>

    <div class="feedback-dual-grid">
      <!-- 左列：规则评分反馈矩阵 (GitHub 表格清单) -->
      <section class="feedback-card-panel">
        <div class="panel-header-line">
          <div class="panel-header-left">
            <span class="panel-icon" aria-hidden="true">📊</span>
            <h3>规则效用评分 (0~5 分)</h3>
          </div>
          <span class="muted font-mono">{{ ledger.rules.length }} 条规则</span>
        </div>

        <div class="panel-scroll-table">
          <div v-if="!ledger.rules.length" class="empty compact">暂无规则反馈数据。</div>
          <table v-else class="feedback-table">
            <thead>
              <tr>
                <th>规则标题 / 适用边界</th>
                <th style="width: 80px; text-align: center">效用均分</th>
                <th style="width: 140px; text-align: right">反馈统计</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="rule in ledger.rules" :key="rule.id">
                <td>
                  <strong class="font-title">{{ rule.title }}</strong>
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
                  <span class="font-mono stat-line">{{ rule.eval_count }} 次反馈</span>
                  <span class="stat-sub-line">下发 {{ rule.delivery_count ?? 0 }} 次</span>
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
            <h3>开发便签</h3>
          </div>
          <span class="muted font-mono">{{ ledger.findings?.length ?? 0 }} 条便签</span>
        </div>

        <!-- 便签重新分类 / 处理抽屉卡片 -->
        <div v-if="selected" class="panel finding-triage-panel">
          <div class="triage-panel-header">
            <div class="triage-title-group">
              <span class="triage-badge">便签处置</span>
              <strong class="triage-target">{{ selected.text }} · v{{ selected.version }}</strong>
            </div>
            <button type="button" class="subtle btn-close-triage" aria-label="关闭处置面板" @click="selected = null">✕</button>
          </div>

          <div class="triage-form">
            <label class="form-field-group">
              <span class="field-label-text">
                已登记主题（逗号分隔）
                <span class="field-help">业务主题 key，例如 frontend-layout</span>
              </span>
              <input v-model="topicText" :disabled="busy" class="gh-input font-mono" />
            </label>

            <label class="form-field-group">
              <span class="field-label-text">
                操作理由
                <span class="field-required">* 必须登记审计说明</span>
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
              <button type="button" class="primary" :disabled="busy" @click="saveFinding(false)">更新分类</button>
              <button type="button" class="success" :disabled="busy" @click="saveFinding(true)">标记已处理</button>
              <button type="button" class="subtle" :disabled="busy" @click="selected = null">取消</button>
            </div>
            <p v-if="error" class="error-box" role="alert">{{ error }}</p>
          </div>
        </div>

        <!-- 便签流清单 -->
        <div class="panel-scroll-cards">
          <div v-if="!ledger.findings?.length" class="empty compact">
            当前工程暂无开发便签。编码助手记录的模块便签将展示在此。
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
                <span class="tag warning">避坑</span>
                <code class="gotcha-path">{{ f.target_path || '无文件锚点' }} · {{ f.topics.join(', ') || '待分类' }}</code>
              </div>
              <p class="gotcha-body-text">{{ f.text }}</p>
              <div class="gotcha-footer">
                <span class="muted font-mono">关联任务: {{ f.task_id }}</span>
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
                    :disabled="busy"
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
  gap: 16px;
  height: 100%;
  overflow: hidden;
}

.head-title-wrap {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.feedback-dual-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  flex: 1;
  overflow: hidden;
}

@media (max-width: 880px) {
  .feedback-dual-grid {
    grid-template-columns: 1fr;
    overflow-y: auto;
  }
}

.feedback-card-panel {
  background: var(--gh-canvas-subtle);
  border: 1px solid var(--gh-border-default);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
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

.panel-header-line h3 {
  font-size: 13px;
  margin: 0;
  font-weight: 600;
  color: var(--gh-fg-default);
}

.panel-scroll-table,
.panel-scroll-cards {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}

/* 规则效用表格 */
.feedback-table {
  width: 100%;
  border-collapse: collapse;
}

.feedback-table th {
  padding: 8px 10px;
  font-size: 11px;
  font-weight: 600;
  color: var(--gh-fg-muted);
  border-bottom: 1px solid var(--gh-border-default);
  text-align: left;
}

.feedback-table td {
  padding: 10px 10px;
  border-bottom: 1px solid var(--gh-border-muted);
  vertical-align: middle;
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
  font-size: 11px;
  color: var(--gh-accent-fg);
  font-family: var(--font-mono);
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
  align-items: center;
  gap: 8px;
}

.gotcha-path {
  font-size: 11px;
  color: var(--gh-fg-default);
  background: var(--gh-canvas-inset);
  padding: 2px 8px;
  border-radius: 4px;
  border: 1px solid var(--gh-border-muted);
  font-family: var(--font-mono);
}

.gotcha-body-text {
  font-size: 12px;
  line-height: 1.6;
  color: var(--gh-fg-default);
  margin: 0;
  word-break: break-word;
}

.gotcha-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 11px;
  border-top: 1px solid var(--gh-border-muted);
  padding-top: 8px;
  gap: 8px;
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
