<script setup lang="ts">
import { computed, ref, nextTick } from 'vue'
import type { Ledger, Rule, RuleStatus } from '../../types/ledger'
import GhDrawer from '../ui/GhDrawer.vue'
import RuleGovernancePanel from './RuleGovernancePanel.vue'

const props = defineProps<{
  ledger: Ledger
  projectId: string
}>()
const emit = defineEmits<{ (e: 'refresh'): void }>()
const topicFilter = ref('')

const filterStatus = ref<'all' | RuleStatus>('active')
const filterLifecycle = ref<'all' | 'long_term' | 'short_term'>('all')
const searchKeyword = ref('')
const selectedRuleId = ref<string | null>(null)
let openerElement: HTMLElement | null = null
const closeBtnRef = ref<HTMLButtonElement | null>(null)

const selectedRule = computed<Rule | null>(() => {
  if (!selectedRuleId.value) return null
  return props.ledger.rules.find(r => r.id === selectedRuleId.value) || null
})

const filteredRules = computed(() => {
  return props.ledger.rules.filter(rule => {
    if (filterStatus.value !== 'all' && rule.status !== filterStatus.value) return false
    if (topicFilter.value && !rule.topics.includes(topicFilter.value)) return false
    if (filterLifecycle.value === 'long_term' && rule.task_id !== null) return false
    if (filterLifecycle.value === 'short_term' && rule.task_id === null) return false
    if (searchKeyword.value.trim()) {
      const q = searchKeyword.value.toLowerCase()
      const matchTitle = rule.title.toLowerCase().includes(q)
      const matchPoints = rule.points.some(p => p.toLowerCase().includes(q))
      const matchPatterns = rule.patterns.some(p => p.toLowerCase().includes(q))
      const matchTopics = rule.topics.some(topic => topic.includes(q))
      if (!matchTitle && !matchPoints && !matchPatterns && !matchTopics) return false
    }
    return true
  })
})

function openDetail(rule: Rule, opener?: HTMLElement | null) {
  openerElement = opener || (document.activeElement as HTMLElement | null)
  selectedRuleId.value = rule.id
  nextTick(() => {
    const btn = closeBtnRef.value || (document.querySelector('.detail-drawer .close-btn') as HTMLElement | null)
    if (btn && typeof btn.focus === 'function') {
      btn.focus()
    } else {
      (document.querySelector('.detail-drawer') as HTMLElement | null)?.focus()
    }
  })
}

function closeDetail() {
  selectedRuleId.value = null
  nextTick(() => {
    if (openerElement && document.body.contains(openerElement) && typeof openerElement.focus === 'function') {
      openerElement.focus()
    } else {
      const contentEl = document.getElementById('content') || (document.querySelector('#content') as HTMLElement | null)
      if (contentEl && typeof contentEl.focus === 'function') {
        contentEl.focus()
      }
    }
  })
}

function statusLabel(status: RuleStatus | string): string {
  switch (status) {
    case 'active': return '生效中'
    case 'draft': return '草稿待审核'
    case 'deprecated': return '已停用'
    case 'revoked': return '已撤销'
    default: return `未知状态（${status}）`
  }
}

</script>

<template>
  <div class="rules-view-root">
    <!-- 顶部过滤栏 -->
    <div class="toolbar">
      <select v-model="topicFilter" aria-label="业务主题过滤"><option value="">主题：全部</option><option v-for="topic in ledger.topics" :key="topic.key" :value="topic.key">{{ topic.name }}</option></select>
      <select v-model="filterStatus" aria-label="规则状态过滤" style="width: 170px">
        <option value="all">状态：全部</option>
        <option value="active">状态：生效中</option>
        <option value="draft">状态：草稿待审核</option>
        <option value="deprecated">状态：已停用</option>
        <option value="revoked">状态：已撤销</option>
      </select>
      <select v-model="filterLifecycle" aria-label="规则类型过滤" style="width: 140px">
        <option value="all">类型：全部</option>
        <option value="long_term">类型：长期规则</option>
        <option value="short_term">类型：任务规则</option>
      </select>
      <input
        v-model="searchKeyword"
        placeholder="搜索规则标题、条款或适用文件…"
        aria-label="搜索规则"
        style="max-width: 320px"
      />
      <span class="muted" style="margin-left: auto; font-size: 11px; white-space: nowrap; flex-shrink: 0">
        共匹配 <strong>{{ filteredRules.length }}</strong> 条规则
      </span>
    </div>

    <!-- GitHub 经典清单表格 -->
    <div class="rules-table-container">
      <div v-if="!filteredRules.length" class="empty compact" style="margin: 20px">
        没有符合条件的规则。
      </div>
      <table v-else class="github-rules-table" role="table">
        <thead>
          <tr>
            <th style="width: 70px">优先级</th>
            <th>规则标题 / 主要条款</th>
            <th style="width: 200px">适用文件</th>
            <th style="width: 160px">类型 / 状态</th>
            <th style="width: 130px; text-align: right">推送 · 评分 · 均分</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="rule in filteredRules"
            :key="rule.id"
            class="rule-tr"
            :class="{ selected: selectedRule?.id === rule.id }"
            tabindex="0"
            role="row"
            :aria-selected="selectedRule?.id === rule.id"
            @click="openDetail(rule, ($event.currentTarget as HTMLElement))"
            @keydown.enter.self.prevent="openDetail(rule, ($event.currentTarget as HTMLElement))"
            @keydown.space.self.prevent="openDetail(rule, ($event.currentTarget as HTMLElement))"
          >
            <td>
              <span class="tag" :class="rule.priority.toLowerCase()">{{ rule.priority }}</span>
            </td>
            <td>
              <div class="title-cell-wrap">
                <strong class="rule-title-text">{{ rule.title }}</strong>
                <span class="rule-clause-preview">{{ rule.points[0] || '无具体条款' }}</span>
              </div>
            </td>
            <td>
              <code
                class="path-mono"
                :title="rule.is_global ? '全局适用' : (rule.patterns.join('、') || rule.topics.join(', ') || '待分类')"
              >{{ rule.is_global ? '全局适用' : rule.patterns[0] || rule.topics.join(', ') || '待分类' }}</code>
              <span v-if="rule.patterns.length > 1" class="muted path-extra">+{{ rule.patterns.length - 1 }}</span>
            </td>
            <td>
              <span class="tag" :class="rule.status">{{ statusLabel(rule.status) }}</span>
              <span class="tag neutral" style="margin-left: 4px">{{ rule.task_id ? '任务规则' : '长期规则' }}</span>
              <span v-if="rule.delivery_mode === 'card'" class="tag neutral" style="margin-left: 4px">按动作出现</span>
            </td>
            <td style="text-align: right">
              <span class="score-val">{{ rule.avg_score !== null ? rule.avg_score + ' 分' : '—' }}</span>
              <small class="muted" style="display: block; font-size: 10px">
                推送 {{ rule.delivery_count ?? 0 }} 次 · 评分 {{ rule.eval_count }} 次
              </small>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 规则详情右侧抽屉（采用通用 GhDrawer 统一封装无障碍焦点与退出逻辑） -->
    <GhDrawer
      :model-value="!!selectedRule"
      overlay-class="gh-drawer-overlay"
      content-class="detail-drawer"
      aria-labelledby="rule-drawer-title"
      width="min(540px, 92vw)"
      @close="closeDetail"
    >
      <template #header>
        <div v-if="selectedRule" class="drawer-header-top">
          <div>
            <h3 id="rule-drawer-title">规则详情</h3>
            <p class="muted font-mono" style="margin: 2px 0 0; font-size: 11px">编号：{{ selectedRule.id }} · 版本 v{{ selectedRule.version ?? 1 }}</p>
          </div>
          <button
            ref="closeBtnRef"
            type="button"
            class="subtle close-btn"
            aria-label="关闭抽屉"
            @click="closeDetail"
          >✕</button>
        </div>
      </template>

      <div v-if="selectedRule" class="drawer-content-scroll">
        <div class="drawer-section">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 8px">
            <h2 style="font-size: 15px; margin: 0; line-height: 1.4">{{ selectedRule.title }}</h2>
            <span class="tag" :class="selectedRule.priority.toLowerCase()">{{ selectedRule.priority }}</span>
          </div>
          <div class="tags" style="margin-top: 8px">
            <span class="tag" :class="selectedRule.status">{{ statusLabel(selectedRule.status) }}</span>
            <span class="tag neutral">{{ selectedRule.task_id ? '任务规则' : '长期规则' }}</span>
            <span v-for="topic in selectedRule.topics" :key="topic" class="tag neutral">{{ topic }}</span>
            <span v-if="selectedRule.is_global" class="tag warning">对所有文件生效</span>
            <span v-if="selectedRule.delivery_mode === 'card'" class="tag neutral">按动作出现</span>
            <span v-if="selectedRule.origin_rule_id" class="tag">源自任务规则 v{{ selectedRule.origin_version }}</span>
          </div>
          <p v-if="selectedRule.delivery_mode === 'card'" class="caption" style="margin-top: 8px">
            使用时机：{{ selectedRule.applies_when }}
          </p>
          <p v-else class="caption" style="margin-top: 8px">每次查询都给完整条款。</p>
        </div>

        <div class="drawer-section">
          <div class="section-label">具体条款（{{ selectedRule.points.length }} 条）</div>
          <ol class="clause-ol">
            <li v-for="(p, i) in selectedRule.points" :key="i">
              <span class="clause-text">{{ p }}</span>
            </li>
          </ol>
        </div>

        <div class="drawer-section">
          <div class="section-label">适用文件</div>
          <p v-if="!selectedRule.patterns.length" class="caption">无指定文件，按主题或全局规则生效。</p>
          <div class="tags">
            <code v-for="(pat, i) in selectedRule.patterns" :key="i" class="path-badge">{{ pat }}</code>
          </div>
        </div>

        <div class="drawer-section">
          <RuleGovernancePanel :project-id="projectId" :rule="selectedRule" @refresh="emit('refresh')" />
          <div class="section-label">使用情况</div>
          <div class="stat-meta-grid">
            <div class="stat-meta-item">
              <span>推送</span>
              <strong>{{ selectedRule.delivery_count ?? 0 }} 次</strong>
            </div>
            <div class="stat-meta-item">
              <span>被评分</span>
              <strong>{{ selectedRule.eval_count }} 次</strong>
            </div>
            <div class="stat-meta-item">
              <span>标记为已知</span>
              <strong>{{ selectedRule.known_count }} 次</strong>
            </div>
            <div class="stat-meta-item">
              <span>平均分</span>
              <strong>{{ selectedRule.avg_score !== null ? selectedRule.avg_score + ' 分' : '暂无' }}</strong>
            </div>
          </div>
        </div>
      </div>

      <template #footer>
        <button type="button" @click="closeDetail">关闭</button>
      </template>
    </GhDrawer>
  </div>
</template>

<style scoped>
.rules-view-root {
  display: flex;
  flex-direction: column;
  gap: 14px;
  height: 100%;
  overflow: hidden;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.rules-table-container {
  border: 1px solid var(--gh-border-default);
  border-radius: 6px;
  background: var(--gh-canvas-subtle);
  flex: 1;
  overflow-y: auto;
}

.github-rules-table {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
  text-align: left;
}

.github-rules-table th {
  background: var(--gh-canvas-subtle);
  border-bottom: 1px solid var(--gh-border-default);
  padding: 8px 14px;
  font-size: 11px;
  font-weight: 600;
  color: var(--gh-fg-muted);
  position: sticky;
  top: 0;
  z-index: 5;
}

.github-rules-table td {
  padding: 10px 14px;
  border-bottom: 1px solid var(--gh-border-muted);
  vertical-align: middle;
}

.rule-tr {
  cursor: pointer;
  transition: background 0.1s ease;
}
.rule-tr:hover, .rule-tr:focus {
  background: var(--gh-surface-card-hover);
}

.rule-tr:focus-visible {
  outline: 2px solid var(--gh-accent-fg);
  outline-offset: -2px;
}
.rule-tr.selected {
  background: var(--gh-surface-card);
  border-left: 2px solid var(--gh-accent-fg);
}

.title-cell-wrap {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.rule-title-text {
  font-size: 13px;
  color: var(--gh-fg-default);
}
.rule-clause-preview {
  font-size: 11px;
  color: var(--gh-fg-subtle);
  max-width: 480px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.path-mono {
  display: block;
  max-width: 100%;
  font-family: var(--font-mono);
  font-size: 11px;
  background: var(--gh-canvas-inset);
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid var(--gh-border-default);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.path-extra {
  font-size: 10px;
  margin-left: 4px;
}

.score-val {
  font-weight: 600;
  color: var(--gh-fg-default);
}

/* 详情抽屉 */
.gh-drawer-overlay {
  position: fixed;
  inset: 0;
  background: rgba(1, 4, 9, 0.7);
  backdrop-filter: blur(2px);
  z-index: 100;
  display: flex;
  justify-content: flex-end;
}

.detail-drawer {
  width: min(540px, 92vw);
  height: 100vh;
  background: var(--gh-canvas-subtle) !important;
  opacity: 1 !important;
  border-left: 1px solid var(--gh-border-default);
  display: flex;
  flex-direction: column;
  box-shadow: -6px 0 28px rgba(0, 0, 0, 0.5);
  outline: none;
}

.drawer-header {
  padding: 16px 20px;
  border-bottom: 1px solid var(--gh-border-default);
}
.drawer-header-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.drawer-header-top h3 {
  margin: 0;
  font-size: 15px;
}
.close-btn {
  font-size: 16px;
  padding: 2px 6px;
}

.drawer-content-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.drawer-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.section-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--gh-fg-subtle);
  text-transform: uppercase;
}

.clause-ol {
  margin: 0;
  padding-left: 20px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.clause-text {
  font-size: 13px;
  color: var(--gh-fg-default);
  line-height: 1.5;
}

.path-badge {
  font-family: var(--font-mono);
  font-size: 11px;
  background: var(--gh-canvas-inset);
  padding: 3px 8px;
  border-radius: 4px;
  border: 1px solid var(--gh-border-default);
}

.stat-meta-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}
.stat-meta-item {
  background: var(--gh-canvas-inset);
  border: 1px solid var(--gh-border-default);
  border-radius: 6px;
  padding: 10px 14px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.stat-meta-item span {
  font-size: 11px;
  color: var(--gh-fg-subtle);
}
.stat-meta-item strong {
  font-size: 14px;
  color: var(--gh-fg-default);
}

.drawer-footer {
  padding: 14px 20px;
  border-top: 1px solid var(--gh-border-default);
  display: flex;
  justify-content: flex-end;
}
</style>
