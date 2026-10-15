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

const totalRequirements = computed(() => props.ledger.requirements.length)
const archivedRequirements = computed(() => totalRequirements.value - props.activeRequirementsCount)
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
      <div class="section-title">核心指标与健康度</div>
      <div class="overview-cards-grid">
        <div class="overview-card accent" @click="emit('navigate', 'tasks')">
          <div class="card-head">
            <span class="card-label">活跃业务需求</span>
            <span class="card-icon">▥</span>
          </div>
          <div class="card-value">{{ activeRequirementsCount }}</div>
          <div class="card-meta">
            <span>待交付：{{ activeRequirementsCount }} 项</span>
            <span>已归档：{{ archivedRequirements }} 项</span>
          </div>
          <div class="card-action">前往需求看板 →</div>
        </div>

        <div class="overview-card green" @click="emit('navigate', 'tasks')">
          <div class="card-head">
            <span class="card-label">进行中任务</span>
            <span class="card-icon">⚡</span>
          </div>
          <div class="card-value">{{ activeTasksCount }}</div>
          <div class="card-meta">
            <span>执行中：{{ activeTasksCount }} 个</span>
            <span>任务总数：{{ ledger.tasks.length }} 个</span>
          </div>
          <div class="card-action">查看任务流转 →</div>
        </div>

        <div class="overview-card purple" @click="emit('navigate', 'rules')">
          <div class="card-head">
            <span class="card-label">P0 核心项目契约</span>
            <span class="card-icon">≋</span>
          </div>
          <div class="card-value">{{ contractsCount }}</div>
          <div class="card-meta">
            <span>生效中规则：{{ activeRules }} 条</span>
            <span>规则库总数：{{ totalRules }} 条</span>
          </div>
          <div class="card-action">查阅规则库 →</div>
        </div>

        <div class="overview-card amber" @click="emit('navigate', 'review')">
          <div class="card-head">
            <span class="card-label">待审契约变更</span>
            <span class="card-icon">◈</span>
          </div>
          <div class="card-value" :class="{ 'has-pending': pendingProposalsCount > 0 }">
            {{ pendingProposalsCount }}
          </div>
          <div class="card-meta">
            <span>待人工核准：{{ pendingProposalsCount }} 项</span>
            <span>历史提案：{{ totalProposals }} 项</span>
          </div>
          <div class="card-action">审阅变更提案 →</div>
        </div>
      </div>
    </div>

    <!-- 2. 工程认知与资产全貌双列面板 -->
    <div class="overview-detail-grid">
      <!-- 左列：规则与契约分布 -->
      <div class="detail-panel">
        <div class="panel-header">
          <h3>规则与规范资产分布</h3>
          <button class="subtle" @click="emit('navigate', 'rules')">管理规则</button>
        </div>
        <div class="stat-list">
          <div class="stat-row">
            <span class="stat-name">长期项目契约 (长期生效)</span>
            <strong class="stat-val">{{ ledger.rules.filter(r => !r.task_id).length }}</strong>
          </div>
          <div class="stat-row">
            <span class="stat-name">任务短期规则 (绑定活跃任务)</span>
            <strong class="stat-val">{{ ledger.rules.filter(r => r.task_id).length }}</strong>
          </div>
          <div class="stat-row">
            <span class="stat-name">纯主题规则（无文件锚点）</span>
            <strong class="stat-val">{{ ledger.rules.filter(r => !r.patterns.length && !r.is_global).length }}</strong>
          </div>
          <div class="stat-row">
            <span class="stat-name">待分类验收规则</span>
            <strong class="stat-val">{{ ledger.topic_coverage.rules.length }}</strong>
          </div>
        </div>
      </div>

      <!-- 右列：环境与协同状态 -->
      <div class="detail-panel">
        <div class="panel-header">
          <h3>协同与避坑知识库</h3>
          <button class="subtle" @click="emit('navigate', 'feedback')">查看便签</button>
        </div>
        <div class="stat-list">
          <div class="stat-row">
            <span class="stat-name">避坑便签总数 (Gotcha Findings)</span>
            <strong class="stat-val">{{ totalFindings }}</strong>
          </div>
          <div class="stat-row">
            <span class="stat-name">声明客户端工作区 (Worktrees)</span>
            <strong class="stat-val">{{ totalWorktrees }}</strong>
          </div>
          <div class="stat-row">
            <span class="stat-name">审计流水事件 (Audit Events)</span>
            <strong class="stat-val">{{ totalEvents }}</strong>
          </div>
          <div class="stat-row">
            <span class="stat-name">作用域规则密度 (Scope Regions)</span>
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
  height: 100%;
  overflow-y: auto;
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

.panel-header h3 {
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
  padding-bottom: 8px;
  border-bottom: 1px solid var(--gh-border-muted);
}

.stat-row:last-child {
  border-bottom: none;
  padding-bottom: 0;
}

.stat-name {
  font-size: 12px;
  color: var(--gh-fg-muted);
}

.stat-val {
  font-size: 14px;
  font-family: var(--font-mono);
  color: var(--gh-fg-default);
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
