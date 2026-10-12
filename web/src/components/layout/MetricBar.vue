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
      <div>
        <span>活跃需求</span>
        <strong>{{ activeRequirementsCount }}</strong>
      </div>
      <small>待完成 {{ activeRequirementsCount }} · 已归档 {{ (ledger?.requirements.length ?? 0) - activeRequirementsCount }}</small>
    </div>
    <div class="metric">
      <div>
        <span>进行中任务</span>
        <strong>{{ activeTasksCount }}</strong>
      </div>
      <small>全项目共 {{ ledger?.tasks.length ?? 0 }} 个任务看板流转中</small>
    </div>
    <div class="metric">
      <div>
        <span>核心契约 (P0)</span>
        <strong>{{ contractsCount }}</strong>
      </div>
      <small>长期生效 · 最高优先级强制约束规范</small>
    </div>
    <div class="metric">
      <div>
        <span>待审提案</span>
        <strong :style="{ color: pendingProposalsCount ? 'var(--amber)' : 'inherit' }">
          {{ pendingProposalsCount }}
        </strong>
      </div>
      <small>长期规范修改待人工审阅批准</small>
    </div>
  </div>
</template>
