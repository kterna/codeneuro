<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Ledger, Rule } from '../../types/ledger'

const props = defineProps<{
  ledger: Ledger
  projectId?: string
}>()

type TreeNode = {
  id: string
  name: string
  path: string
  isDir: boolean
  children: TreeNode[]
  p0Count: number
  p1Count: number
}

const openDirs = ref<Set<string>>(new Set())
const selectedPath = ref<string>('')
const treeSearch = ref<string>('')
const realTreeItems = ref<{ path: string; is_dir: boolean }[]>([])

// 异步拉取真实目录树
async function loadRealTree() {
  if (!props.projectId) return
  try {
    const res = await fetch(`/api/projects/${encodeURIComponent(props.projectId)}/tree`)
    if (res.ok) {
      const data = await res.json()
      realTreeItems.value = data.tree || []
    }
  } catch {
    realTreeItems.value = []
  }
}

watch(() => props.projectId, () => {
  selectedPath.value = ''
  void loadRealTree()
}, { immediate: true })

// 核心：构建标准层级树
const directoryTree = computed(() => {
  const root: TreeNode = {
    id: 'root',
    name: '项目根目录',
    path: '',
    isDir: true,
    children: [],
    p0Count: 0,
    p1Count: 0,
  }

  const nodeMap = new Map<string, TreeNode>()
  nodeMap.set('', root)

  const rawPaths: { path: string; isDir: boolean }[] = []
  if (realTreeItems.value.length > 0) {
    for (const item of realTreeItems.value) {
      rawPaths.push({ path: item.path, isDir: item.is_dir })
    }
  } else {
    for (const rule of props.ledger.rules) {
      for (const pat of rule.patterns) {
        const clean = pat.replace(/^\.\//, '').replace(/\/\*\*|\/\*/g, '').trim()
        if (clean && !clean.includes(' ') && !clean.includes('(') && !clean.includes('=')) {
          rawPaths.push({ path: clean, isDir: !clean.includes('.') })
        }
      }
    }
  }

  for (const item of rawPaths) {
    const parts = item.path.split('/')
    let currentPath = ''

    for (let i = 0; i < parts.length; i++) {
      const part = parts[i]
      const parentPath = currentPath
      currentPath = parentPath ? `${parentPath}/${part}` : part
      const isDir = i < parts.length - 1 || item.isDir

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
        }
        nodeMap.set(currentPath, node)
        const parent = nodeMap.get(parentPath) || root
        parent.children.push(node)
      }
    }
  }

  const activeRules = props.ledger.rules.filter(r => r.status === 'active')
  for (const [, node] of nodeMap) {
    for (const rule of activeRules) {
      if (isRuleApplicableToPath(rule, node.path, false)) {
        if (rule.priority === 'P0') node.p0Count++
        else node.p1Count++
      }
    }
  }

  for (const child of root.children) {
    openDirs.value.add(child.path)
  }

  return root.children
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

function selectNode(node: TreeNode) {
  selectedPath.value = node.path
}

function isRuleApplicableToPath(rule: Rule, targetPath: string, includeGlobal = true): boolean {
  if (!targetPath) return includeGlobal
  for (const rawPattern of rule.patterns) {
    const pat = rawPattern.replace(/^\.\//, '').trim()
    if (pat === '**' || pat === '*' || !pat) {
      if (includeGlobal) return true
      continue
    }
    const cleanPrefix = pat.replace(/\/\*\*|\/\*/g, '')
    if (targetPath.startsWith(cleanPrefix) || cleanPrefix.startsWith(targetPath)) {
      return true
    }
    if (pat === targetPath || pat.endsWith(targetPath) || targetPath.endsWith(pat)) {
      return true
    }
  }
  return false
}

const filteredTree = computed(() => {
  const q = treeSearch.value.trim().toLowerCase()
  if (!q) return directoryTree.value
  return directoryTree.value.filter(n => n.name.toLowerCase().includes(q) || n.path.toLowerCase().includes(q))
})

const directMatchedRules = computed<Rule[]>(() => {
  if (!selectedPath.value) return []
  const rules = props.ledger.rules.filter(r => r.status === 'active')
  return rules.filter(r => isRuleApplicableToPath(r, selectedPath.value, false))
})

const globalInheritedRules = computed<Rule[]>(() => {
  const rules = props.ledger.rules.filter(r => r.status === 'active')
  return rules.filter(r => r.patterns.some(p => p === '**' || p === '*' || !p.trim()))
})
</script>

<template>
  <div class="explorer-view-wrapper">
    <div class="section-head">
      <h2>代码作用域与层级目录</h2>
      <span class="caption">
        {{ realTreeItems.length ? '已连接本地工作区，读取真实代码目录结构' : '解析规则路径模式，呈现受控目录层级' }}
      </span>
    </div>

    <div v-if="!ledger.rules.length" class="empty">
      当前项目尚未配置任何针对代码路径的规则。
    </div>

    <div v-else class="explorer-split-container">
      <!-- 左侧：目录树面板（固定 300px 宽，完全禁止文本折行） -->
      <aside class="tree-sidebar-panel">
        <div class="tree-header">
          <h3>工程目录</h3>
          <span class="muted font-mono">{{ directoryTree.length }} 顶层节点</span>
        </div>

        <div class="tree-filter-box">
          <input
            v-model="treeSearch"
            placeholder="快速过滤目录或文件…"
            class="tree-search-input"
          />
        </div>

        <div class="tree-scroll-area">
          <ul class="tree-ul">
            <template v-for="node in filteredTree" :key="node.id">
              <li class="tree-li">
                <div
                  class="tree-row"
                  :class="{ active: selectedPath === node.path }"
                  :title="node.path"
                  @click="selectNode(node)"
                >
                  <button
                    v-if="node.children.length"
                    type="button"
                    class="tree-expander"
                    @click.stop="toggleDir(node.path)"
                  >
                    {{ openDirs.has(node.path) ? '▾' : '▸' }}
                  </button>
                  <span v-else class="tree-expander-space"></span>
                  <span class="tree-type-icon">{{ node.isDir ? '📁' : '📄' }}</span>
                  <span class="tree-text-truncate">{{ node.name }}</span>
                  <div class="tree-pill-tags">
                    <span v-if="node.p0Count" class="tag p0 mini">P0:{{ node.p0Count }}</span>
                    <span v-if="node.p1Count" class="tag p1 mini">P1:{{ node.p1Count }}</span>
                  </div>
                </div>

                <!-- 二级目录 -->
                <ul v-if="node.children.length && openDirs.has(node.path)" class="tree-ul sub-tree">
                  <li v-for="sub in node.children" :key="sub.id" class="tree-li">
                    <div
                      class="tree-row"
                      :class="{ active: selectedPath === sub.path }"
                      :title="sub.path"
                      @click="selectNode(sub)"
                    >
                      <button
                        v-if="sub.children.length"
                        type="button"
                        class="tree-expander"
                        @click.stop="toggleDir(sub.path)"
                      >
                        {{ openDirs.has(sub.path) ? '▾' : '▸' }}
                      </button>
                      <span v-else class="tree-expander-space"></span>
                      <span class="tree-type-icon">{{ sub.isDir ? '📁' : '📄' }}</span>
                      <span class="tree-text-truncate">{{ sub.name }}</span>
                      <div class="tree-pill-tags">
                        <span v-if="sub.p0Count" class="tag p0 mini">P0:{{ sub.p0Count }}</span>
                        <span v-if="sub.p1Count" class="tag p1 mini">P1:{{ sub.p1Count }}</span>
                      </div>
                    </div>

                    <!-- 三级目录 -->
                    <ul v-if="sub.children.length && openDirs.has(sub.path)" class="tree-ul sub-tree">
                      <li v-for="deep in sub.children" :key="deep.id" class="tree-li">
                        <div
                          class="tree-row"
                          :class="{ active: selectedPath === deep.path }"
                          :title="deep.path"
                          @click="selectNode(deep)"
                        >
                          <span class="tree-expander-space"></span>
                          <span class="tree-type-icon">{{ deep.isDir ? '📁' : '📄' }}</span>
                          <span class="tree-text-truncate">{{ deep.name }}</span>
                          <div class="tree-pill-tags">
                            <span v-if="deep.p0Count" class="tag p0 mini">P0:{{ deep.p0Count }}</span>
                            <span v-if="deep.p1Count" class="tag p1 mini">P1:{{ deep.p1Count }}</span>
                          </div>
                        </div>
                      </li>
                    </ul>
                  </li>
                </ul>
              </li>
            </template>
          </ul>
        </div>
      </aside>

      <!-- 右侧：主焦点视口（单栏舒适阅读流，宽度自适应展开） -->
      <main class="inspector-main-flow">
        <div class="selected-target-bar">
          <div class="target-title-line">
            <span class="target-label">选定路径：</span>
            <code class="target-code">{{ selectedPath || '项目根目录' }}</code>
          </div>
          <div class="target-summary">
            <span>专属匹配：<strong>{{ directMatchedRules.length }}</strong> 条</span>
            <span class="divider">/</span>
            <span>全局继承：<strong>{{ globalInheritedRules.length }}</strong> 条</span>
          </div>
        </div>

        <!-- 专属规则板块 -->
        <div v-if="directMatchedRules.length" class="rules-section-block">
          <h3 class="section-title-line">
            <span>模块专属规矩</span>
            <span class="badge-count">{{ directMatchedRules.length }}</span>
          </h3>

          <div class="rule-cards-vertical">
            <article
              v-for="rule in directMatchedRules"
              :key="rule.id"
              class="spec-article-card"
              :class="rule.priority.toLowerCase()"
            >
              <div class="article-top">
                <div class="article-title-wrap">
                  <h4>{{ rule.title }}</h4>
                  <div class="tags">
                    <span class="tag" :class="rule.priority.toLowerCase()">
                      {{ rule.priority === 'P0' ? 'P0 强制核心契约' : rule.priority === 'P1' ? 'P1 任务约束规范' : 'P2 建议' }}
                    </span>
                    <span class="tag" :class="rule.status">{{ rule.status === 'active' ? '生效中' : '已停用' }}</span>
                    <span class="tag">{{ rule.task_id ? '任务短期规则' : '长期项目契约' }}</span>
                  </div>
                </div>
              </div>

              <!-- 条款列表：充足宽度与行高，自然段落排版 -->
              <div class="article-points-content">
                <div class="points-header">具体执行条款：</div>
                <ol class="points-ol">
                  <li v-for="(point, i) in rule.points" :key="i">
                    <span class="point-text">{{ point }}</span>
                  </li>
                </ol>
              </div>

              <!-- 元数据横向流动标签 -->
              <div class="article-meta-footer">
                <div class="meta-item">
                  <span class="meta-name">管辖模式:</span>
                  <code class="meta-code" v-for="(pat, i) in rule.patterns" :key="i">{{ pat }}</code>
                </div>
                <div class="meta-item right">
                  <span class="muted">引用: {{ rule.eval_count }} 次 · 标记已知: {{ rule.known_count }} 次 · 均分: <strong>{{ rule.avg_score ?? '—' }}</strong></span>
                </div>
              </div>
            </article>
          </div>
        </div>

        <div v-else class="empty-hint-card">
          该路径暂未定制模块专属规矩，编码时将默认遵循下方全项目通用的全局核心规范。
        </div>

        <!-- 全局继承规矩板块 -->
        <div v-if="globalInheritedRules.length" class="rules-section-block global-block">
          <h3 class="section-title-line global">
            <span>全项目通用核心规范 (全局继承)</span>
            <span class="badge-count">{{ globalInheritedRules.length }}</span>
          </h3>

          <div class="rule-cards-vertical">
            <article
              v-for="rule in globalInheritedRules"
              :key="rule.id"
              class="spec-article-card global"
              :class="rule.priority.toLowerCase()"
            >
              <div class="article-top">
                <div class="article-title-wrap">
                  <h4>{{ rule.title }}</h4>
                  <div class="tags">
                    <span class="tag" :class="rule.priority.toLowerCase()">{{ rule.priority }} 全局契约</span>
                  </div>
                </div>
              </div>
              <div class="article-points-content">
                <ol class="points-ol">
                  <li v-for="(point, i) in rule.points" :key="i">
                    <span class="point-text">{{ point }}</span>
                  </li>
                </ol>
              </div>
            </article>
          </div>
        </div>
      </main>
    </div>
  </div>
</template>

<style scoped>
.explorer-view-wrapper {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.explorer-split-container {
  display: flex;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--bg-surface);
  min-height: 700px;
  overflow: hidden;
}

/* 左侧目录树面板（严格单行、截断排版） */
.tree-sidebar-panel {
  width: 300px;
  min-width: 300px;
  max-width: 300px;
  border-right: 1px solid var(--border-subtle);
  background: var(--bg-subtle);
  display: flex;
  flex-direction: column;
}

.tree-header {
  padding: 14px 16px;
  border-bottom: 1px solid var(--border-subtle);
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.tree-header h3 {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-tertiary);
  margin: 0;
}

.tree-filter-box {
  padding: 10px 12px;
  border-bottom: 1px solid var(--border-subtle);
}
.tree-search-input {
  padding: 6px 10px;
  font-size: 11px;
  background: var(--bg-surface);
}

.tree-scroll-area {
  padding: 8px 6px;
  overflow-y: auto;
  flex: 1;
  max-height: 700px;
}

.tree-ul {
  list-style: none;
  padding: 0;
  margin: 0;
}
.tree-ul.sub-tree {
  padding-left: 12px;
  border-left: 1px solid var(--border-subtle);
  margin-left: 10px;
}

.tree-li {
  margin: 2px 0;
}

/* 核心：单行截断，坚决不折叠为多行竖直字 */
.tree-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  border-radius: 4px;
  cursor: pointer;
  color: var(--text-secondary);
  font-size: 11px;
  font-family: var(--font-mono);
  white-space: nowrap;
  overflow: hidden;
  transition: all 0.1s ease;
}
.tree-row:hover {
  background: var(--bg-surface);
  color: var(--text-primary);
}
.tree-row.active {
  background: var(--accent-bg);
  color: #d1caff;
  font-weight: 600;
}

.tree-expander {
  background: transparent;
  border: 0;
  color: var(--text-tertiary);
  width: 14px;
  padding: 0;
  font-size: 10px;
  cursor: pointer;
}
.tree-expander-space {
  width: 14px;
  display: inline-block;
}

.tree-type-icon {
  font-size: 12px;
  flex-shrink: 0;
}

.tree-text-truncate {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tree-pill-tags {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}
.tag.mini {
  padding: 1px 4px;
  font-size: 9px;
  border-radius: 2px;
}

/* 右侧：单栏舒适阅读流 */
.inspector-main-flow {
  flex: 1;
  padding: 24px 32px;
  overflow-y: auto;
  max-height: 800px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.selected-target-bar {
  background: var(--bg-subtle);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  padding: 14px 18px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.target-title-line {
  display: flex;
  align-items: center;
  gap: 8px;
}
.target-label {
  font-size: 12px;
  color: var(--text-tertiary);
  font-weight: 600;
}
.target-code {
  font-size: 13px;
  color: var(--accent);
  background: rgba(0, 0, 0, 0.2);
  padding: 2px 8px;
  border-radius: 4px;
}
.target-summary {
  font-size: 12px;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  gap: 8px;
}
.divider {
  color: var(--text-tertiary);
}

.section-title-line {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 12px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.section-title-line.global {
  color: var(--accent);
}
.badge-count {
  font-size: 11px;
  background: var(--bg-subtle);
  border: 1px solid var(--border-subtle);
  padding: 2px 7px;
  border-radius: 10px;
  color: var(--text-secondary);
}

.rule-cards-vertical {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

/* 规范文章卡片：给足宽度，舒展大方 */
.spec-article-card {
  background: var(--bg-subtle);
  border: 1px solid var(--border-subtle);
  border-left: 4px solid var(--accent);
  border-radius: 6px;
  padding: 18px 22px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.15);
}
.spec-article-card.p0 {
  border-left-color: var(--red);
}
.spec-article-card.p1 {
  border-left-color: var(--amber);
}
.spec-article-card.global {
  border-left-color: #6366f1;
}

.article-title-wrap h4 {
  font-size: 14px;
  font-weight: 600;
  margin: 0 0 6px;
  color: var(--text-primary);
}

.article-points-content {
  background: rgba(0, 0, 0, 0.2);
  border-radius: 6px;
  padding: 12px 16px;
}
.points-header {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-tertiary);
  text-transform: uppercase;
  margin-bottom: 8px;
}
.points-ol {
  margin: 0;
  padding-left: 20px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.point-text {
  font-size: 13px;
  line-height: 1.65;
  color: var(--text-primary);
}

.article-meta-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 10px;
  border-top: 1px solid var(--border-subtle);
  font-size: 11px;
}
.meta-item {
  display: flex;
  align-items: center;
  gap: 6px;
}
.meta-name {
  color: var(--text-tertiary);
}
.meta-code {
  font-size: 11px;
  background: rgba(255, 255, 255, 0.05);
  padding: 1px 6px;
  border-radius: 3px;
  color: #c4b5fd;
}

.empty-hint-card {
  background: var(--bg-subtle);
  border: 1px dashed var(--border-subtle);
  border-radius: 6px;
  padding: 24px;
  text-align: center;
  color: var(--text-tertiary);
  font-size: 12px;
}
</style>
