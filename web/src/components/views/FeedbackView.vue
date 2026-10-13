<script setup lang="ts">
import type { Ledger } from '../../types/ledger'

defineProps<{
  ledger: Ledger
}>()

function formatFindingStatus(status: string): string {
  const map: Record<string, string> = {
    pending_review: '待审阅',
    active: '生效中',
    archived: '已归档',
  }
  return map[status] || status
}
</script>

<template>
  <div class="feedback-view-root">
    <div class="section-head">
      <div>
        <h2>规则效用反馈与开发便签</h2>
        <span class="caption">查看编码助手对规则的效用评分与实践中记录的开发便签</span>
      </div>
    </div>

    <div class="feedback-dual-grid">
      <!-- 左列：规则评分反馈矩阵 (GitHub 表格清单) -->
      <section class="feedback-card-panel">
        <div class="panel-header-line">
          <h3>规则效用评分 (0~5 分)</h3>
          <span class="muted font-mono">{{ ledger.rules.length }} 条规则</span>
        </div>

        <div class="panel-scroll-table">
          <div v-if="!ledger.rules.length" class="empty compact">暂无规则反馈数据。</div>
          <table v-else class="feedback-table">
            <thead>
              <tr>
                <th>规则标题</th>
                <th style="width: 80px; text-align: center">效用均分</th>
                <th style="width: 120px; min-width: 120px; text-align: right">反馈次数</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="rule in ledger.rules" :key="rule.id">
                <td>
                  <strong class="font-title">{{ rule.title }}</strong>
                  <code class="font-sub-code">{{ rule.patterns[0] || '**' }}</code>
                </td>
                <td style="text-align: center">
                  <span class="score-badge" :class="{ 'has-score': rule.avg_score }">
                    {{ rule.avg_score ?? '—' }}
                  </span>
                </td>
                <td class="feedback-stats-cell">
                  <span class="muted font-mono stat-line">{{ rule.eval_count }} 次反馈</span>
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
          <h3>开发便签</h3>
          <span class="muted font-mono">{{ ledger.findings?.length ?? 0 }} 条便签</span>
        </div>

        <div class="panel-scroll-cards">
          <div v-if="!ledger.findings?.length" class="empty compact">
            当前工程暂无开发便签。编码助手记录的模块便签将展示在此。
          </div>
          <div v-else class="findings-cards-flow">
            <article v-for="f in ledger.findings" :key="f.id" class="gotcha-article">
              <div class="gotcha-header">
                <span class="tag warning">避坑</span>
                <code class="gotcha-path">{{ f.target_path }}</code>
              </div>
              <p class="gotcha-body-text">{{ f.text }}</p>
              <div class="gotcha-footer">
                <span class="muted">关联任务: {{ f.task_id }}</span>
                <span class="tag mini">{{ formatFindingStatus(f.status) }}</span>
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

.feedback-dual-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  flex: 1;
  overflow: hidden;
}

.feedback-card-panel {
  background: var(--color-canvas-subtle);
  border: 1px solid var(--color-border-default);
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.panel-header-line {
  padding: 12px 16px;
  border-bottom: 1px solid var(--color-border-default);
  background: #161b22;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-shrink: 0;
}
.panel-header-line h3 {
  font-size: 13px;
  margin: 0;
  font-weight: 600;
}

.panel-scroll-table, .panel-scroll-cards {
  flex: 1;
  overflow-y: auto;
  padding: 8px 12px;
}

.feedback-table {
  width: 100%;
  border-collapse: collapse;
}
.feedback-table th {
  padding: 8px 10px;
  font-size: 11px;
  color: var(--color-fg-muted);
  border-bottom: 1px solid var(--color-border-default);
  text-align: left;
}
.feedback-table td {
  padding: 10px 10px;
  border-bottom: 1px solid var(--color-border-muted);
  vertical-align: middle;
}

.feedback-stats-cell {
  text-align: right;
  white-space: nowrap;
}

.stat-line {
  display: block;
  white-space: nowrap;
}

.stat-sub-line {
  display: block;
  font-size: 11px;
  color: var(--color-fg-muted);
  white-space: nowrap;
}

.font-title {
  display: block;
  font-size: 12px;
  color: var(--color-fg-default);
}
.font-sub-code {
  font-size: 10px;
  color: var(--color-accent-fg);
}

.score-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--color-canvas-inset);
  color: var(--color-fg-subtle);
  font-weight: 600;
  font-size: 12px;
}
.score-badge.has-score {
  background: var(--color-success-subtle);
  color: var(--color-success-fg);
}

.findings-cards-flow {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.gotcha-article {
  background: var(--color-canvas-inset);
  border: 1px solid var(--color-border-muted);
  border-left: 3px solid var(--color-attention-fg);
  border-radius: 4px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.gotcha-header {
  display: flex;
  align-items: center;
  gap: 8px;
}
.gotcha-path {
  font-size: 11px;
  color: var(--color-fg-default);
  background: rgba(255, 255, 255, 0.05);
  padding: 1px 6px;
  border-radius: 3px;
}

.gotcha-body-text {
  font-size: 12px;
  line-height: 1.6;
  color: var(--color-fg-default);
  margin: 0;
}

.gotcha-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 11px;
  border-top: 1px solid var(--color-border-subtle);
  padding-top: 6px;
}
</style>
