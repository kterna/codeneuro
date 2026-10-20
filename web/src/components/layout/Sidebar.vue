<script setup lang="ts">
import { computed } from 'vue'
import type { Project, TabId, TabItem } from '../../types/ledger'
import { useTheme } from '../../composables/useTheme'

const props = withDefaults(defineProps<{
  projects: Project[]
  currentProjectId: string
  tabs: readonly TabItem[]
  currentTab: TabId
  connectionStatus?: 'connecting' | 'connected' | 'disconnected'
  errorText?: string
}>(), {
  connectionStatus: 'connected',
  errorText: '',
})

const emit = defineEmits<{
  (e: 'select-project', id: string): void
  (e: 'open-create-project'): void
  (e: 'select-tab', tab: TabId): void
  (e: 'open-palette'): void
}>()

const { theme, setTheme } = useTheme()

function toggleTheme() {
  setTheme(theme.value === 'dark' ? 'light' : 'dark')
}

// 明确分离业务工作区（项目级）与系统配置（系统级）
const projectTabs = computed(() => props.tabs.filter(t => t.id !== 'settings'))
const systemTab = computed(() => props.tabs.find(t => t.id === 'settings'))
</script>

<template>
  <aside class="sidebar" aria-label="侧边栏">
    <!-- 顶部 Brand 与项目选择条 (合并紧凑单行) -->
    <div class="sidebar-brand-project">
      <a class="brand" href="/app/" aria-label="CodeNeuro 首页">
        <span class="brand-mark">C</span>
        <span class="brand-title">CodeNeuro<small>任务与规则工作台</small></span>
      </a>

      <!-- 紧凑型项目切换栏：下拉框与新增按钮并列 -->
      <div class="project-selector-compact">
        <select
          id="project"
          class="project-select-input"
          :value="currentProjectId"
          :title="projects.find(p => p.id === currentProjectId)?.name || '未选项目'"
          aria-label="切换项目"
          @change="emit('select-project', ($event.target as HTMLSelectElement).value)"
        >
          <option v-if="!projects.length" value="">暂无项目</option>
          <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
        <button
          id="new-project"
          class="btn-add-project"
          title="注册新项目"
          aria-label="注册新项目"
          @click="emit('open-create-project')"
        >
          ＋
        </button>
      </div>
    </div>

    <!-- 侧边栏导航：项目级核心业务工作区 -->
    <nav id="navigation" class="sidebar-nav" aria-label="项目工作台导航">
      <div class="nav-section-label">项目工作区</div>
      <button
        v-for="item in projectTabs"
        :key="item.id"
        class="nav-tab-item"
        :class="{ active: currentTab === item.id }"
        @click="emit('select-tab', item.id)"
      >
        <span class="nav-icon">{{ item.icon }}</span>
        <span class="nav-text">{{ item.title }}</span>
      </button>

      <!-- 系统级功能分组 -->
      <div class="nav-section-label system-label">系统与设置</div>
      <button
        v-if="systemTab"
        class="nav-tab-item"
        :class="{ active: currentTab === systemTab.id }"
        @click="emit('select-tab', systemTab.id)"
      >
        <span class="nav-icon">{{ systemTab.icon }}</span>
        <span class="nav-text">{{ systemTab.title }}</span>
      </button>
    </nav>

    <!-- 侧边栏极简工具条底栏 -->
    <div class="aside-foot-compact">
      <div class="foot-tool-row">
        <button
          id="open-palette"
          class="palette-btn-compact"
          title="打开命令面板 (Ctrl K)"
          @click="emit('open-palette')"
        >
          ⌘ 命令 <kbd>Ctrl K</kbd>
        </button>

        <button
          class="theme-toggle-btn"
          :title="theme === 'dark' ? '切换为浅色主题' : '切换为深色主题'"
          @click="toggleTheme"
        >
          {{ theme === 'dark' ? '🌙' : '☀️' }}
        </button>
      </div>

      <div class="foot-status-row">
        <span
          id="health"
          role="status"
          class="status-indicator"
          :class="connectionStatus"
        >
          <span class="status-dot"></span>
          {{
            connectionStatus === 'connecting'
              ? '连接中…'
              : connectionStatus === 'disconnected'
                ? '服务断开'
                : '服务正常'
          }}
        </span>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.sidebar-brand-project {
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex-shrink: 0;
}

.brand {
  text-decoration: none;
  color: var(--gh-fg-default);
  font-size: 14px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 2px;
}

.project-selector-compact {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
}

.project-select-input {
  flex: 1;
  min-width: 0;
  font-size: 12px;
  padding: 5px 8px;
  height: 30px;
  background: var(--gh-canvas-inset);
  color: var(--gh-fg-default);
  border: 1px solid var(--gh-border-default);
  border-radius: var(--radius-sm);
  text-overflow: ellipsis;
  white-space: nowrap;
  overflow: hidden;
}

.btn-add-project {
  width: 28px !important;
  min-width: 28px !important;
  max-width: 28px !important;
  height: 28px !important;
  min-height: 28px !important;
  max-height: 28px !important;
  flex: 0 0 28px !important;
  padding: 0 !important;
  margin: 0 !important;
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  font-size: 15px !important;
  line-height: 1 !important;
  background: var(--gh-surface-card);
  border: 1px solid var(--gh-border-default);
  color: var(--gh-fg-default);
  border-radius: var(--radius-sm);
  cursor: pointer;
  box-sizing: border-box;
}

.btn-add-project:hover {
  background: var(--gh-surface-card-hover);
  border-color: var(--gh-accent-fg);
  color: var(--gh-accent-fg);
}

.sidebar-nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-top: 14px;
  flex: 1;
  overflow-y: auto;
}

.nav-section-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--gh-fg-subtle);
  padding: 8px 10px 4px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.system-label {
  margin-top: 12px;
  border-top: 1px solid var(--gh-border-muted);
  padding-top: 10px;
}

.nav-tab-item {
  text-align: left;
  background: transparent;
  border: 0;
  padding: 6px 10px;
  color: var(--gh-fg-muted);
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  font-weight: 400;
  cursor: pointer;
  transition: all 0.1s ease;
  width: 100%;
}

.nav-tab-item:hover {
  background: var(--gh-surface-card);
  color: var(--gh-fg-default);
}

.nav-tab-item.active {
  background: var(--gh-surface-card-hover);
  color: var(--gh-accent-fg);
  font-weight: 600;
}

.nav-icon {
  width: 16px;
  font-size: 13px;
  display: inline-block;
  flex-shrink: 0;
}

.nav-text {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.aside-foot-compact {
  padding-top: 10px;
  border-top: 1px solid var(--gh-border-default);
  display: flex;
  flex-direction: column;
  gap: 8px;
  flex-shrink: 0;
}

.foot-tool-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.palette-btn-compact {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 5px 8px;
  font-size: 11px;
  background: var(--gh-canvas-default);
  border: 1px solid var(--gh-border-default);
  color: var(--gh-fg-muted);
  border-radius: var(--radius-sm);
  cursor: pointer;
}

.palette-btn-compact:hover {
  border-color: var(--gh-fg-muted);
  color: var(--gh-fg-default);
}

.theme-toggle-btn {
  width: 30px;
  height: 28px;
  padding: 0;
  display: grid;
  place-items: center;
  font-size: 13px;
  background: var(--gh-canvas-default);
  border: 1px solid var(--gh-border-default);
  border-radius: var(--radius-sm);
  cursor: pointer;
  flex-shrink: 0;
}

.theme-toggle-btn:hover {
  background: var(--gh-surface-card);
  border-color: var(--gh-accent-fg);
}

.foot-status-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.status-indicator {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--gh-fg-subtle);
  font-family: var(--font-mono);
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--gh-success-fg);
}

.status-indicator.connecting .status-dot {
  background: var(--gh-attention-fg);
}

.status-indicator.disconnected .status-dot {
  background: var(--gh-danger-fg);
}

@media (max-width: 1024px) {
  .sidebar-brand-project {
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }

  .brand {
    flex: 0 0 auto;
    margin: 0;
  }

  .project-selector-compact {
    flex: 0 1 260px;
    width: auto;
    max-width: 50%;
    min-width: 0;
  }

  .nav-section-label {
    display: none;
  }

  .nav-tab-item {
    width: auto;
  }

  .aside-foot-compact {
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding-top: 6px;
  }
}
</style>
