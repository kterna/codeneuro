<script setup lang="ts">
import type { Ledger, TabId } from '../../types/ledger'

defineProps<{
  ledger: Ledger | null
  activeRequirementsCount: number
  activeTasksCount: number
  contractsCount: number
  pendingProposalsCount: number
}>()

const emit = defineEmits<{
  (e: 'navigate', tabId: TabId): void
}>()
</script>

<template>
  <div id="metrics" class="metrics-strip-compact" role="region" aria-label="项目核心指标概览">
    <div class="metric-pill" title="查看业务需求" @click="emit('navigate', 'tasks')">
      <span class="pill-dot blue"></span>
      <span class="pill-label">活跃需求</span>
      <strong class="pill-value">{{ activeRequirementsCount }}</strong>
    </div>

    <div class="metric-pill" title="查看任务看板" @click="emit('navigate', 'tasks')">
      <span class="pill-dot green"></span>
      <span class="pill-label">进行中任务</span>
      <strong class="pill-value">{{ activeTasksCount }}</strong>
    </div>

    <div class="metric-pill" title="查阅规则库" @click="emit('navigate', 'rules')">
      <span class="pill-dot purple"></span>
      <span class="pill-label">P0 契约</span>
      <strong class="pill-value">{{ contractsCount }}</strong>
    </div>

    <div
      class="metric-pill"
      :class="{ 'has-proposals': pendingProposalsCount > 0 }"
      title="前往变更审阅"
      @click="emit('navigate', 'review')"
    >
      <span class="pill-dot amber"></span>
      <span class="pill-label">待审提案</span>
      <strong class="pill-value">{{ pendingProposalsCount }}</strong>
    </div>

    <div class="metric-pill overview-entry" title="查看完整数据看板" @click="emit('navigate', 'overview')">
      <span class="pill-label">全貌看板 ↗</span>
    </div>
  </div>
</template>

<style scoped>
.metrics-strip-compact {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  flex-wrap: wrap;
  flex-shrink: 0;
}

.metric-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  background: var(--gh-canvas-subtle);
  border: 1px solid var(--gh-border-default);
  border-radius: var(--radius-full);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.12s ease;
  user-select: none;
}

.metric-pill:hover {
  background: var(--gh-surface-card);
  border-color: var(--gh-accent-fg);
  transform: translateY(-1px);
}

.pill-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--gh-fg-subtle);
}

.pill-dot.blue { background: var(--gh-accent-fg); }
.pill-dot.green { background: var(--gh-success-fg); }
.pill-dot.purple { background: var(--gh-done-purple); }
.pill-dot.amber { background: var(--gh-attention-fg); }

.pill-label {
  color: var(--gh-fg-muted);
}

.pill-value {
  color: var(--gh-fg-default);
  font-weight: 600;
  font-family: var(--font-mono);
}

.metric-pill.has-proposals {
  border-color: rgba(210, 153, 34, 0.4);
  background: var(--gh-attention-subtle);
}

.metric-pill.has-proposals .pill-value {
  color: var(--gh-attention-fg);
}

.overview-entry {
  border-style: dashed;
  color: var(--gh-accent-fg);
  margin-left: auto;
}

.overview-entry .pill-label {
  color: var(--gh-accent-fg);
  font-weight: 500;
}
</style>
