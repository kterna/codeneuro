<script setup lang="ts">
import type { Ledger } from '../../types/ledger'

defineProps<{
  ledger: Ledger
}>()

function formatTime(iso: string) {
  if (!iso) return '—'
  const d = new Date(iso)
  return isNaN(d.getTime()) ? iso : d.toLocaleString()
}
</script>

<template>
  <div>
    <div class="section-head">
      <h2>变更审计时间线</h2>
      <span class="caption">每一次需求完成归档、规则变更与审批决策均在同一事务持久化留存</span>
    </div>
    <div v-if="!ledger.events.length" class="empty">
      暂无审计事件记录。
    </div>
    <div v-else class="panel timeline">
      <div v-for="ev in ledger.events" :key="ev.sequence" class="row">
        <div class="card-top">
          <strong>{{ ev.action }}</strong>
          <span class="muted">{{ formatTime(ev.created_at) }}</span>
        </div>
        <p class="code">目标实体：{{ ev.entity_id }} · 序列 #{{ ev.sequence }}</p>
      </div>
    </div>
  </div>
</template>
