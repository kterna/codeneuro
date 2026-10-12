<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Ledger } from '../../types/ledger'

const props = defineProps<{
  ledger: Ledger
}>()

const filterStatus = ref<'all' | 'active' | 'revoked'>('active')
const filterLifecycle = ref<'all' | 'long_term' | 'short_term'>('all')
const searchKeyword = ref('')

const filteredRules = computed(() => {
  return props.ledger.rules.filter(rule => {
    if (filterStatus.value !== 'all' && rule.status !== filterStatus.value) return false
    if (filterLifecycle.value === 'long_term' && rule.task_id !== null) return false
    if (filterLifecycle.value === 'short_term' && rule.task_id === null) return false
    if (searchKeyword.value.trim()) {
      const q = searchKeyword.value.toLowerCase()
      const matchTitle = rule.title.toLowerCase().includes(q)
      const matchPoints = rule.points.some(p => p.toLowerCase().includes(q))
      const matchPatterns = rule.patterns.some(p => p.toLowerCase().includes(q))
      if (!matchTitle && !matchPoints && !matchPatterns) return false
    }
    return true
  })
})
</script>

<template>
  <div>
    <div class="section-head">
      <h2>项目规则库</h2>
      <span class="caption">长期项目契约与任务短期规则统一管理，支持多维筛选与检索</span>
    </div>

    <div class="toolbar">
      <select v-model="filterStatus" aria-label="规则状态过滤">
        <option value="active">状态：正在生效</option>
        <option value="revoked">状态：已停用</option>
        <option value="all">状态：全部</option>
      </select>
      <select v-model="filterLifecycle" aria-label="生命周期过滤">
        <option value="all">类型：全部规则</option>
        <option value="long_term">类型：长期契约</option>
        <option value="short_term">类型：任务约束</option>
      </select>
      <input
        v-model="searchKeyword"
        placeholder="搜索规则标题、条款内容或路径模式…"
        aria-label="搜索规则"
      />
    </div>

    <div v-if="!filteredRules.length" class="empty">
      没有找到符合条件的规则。
    </div>
    <div v-else class="grid">
      <article v-for="rule in filteredRules" :key="rule.id" class="card">
        <div class="card-top">
          <h3>{{ rule.title }}</h3>
          <span class="tag" :class="rule.priority.toLowerCase()">
            {{ rule.priority === 'P0' ? 'P0 强制核心规范' : rule.priority === 'P1' ? 'P1 任务约束规范' : 'P2 架构建议' }}
          </span>
        </div>
        <div class="tags">
          <span class="tag" :class="rule.status">{{ rule.status === 'active' ? '生效中' : '已停用' }}</span>
          <span class="tag">{{ rule.task_id ? '任务短期规则' : '长期契约' }}</span>
          <span v-if="rule.origin_rule_id" class="tag">由任务规则晋升</span>
        </div>
        <ul style="margin: 10px 0; padding-left: 18px; line-height: 1.7">
          <li v-for="(point, i) in rule.points" :key="i">{{ point }}</li>
        </ul>
        <div class="definition">
          <dt>管辖路径：</dt>
          <dd><code>{{ rule.patterns.join(' · ') }}</code></dd>
          <dt>效用统计：</dt>
          <dd>
            已被引用 {{ rule.eval_count }} 次 · 标记已知 {{ rule.known_count }} 次 · 效用均分：{{ rule.avg_score ?? '—' }}
          </dd>
        </div>
      </article>
    </div>
  </div>
</template>
