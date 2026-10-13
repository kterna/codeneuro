<script setup lang="ts">
import { computed, ref, nextTick } from 'vue'
import type { Ledger, Rule, RuleStatus } from '../../types/ledger'

const props = defineProps<{
  ledger: Ledger
}>()

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
    case 'active': return '正在生效'
    case 'draft': return '草稿待验'
    case 'deprecated': return '需求完成已停用'
    case 'revoked': return '人工撤销'
    default: return status
  }
}

function categoryLabel(cat?: string | null): string {
  if (!cat) return ''
  switch (cat) {
    case 'business': return '业务'
    case 'security': return '安全'
    case 'gotcha': return '避坑'
    default: return cat
  }
}

function handleDrawerKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    e.preventDefault()
    closeDetail()
  } else if (e.key === 'Tab') {
    const drawerEl = document.querySelector('.detail-drawer') as HTMLElement | null
    if (!drawerEl) return
    const focusable = drawerEl.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [tabindex]:not([tabindex="-1"]):not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled])'
    )
    if (!focusable.length) return
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (!drawerEl.contains(document.activeElement)) {
      e.preventDefault()
      first.focus()
    } else if (e.shiftKey && document.activeElement === first) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault()
      first.focus()
    }
  }
}
</script>

<template>
  <div class="rules-view-root">
    <div class="section-head">
      <div>
        <h2>项目规则库</h2>
        <span class="caption">紧凑呈现项目长期契约与任务短期规则，支持按完整生命周期状态精准筛选</span>
      </div>
    </div>

    <!-- 顶部过滤栏 -->
    <div class="toolbar">
      <select v-model="filterStatus" aria-label="规则状态过滤" style="width: 170px">
        <option value="all">状态：全部规则</option>
        <option value="active">状态：正在生效</option>
        <option value="draft">状态：草稿待验</option>
        <option value="deprecated">状态：需求完成已停用</option>
        <option value="revoked">状态：人工撤销</option>
      </select>
      <select v-model="filterLifecycle" aria-label="生命周期过滤" style="width: 140px">
        <option value="all">类型：全部规则</option>
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
        没有找到符合条件的规则条目。
      </div>
      <table v-else class="github-rules-table" role="table">
        <thead>
          <tr>
            <th style="width: 70px">优先级</th>
            <th>规则标题 / 核心约束</th>
            <th style="width: 200px">管辖路径模式</th>
            <th style="width: 160px">类型与状态</th>
            <th style="width: 130px; text-align: right">下发 · 反馈 · 均分</th>
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
              <code class="path-mono">{{ rule.patterns[0] || '**' }}</code>
              <span v-if="rule.patterns.length > 1" class="muted path-extra">+{{ rule.patterns.length - 1 }}</span>
            </td>
            <td>
              <span class="tag" :class="rule.status">{{ statusLabel(rule.status) }}</span>
              <span class="tag neutral" style="margin-left: 4px">{{ rule.task_id ? '任务短期' : '长期契约' }}</span>
            </td>
            <td style="text-align: right">
              <span class="score-val">{{ rule.avg_score !== null ? rule.avg_score + ' 分' : '—' }}</span>
              <small class="muted" style="display: block; font-size: 10px">
                下发 {{ rule.delivery_count ?? 0 }} 次 · 反馈 {{ rule.eval_count }} 次
              </small>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 规则详情右侧抽屉（带遮罩，无障碍 dialog 语义，焦点管理与关闭还原） -->
    <div
      v-if="selectedRule"
      class="gh-drawer-overlay"
      @click.self="closeDetail"
      @keydown="handleDrawerKeydown"
    >
      <aside
        class="detail-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="rule-drawer-title"
        tabindex="-1"
      >
        <div class="drawer-header">
          <div class="drawer-header-top">
            <h3 id="rule-drawer-title">规则详情</h3>
            <button
              ref="closeBtnRef"
              type="button"
              class="subtle close-btn"
              aria-label="关闭抽屉"
              @click="closeDetail"
            >✕</button>
          </div>
          <p class="muted font-mono" style="margin: 2px 0 0; font-size: 11px">标识：{{ selectedRule.id }} · 版本 v{{ selectedRule.version ?? 1 }}</p>
        </div>

        <div class="drawer-content-scroll">
          <div class="drawer-section">
            <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 8px">
              <h2 style="font-size: 15px; margin: 0; line-height: 1.4">{{ selectedRule.title }}</h2>
              <span class="tag" :class="selectedRule.priority.toLowerCase()">{{ selectedRule.priority }}</span>
            </div>
            <div class="tags" style="margin-top: 8px">
              <span class="tag" :class="selectedRule.status">{{ statusLabel(selectedRule.status) }}</span>
              <span class="tag neutral">{{ selectedRule.task_id ? '任务短期规则' : '长期项目契约' }}</span>
              <span v-if="selectedRule.category" class="tag neutral">{{ categoryLabel(selectedRule.category) }}</span>
              <span v-if="selectedRule.origin_rule_id" class="tag">由任务规则晋升 (源: v{{ selectedRule.origin_version }})</span>
            </div>
          </div>

          <div class="drawer-section">
            <div class="section-label">具体执行条款 ({{ selectedRule.points.length }})</div>
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
            <div class="section-label">使用情况与真实反馈 (当前版本)</div>
            <div class="stat-meta-grid">
              <div class="stat-meta-item">
                <span>实际下发</span>
                <strong>{{ selectedRule.delivery_count ?? 0 }} 次</strong>
              </div>
              <div class="stat-meta-item">
                <span>评价反馈</span>
                <strong>{{ selectedRule.eval_count }} 次</strong>
              </div>
              <div class="stat-meta-item">
                <span>已掌握标记</span>
                <strong>{{ selectedRule.known_count }} 次</strong>
              </div>
              <div class="stat-meta-item">
                <span>实用度均分</span>
                <strong>{{ selectedRule.avg_score !== null ? selectedRule.avg_score + ' 分' : '暂无' }}</strong>
              </div>
            </div>
          </div>
        </div>

        <div class="drawer-footer">
          <button type="button" @click="closeDetail">关闭抽屉</button>
        </div>
      </aside>
    </div>
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
  outline: none;
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
  font-family: var(--font-mono);
  font-size: 11px;
  background: var(--gh-canvas-inset);
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid var(--gh-border-default);
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
