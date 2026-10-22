<script setup lang="ts">
import { computed } from 'vue'
import type { Ledger, TabId } from '../../types/ledger'

const props = defineProps<{
  ledger: Ledger
  activeRequirementsCount: number
  activeTasksCount: number
  contractsCount: number
  pendingProposalsCount: number
}>()

const emit = defineEmits<{
  (e: 'navigate', tabId: TabId): void
}>()

const archivedRequirements = computed(() => props.ledger.counts.requirements.archived)
const totalRules = computed(() => props.ledger.rules.length)
const activeRules = computed(() => props.ledger.rules.filter(r => r.status === 'active').length)
const totalFindings = computed(() => props.ledger.findings?.length ?? 0)
const totalWorktrees = computed(() => props.ledger.worktrees.length)
const totalProposals = computed(() => props.ledger.proposals.length)
const totalEvents = computed(() => props.ledger.events?.length ?? 0)
</script>

<template>
  <div class="overview-view-root">
    <!-- 1. 核心业务健康度 4 维大卡片 -->
    <div class="overview-section">
      <div class="section-title">核心指标</div>
      <div class="overview-cards-grid">
        <button type="button" class="overview-card accent" @click="emit('navigate', 'tasks')">
          <div class="card-head">
            <span class="card-label">进行中的需求</span>
            <span class="card-icon">▥</span>
          </div>
          <div class="card-value">{{ activeRequirementsCount }}</div>
          <div class="card-meta">
            <span>待交付 {{ activeRequirementsCount }} 项 · 已归档 {{ archivedRequirements }} 项</span>
          </div>
          <div class="card-action">查看需求与任务 →</div>
        </button>

        <button type="button" class="overview-card green" @click="emit('navigate', 'tasks')">
          <div class="card-head">
            <span class="card-label">进行中任务</span>
            <span class="card-icon">⚡</span>
          </div>
          <div class="card-value">{{ activeTasksCount }}</div>
          <div class="card-meta">
            <span>执行中 {{ activeTasksCount }} 个 · 任务总数 {{ ledger.counts.tasks.total }} 个</span>
          </div>
          <div class="card-action">查看任务 →</div>
        </button>

        <button type="button" class="overview-card purple" @click="emit('navigate', 'rules')">
          <div class="card-head">
            <span class="card-label">P0 核心规则</span>
            <span class="card-icon">≋</span>
          </div>
          <div class="card-value">{{ contractsCount }}</div>
          <div class="card-meta">
            <span>生效中 {{ activeRules }} 条 · 全部规则 {{ totalRules }} 条</span>
          </div>
          <div class="card-action">查看规则库 →</div>
        </button>

        <button type="button" class="overview-card amber" @click="emit('navigate', 'review')">
          <div class="card-head">
            <span class="card-label">待审规则修改</span>
            <span class="card-icon">◈</span>
          </div>
          <div class="card-value" :class="{ 'has-pending': pendingProposalsCount > 0 }">
            {{ pendingProposalsCount }}
          </div>
          <div class="card-meta">
            <span>待处理 {{ pendingProposalsCount }} 项 · 历史建议 {{ totalProposals }} 项</span>
          </div>
          <div class="card-action">前往审阅 →</div>
        </button>
      </div>
    </div>

    <!-- 2. 工程认知与资产全貌双列面板 -->
    <div class="overview-detail-grid">
      <!-- 左列：规则与契约分布 -->
      <div class="detail-panel">
        <div class="panel-header">
          <h2>规则分布</h2>
          <button class="subtle" @click="emit('navigate', 'rules')">管理规则</button>
        </div>
        <div class="stat-list">
          <div class="stat-row">
            <span class="stat-name">长期规则</span>
            <strong class="stat-val">{{ ledger.rules.filter(r => !r.task_id).length }}</strong>
          </div>
          <div class="stat-row">
            <span class="stat-name">任务规则</span>
            <strong class="stat-val">{{ ledger.rules.filter(r => r.task_id).length }}</strong>
          </div>
          <div class="stat-row">
            <span class="stat-name">主题规则</span>
            <strong class="stat-val">{{ ledger.rules.filter(r => !r.patterns.length && !r.is_global).length }}</strong>
          </div>
          <div class="stat-row">
            <span class="stat-name">待归类规则</span>
            <strong class="stat-val">{{ ledger.topic_coverage.rules.length }}</strong>
          </div>
        </div>
      </div>

      <!-- 右列：环境与协同状态 -->
      <div class="detail-panel">
        <div class="panel-header">
          <h2>便签与统计</h2>
          <button class="subtle" @click="emit('navigate', 'feedback')">查看便签</button>
        </div>
        <div class="stat-list">
          <div class="stat-row">
            <span class="stat-name">经验便签</span>
            <strong class="stat-val">{{ totalFindings }}</strong>
          </div>
          <div class="stat-row">
            <span class="stat-name">已登记的工作区</span>
            <strong class="stat-val">{{ totalWorktrees }}</strong>
          </div>
          <div class="stat-row">
            <span class="stat-name">操作记录</span>
            <strong class="stat-val">{{ totalEvents }}</strong>
          </div>
          <div class="stat-row">
            <span class="stat-name">规则覆盖目录</span>
            <strong class="stat-val">{{ ledger.scope_density?.length ?? 0 }}</strong>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.overview-view-root {
  display: flex;
  flex-direction: column;
  gap: 20px;
  min-height: 100%;
  padding-bottom: 24px;
}

.overview-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--gh-fg-muted);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.overview-cards-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
}

.overview-card {
  background: var(--gh-canvas-subtle);
  border: 1px solid var(--gh-border-default);
  border-radius: var(--radius-md);
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  justify-content: flex-start;
  width: 100%;
  text-align: left;
  gap: 6px;
  cursor: pointer;
  transition: transform 0.15s ease, border-color 0.15s ease, background 0.15s ease;
  position: relative;
  overflow: hidden;
}

.overview-card:hover {
  transform: translateY(-2px);
  border-color: var(--gh-accent-fg);
  background: var(--gh-surface-card);
}

.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.card-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--gh-fg-muted);
}

.card-icon {
  font-size: 14px;
  color: var(--gh-fg-subtle);
}

.card-value {
  font-size: 32px;
  font-weight: 700;
  color: var(--gh-fg-default);
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
  margin: 4px 0;
}

.card-value.has-pending {
  color: var(--gh-attention-fg);
}

.card-meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 11px;
  color: var(--gh-fg-subtle);
}

.card-action {
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px solid var(--gh-border-muted);
  font-size: 11px;
  color: var(--gh-accent-fg);
  font-weight: 500;
}

.overview-detail-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
}

.detail-panel {
  background: var(--gh-canvas-subtle);
  border: 1px solid var(--gh-border-default);
  border-radius: var(--radius-md);
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.panel-header h2 {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
}

.stat-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.stat-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 10px;
  border-radius: 6px;
  transition: background 0.12s ease;
}

.stat-row:hover {
  background: var(--gh-surface-card);
}

.stat-name {
  font-size: 12px;
  color: var(--gh-fg-muted);
}

.stat-val {
  font-size: 12px;
  font-family: var(--font-mono);
  color: var(--gh-fg-default);
  background: var(--gh-canvas-inset);
  padding: 2px 8px;
  border-radius: 10px;
  border: 1px solid var(--gh-border-muted);
}

@media (max-width: 1024px) {
  .overview-cards-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .overview-detail-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .overview-cards-grid {
    grid-template-columns: 1fr;
  }
}
</style>
