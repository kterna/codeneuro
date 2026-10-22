<script setup lang="ts">
import type { Ledger, Proposal, ProposalStatus, ValidationSpec } from '../../types/ledger'

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
    case 'approved': return '已通过'
    case 'pending': return '待审阅'
    case 'rejected': return '已拒绝'
    default: return `未知状态（${status}）`
  }
}

function deliveryModeLabel(mode: Proposal['delivery_mode'] | undefined): string {
  switch (mode) {
    case 'full': return '完整条款'
    case 'card': return '一行提示（按需读取正文）'
    default: return '未记录'
  }
}

function isStale(prop: Proposal): boolean {
  if (prop.status !== 'pending') return false
  if (prop.current_target_version === null || prop.current_target_version === undefined) return false
  return prop.current_target_version !== prop.target_version
}

function hasApprovalBlock(prop: Proposal): boolean {
  if (prop.status !== 'pending') return false
  return !prop.source_rule_id || !prop.validation_spec || isStale(prop) ||
    prop.current_target_version === null ||
    prop.current_target_version === undefined ||
    !prop.target_snapshot
}

function formatSpec(spec: ValidationSpec | null | undefined): string {
  if (!spec) return '未记录'
  if (spec.kind === 'review') return `人工审阅：${spec.basis || '未填写依据'}`
  const checks = spec.checks.map(check =>
    `测试 ${check.test_ids.join('、') || '未指定'}（覆盖第 ${check.clause_indexes.map(i => i + 1).join('、') || '—'} 条）`)
  return checks.length ? checks.join('；') : '未记录'
}

function getApprovalBlockReason(prop: Proposal): string {
  if (!prop.source_rule_id || !prop.validation_spec) return '这条建议缺少来源规则或验证方式，请补全后重新提交。'
  if (isStale(prop)) {
    return `提交后规则已更新至 v${prop.current_target_version}，本建议基于 v${prop.target_version}，已过期，不能直接通过。请刷新核对或重新提交。`
  }
  if (prop.current_target_version === null || prop.current_target_version === undefined) {
    return '拿不到规则的最新版本，无法确认改动是否还成立，暂时不能通过。'
  }
  if (!prop.target_snapshot) {
    return '找不到规则的历史版本，无法对比改了什么，暂时不能通过。'
  }
  return ''
}
</script>

<template>
  <div class="review-view-root">
    <div v-if="!ledger.proposals.length" class="empty">
      暂无待审阅的规则修改。
    </div>

    <div v-else class="proposals-list">
      <article v-for="prop in ledger.proposals" :key="prop.id" :data-proposal-id="prop.id" class="card proposal-card">
        <div class="card-head">
          <div class="proposal-title-row">
            <span class="tag" :class="statusBadgeClass(prop.status)">
              {{ statusLabel(prop.status) }}
            </span>
            <h3>{{ prop.title }}</h3>
          </div>
          <span class="caption font-mono">建议编号：{{ prop.id }}</span>
        </div>

        <!-- 目标规则版本信息与仅针对待审建议的过时警示 (D07) -->
        <div class="target-meta-line">
          <span><strong>要修改的规则：</strong><code>{{ prop.target_rule_id }}</code></span>
          <span><strong>建议基于版本：</strong><code>v{{ prop.target_version }}</code></span>
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
          <span class="caption">修改原因：</span>
          <p>{{ prop.reason }}</p>
        </div>

        <p class="caption">来源规则：{{ prop.source_rule_id }} @ {{ prop.source_version }} · 对所有文件生效：{{ prop.target_snapshot?.is_global ? '是' : '否' }} → {{ prop.is_global ? '是' : '否' }}</p>
        <details><summary>验证方式与优先级说明</summary><p>原优先级说明：{{ prop.target_snapshot?.priority_reason || '未记录' }}</p><p>修改后说明：{{ prop.priority_reason || '未记录' }}</p><p>原验证方式：{{ formatSpec(prop.target_snapshot?.validation_spec) }}</p><p>修改后验证方式：{{ formatSpec(prop.validation_spec) }}</p></details>
        <!-- 不回填新分类到历史快照。 -->
        <details class="diff-container panel" :open="prop.status === 'pending'">
          <summary class="diff-summary">
            <strong>修改前后对比（7 项）</strong>
          </summary>

          <div class="diff-body" style="margin-top: 12px">
            <!-- 1. 规则标题 -->
            <div class="diff-field" style="margin-bottom: 12px">
              <span class="caption">1. 规则标题</span>
              <div class="diff-row">
                <span class="diff-before">修改前：{{ prop.target_snapshot?.title || '无历史版本' }}</span>
                <span class="diff-arrow">→</span>
                <span class="diff-after">修改后：{{ prop.title }}</span>
              </div>
            </div>

            <!-- 2 & 3. 优先级与主题，不伪造默认值 -->
            <div class="diff-grid" style="margin-bottom: 12px">
              <div class="diff-field">
                <span class="caption">2. 优先级</span>
                <div class="diff-val-row">
                  <span class="tag neutral">修改前：{{ prop.target_snapshot?.priority || '无历史版本' }}</span>
                  <span class="diff-arrow">→</span>
                  <span class="tag" :class="(prop.priority || prop.target_snapshot?.priority || 'neutral').toLowerCase()">
                    修改后：{{ prop.priority || prop.target_snapshot?.priority || '未修改' }}
                  </span>
                </div>
              </div>

              <div class="diff-field">
                <span class="caption">3. 业务主题</span>
                <div class="diff-val-row">
                  <span class="tag neutral">修改前：{{ prop.target_snapshot?.topics?.join(', ') || '无主题或历史版本' }}</span>
                  <span class="diff-arrow">→</span>
                  <span class="tag neutral">
                    修改后：{{ prop.topics.join(', ') || '无主题' }}
                  </span>
                </div>
              </div>
            </div>

            <!-- 4. 适用文件前后对比 -->
            <div class="diff-field" style="margin-bottom: 12px">
              <span class="caption">4. 适用文件</span>
              <div class="diff-row" style="margin-top: 4px; gap: 16px">
                <div>
                  <span class="caption">修改前：</span>
                  <div class="tags" style="margin-top: 4px">
                    <code v-for="pat in (prop.target_snapshot?.patterns || [])" :key="'orig-' + pat" class="code-badge">
                      {{ pat }}
                    </code>
                    <span v-if="!prop.target_snapshot?.patterns?.length" class="muted">
                      {{ prop.target_snapshot ? '不限文件' : '无历史版本' }}
                    </span>
                  </div>
                </div>
                <span class="diff-arrow" style="align-self: center">→</span>
                <div>
                  <span class="caption">修改后：</span>
                  <div class="tags" style="margin-top: 4px">
                    <code v-for="pat in prop.patterns" :key="'new-' + pat" class="code-badge">
                      {{ pat }}
                    </code>
                    <span v-if="!prop.patterns?.length" class="muted">不限文件</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- 5. 条款清单前后对比 -->
            <div class="diff-field">
              <span class="caption">5. 条款</span>
              <div class="diff-clauses-grid" style="margin-top: 6px">
                <div class="clauses-column">
                  <span class="caption">修改前：</span>
                  <ul class="points-list">
                    <li v-for="(p, i) in (prop.target_snapshot?.points || [])" :key="'orig-pt-' + i">{{ p }}</li>
                    <li v-if="!prop.target_snapshot?.points?.length" class="muted">
                      {{ prop.target_snapshot ? '无条款' : '无历史版本' }}
                    </li>
                  </ul>
                </div>
                <div class="clauses-column">
                  <span class="caption">修改后：</span>
                  <ul class="points-list">
                    <li v-for="(p, i) in prop.points" :key="'new-pt-' + i">{{ p }}</li>
                    <li v-if="!prop.points?.length" class="muted">无条款</li>
                  </ul>
                </div>
              </div>
            </div>
            <!-- 6 & 7. 下发方式与使用时机，缺失的历史字段不回填。 -->
            <div class="diff-grid" style="margin-top: 12px">
              <div class="diff-field" data-field="delivery_mode">
                <span class="caption">6. 下发方式</span>
                <div class="diff-row">
                  <span class="diff-before">修改前：{{ deliveryModeLabel(prop.target_snapshot?.delivery_mode) }}</span>
                  <span class="diff-arrow">→</span>
                  <span class="diff-after">修改后：{{ deliveryModeLabel(prop.delivery_mode) }}</span>
                </div>
              </div>

              <div class="diff-field" data-field="applies_when">
                <span class="caption">7. 使用时机</span>
                <div class="diff-row">
                  <span class="diff-before">修改前：{{ prop.target_snapshot?.applies_when === '' ? '未设置' : (prop.target_snapshot?.applies_when ?? '未记录') }}</span>
                  <span class="diff-arrow">→</span>
                  <span class="diff-after">修改后：{{ prop.applies_when || '未设置' }}</span>
                </div>
              </div>
            </div>
          </div>
        </details>

        <div v-if="prop.decision_reason" class="decision-reason-box">
          <strong>审阅结果：</strong>{{ prop.decision_reason }}
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
            通过修改
          </button>
          <button class="button danger-subtle" :disabled="busy" @click="emit('open-reject', prop)">
            拒绝修改
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
