<script setup lang="ts">
import type { Ledger, Proposal, ProposalStatus } from '../../types/ledger'

defineProps<{
  ledger: Ledger
  busy: boolean
}>()

const emit = defineEmits<{
  (e: 'open-approve', proposal: Proposal): void
  (e: 'open-reject', proposal: Proposal): void
}>()

function statusBadgeClass(status: ProposalStatus | string): string {
  switch (status) {
    case 'approved': return 'success'
    case 'pending': return 'warning'
    case 'rejected': return 'danger'
    default: return 'neutral'
  }
}

function statusLabel(status: ProposalStatus | string): string {
  switch (status) {
    case 'approved': return '已批准'
    case 'pending': return '待审阅'
    case 'rejected': return '已拒绝'
    default: return `未知状态 (${status})`
  }
}

function isStale(prop: Proposal): boolean {
  if (prop.status !== 'pending') return false
  if (prop.current_target_version === null || prop.current_target_version === undefined) return false
  return prop.current_target_version !== prop.target_version
}

function categoryLabel(cat?: string | null): string {
  if (!cat) return ''
  switch (cat) {
    case 'business': return '业务'
    case 'security': return '安全'
    case 'gotcha': return '避坑'
    default: return cat
  }
}

function hasApprovalBlock(prop: Proposal): boolean {
  if (prop.status !== 'pending') return false
  return isStale(prop) ||
    prop.current_target_version === null ||
    prop.current_target_version === undefined ||
    !prop.target_snapshot
}

function getApprovalBlockReason(prop: Proposal): string {
  if (isStale(prop)) {
    return `目标规则已在此提案提交后发生变更（最新版本为 v${prop.current_target_version}，提案基于 v${prop.target_version}）。此提案已过时，无法直接批准，请刷新页面重新核对或要求重新提交。`
  }
  if (prop.current_target_version === null || prop.current_target_version === undefined) {
    return '缺失目标规则当前最新版本信息，无法校验版本基准，禁止批准此变更。'
  }
  if (!prop.target_snapshot) {
    return '缺失目标规则的历史版本快照，无法核对修改基准，禁止批准此变更。'
  }
  return ''
}
</script>

<template>
  <div class="review-view-root">
    <div class="section-head">
      <div>
        <h2>长期契约变更审阅</h2>
        <span class="caption">对比变更前后的标题、优先级、分类、适用路径和条款，再决定是否批准。</span>
      </div>
    </div>

    <div v-if="!ledger.proposals.length" class="empty">
      当前没有待审阅的契约变更提案。
    </div>

    <div v-else class="proposals-list">
      <article v-for="prop in ledger.proposals" :key="prop.id" class="card proposal-card">
        <div class="card-head">
          <div class="proposal-title-row">
            <span class="tag" :class="statusBadgeClass(prop.status)">
              {{ statusLabel(prop.status) }}
            </span>
            <h3>{{ prop.title }}</h3>
          </div>
          <span class="caption font-mono">提案标识: {{ prop.id }}</span>
        </div>

        <!-- 目标契约版本信息与仅针对待审提案的过时警示 (D07) -->
        <div class="target-meta-line">
          <span><strong>目标契约：</strong><code>{{ prop.target_rule_id }}</code></span>
          <span><strong>拟议基础版本：</strong><code>v{{ prop.target_version }}</code></span>
          <span v-if="prop.current_target_version !== null && prop.current_target_version !== undefined">
            <strong>当前最新版本：</strong><code>v{{ prop.current_target_version }}</code>
          </span>
        </div>

        <!-- 仅针对 pending 提案进行警示（版本过时、缺失当前版本或缺失快照） -->
        <div
          v-if="prop.status === 'pending' && hasApprovalBlock(prop)"
          class="error-box"
          style="margin-top: 8px"
          role="alert"
        >
          ⚠️ {{ getApprovalBlockReason(prop) }}
        </div>

        <div class="proposal-reason-box">
          <span class="caption">变更理由与依据：</span>
          <p>{{ prop.reason }}</p>
        </div>

        <!-- 全五项字段的前后完整对比 (title/points/patterns/priority/category)，所有提案均保留，支持 details 折叠 -->
        <details class="diff-container panel" :open="prop.status === 'pending'">
          <summary class="diff-summary">
            <strong>契约变更五项对比</strong>
            <span class="caption muted" style="margin-left: 8px">
              {{ prop.status === 'pending' ? '标题 · 优先级 · 分类 · 路径模式 · 条款' : '点击查看决议前完整五项对比' }}
            </span>
          </summary>

          <div class="diff-body" style="margin-top: 12px">
            <!-- 1. 规则标题 -->
            <div class="diff-field" style="margin-bottom: 12px">
              <span class="caption">1. 规则标题</span>
              <div class="diff-row">
                <span class="diff-before">原标题：{{ prop.target_snapshot?.title || '（无历史快照）' }}</span>
                <span class="diff-arrow">→</span>
                <span class="diff-after">拟议标题：{{ prop.title }}</span>
              </div>
            </div>

            <!-- 2 & 3. 优先级与类别 (不伪造默认值) -->
            <div class="diff-grid" style="margin-bottom: 12px">
              <div class="diff-field">
                <span class="caption">2. 优先级</span>
                <div class="diff-val-row">
                  <span class="tag neutral">原: {{ prop.target_snapshot?.priority || '（无历史快照）' }}</span>
                  <span class="diff-arrow">→</span>
                  <span class="tag" :class="(prop.priority || prop.target_snapshot?.priority || 'neutral').toLowerCase()">
                    拟议: {{ prop.priority || prop.target_snapshot?.priority || '（未变更）' }}
                  </span>
                </div>
              </div>

              <div class="diff-field">
                <span class="caption">3. 规则分类</span>
                <div class="diff-val-row">
                  <span class="tag neutral">原: {{ categoryLabel(prop.target_snapshot?.category) || '（无历史快照）' }}</span>
                  <span class="diff-arrow">→</span>
                  <span class="tag neutral">
                    拟议: {{ categoryLabel(prop.category || prop.target_snapshot?.category) || '（未变更）' }}
                  </span>
                </div>
              </div>
            </div>

            <!-- 4. 管辖模式前后对比 -->
            <div class="diff-field" style="margin-bottom: 12px">
              <span class="caption">4. 管辖路径模式</span>
              <div class="diff-row" style="margin-top: 4px; gap: 16px">
                <div>
                  <span class="caption">原管辖模式：</span>
                  <div class="tags" style="margin-top: 4px">
                    <code v-for="pat in (prop.target_snapshot?.patterns || [])" :key="'orig-' + pat" class="code-badge">
                      {{ pat }}
                    </code>
                    <span v-if="!prop.target_snapshot?.patterns?.length" class="muted">
                      {{ prop.target_snapshot ? '（无路径约束）' : '（无历史快照）' }}
                    </span>
                  </div>
                </div>
                <span class="diff-arrow" style="align-self: center">→</span>
                <div>
                  <span class="caption">拟议管辖模式：</span>
                  <div class="tags" style="margin-top: 4px">
                    <code v-for="pat in prop.patterns" :key="'new-' + pat" class="code-badge">
                      {{ pat }}
                    </code>
                    <span v-if="!prop.patterns?.length" class="muted">（无路径约束）</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- 5. 条款清单前后对比 -->
            <div class="diff-field">
              <span class="caption">5. 生效条款列表</span>
              <div class="diff-clauses-grid" style="margin-top: 6px">
                <div class="clauses-column">
                  <span class="caption">原生效条款：</span>
                  <ul class="points-list">
                    <li v-for="(p, i) in (prop.target_snapshot?.points || [])" :key="'orig-pt-' + i">{{ p }}</li>
                    <li v-if="!prop.target_snapshot?.points?.length" class="muted">
                      {{ prop.target_snapshot ? '（无条款）' : '（无历史快照）' }}
                    </li>
                  </ul>
                </div>
                <div class="clauses-column">
                  <span class="caption">拟议条款：</span>
                  <ul class="points-list">
                    <li v-for="(p, i) in prop.points" :key="'new-pt-' + i">{{ p }}</li>
                    <li v-if="!prop.points?.length" class="muted">（无条款）</li>
                  </ul>
                </div>
              </div>
            </div>
          </div>
        </details>

        <div v-if="prop.decision_reason" class="decision-reason-box">
          <strong>审阅决议结论：</strong>{{ prop.decision_reason }}
          <span v-if="prop.reviewer_id" class="caption" style="margin-left: 8px">
            (审阅人: {{ prop.reviewer_id }})
          </span>
        </div>

        <!-- 只有 pending 状态才显示审批/拒绝按钮 (D06) -->
        <div v-if="prop.status === 'pending'" class="card-footer-actions">
          <button
            class="primary"
            :disabled="busy || hasApprovalBlock(prop)"
            :title="hasApprovalBlock(prop) ? getApprovalBlockReason(prop) : undefined"
            @click="emit('open-approve', prop)"
          >
            批准此变更
          </button>
          <button class="button danger-subtle" :disabled="busy" @click="emit('open-reject', prop)">
            拒绝此提案
          </button>
        </div>
      </article>
    </div>
  </div>
</template>

<style scoped>
.review-view-root {
  display: flex;
  flex-direction: column;
  gap: 16px;
  height: 100%;
}

.proposals-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding-bottom: 24px;
}

.proposal-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.proposal-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.diff-summary {
  cursor: pointer;
  user-select: none;
  font-size: 13px;
  color: var(--gh-fg-default);
}
.diff-summary:hover {
  color: var(--gh-accent-fg);
}

.target-meta-line {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  font-size: 12px;
  color: var(--gh-fg-muted);
}

.proposal-reason-box p {
  margin: 4px 0 0;
  font-size: 13px;
  line-height: 1.5;
}

.diff-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 12px;
}

.diff-row {
  display: flex;
  align-items: baseline;
  gap: 10px;
  font-size: 13px;
  flex-wrap: wrap;
}

.diff-val-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
}

.diff-arrow {
  color: var(--gh-fg-subtle);
  font-weight: bold;
}

.diff-clauses-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 16px;
}

.clauses-column {
  background: var(--gh-canvas-inset);
  padding: 10px 14px;
  border-radius: 6px;
  border: 1px solid var(--gh-border-default);
}

.code-badge {
  font-family: var(--font-mono);
  font-size: 11px;
  background: var(--gh-canvas-inset);
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid var(--gh-border-default);
}

.decision-reason-box {
  background: var(--gh-canvas-inset);
  border-left: 3px solid var(--gh-accent-fg);
  padding: 8px 12px;
  border-radius: 4px;
  font-size: 12px;
}

.card-footer-actions {
  display: flex;
  gap: 10px;
  margin-top: 8px;
}
</style>
