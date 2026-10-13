<script setup lang="ts">
import type { Ledger } from '../../types/ledger'

defineProps<{
  ledger: Ledger | null
  activeRequirementsCount: number
  activeTasksCount: number
  contractsCount: number
  pendingProposalsCount: number
}>()
</script>

<template>
  <div id="metrics" class="metrics">
    <div class="metric">
      <div class="metric-content">
        <span>活跃需求</span>
        <strong>{{ activeRequirementsCount }}</strong>
      </div>
      <small class="metric-caption">待完成 {{ activeRequirementsCount }} · 已归档 {{ (ledger?.requirements.length ?? 0) - activeRequirementsCount }}</small>
    </div>
    <div class="metric">
      <div class="metric-content">
        <span>进行中任务</span>
        <strong>{{ activeTasksCount }}</strong>
      </div>
      <small class="metric-caption">任务总数 {{ ledger?.tasks.length ?? 0 }}</small>
    </div>
    <div class="metric">
      <div class="metric-content">
        <span>核心契约 (P0)</span>
        <strong>{{ contractsCount }}</strong>
      </div>
      <small class="metric-caption">长期最高优先级约束</small>
    </div>
    <div class="metric">
      <div class="metric-content">
        <span>待审提案</span>
        <strong :style="{ color: pendingProposalsCount ? 'var(--amber)' : 'inherit' }">
          {{ pendingProposalsCount }}
        </strong>
      </div>
      <small class="metric-caption">长期规范变更待审阅</small>
    </div>
  </div>
</template>
