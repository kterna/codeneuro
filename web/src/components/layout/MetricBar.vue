<script setup lang="ts">
import type { Ledger, TabId } from '../../types/ledger'

defineProps<{
  ledger: Ledger | null
  title: string
  currentTab: TabId
  refreshing: boolean
  activeRequirementsCount: number
  activeTasksCount: number
  contractsCount: number
  pendingProposalsCount: number
}>()

const emit = defineEmits<{
  (e: 'navigate', tabId: TabId): void
  (e: 'refresh'): void
}>()
</script>

<template>
  <div id="metrics" class="metrics-strip-compact" role="region" aria-label="项目概况与快捷入口">
    <h1 id="title" class="strip-title">{{ title }}</h1>

    <div class="pill-set">
      <div class="metric-pill" title="查看需求" @click="emit('navigate', 'tasks')">
        <span class="pill-dot blue"></span>
        <span class="pill-label">进行中需求</span>
        <strong class="pill-value">{{ activeRequirementsCount }}</strong>
      </div>

      <div class="metric-pill" title="查看任务看板" @click="emit('navigate', 'tasks')">
        <span class="pill-dot green"></span>
        <span class="pill-label">进行中任务</span>
        <strong class="pill-value">{{ activeTasksCount }}</strong>
      </div>

      <div class="metric-pill" title="P0：最高优先级规则" @click="emit('navigate', 'rules')">
        <span class="pill-dot purple"></span>
        <span class="pill-label">P0 规则</span>
        <strong class="pill-value">{{ contractsCount }}</strong>
      </div>

      <div
        class="metric-pill"
        :class="{ 'has-proposals': pendingProposalsCount > 0 }"
        title="查看待审阅的规则修改"
        @click="emit('navigate', 'review')"
      >
        <span class="pill-dot amber"></span>
        <span class="pill-label">待审建议</span>
        <strong class="pill-value">{{ pendingProposalsCount }}</strong>
      </div>

      <div
        v-if="currentTab !== 'overview'"
        class="metric-pill overview-entry"
        title="查看项目总览"
        @click="emit('navigate', 'overview')"
      >
        <span class="pill-label">项目总览 ↗</span>
      </div>
    </div>

    <div class="strip-actions">
      <button
        id="refresh"
        class="strip-refresh"
        type="button"
        aria-label="刷新当前页面"
        :disabled="refreshing"
        @click="emit('refresh')"
      >
        {{ refreshing ? '刷新中…' : '⟳ 刷新' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.metrics-strip-compact {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
  flex-wrap: wrap;
  flex-shrink: 0;
}

.strip-title {
  font-size: 14px;
  font-weight: 600;
  line-height: 1.3;
  margin: 0;
  padding-right: 10px;
  border-right: 1px solid var(--gh-border-muted);
  color: var(--gh-fg-default);
  white-space: nowrap;
}

.pill-set {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  min-width: 0;
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
}

.strip-actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 8px;
}

.strip-refresh {
  padding: 3px 10px;
  font-size: 11px;
  line-height: 1.4;
  background: var(--gh-canvas-subtle);
  border: 1px solid var(--gh-border-default);
  border-radius: var(--radius-full);
  color: var(--gh-fg-muted);
  cursor: pointer;
}

.strip-refresh:hover:not(:disabled) {
  background: var(--gh-surface-card);
  border-color: var(--gh-accent-fg);
  color: var(--gh-fg-default);
}

.strip-refresh:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.overview-entry .pill-label {
  color: var(--gh-accent-fg);
  font-weight: 500;
}
</style>
