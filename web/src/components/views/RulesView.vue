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
  <div class="rules-view-container">
    <div class="section-head">
      <h2>项目规则库</h2>
      <span class="caption">以 GitHub 清单形式紧凑呈现项目长期契约与任务短期规则，点击条目查看完整条款</span>
    </div>

    <!-- 顶部过滤工具栏 -->
    <div class="toolbar">
      <select v-model="filterStatus" aria-label="规则状态过滤">
        <option value="active">状态：正在生效</option>
        <option value="revoked">状态：已停用</option>
        <option value="all">状态：全部</option>
      </select>
      <select v-model="filterLifecycle" aria-label="生命周期过滤">
        <option value="all">类型：全部规矩</option>
        <option value="long_term">类型：长期契约</option>
        <option value="short_term">类型：任务约束</option>
      </select>
      <input
        v-model="searchKeyword"
        placeholder="搜索规则标题、条款内容或路径模式…"
        aria-label="搜索规则"
      />
    </div>

    <!-- 经典清单式列表 (GitHub Issues Style) -->
    <div class="table-wrap">
      <div v-if="!filteredRules.length" class="empty">
        没有找到符合条件的规矩。
      </div>
      <table v-else class="rule-list-table">
        <thead>
          <tr>
            <th style="width: 70px">优先级</th>
            <th>规则标题 / 核心约束</th>
            <th style="width: 180px">适用路径模式</th>
            <th style="width: 120px">类型与状态</th>
            <th style="width: 100px; text-align: right">引用 / 评分</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="rule in filteredRules"
            :key="rule.id"
            class="rule-row"
            :class="{ active: selectedRule?.id === rule.id }"
            @click="openDetail(rule)"
          >
            <td>
              <span class="tag" :class="rule.priority.toLowerCase()">{{ rule.priority }}</span>
            </td>
            <td>
              <div class="rule-title-cell">
                <strong>{{ rule.title }}</strong>
                <small class="muted truncate-text">{{ rule.points[0] || '无具体条款' }}</small>
              </div>
            </td>
            <td>
              <code class="path-code">{{ rule.patterns[0] || '**' }}</code>
              <small v-if="rule.patterns.length > 1" class="muted">+{{ rule.patterns.length - 1 }}</small>
            </td>
            <td>
              <span class="tag" :class="rule.status">{{ rule.status === 'active' ? '生效' : '停用' }}</span>
              <span class="tag">{{ rule.task_id ? '任务' : '长期' }}</span>
            </td>
            <td style="text-align: right">
              <span class="score-text">{{ rule.avg_score ?? '—' }} 分</span>
              <small class="muted" style="display: block">{{ rule.eval_count }} 次引用</small>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 规则详情右侧抽屉 / 模态卡片 (Detail Drawer) -->
    <aside v-if="selectedRule" class="rule-detail-drawer">
      <div class="drawer-header">
        <div class="card-top" style="margin-bottom: 0">
          <h3>规则详情</h3>
          <button type="button" class="subtle close-btn" @click="closeDetail">✕</button>
        </div>
        <p class="muted" style="margin: 4px 0 0">规则标识：<code>{{ selectedRule.id }}</code></p>
      </div>

      <div class="drawer-body">
        <div class="section">
          <div class="card-top">
            <h2 style="font-size: 15px; margin: 0">{{ selectedRule.title }}</h2>
            <span class="tag" :class="selectedRule.priority.toLowerCase()">{{ selectedRule.priority }}</span>
          </div>
          <div class="tags" style="margin-top: 8px">
            <span class="tag" :class="selectedRule.status">{{ selectedRule.status === 'active' ? '生效中' : '已停用' }}</span>
            <span class="tag">{{ selectedRule.task_id ? '任务短期规则' : '长期项目契约' }}</span>
            <span v-if="selectedRule.origin_rule_id" class="tag">由任务规则晋升而来</span>
          </div>
        </div>

        <div class="section">
          <h3>具体条款明细</h3>
          <ul class="rule-points-list">
            <li v-for="(p, i) in selectedRule.points" :key="i">{{ p }}</li>
          </ul>
        </div>

        <div class="section">
          <h3>管辖文件路径模式</h3>
          <div class="tags">
            <code v-for="(pat, i) in selectedRule.patterns" :key="i" class="path-badge">{{ pat }}</code>
          </div>
        </div>

        <div class="section">
          <h3>使用情况与反馈</h3>
          <div class="definition">
            <dt>实际引用：</dt>
            <dd>{{ selectedRule.eval_count }} 次</dd>
            <dt>已掌握提示：</dt>
            <dd>{{ selectedRule.known_count }} 次</dd>
            <dt>实用度评分：</dt>
            <dd><strong>{{ selectedRule.avg_score ?? '暂无打分' }}</strong></dd>
          </div>
        </div>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.rules-view-container {
  position: relative;
}
.rule-list-table {
  width: 100%;
  border-collapse: collapse;
}
.rule-row {
  cursor: pointer;
  transition: background 0.1s;
}
.rule-row:hover {
  background: var(--surface);
}
.rule-row.active {
  background: #28233d;
}
.rule-title-cell strong {
  display: block;
  font-size: 12px;
  color: var(--text);
  margin-bottom: 2px;
}
.truncate-text {
  display: block;
  max-width: 480px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.path-code {
  font-size: 11px;
  color: #a49aff;
}
.score-text {
  font-weight: bold;
  color: var(--green);
}

/* 详情抽屉 */
.rule-detail-drawer {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: min(520px, 90vw);
  background: var(--panel);
  border-left: 1px solid var(--line);
  box-shadow: -10px 0 40px rgba(0, 0, 0, 0.6);
  z-index: 50;
  display: flex;
  flex-direction: column;
  animation: slideIn 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}
@keyframes slideIn {
  from { transform: translateX(100%); }
  to { transform: translateX(0); }
}
.drawer-header {
  padding: 20px 24px;
  border-bottom: 1px solid var(--line);
  background: #101119;
}
.close-btn {
  font-size: 16px;
  padding: 4px 8px;
}
.drawer-body {
  padding: 24px;
  overflow-y: auto;
  flex: 1;
}
.drawer-body .section {
  margin-bottom: 24px;
  padding-bottom: 20px;
  border-bottom: 1px solid var(--line);
}
.drawer-body .section:last-child {
  border-bottom: 0;
}
.rule-points-list {
  padding-left: 20px;
  line-height: 1.8;
  font-size: 12px;
}
.path-badge {
  background: var(--surface);
  border: 1px solid var(--line);
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 11px;
  color: var(--accent);
}
</style>
