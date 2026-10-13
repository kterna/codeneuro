<script setup lang="ts">
export type ScopeTreeNodeModel = {
  id: string
  name: string
  path: string
  isDir: boolean
  children: ScopeTreeNodeModel[]
  p0Count: number
  p1Count: number
  p2Count: number
  ruleIds: string[]
}

const props = defineProps<{
  node: ScopeTreeNodeModel
  selectedPath: string
  openDirs: Set<string>
  depth?: number
}>()

const emit = defineEmits<{
  (e: 'select', node: ScopeTreeNodeModel): void
  (e: 'toggle', path: string): void
}>()

const currentDepth = props.depth ?? 0
</script>

<template>
  <li class="tree-li">
    <div
      class="tree-row"
      :class="{ active: selectedPath === node.path }"
      :style="{ paddingLeft: `${8 + currentDepth * 16}px` }"
      :title="node.path"
      role="treeitem"
      tabindex="0"
      :aria-selected="selectedPath === node.path"
      :aria-expanded="node.children.length ? openDirs.has(node.path) : undefined"
      @click="emit('select', node)"
      @keydown.enter="emit('select', node)"
      @keydown.space.prevent="emit('select', node)"
    >
      <button
        v-if="node.children.length"
        type="button"
        class="tree-expander"
        :aria-label="openDirs.has(node.path) ? '折叠' : '展开'"
        @click.stop="emit('toggle', node.path)"
      >
        {{ openDirs.has(node.path) ? '▾' : '▸' }}
      </button>
      <span v-else class="tree-expander-space"></span>

      <span class="tree-type-icon">{{ node.isDir ? '📁' : '📄' }}</span>
      <span class="tree-text-truncate">{{ node.name }}</span>

      <div class="tree-pill-tags">
        <span v-if="node.p0Count" class="tag p0 mini" title="核心契约 (P0)">P0:{{ node.p0Count }}</span>
        <span v-if="node.p1Count" class="tag p1 mini" title="重要规则 (P1)">P1:{{ node.p1Count }}</span>
        <span v-if="node.p2Count" class="tag p2 mini" title="参考规则 (P2)">P2:{{ node.p2Count }}</span>
      </div>
    </div>

    <!-- 递归子节点 -->
    <ul
      v-if="node.children.length && openDirs.has(node.path)"
      class="tree-ul sub-tree"
      role="group"
    >
      <ScopeTreeNodeItem
        v-for="child in node.children"
        :key="child.id"
        :node="child"
        :selected-path="selectedPath"
        :open-dirs="openDirs"
        :depth="currentDepth + 1"
        @select="emit('select', $event)"
        @toggle="emit('toggle', $event)"
      />
    </ul>
  </li>
</template>

<style scoped>
.tree-li {
  list-style: none;
  margin: 0;
  padding: 0;
}

.tree-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding-top: 4px;
  padding-bottom: 4px;
  padding-right: 8px;
  cursor: pointer;
  border-radius: 4px;
  font-size: 12px;
  color: var(--gh-fg-default);
  transition: background 0.1s ease;
  user-select: none;
  outline: none;
}

.tree-row:hover, .tree-row:focus {
  background: var(--gh-surface-card-hover);
}

.tree-row.active {
  background: var(--gh-surface-card);
  border-left: 2px solid var(--gh-accent-fg);
  font-weight: 600;
}

.tree-expander {
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
  font-size: 10px;
  color: var(--gh-fg-muted);
  width: 14px;
  height: 14px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 2px;
}

.tree-expander-space {
  width: 14px;
  display: inline-block;
  flex-shrink: 0;
}

.tree-type-icon {
  font-size: 12px;
  flex-shrink: 0;
}

.tree-text-truncate {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tree-pill-tags {
  display: flex;
  gap: 3px;
  flex-shrink: 0;
  margin-left: auto;
}

.tag.mini {
  padding: 1px 4px;
  font-size: 9px;
  border-radius: 3px;
}

.sub-tree {
  list-style: none;
  margin: 0;
  padding: 0;
}
</style>
