<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import type { Ledger, Rule, InspectResponse, RulePriority } from '../../types/ledger'
import { apiService } from '../../api/client'
import ScopeTreeNodeItem, { type ScopeTreeNodeModel } from './ScopeTreeNodeItem.vue'

const props = defineProps<{
  ledger: Ledger
  projectId?: string
}>()

const openDirs = ref<Set<string>>(new Set())
const selectedPath = ref<string>('')
const treeSearch = ref<string>('')

// JIT 检查相关
const inspectFilePath = ref<string>('')
const inspectTaskId = ref<string>('')
const inspectPriorities = ref<RulePriority[]>([])
const priorityOptions: RulePriority[] = ['P0', 'P1', 'P2', 'P3']
const inspectLoading = ref(false)
const inspectError = ref('')
const inspectResult = ref<InspectResponse | null>(null)
let inspectSeq = 0
let inspectAbortCtrl: AbortController | null = null

function invalidateInspect() {
  inspectSeq++
  if (inspectAbortCtrl) {
    inspectAbortCtrl.abort()
    inspectAbortCtrl = null
  }
  inspectLoading.value = false
  inspectResult.value = null
  inspectError.value = ''
}

// 监听输入路径、关联任务、项目与账本变动，立即失效并取消旧请求
watch(
  [inspectFilePath, inspectTaskId, () => inspectPriorities.value.join(','), () => props.projectId, () => props.ledger],
  () => {
    invalidateInspect()
  },
)

onUnmounted(() => {
  invalidateInspect()
})

// 任务候选（过滤 active / testing 状态）
const availableTasks = computed(() => {
  return props.ledger.tasks.filter(t => ['active', 'testing'].includes(t.status))
})

function formatTaskStatus(status: string): string {
  const map: Record<string, string> = {
    draft: '待开始',
    active: '进行中',
    paused: '已暂停',
    testing: '待验证',
    released: '已发布',
    archived: '已归档',
  }
  return map[status] || status
}

// 从规则集合派生作用域目录树
const directoryTree = computed<ScopeTreeNodeModel[]>(() => {
  const root: ScopeTreeNodeModel = {
    id: 'root',
    name: '作用域根目录',
    path: '',
    isDir: true,
    children: [],
    p0Count: 0,
    p1Count: 0,
    p2Count: 0,
    p3Count: 0,
    ruleIds: [],
  }

  const nodeMap = new Map<string, ScopeTreeNodeModel>()
  nodeMap.set('', root)

  // 收集所有已登记规则的 pattern 与关联规则
  const patternToRules = new Map<string, { p0: number; p1: number; p2: number; p3: number; ids: Set<string> }>()

  const activeRules = props.ledger.rules.filter(r => r.status === 'active')
  for (const rule of activeRules) {
    for (const rawPat of rule.patterns) {
      const pat = rawPat.trim()
      if (!pat) continue
      let entry = patternToRules.get(pat)
      if (!entry) {
        entry = { p0: 0, p1: 0, p2: 0, p3: 0, ids: new Set() }
        patternToRules.set(pat, entry)
      }
      entry.ids.add(rule.id)
      if (rule.priority === 'P0') entry.p0++
      else if (rule.priority === 'P1') entry.p1++
      else if (rule.priority === 'P2') entry.p2++
      else entry.p3++
    }
  }

  // 构造层级路径
  for (const [pattern, stat] of patternToRules.entries()) {
    const parts = pattern.split('/')
    let currentPath = ''

    for (let i = 0; i < parts.length; i++) {
      const part = parts[i]
      const parentPath = currentPath
      currentPath = parentPath ? `${parentPath}/${part}` : part
      const isDir = i < parts.length - 1

      let node = nodeMap.get(currentPath)
      if (!node) {
        node = {
          id: currentPath,
          name: part,
          path: currentPath,
          isDir,
          children: [],
          p0Count: 0,
          p1Count: 0,
          p2Count: 0,
          p3Count: 0,
          ruleIds: [],
        }
        nodeMap.set(currentPath, node)
        const parent = nodeMap.get(parentPath) || root
        parent.children.push(node)
      }

      // 累加本节点作用域关联
      if (i === parts.length - 1) {
        node.p0Count += stat.p0
        node.p1Count += stat.p1
        node.p2Count += stat.p2
        node.p3Count += stat.p3
        node.ruleIds = Array.from(stat.ids)
      }
    }
  }

  // 默认展开所有顶层节点
  for (const child of root.children) {
    openDirs.value.add(child.path)
    for (const sub of child.children) {
      openDirs.value.add(sub.path)
    }
  }

  return root.children
})

// 递归搜索保留祖先路径 (D16)
function filterTreeRecursive(nodes: ScopeTreeNodeModel[], query: string): ScopeTreeNodeModel[] {
  const result: ScopeTreeNodeModel[] = []
  for (const node of nodes) {
    const selfMatch = node.name.toLowerCase().includes(query) || node.path.toLowerCase().includes(query)
    const filteredChildren = filterTreeRecursive(node.children, query)

    if (selfMatch || filteredChildren.length > 0) {
      // 保持祖先展开
      openDirs.value.add(node.path)
      result.push({
        ...node,
        children: filteredChildren,
      })
    }
  }
  return result
}

const filteredTree = computed(() => {
  const q = treeSearch.value.trim().toLowerCase()
  if (!q) return directoryTree.value
  return filterTreeRecursive(directoryTree.value, q)
})

watch(
  () => directoryTree.value,
  nodes => {
    if (nodes.length && !selectedPath.value) {
      selectedPath.value = nodes[0].path
    }
  },
  { immediate: true },
)

function toggleDir(path: string) {
  if (openDirs.value.has(path)) {
    openDirs.value.delete(path)
  } else {
    openDirs.value.add(path)
  }
}

function selectNode(node: ScopeTreeNodeModel) {
  selectedPath.value = node.path
}

// 当前选中节点的对应规则
const selectedNodeRules = computed<Rule[]>(() => {
  if (!selectedPath.value) return []
  return props.ledger.rules.filter(r =>
    r.status === 'active' && r.patterns.some(p => p.trim() === selectedPath.value),
  )
})

// 调用后端执行真实 JIT 语义检查 (带异步序号与 AbortSignal 保护)
async function handleInspect() {
  const targetPath = inspectFilePath.value.trim()
  if (!props.projectId || !targetPath || !inspectPriorities.value.length) return

  if (inspectAbortCtrl) {
    inspectAbortCtrl.abort()
  }
  inspectAbortCtrl = new AbortController()
  const ctrl = inspectAbortCtrl

  const currentSeq = ++inspectSeq
  const targetTask = inspectTaskId.value || null

  inspectLoading.value = true
  inspectError.value = ''
  inspectResult.value = null

  try {
    const res = await apiService.inspectPath(props.projectId, targetPath, [...inspectPriorities.value], targetTask, ctrl.signal)
    if (currentSeq !== inspectSeq || ctrl.signal.aborted) return
    inspectResult.value = res
  } catch (err: unknown) {
    if (ctrl.signal.aborted || (err instanceof DOMException && err.name === 'AbortError')) {
      return
    }
    if (currentSeq !== inspectSeq) return
    inspectError.value = (err as Error).message || String(err)
  } finally {
    if (currentSeq === inspectSeq) {
      inspectLoading.value = false
      if (inspectAbortCtrl === ctrl) {
        inspectAbortCtrl = null
      }
    }
  }
}

const resultTaskLabel = computed(() => {
  if (!inspectResult.value?.task_id) return '仅长期核心契约 (无任务)'
  const matchedTask = props.ledger.tasks.find(t => t.id === inspectResult.value?.task_id)
  return matchedTask ? `[${formatTaskStatus(matchedTask.status)}] ${matchedTask.title}` : inspectResult.value.task_id
})

const inspectedRules = computed<Rule[]>(() => {
  if (!inspectResult.value) return []
  const ids = new Set(inspectResult.value.rule_ids)
  return props.ledger.rules.filter(r => ids.has(r.id))
})
</script>

<template>
  <div class="explorer-view-wrapper">
    <div class="section-head">
      <div>
        <h2>规则作用域目录</h2>
        <span class="caption">
          展示项目登记的规则作用域模式，并提供真实适用的规则检查。
        </span>
      </div>
    </div>

    <details v-if="ledger.rules.some(r => r.status === 'active' && !r.patterns.length)" class="panel pathless-rules-panel">
      <summary class="pathless-rules-summary">
        <span class="pathless-summary-title">
          <span class="summary-arrow" aria-hidden="true">▶</span>
          <span>无文件锚点的主题 / 全局规则（不伪造目录）</span>
        </span>
        <span class="caption pathless-summary-count">
          {{ ledger.rules.filter(r => r.status === 'active' && !r.patterns.length).length }} 条生效规则
        </span>
      </summary>
      <div class="pathless-rules-list">
        <div
          v-for="rule in ledger.rules.filter(r => r.status === 'active' && !r.patterns.length)"
          :key="rule.id"
          class="pathless-rule-row"
        >
          <span class="tag" :class="rule.priority.toLowerCase()">{{ rule.priority }}</span>
          <strong class="pathless-rule-title">{{ rule.title }}</strong>
          <span class="pathless-rule-topics caption">
            {{ rule.is_global ? '明确全局适用' : rule.topics.join(', ') }}
          </span>
        </div>
      </div>
    </details>

    <!-- 规则适用检查 (解决 D04/D05/E15) -->
    <div class="panel inspect-panel">
      <div class="inspect-title-row">
        <div class="inspect-title-group">
          <span class="inspect-icon" aria-hidden="true">🎯</span>
          <strong>规则适用检查</strong>
        </div>
        <span class="caption">输入代码相对路径，按服务端分段锚定规则精确匹配。</span>
      </div>
      <form class="inspect-form" @submit.prevent="handleInspect">
        <fieldset class="inspect-priorities-fieldset">
          <legend class="inspect-priorities-legend">显式选择查询等级（没有默认等级）</legend>
          <div class="inspect-pills-row">
            <label
              v-for="p in priorityOptions"
              :key="p"
              class="priority-check-pill"
              :class="{ 'is-checked': inspectPriorities.includes(p) }"
            >
              <input v-model="inspectPriorities" type="checkbox" :value="p" />
              <span class="pill-label">{{ p }}</span>
            </label>
          </div>
        </fieldset>
        <div class="inspect-inputs">
          <input
            v-model="inspectFilePath"
            class="input font-mono"
            placeholder="输入文件相对路径，如 src/pay/refund.py"
            required
          />
          <select v-model="inspectTaskId" class="select" aria-label="关联任务上下文">
            <option value="">仅长期核心契约 (无任务)</option>
            <option v-for="t in availableTasks" :key="t.id" :value="t.id">
              [{{ formatTaskStatus(t.status) }}] {{ t.title }}
            </option>
          </select>
          <button type="submit" class="button primary" :disabled="inspectLoading || !inspectFilePath.trim() || !inspectPriorities.length">
            {{ inspectLoading ? '检查中…' : '检查适用规则' }}
          </button>
        </div>
      </form>

      <!-- 探测结果区 -->
      <div v-if="inspectError" class="error-box" role="alert">
        {{ inspectError }}
      </div>
      <div v-else-if="inspectResult" class="inspect-results">
        <div class="inspect-summary">
          <span>
            目标路径：<code>{{ inspectResult.path }}</code> ·
            关联任务：<code>{{ resultTaskLabel }}</code> ·
            匹配规则：<strong>{{ inspectResult.rule_ids.length }}</strong> 条
            ({{ inspectResult.task_id ? '包含选定任务规则' : '仅项目全局规则' }})
          </span>
        </div>
        <div v-if="!inspectedRules.length" class="empty-compact">
          该路径无适用规则（未命中全局契约或所选任务规则）。
        </div>
        <div v-else class="rule-match-chips">
          <div v-for="r in inspectedRules" :key="r.id" class="rule-chip">
            <span class="tag" :class="r.priority.toLowerCase()">{{ r.priority }}</span>
            <span class="rule-chip-title">{{ r.title }}</span>
            <span class="caption font-mono">{{ r.patterns.join(', ') }}</span>
          </div>
        </div>
      </div>
    </div>

    <div v-if="!ledger.rules.length" class="empty">
      当前项目尚未配置任何规则。
    </div>

    <div v-else class="explorer-split-container">
      <!-- 左侧：递归作用域目录面板 -->
      <aside class="tree-sidebar-panel" aria-label="作用域目录结构">
        <div class="tree-header">
          <h3>作用域模式</h3>
          <span class="caption font-mono">{{ directoryTree.length }} 顶层节点</span>
        </div>

        <div class="tree-filter-box">
          <input
            v-model="treeSearch"
            placeholder="搜索模式或路径段…"
            class="tree-search-input"
            aria-label="搜索作用域"
          />
        </div>

        <div class="tree-scroll-area">
          <div v-if="!filteredTree.length" class="empty-compact">
            无匹配作用域
          </div>
          <ul v-else class="tree-ul" role="tree">
            <ScopeTreeNodeItem
              v-for="node in filteredTree"
              :key="node.id"
              :node="node"
              :selected-path="selectedPath"
              :open-dirs="openDirs"
              :depth="0"
              @select="selectNode"
              @toggle="toggleDir"
            />
          </ul>
        </div>
      </aside>

      <!-- 右侧：选中作用域详细规则卡片 -->
      <section class="explorer-detail-panel" aria-label="选中作用域规则">
        <div class="detail-header-card">
          <div class="detail-title-line">
            <span class="caption">当前选中作用域</span>
            <h3 class="font-mono">{{ selectedPath || '未选择' }}</h3>
          </div>
          <span class="caption">共关联 {{ selectedNodeRules.length }} 条生效规则</span>
        </div>

        <div v-if="!selectedNodeRules.length" class="empty">
          此节点为路径层级容器，未直接绑定独立规则；请展开下级模式节点查看。
        </div>

        <div v-else class="matched-rules-list">
          <article v-for="rule in selectedNodeRules" :key="rule.id" class="card rule-detail-card">
            <div class="card-head">
              <div>
                <span class="tag" :class="rule.priority.toLowerCase()">{{ rule.priority }}</span>
                <span v-for="topic in rule.topics" :key="topic" class="tag neutral" style="margin-left: 6px">{{ topic }}</span>
                <span v-if="rule.task_id" class="tag neutral" style="margin-left: 6px">任务短期</span>
                <span v-else class="tag success" style="margin-left: 6px">长期契约</span>
                <h4 style="display: inline-block; margin-left: 8px">{{ rule.title }}</h4>
              </div>
              <span class="caption font-mono">标识: {{ rule.id }}</span>
            </div>

            <div class="card-body">
              <div class="caption">生效条款:</div>
              <ul class="points-list">
                <li v-for="(pt, idx) in rule.points" :key="idx">{{ pt }}</li>
              </ul>
              <div class="scope-badges" style="margin-top: 8px">
                <span class="caption">覆盖范围:</span>
                <code v-for="pat in rule.patterns" :key="pat" class="code-badge">{{ pat }}</code>
              </div>
            </div>
          </article>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.explorer-view-wrapper {
  display: flex;
  flex-direction: column;
  gap: 16px;
  height: 100%;
}

/* 无文件锚点规则折叠卡片 */
.pathless-rules-panel {
  background: var(--gh-canvas-subtle);
  border: 1px solid var(--gh-border-default);
  border-radius: 6px;
  padding: 10px 14px;
}

.pathless-rules-summary {
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  font-weight: 600;
  color: var(--gh-fg-default);
  user-select: none;
}

.pathless-summary-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.pathless-rules-summary::-webkit-details-marker {
  display: none;
}

.summary-arrow {
  font-size: 10px;
  color: var(--gh-fg-muted);
  transition: transform 0.15s ease;
  display: inline-block;
}

details[open] .summary-arrow {
  transform: rotate(90deg);
}

.pathless-rules-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--gh-border-muted);
}

.pathless-rule-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 10px;
  background: var(--gh-canvas-default);
  border: 1px solid var(--gh-border-muted);
  border-radius: 4px;
  font-size: 12px;
}

.pathless-rule-title {
  color: var(--gh-fg-default);
}

.pathless-rule-topics {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 11px;
}

/* 探测面板 */
.inspect-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
  background: var(--gh-canvas-subtle);
  border: 1px solid var(--gh-border-default);
  border-radius: 6px;
  padding: 14px;
}

.inspect-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.inspect-title-group {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--gh-fg-default);
}

.inspect-icon {
  font-size: 14px;
}

.inspect-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.inspect-priorities-fieldset {
  border: 1px solid var(--gh-border-muted);
  border-radius: 6px;
  padding: 8px 12px;
  margin: 0;
  background: var(--gh-canvas-default);
}

.inspect-priorities-legend {
  font-size: 11px;
  font-weight: 600;
  color: var(--gh-fg-muted);
  padding: 0 4px;
}

.inspect-pills-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
}

.priority-check-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  background: var(--gh-canvas-subtle);
  border: 1px solid var(--gh-border-default);
  color: var(--gh-fg-default);
  user-select: none;
  transition: all 0.1s ease;
}

.priority-check-pill input {
  cursor: pointer;
  margin: 0;
}

.priority-check-pill.is-checked {
  background: var(--gh-accent-subtle);
  border-color: var(--gh-accent-fg);
  color: var(--gh-accent-fg);
}

.inspect-inputs {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
}

.inspect-inputs input {
  flex: 1;
  min-width: 240px;
}

.inspect-inputs select {
  min-width: 180px;
}

.inspect-results {
  margin-top: 10px;
  padding: 10px 14px;
  background: var(--gh-canvas-inset);
  border: 1px solid var(--gh-border-default);
  border-radius: 6px;
}

.inspect-summary {
  font-size: 12px;
  color: var(--gh-fg-muted);
}

.rule-match-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}

.rule-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: var(--gh-surface-card);
  border: 1px solid var(--gh-border-default);
  padding: 5px 10px;
  border-radius: 6px;
}

.rule-chip-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--gh-fg-default);
}

.explorer-split-container {
  display: flex;
  gap: 16px;
  min-height: 420px;
  flex: 1;
}

.tree-sidebar-panel {
  width: 320px;
  min-width: 280px;
  background: var(--gh-canvas-subtle);
  border: 1px solid var(--gh-border-default);
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.tree-header {
  padding: 10px 14px;
  border-bottom: 1px solid var(--gh-border-default);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.tree-filter-box {
  padding: 8px 12px;
  border-bottom: 1px solid var(--gh-border-default);
}

.tree-search-input {
  width: 100%;
}

.tree-scroll-area {
  flex: 1;
  overflow-y: auto;
  padding: 6px 0;
}

.tree-ul {
  list-style: none;
  margin: 0;
  padding: 0;
}

.explorer-detail-panel {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.detail-header-card {
  background: var(--gh-canvas-subtle);
  border: 1px solid var(--gh-border-default);
  border-radius: 6px;
  padding: 12px 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.detail-title-line h3 {
  margin: 2px 0 0;
  font-size: 15px;
}

.matched-rules-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow-y: auto;
}

.rule-detail-card {
  background: var(--gh-surface-card);
  border: 1px solid var(--gh-border-default);
  border-radius: 6px;
  padding: 14px 16px;
}

.points-list {
  margin: 4px 0 0;
  padding-left: 20px;
  font-size: 12px;
  line-height: 1.6;
}

.code-badge {
  font-family: var(--font-mono);
  font-size: 11px;
  background: var(--gh-canvas-inset);
  padding: 2px 6px;
  border-radius: 4px;
  border: 1px solid var(--gh-border-default);
  margin-right: 6px;
}
</style>
