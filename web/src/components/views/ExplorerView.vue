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

  // 1. 优先使用真实文件系统扫描结果
  const rawPaths: { path: string; isDir: boolean }[] = []
  if (realTreeItems.value.length > 0) {
    for (const item of realTreeItems.value) {
      rawPaths.push({ path: item.path, isDir: item.is_dir })
    }
  } else {
    // 兜底从规则 patterns 提炼合法路径
    for (const rule of props.ledger.rules) {
      for (const pat of rule.patterns) {
        const clean = pat.replace(/^\.\//, '').replace(/\/\*\*|\/\*/g, '').trim()
        if (clean && !clean.includes(' ') && !clean.includes('(') && !clean.includes('=')) {
          rawPaths.push({ path: clean, isDir: !clean.includes('.') })
        }
      }
    }
  }

  // 2. 将路径插入树结构中
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

  // 3. 计算每个节点的统计数
  const activeRules = props.ledger.rules.filter(r => r.status === 'active')
  for (const [, node] of nodeMap) {
    for (const rule of activeRules) {
      if (isRuleApplicableToPath(rule, node.path, false)) {
        if (rule.priority === 'P0') node.p0Count++
        else node.p1Count++
      }
    }
  }

  // 默认展开顶层目录
  for (const child of root.children) {
    openDirs.value.add(child.path)
  }

  return root.children
})

// 默认选中
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

// 核心规则匹配算法
function isRuleApplicableToPath(rule: Rule, targetPath: string, includeGlobal = true): boolean {
  if (!targetPath) return includeGlobal
  for (const rawPattern of rule.patterns) {
    const pat = rawPattern.replace(/^\.\//, '').trim()
    if (pat === '**' || pat === '*' || !pat) {
      if (includeGlobal) return true
      continue
    }
    const cleanPrefix = pat.replace(/\/\*\*|\/\*/g, '')
    // 选中的是该子树或其下文件（如选 src，规则在 src/adapters/**，或者选 src/adapters，规则在 src/**）
    if (targetPath.startsWith(cleanPrefix) || cleanPrefix.startsWith(targetPath)) {
      return true
    }
    if (pat === targetPath || pat.endsWith(targetPath) || targetPath.endsWith(pat)) {
      return true
    }
  }
  return false
}

// 过滤后的树节点
const filteredTree = computed(() => {
  const q = treeSearch.value.trim().toLowerCase()
  if (!q) return directoryTree.value
  return directoryTree.value.filter(n => n.name.toLowerCase().includes(q) || n.path.toLowerCase().includes(q))
})

// 当前路径直接专属匹配的规则
const directMatchedRules = computed<Rule[]>(() => {
  if (!selectedPath.value) return []
  const rules = props.ledger.rules.filter(r => r.status === 'active')
  return rules.filter(r => isRuleApplicableToPath(r, selectedPath.value, false))
})

// 全局通配继承的规则（在任何目录都会兜底生效的 P0/P1）
const globalInheritedRules = computed<Rule[]>(() => {
  const rules = props.ledger.rules.filter(r => r.status === 'active')
  return rules.filter(r => r.patterns.some(p => p === '**' || p === '*' || !p.trim()))
})
</script>

<template>
  <div>
    <div class="section-head">
      <h2>代码作用域与层级目录</h2>
      <span class="caption">
        {{ realTreeItems.length ? '已连接本地工作区，真实呈现代码目录结构' : '解析规则路径模式，呈现受控目录层级' }}
      </span>
    </div>

    <div v-if="!ledger.rules.length" class="empty">
      当前项目尚未配置任何针对代码路径的规则。
    </div>

    <div v-else class="split-view">
      <!-- 左侧：目录树面板 -->
      <div class="tree-pane">
        <div class="pane-title">
          <h2>工程目录结构 (Directory Tree)</h2>
          <span class="muted">{{ directoryTree.length }} 顶层节点</span>
        </div>

        <div style="padding: 10px 12px; border-bottom: 1px solid var(--line)">
          <input
            v-model="treeSearch"
            placeholder="过滤目录或文件…"
            style="padding: 5px 8px; font-size: 11px"
          />
        </div>

        <div class="tree-content">
          <ul class="file-tree-root">
            <template v-for="node in filteredTree" :key="node.id">
              <li class="tree-node-item">
                <div
                  class="tree-node-row"
                  :class="{ selected: selectedPath === node.path }"
                  @click="selectNode(node)"
                >
                  <button
                    v-if="node.children.length"
                    type="button"
                    class="tree-arrow-btn"
                    @click.stop="toggleDir(node.path)"
                  >
                    {{ openDirs.has(node.path) ? '▼' : '▶' }}
                  </button>
                  <span v-else class="tree-arrow-placeholder"></span>
                  <span class="tree-icon">{{ node.isDir ? '📁' : '📄' }}</span>
                  <span class="tree-label">{{ node.name }}</span>
                  <div class="tree-counts">
                    <span v-if="node.p0Count" class="p0">P0:{{ node.p0Count }}</span>
                    <span v-if="node.p1Count" class="p1">P1:{{ node.p1Count }}</span>
                  </div>
                </div>

                <!-- 二级目录 -->
                <ul v-if="node.children.length && openDirs.has(node.path)" class="tree-sub-list">
                  <li v-for="sub in node.children" :key="sub.id" class="tree-node-item">
                    <div
                      class="tree-node-row"
                      :class="{ selected: selectedPath === sub.path }"
                      @click="selectNode(sub)"
                    >
                      <button
                        v-if="sub.children.length"
                        type="button"
                        class="tree-arrow-btn"
                        @click.stop="toggleDir(sub.path)"
                      >
                        {{ openDirs.has(sub.path) ? '▼' : '▶' }}
                      </button>
                      <span v-else class="tree-arrow-placeholder"></span>
                      <span class="tree-icon">{{ sub.isDir ? '📁' : '📄' }}</span>
                      <span class="tree-label">{{ sub.name }}</span>
                      <div class="tree-counts">
                        <span v-if="sub.p0Count" class="p0">P0:{{ sub.p0Count }}</span>
                        <span v-if="sub.p1Count" class="p1">P1:{{ sub.p1Count }}</span>
                      </div>
                    </div>

                    <!-- 三级目录 -->
                    <ul v-if="sub.children.length && openDirs.has(sub.path)" class="tree-sub-list">
                      <li v-for="deep in sub.children" :key="deep.id" class="tree-node-item">
                        <div
                          class="tree-node-row"
                          :class="{ selected: selectedPath === deep.path }"
                          @click="selectNode(deep)"
                        >
                          <span class="tree-arrow-placeholder"></span>
                          <span class="tree-icon">{{ deep.isDir ? '📁' : '📄' }}</span>
                          <span class="tree-label">{{ deep.name }}</span>
                          <div class="tree-counts">
                            <span v-if="deep.p0Count" class="p0">P0:{{ deep.p0Count }}</span>
                            <span v-if="deep.p1Count" class="p1">P1:{{ deep.p1Count }}</span>
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

        <div class="tree-legend">
          <span>P0 强制核心契约</span>
          <span>P1 任务约束规范</span>
        </div>
      </div>

      <!-- 右侧：焦点视口 (Focus Inspector) -->
      <div class="focus-pane">
        <div class="focus-path">
          <strong>当前选定代码路径：</strong><code>{{ selectedPath || '项目根目录' }}</code>
        </div>
        <div class="breadcrumbs">
          <span>该路径专属匹配 {{ directMatchedRules.length }} 条 · 全局继承 {{ globalInheritedRules.length }} 条</span>
          <span>Agent 触碰该代码时自动下发</span>
        </div>

        <!-- 专属匹配规则板块 -->
        <div v-if="directMatchedRules.length">
          <div class="section-head" style="margin: 16px 0 10px">
            <h3 style="margin: 0">模块专属规矩 ({{ directMatchedRules.length }} 条)</h3>
          </div>
          <article
            v-for="rule in directMatchedRules"
            :key="rule.id"
            class="focus-rule"
            :class="rule.priority.toLowerCase()"
          >
            <div class="card-top">
              <h3>{{ rule.title }}</h3>
              <div class="tags">
                <span class="tag" :class="rule.priority.toLowerCase()">
                  {{ rule.priority === 'P0' ? 'P0 强制核心契约' : rule.priority === 'P1' ? 'P1 任务约束规范' : 'P2 建议' }}
                </span>
                <span class="tag" :class="rule.status">{{ rule.status === 'active' ? '生效中' : '已停用' }}</span>
                <span class="tag">{{ rule.task_id ? '任务短期规则' : '长期项目契约' }}</span>
              </div>
            </div>

            <ul style="margin: 10px 0; padding-left: 18px; line-height: 1.7">
              <li v-for="(point, i) in rule.points" :key="i">{{ point }}</li>
            </ul>

            <div class="definition">
              <dt>管辖模式：</dt>
              <dd><code>{{ rule.patterns.join(' · ') }}</code></dd>
              <dt>效用评估：</dt>
              <dd>
                被引用 {{ rule.eval_count }} 次 · 标记已知 {{ rule.known_count }} 次 · 均分：{{ rule.avg_score ?? '—' }}
              </dd>
            </div>
          </article>
        </div>

        <div v-else class="empty compact" style="margin: 16px 0">
          该路径暂无单独定制的局部规矩，当前默认遵循下方全项目通用的全局核心规范。
        </div>

        <!-- 全局继承规矩板块 (兜底契约) -->
        <div v-if="globalInheritedRules.length" style="margin-top: 24px">
          <div class="section-head" style="margin: 16px 0 10px">
            <h3 style="margin: 0; color: var(--accent)">全项目通用契约 (全局继承 · {{ globalInheritedRules.length }} 条)</h3>
          </div>
          <article
            v-for="rule in globalInheritedRules"
            :key="rule.id"
            class="focus-rule"
            :class="rule.priority.toLowerCase()"
            style="opacity: 0.9"
          >
            <div class="card-top">
              <h3>{{ rule.title }}</h3>
              <div class="tags">
                <span class="tag" :class="rule.priority.toLowerCase()">{{ rule.priority }} 全局契约</span>
              </div>
            </div>
            <ul style="margin: 10px 0; padding-left: 18px; line-height: 1.7">
              <li v-for="(point, i) in rule.points" :key="i">{{ point }}</li>
            </ul>
            <small class="muted">全项目代码改动均受此约束管辖</small>
          </article>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.file-tree-root {
  list-style: none;
  padding: 8px 6px;
  margin: 0;
}
.tree-sub-list {
  list-style: none;
  padding-left: 14px;
  margin: 0;
  border-left: 1px solid var(--line);
}
.tree-node-item {
  margin: 2px 0;
}
.tree-node-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 11px;
  font-family: var(--mono);
  color: #bfc5d8;
  transition: background 0.12s;
}
.tree-node-row:hover {
  background: var(--surface);
  color: var(--text);
}
.tree-node-row.selected {
  background: #28233d;
  color: #e0d9ff;
  border-left: 2px solid var(--accent);
}
.tree-arrow-btn {
  background: transparent;
  border: 0;
  color: var(--muted);
  padding: 0;
  width: 14px;
  font-size: 9px;
  line-height: 1;
}
.tree-arrow-placeholder {
  width: 14px;
  display: inline-block;
}
.tree-icon {
  font-size: 12px;
}
.tree-label {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
