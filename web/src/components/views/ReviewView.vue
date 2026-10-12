<script setup lang="ts">
import type { Ledger, Proposal } from '../../types/ledger'

defineProps<{
  ledger: Ledger
  busy: boolean
}>()

const emit = defineEmits<{
  (e: 'open-approve', proposal: Proposal): void
  (e: 'open-reject', proposal: Proposal): void
}>()
</script>

<template>
  <div>
    <div class="section-head">
      <h2>长期契约变更审阅</h2>
      <span class="caption">人工核准 Agent 提交的长期契约修改提案，按目标版本执行严谨决议</span>
    </div>

    <div v-if="!ledger.proposals.length" class="empty">
      当前没有待审阅的契约变更提案。
    </div>
    <div v-else class="grid">
      <article v-for="prop in ledger.proposals" :key="prop.id" class="card">
        <div class="card-top">
          <h3>{{ prop.title }}</h3>
          <span class="tag" :class="prop.status">
            {{ prop.status === 'pending' ? '待审阅' : prop.status === 'applied' ? '已批准' : '已拒绝' }}
          </span>
        </div>
        <p><strong>目标契约：</strong><code>{{ prop.target_rule_id }} (版本 v{{ prop.target_version }})</code></p>
        <p><strong>变更依据：</strong>{{ prop.reason }}</p>
        <div class="panel" style="background: var(--surface); margin: 10px 0">
          <span class="caption">拟修订条款：</span>
          <ul style="margin: 10px 0; padding-left: 18px; line-height: 1.7">
            <li v-for="(p, i) in prop.points" :key="i">{{ p }}</li>
          </ul>
          <small>管辖路径模式：<code>{{ prop.patterns.join(' · ') }}</code></small>
        </div>
        <p v-if="prop.decision_reason" class="muted">
          <strong>审阅结论：</strong>{{ prop.decision_reason }}
        </p>

        <div v-if="prop.status === 'pending'" class="toolbar" style="margin-top: 14px">
          <button class="primary" :disabled="busy" @click="emit('open-approve', prop)">
            批准变更
          </button>
          <button :disabled="busy" @click="emit('open-reject', prop)">
            拒绝提案
          </button>
        </div>
      </article>
    </div>
  </div>
</template>
