<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Ledger, Rule } from '../../types/ledger'

const props = defineProps<{
  ledger: Ledger
}>()

const filterStatus = ref<'all' | 'active' | 'revoked'>('active')
const filterLifecycle = ref<'all' | 'long_term' | 'short_term'>('all')
const searchKeyword = ref('')
const selectedRule = ref<Rule | null>(null)

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

function openDetail(rule: Rule) {
  selectedRule.value = rule
}

function closeDetail() {
  selectedRule.value = null
}
</script>

<template>
  <div class="rules-view-root">
    <div class="section-head">
      <h2>项目规则库</h2>
      <span class="caption">以 GitHub 清单形式紧凑呈现项目长期契约与任务短期规则，点击条目查看完整条款</span>
    </div>

    <!-- 顶部过滤栏 -->
    <div class="toolbar">
      <select v-model="filterStatus" aria-label="规则状态过滤" style="width: 140px">
        <option value="active">状态：正在生效</option>
        <option value="revoked">状态：已停用</option>
        <option value="all">状态：全部</option>
      </select>
      <select v-model="filterLifecycle" aria-label="生命周期过滤" style="width: 140px">
        <option value="all">类型：全部规矩</option>
        <option value="long_term">类型：长期契约</option>
        <option value="short_term">类型：任务约束</option>
      </select>
      <input
        v-model="searchKeyword"
        placeholder="搜索规则标题、条款内容或路径模式…"
        aria-label="搜索规则"
        style="max-width: 320px"
      />
      <span class="muted" style="margin-left: auto; font-size: 11px">
        共匹配 <strong>{{ filteredRules.length }}</strong> 条规则
      </span>
    </div>

    <!-- GitHub 经典清单表格 -->
    <div class="rules-table-container">
      <div v-if="!filteredRules.length" class="empty compact" style="margin: 20px">
        没有找到符合条件的规矩。
      </div>
      <table v-else class="github-rules-table">
        <thead>
          <tr>
            <th style="width: 70px">优先级</th>
            <th>规则标题 / 核心约束</th>
            <th style="width: 220px">管辖路径模式</th>
            <th style="width: 130px">类型与状态</th>
            <th style="width: 110px; text-align: right">引用 / 评分</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="rule in filteredRules"
            :key="rule.id"
            class="rule-tr"
            :class="{ selected: selectedRule?.id === rule.id }"
            @click="openDetail(rule)"
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
              <code class="path-mono">{{ rule.patterns[0] || '**' }}</code>
              <span v-if="rule.patterns.length > 1" class="muted path-extra">+{{ rule.patterns.length - 1 }}</span>
            </td>
            <td>
              <span class="tag" :class="rule.status">{{ rule.status === 'active' ? '生效' : '停用' }}</span>
              <span class="tag">{{ rule.task_id ? '任务' : '长期' }}</span>
            </td>
            <td style="text-align: right">
              <span class="score-val">{{ rule.avg_score ?? '—' }} 分</span>
              <small class="muted" style="display: block; font-size: 10px">{{ rule.eval_count }} 次引用</small>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 规则详情右侧抽屉 -->
    <aside v-if="selectedRule" class="detail-drawer">
      <div class="drawer-header">
        <div class="drawer-header-top">
          <h3>规则详情</h3>
          <button type="button" class="subtle close-btn" @click="closeDetail">✕</button>
        </div>
        <p class="muted font-mono" style="margin: 2px 0 0; font-size: 11px">标识：{{ selectedRule.id }}</p>
      </div>

      <div class="drawer-content-scroll">
        <div class="drawer-section">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 8px">
            <h2 style="font-size: 15px; margin: 0; line-height: 1.4">{{ selectedRule.title }}</h2>
            <span class="tag" :class="selectedRule.priority.toLowerCase()">{{ selectedRule.priority }}</span>
          </div>
          <div class="tags" style="margin-top: 8px">
            <span class="tag" :class="selectedRule.status">{{ selectedRule.status === 'active' ? '生效中' : '已停用' }}</span>
            <span class="tag">{{ selectedRule.task_id ? '任务短期规则' : '长期项目契约' }}</span>
            <span v-if="selectedRule.origin_rule_id" class="tag">由任务规则晋升</span>
          </div>
        </div>

        <div class="drawer-section">
          <div class="section-label">具体执行条款</div>
          <ol class="clause-ol">
            <li v-for="(p, i) in selectedRule.points" :key="i">
              <span class="clause-text">{{ p }}</span>
            </li>
          </ol>
        </div>

        <div class="drawer-section">
          <div class="section-label">管辖文件路径模式</div>
          <div class="tags">
            <code v-for="(pat, i) in selectedRule.patterns" :key="i" class="path-badge">{{ pat }}</code>
          </div>
        </div>

        <div class="drawer-section">
          <div class="section-label">使用情况与真实反馈</div>
          <div class="stat-meta-grid">
            <div class="stat-meta-item">
              <span>实际引用</span>
              <strong>{{ selectedRule.eval_count }} 次</strong>
            </div>
            <div class="stat-meta-item">
              <span>已掌握标记</span>
              <strong>{{ selectedRule.known_count }} 次</strong>
            </div>
            <div class="stat-meta-item">
              <span>实用度均分</span>
              <strong>{{ selectedRule.avg_score ?? '暂无' }}</strong>
            </div>
          </div>
        </div>
      </div>
    </aside>
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

/* 核心：带内部滚动的 GitHub 风格表格容器 */
.rules-table-container {
  border: 1px solid var(--color-border-default);
  border-radius: 6px;
  background: var(--color-canvas-subtle);
  flex: 1;
  overflow-y: auto;
}

.github-rules-table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
}

.github-rules-table th {
  background: #161b22;
  border-bottom: 1px solid var(--color-border-default);
  padding: 8px 14px;
  font-size: 11px;
  font-weight: 600;
  color: var(--color-fg-muted);
  position: sticky;
  top: 0;
  z-index: 5;
}

.github-rules-table td {
  padding: 10px 14px;
  border-bottom: 1px solid var(--color-border-muted);
  vertical-align: middle;
}

.rule-tr {
  cursor: pointer;
  transition: background 0.1s ease;
}
.rule-tr:hover {
  background: #1c2128;
}
.rule-tr.selected {
  background: rgba(56, 139, 253, 0.12);
}

.title-cell-wrap {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.rule-title-text {
  font-size: 13px;
  color: var(--color-fg-default);
  font-weight: 600;
}
.rule-clause-preview {
  font-size: 11px;
  color: var(--color-fg-muted);
  max-width: 480px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.path-mono {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--color-accent-fg);
}
.path-extra {
  font-size: 10px;
  margin-left: 4px;
}

.score-val {
  font-weight: 600;
  color: var(--color-success-fg);
  font-size: 12px;
}

/* 抽屉样式 */
.detail-drawer {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: min(540px, 92vw);
  background: var(--color-canvas-overlay);
  border-left: 1px solid var(--color-border-default);
  box-shadow: -10px 0 32px rgba(1, 4, 9, 0.8);
  z-index: 100;
  display: flex;
  flex-direction: column;
  animation: slideRight 0.18s cubic-bezier(0.16, 1, 0.3, 1);
}
@keyframes slideRight {
  from { transform: translateX(100%); }
  to { transform: translateX(0); }
}

.drawer-header {
  padding: 18px 22px;
  border-bottom: 1px solid var(--color-border-default);
  background: var(--color-canvas-subtle);
}
.drawer-header-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.drawer-header-top h3 {
  font-size: 14px;
  margin: 0;
}
.close-btn {
  font-size: 14px;
  padding: 2px 6px;
}

.drawer-content-scroll {
  padding: 22px;
  overflow-y: auto;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.drawer-section {
  padding-bottom: 16px;
  border-bottom: 1px solid var(--color-border-muted);
}
.drawer-section:last-child {
  border-bottom: 0;
}

.section-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-fg-subtle);
  text-transform: uppercase;
  margin-bottom: 8px;
}

.clause-ol {
  margin: 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.clause-text {
  font-size: 13px;
  line-height: 1.65;
  color: var(--color-fg-default);
}

.path-badge {
  background: var(--color-canvas-inset);
  border: 1px solid var(--color-border-default);
  padding: 3px 8px;
  border-radius: 4px;
  font-size: 11px;
}

.stat-meta-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}
.stat-meta-item {
  background: var(--color-canvas-inset);
  border: 1px solid var(--color-border-muted);
  padding: 8px 12px;
  border-radius: 4px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.stat-meta-item span {
  font-size: 10px;
  color: var(--color-fg-subtle);
}
.stat-meta-item strong {
  font-size: 13px;
  color: var(--color-fg-default);
}
</style>
