<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import type { Ledger, Project, Proposal, TabId, TabItem } from './types/ledger'
import { apiService, ApiError } from './api/client'

// 布局组件
import Sidebar from './components/layout/Sidebar.vue'
import MetricBar from './components/layout/MetricBar.vue'
import CommandPalette from './components/common/CommandPalette.vue'
import ActionDialog from './components/common/ActionDialog.vue'

// 核心业务视图组件
import ExplorerView from './components/views/ExplorerView.vue'
import TasksView from './components/views/TasksView.vue'
import RulesView from './components/views/RulesView.vue'
import ReviewView from './components/views/ReviewView.vue'
import FeedbackView from './components/views/FeedbackView.vue'
import ActivityView from './components/views/ActivityView.vue'
import ProjectSettingsView from './components/views/ProjectSettingsView.vue'
import OverviewView from './components/views/OverviewView.vue'

const tabs: readonly TabItem[] = [
  { id: 'overview', icon: '◫', title: '项目总览', subtitle: '查看项目核心指标与规则、便签分布。' },
  { id: 'tasks', icon: '▥', title: '需求与任务看板', subtitle: '管理业务需求、子任务与整体验收。' },
  { id: 'rules', icon: '≋', title: '项目规则库', subtitle: '管理长期规则与任务规则。' },
  { id: 'explorer', icon: '⌘', title: '按目录查规则', subtitle: '按目录或文件查询适用规则。' },
  { id: 'review', icon: '◈', title: '规则修改审阅', subtitle: '审阅规则修改建议。' },
  { id: 'feedback', icon: '◎', title: '规则反馈与便签', subtitle: '查看规则评分与开发便签。' },
  { id: 'activity', icon: '↗', title: '操作记录', subtitle: '查看需求、任务与规则的变更历史。' },
  { id: 'settings', icon: '⚙', title: '项目设置与管理', subtitle: '管理项目信息、切换项目与数据清理。' },
]

const tab = ref<TabId>('tasks')
const current = computed(() => tabs.find(item => item.id === tab.value) || tabs[0])

const projects = ref<Project[]>([])
const projectId = ref('')
const ledger = ref<Ledger | null>(null)
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const notice = ref('')
const connectionStatus = ref<'connecting' | 'connected' | 'disconnected'>('connecting')

// 上下文代次、模态代次与动作 token 隔离 (解决跨项目与异步乱序)
let projectEpoch = 0
let modalEpoch = 0
let actionSeq = 0
const activeActionTokens = new Set<number>()

function startAction() {
  const token = ++actionSeq
  activeActionTokens.add(token)
  busy.value = true
  return token
}

function finishAction(token: number, capturedProjectEpoch: number) {
  if (capturedProjectEpoch === projectEpoch) {
    activeActionTokens.delete(token)
    busy.value = activeActionTokens.size > 0
  }
}

function resetProjectContext() {
  projectEpoch++
  modalEpoch++
  activeActionTokens.clear()
  busy.value = false
  error.value = ''
  notice.value = ''
}

// 请求代次与取消保护 (解决 D01 请求乱序覆盖)
let ledgerSeq = 0
let ledgerAbortCtrl: AbortController | null = null

// 组件 Ref
const paletteRef = ref<InstanceType<typeof CommandPalette> | null>(null)
const dialogRef = ref<InstanceType<typeof ActionDialog> | null>(null)

// 项目注册与长期契约审阅；需求/任务操作由其资源视图管理。
const modalMode = ref<'project' | 'approve' | 'reject'>('project')
const modalTitle = computed(() => {
  switch (modalMode.value) {
    case 'project': return '注册新项目'
    case 'approve': return '通过规则修改'
    case 'reject': return '拒绝规则修改'
  }
})
const modalTarget = ref<Proposal | null>(null)

function fail(cause: unknown) {
  const err = cause as Error
  error.value = err.message || String(cause)
  // 分离连接异常与常规业务错误 (解决 D27)
  if (cause instanceof ApiError) {
    if (cause.isNetworkError || cause.status === 0 || cause.status >= 502) {
      connectionStatus.value = 'disconnected'
    } else {
      connectionStatus.value = 'connected'
    }
  } else {
    connectionStatus.value = 'disconnected'
  }
}

// URL 状态恢复与持久化 (解决 D28 刷新丢失项目与位置)
function parseLocationFromUrl(): { projId?: string; tabId?: TabId } {
  const hash = window.location.hash.replace(/^#\/?/, '')
  const parts = hash.split('/')
  // 支持格式 #/projects/{projectId}/{tabId} 或 #{projectId}/{tabId}
  let projId: string | undefined
  let tabId: TabId | undefined

  if (parts[0] === 'projects' && parts[1]) {
    projId = decodeURIComponent(parts[1])
    if (parts[2] && tabs.some(t => t.id === parts[2])) {
      tabId = parts[2] as TabId
    }
  } else if (parts[0] && parts[0] !== 'projects') {
    if (tabs.some(t => t.id === parts[0])) {
      tabId = parts[0] as TabId
    } else {
      projId = decodeURIComponent(parts[0])
      if (parts[1] && tabs.some(t => t.id === parts[1])) {
        tabId = parts[1] as TabId
      }
    }
  }
  return { projId, tabId }
}

function syncUrl(push = false) {
  if (!projectId.value) return
  const newHash = `#/projects/${encodeURIComponent(projectId.value)}/${tab.value}`
  if (window.location.hash !== newHash) {
    if (push) {
      window.history.pushState(null, '', newHash)
    } else {
      window.history.replaceState(null, '', newHash)
    }
  }
}

function handleSelectTab(newTab: TabId) {
  tab.value = newTab
  syncUrl(true)
}

function focusContent() {
  const el = document.getElementById('content')
  el?.focus()
}

async function connect() {
  error.value = ''
  loading.value = true
  connectionStatus.value = 'connecting'
  try {
    projects.value = await apiService.getProjects()
    connectionStatus.value = 'connected'

    const { projId: urlProjId, tabId: urlTabId } = parseLocationFromUrl()
    if (urlTabId) {
      tab.value = urlTabId
    }

    if (urlProjId && projects.value.some(p => p.id === urlProjId)) {
      if (projectId.value !== urlProjId) {
        resetProjectContext()
        projectId.value = urlProjId
      }
    } else if (!projects.value.some(p => p.id === projectId.value)) {
      resetProjectContext()
      projectId.value = projects.value[0]?.id || ''
    }

    syncUrl()
    await refresh()
  } catch (cause) {
    fail(cause)
  } finally {
    loading.value = false
  }
}

async function refresh() {
  if (!projectId.value) {
    ledger.value = null
    return
  }

  const currentPid = projectId.value
  const seq = ++ledgerSeq
  const currentEpoch = projectEpoch

  if (ledgerAbortCtrl) {
    ledgerAbortCtrl.abort()
  }
  ledgerAbortCtrl = new AbortController()

  loading.value = true
  error.value = ''

  try {
    const data = await apiService.getLedger(currentPid, ledgerAbortCtrl.signal)
    // 检查响应代次，丢弃过时响应 (解决 D01)
    if (seq !== ledgerSeq || projectId.value !== currentPid || currentEpoch !== projectEpoch) {
      return
    }
    ledger.value = data
    connectionStatus.value = 'connected'
  } catch (cause: unknown) {
    if (cause instanceof DOMException && cause.name === 'AbortError') {
      return
    }
    if (seq !== ledgerSeq || currentEpoch !== projectEpoch) {
      return
    }
    fail(cause)
  } finally {
    if (seq === ledgerSeq && currentEpoch === projectEpoch) {
      loading.value = false
    }
  }
}

async function handleSelectProject(id: string) {
  if (projectId.value === id && ledger.value) return

  // 切换项目代次，立即隔离并清除旧 busy 与弹窗状态
  resetProjectContext()

  // 切换项目时立即清理旧数据与弹窗上下文，防止状态串行 (解决 D01)
  if (ledgerAbortCtrl) {
    ledgerAbortCtrl.abort()
    ledgerAbortCtrl = null
  }
  ledger.value = null
  modalTarget.value = null
  dialogRef.value?.close()

  projectId.value = id
  syncUrl(true)
  await refresh()
}

async function handleDeleteProject(targetId?: string) {
  const idToDelete = targetId || projectId.value
  if (!idToDelete) return
  const targetProject = projects.value.find(p => p.id === idToDelete)
  const currentProjectName = targetProject?.name || idToDelete

  const capturedProjectEpoch = projectEpoch
  const capturedProjectId = projectId.value
  const token = startAction()
  error.value = ''

  try {
    await apiService.deleteProject(idToDelete)
    const updatedProjects = await apiService.getProjects()
    projects.value = updatedProjects

    const isContextValid = capturedProjectEpoch === projectEpoch && capturedProjectId === projectId.value

    if (isContextValid) {
      notice.value = `项目「${currentProjectName}」已删除。`
      if (projectId.value === idToDelete) {
        projectId.value = updatedProjects[0]?.id || ''
        ledger.value = null
        syncUrl()
        if (projectId.value) {
          await refresh()
        }
      }
    } else {
      // 上下文已过期 (用户在删除期间切换了项目)：
      // 不显示 success/error，不把新选择强行拉回
      // 仅当当前选中的项目恰好是被删除的项目时，才需要降级切到可用项目
      if (projectId.value === idToDelete) {
        projectId.value = updatedProjects.some(p => p.id === projectId.value)
          ? projectId.value
          : (updatedProjects[0]?.id || '')
        ledger.value = null
        syncUrl()
        if (projectId.value) {
          await refresh()
        }
      }
    }
  } catch (cause) {
    if (capturedProjectEpoch === projectEpoch && capturedProjectId === projectId.value) {
      fail(cause)
    }
  } finally {
    finishAction(token, capturedProjectEpoch)
  }
}

// 统计衍生属性 (解决 D12: 核心契约严格过滤 P0)
const activeRequirementsCount = computed(
  () => ledger.value?.counts.requirements.working ?? 0,
)
const activeTasksCount = computed(
  () => ledger.value?.counts.tasks.working ?? 0,
)
const contractsCount = computed(
  () => ledger.value?.rules.filter(r => r.task_id === null && r.status === 'active' && r.priority === 'P0').length ?? 0,
)
const pendingProposalsCount = computed(
  () => ledger.value?.proposals.filter(p => p.status === 'pending').length ?? 0,
)

// 打开弹窗系列
function openCreateProject() {
  modalEpoch++
  modalMode.value = 'project'
  modalTarget.value = null
  dialogRef.value?.open()
}

function openApprove(prop: Proposal) {
  modalEpoch++
  modalMode.value = 'approve'
  modalTarget.value = prop
  dialogRef.value?.open()
}

function openReject(prop: Proposal) {
  modalEpoch++
  modalMode.value = 'reject'
  modalTarget.value = prop
  dialogRef.value?.open()
}

function handleDialogClose() {
  modalEpoch++
}

// 项目和长期契约弹窗提交。
async function handleDialogSubmit(data: {
  projectId?: string
  projectName?: string
  reason?: string
}) {
  const capturedProjectEpoch = projectEpoch
  const capturedProjectId = projectId.value
  const capturedModalEpoch = modalEpoch
  const capturedMode = modalMode.value
  const capturedTarget = modalTarget.value

  const isModalContextValid = () => {
    if (capturedMode === 'project') {
      return capturedModalEpoch === modalEpoch && modalMode.value === 'project'
    }
    return (
      capturedProjectEpoch === projectEpoch &&
      capturedProjectId === projectId.value &&
      capturedModalEpoch === modalEpoch &&
      modalMode.value === capturedMode &&
      modalTarget.value === capturedTarget
    )
  }

  const token = startAction()
  error.value = ''
  try {
    if (capturedMode === 'project') {
      const created = await apiService.createProject(data.projectId || '', data.projectName || '')
      const list = await apiService.getProjects()
      projects.value = list
      if (!isModalContextValid()) return
      notice.value = `项目「${created.name}」已注册。`
      modalEpoch++
      dialogRef.value?.close()
      projectId.value = created.id
      syncUrl()
      await refresh()
    } else if (capturedMode === 'approve' || capturedMode === 'reject') {
      const p = capturedTarget as Proposal
      await apiService.reviewProposal(
        capturedProjectId,
        p.id,
        capturedMode === 'approve',
        data.reason || '',
      )
      if (!isModalContextValid()) return
      notice.value = capturedMode === 'approve' ? '规则修改已通过。' : '已拒绝这条规则修改。'
      modalEpoch++
      dialogRef.value?.close()
      await refresh()
    }
  } catch (cause) {
    if (isModalContextValid()) {
      fail(cause)
    }
  } finally {
    finishAction(token, capturedProjectEpoch)
  }
}

function handleGlobalKeydown(event: KeyboardEvent) {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    paletteRef.value?.open()
  }
}

function handleHashChange() {
  const { projId, tabId } = parseLocationFromUrl()
  if (tabId && tabId !== tab.value) {
    tab.value = tabId
  }
  if (projId && projId !== projectId.value && projects.value.some(p => p.id === projId)) {
    void handleSelectProject(projId)
  }
  // 无效或缺失的页面地址直接改回当前页面，避免 URL 与界面不一致
  if (!tabId) {
    syncUrl()
  }
}

onMounted(() => {
  void connect()
  document.addEventListener('keydown', handleGlobalKeydown)
  window.addEventListener('hashchange', handleHashChange)
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleGlobalKeydown)
  window.removeEventListener('hashchange', handleHashChange)
})
</script>

<template>
  <div class="workbench">
    <a class="skip-link" href="#content" @click.prevent="focusContent">跳至工作台内容</a>

    <!-- 侧边栏组件 -->
    <Sidebar
      :projects="projects"
      :current-project-id="projectId"
      :tabs="tabs"
      :current-tab="tab"
      :connection-status="connectionStatus"
      :error-text="error"
      @select-project="handleSelectProject"
      @open-create-project="openCreateProject"
      @delete-current-project="handleDeleteProject"
      @select-tab="handleSelectTab"
      @open-palette="paletteRef?.open()"
    />

    <!-- 主展示区 -->
    <main>
      <!-- 页面标题、核心指标与刷新合并为单行胶囊条，不再单独占用顶部标题区 -->
      <MetricBar
        :ledger="ledger"
        :title="current.title"
        :current-tab="tab"
        :refreshing="loading || busy"
        :active-requirements-count="activeRequirementsCount"
        :active-tasks-count="activeTasksCount"
        :contracts-count="contractsCount"
        :pending-proposals-count="pendingProposalsCount"
        @navigate="handleSelectTab"
        @refresh="connect"
      />

      <!-- 全局通知与错误浮条 -->
      <div v-if="error" id="notice" class="error" role="alert">{{ error }}</div>
      <div v-else-if="notice" id="notice" role="status">{{ notice }}</div>

      <!-- 主视图容器 -->
      <section id="content" aria-label="工作区内容" tabindex="-1">
        <div v-if="!projectId" class="empty">
          当前还没有登记项目。点击左侧「＋ 注册」开始。
        </div>

        <template v-else-if="ledger">
          <!-- 0. 数据全貌看板 (Overview) -->
          <OverviewView
            v-if="tab === 'overview'"
            :ledger="ledger"
            :active-requirements-count="activeRequirementsCount"
            :active-tasks-count="activeTasksCount"
            :contracts-count="contractsCount"
            :pending-proposals-count="pendingProposalsCount"
            @navigate="handleSelectTab"
          />

          <!-- 1. 规则作用域 (Explorer) -->
          <ExplorerView v-else-if="tab === 'explorer'" :ledger="ledger" :project-id="projectId" />

          <!-- 2. 需求与任务看板 (Tasks) -->
          <TasksView
            v-else-if="tab === 'tasks'"
            :key="projectId"
            :project-id="projectId"
            :ledger="ledger"
            @refresh="refresh"
          />

          <!-- 3. 项目规则库 (Rules) -->
          <RulesView v-else-if="tab === 'rules'" :key="projectId" :ledger="ledger" :project-id="projectId" @refresh="refresh" />

          <!-- 4. 规范变更审阅 (Review) -->
          <ReviewView
            v-else-if="tab === 'review'"
            :ledger="ledger"
            :busy="busy"
            @open-approve="openApprove"
            @open-reject="openReject"
          />

          <!-- 5. 规则反馈与工作区 (Feedback) -->
          <FeedbackView v-else-if="tab === 'feedback'" :key="projectId" :ledger="ledger" :project-id="projectId" @refresh="refresh" />

          <!-- 6. 变更审计流水 (Activity) -->
          <ActivityView v-else-if="tab === 'activity'" :ledger="ledger" :project-id="projectId" />

          <!-- 7. 项目设置与管理 (Settings) -->
          <ProjectSettingsView
            v-else-if="tab === 'settings'"
            :projects="projects"
            :current-project-id="projectId"
            :ledger="ledger"
            :busy="busy"
            @select-project="handleSelectProject"
            @open-create-project="openCreateProject"
            @delete-project="handleDeleteProject"
            @refresh="refresh"
          />
        </template>
      </section>
    </main>

    <!-- 原生毛玻璃模态弹窗组件 -->
    <ActionDialog
      ref="dialogRef"
      :title="modalTitle"
      :busy="busy"
      :error-text="error"
      :is-project-modal="modalMode === 'project'"
      @submit="handleDialogSubmit"
      @close="handleDialogClose"
    />

    <!-- 全局命令面板组件 (Ctrl+K) -->
    <CommandPalette
      ref="paletteRef"
      :tabs="tabs"
      @select-tab="handleSelectTab"
    />
  </div>
</template>
