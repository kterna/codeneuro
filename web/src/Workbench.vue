<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import type { Ledger, Project, Proposal, Requirement, TabId, TabItem, Task } from './types/ledger'
import { apiService } from './api/client'

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

const tabs: readonly TabItem[] = [
  { id: 'explorer', icon: '⌘', title: '规则作用域', subtitle: '按路径模式检索代码模块适用的工程规范与核心约束。' },
  { id: 'tasks', icon: '▥', title: '需求与任务看板', subtitle: '录入业务需求原文，通过横向看板推进任务流转与归档。' },
  { id: 'rules', icon: '≋', title: '项目规则库', subtitle: '长期契约与任务短期规则统一管理，支持多维分类检索。' },
  { id: 'review', icon: '◈', title: '规范变更审阅', subtitle: '人工审阅 Agent 提交的长期契约修改提案，按目标版本执行核准。' },
  { id: 'feedback', icon: '◎', title: '规则反馈与工作区', subtitle: '统计 Agent 对规则的真实效用评分，监控已连接的工作区实例。' },
  { id: 'activity', icon: '↗', title: '变更审计流水', subtitle: '全链路记录需求归档、规则演进与状态转换的持久化审计日志。' },
  { id: 'settings', icon: '⚙', title: '项目设置与管理', subtitle: '集中查看项目元数据、在不同工程之间无缝切换，或执行安全级的数据清除。' },
]

const tab = ref<TabId>('explorer')
const current = computed(() => tabs.find(item => item.id === tab.value) || tabs[0])

const projects = ref<Project[]>([])
const projectId = ref('')
const ledger = ref<Ledger | null>(null)
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const notice = ref('')

// 组件 Ref
const paletteRef = ref<InstanceType<typeof CommandPalette> | null>(null)
const dialogRef = ref<InstanceType<typeof ActionDialog> | null>(null)

// 模态弹窗状态
const modalMode = ref<'project' | 'pause' | 'resume' | 'archive' | 'approve' | 'reject'>('project')
const modalTitle = computed(() => {
  switch (modalMode.value) {
    case 'project': return '注册新项目'
    case 'archive': return '确认业务需求完成归档'
    case 'approve': return '批准长期契约变更'
    case 'reject': return '拒绝契约变更提案'
    case 'pause': return '暂停任务流转'
    case 'resume': return '恢复任务流转'
  }
})
const modalTarget = ref<Task | Requirement | Proposal | null>(null)

function fail(cause: unknown) {
  error.value = (cause as Error).message || String(cause)
}

async function connect() {
  error.value = ''
  loading.value = true
  try {
    projects.value = await apiService.getProjects()
    if (!projects.value.some(p => p.id === projectId.value)) {
      projectId.value = projects.value[0]?.id || ''
    }
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
  error.value = ''
  try {
    ledger.value = await apiService.getLedger(projectId.value)
  } catch (cause) {
    fail(cause)
  }
}

async function handleSelectProject(id: string) {
  projectId.value = id
  await refresh()
}

async function handleDeleteProject(targetId?: string) {
  const idToDelete = targetId || projectId.value
  if (!idToDelete) return
  const targetProject = projects.value.find(p => p.id === idToDelete)
  const currentProjectName = targetProject?.name || idToDelete
  busy.value = true
  error.value = ''
  try {
    await apiService.deleteProject(idToDelete)
    notice.value = `项目【${currentProjectName}】已安全永久删除。`
    if (projectId.value === idToDelete) {
      projectId.value = ''
    }
    await connect()
  } catch (cause) {
    fail(cause)
  } finally {
    busy.value = false
  }
}

// 统计衍生属性
const activeRequirementsCount = computed(
  () => ledger.value?.requirements.filter(r => r.status === 'active').length ?? 0,
)
const activeTasksCount = computed(
  () => ledger.value?.tasks.filter(t => ['active', 'testing'].includes(t.status)).length ?? 0,
)
const contractsCount = computed(
  () => ledger.value?.rules.filter(r => r.task_id === null && r.status === 'active').length ?? 0,
)
const pendingProposalsCount = computed(
  () => ledger.value?.proposals.filter(p => p.status === 'pending').length ?? 0,
)

// 需求录入提交
async function handleSubmitDemand(payload: { text: string; taskId?: string }) {
  if (!projectId.value || !payload.text.trim()) return
  busy.value = true
  error.value = ''
  try {
    await apiService.submitRequirement(projectId.value, {
      text: payload.text,
      request_id: crypto.randomUUID(),
      ...(payload.taskId ? { task_id: payload.taskId } : { title: payload.text.trim().split(/[。.!?\n]/)[0].slice(0, 80) }),
    })
    notice.value = '业务需求已保存，将作为独立执行约束下发给 Agent。'
    await refresh()
  } catch (cause) {
    fail(cause)
  } finally {
    busy.value = false
  }
}

// 打开弹窗系列
function openCreateProject() {
  modalMode.value = 'project'
  modalTarget.value = null
  dialogRef.value?.open()
}

function openArchive(req: Requirement) {
  modalMode.value = 'archive'
  modalTarget.value = req
  dialogRef.value?.open()
}

function openPause(task: Task) {
  modalMode.value = 'pause'
  modalTarget.value = task
  dialogRef.value?.open()
}

function openResume(task: Task) {
  modalMode.value = 'resume'
  modalTarget.value = task
  dialogRef.value?.open()
}

function openApprove(prop: Proposal) {
  modalMode.value = 'approve'
  modalTarget.value = prop
  dialogRef.value?.open()
}

function openReject(prop: Proposal) {
  modalMode.value = 'reject'
  modalTarget.value = prop
  dialogRef.value?.open()
}

// 弹窗提交处理
async function handleDialogSubmit(data: { projectId?: string; projectName?: string; reason?: string }) {
  busy.value = true
  error.value = ''
  try {
    if (modalMode.value === 'project') {
      const created = await apiService.createProject(data.projectId || '', data.projectName || '')
      await connect()
      projectId.value = created.id
      await refresh()
    } else if (modalMode.value === 'archive') {
      const req = modalTarget.value as Requirement
      await apiService.archiveRequirement(
        projectId.value,
        req.task_id,
        req.id,
        req.version,
        data.reason || '',
      )
      await refresh()
    } else if (modalMode.value === 'pause') {
      const t = modalTarget.value as Task
      await apiService.pauseTask(projectId.value, t.id, t.revision, data.reason || '')
      await refresh()
    } else if (modalMode.value === 'resume') {
      const t = modalTarget.value as Task
      await apiService.resumeTask(projectId.value, t.id, t.revision, data.reason || '')
      await refresh()
    } else if (modalMode.value === 'approve' || modalMode.value === 'reject') {
      const p = modalTarget.value as Proposal
      await apiService.reviewProposal(
        projectId.value,
        p.id,
        modalMode.value === 'approve',
        data.reason || '',
      )
      await refresh()
    }
    notice.value = '操作已成功保存。'
    dialogRef.value?.close()
  } catch (cause) {
    fail(cause)
  } finally {
    busy.value = false
  }
}

function handleGlobalKeydown(event: KeyboardEvent) {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    paletteRef.value?.open()
  }
}

onMounted(() => {
  void connect()
  document.addEventListener('keydown', handleGlobalKeydown)
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleGlobalKeydown)
})
</script>

<template>
  <div class="workbench">
    <a class="skip-link" href="#content">跳至工作台内容</a>

    <!-- 侧边栏组件 -->
    <Sidebar
      :projects="projects"
      :current-project-id="projectId"
      :tabs="tabs"
      :current-tab="tab"
      :error-text="error"
      @select-project="handleSelectProject"
      @open-create-project="openCreateProject"
      @delete-current-project="handleDeleteProject"
      @select-tab="tab = $event"
      @open-palette="paletteRef?.open()"
    />

    <!-- 主展示区 -->
    <main>
      <header>
        <div>
          <div id="breadcrumb" class="caption">
            {{ projects.find(item => item.id === projectId)?.name || '项目' }} / 工程工作台
          </div>
          <h1 id="title">{{ current.title }}</h1>
          <p id="subtitle">{{ current.subtitle }}</p>
        </div>
        <div class="header-actions">
          <button id="refresh" aria-label="刷新当前视图" :disabled="loading || busy" @click="connect">
            {{ loading ? '刷新中…' : '刷新' }}
          </button>
        </div>
      </header>

      <!-- 顶栏指标卡组件 -->
      <MetricBar
        :ledger="ledger"
        :active-requirements-count="activeRequirementsCount"
        :active-tasks-count="activeTasksCount"
        :contracts-count="contractsCount"
        :pending-proposals-count="pendingProposalsCount"
      />

      <!-- 全局通知与错误浮条 -->
      <div v-if="error" id="notice" class="error" role="alert">{{ error }}</div>
      <div v-else-if="notice" id="notice" role="status">{{ notice }}</div>

      <!-- 主视图容器 -->
      <section id="content" aria-label="工作区内容" tabindex="-1">
        <div v-if="!projectId" class="empty">
          当前尚未登记工程项目。点击左侧「＋ 注册项目」即可开始，无需配置复杂的 Token。
        </div>

        <template v-else-if="ledger">
          <!-- 1. 规则作用域 (Explorer) -->
          <ExplorerView v-if="tab === 'explorer'" :ledger="ledger" :project-id="projectId" />

          <!-- 2. 需求与任务看板 (Tasks) -->
          <TasksView
            v-else-if="tab === 'tasks'"
            :ledger="ledger"
            :busy="busy"
            @submit-demand="handleSubmitDemand"
            @open-archive="openArchive"
            @open-pause="openPause"
            @open-resume="openResume"
          />

          <!-- 3. 项目规则库 (Rules) -->
          <RulesView v-else-if="tab === 'rules'" :ledger="ledger" />

          <!-- 4. 规范变更审阅 (Review) -->
          <ReviewView
            v-else-if="tab === 'review'"
            :ledger="ledger"
            :busy="busy"
            @open-approve="openApprove"
            @open-reject="openReject"
          />

          <!-- 5. 规则反馈与工作区 (Feedback) -->
          <FeedbackView v-else-if="tab === 'feedback'" :ledger="ledger" />

          <!-- 6. 变更审计流水 (Activity) -->
          <ActivityView v-else-if="tab === 'activity'" :ledger="ledger" />

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
    />

    <!-- 全局命令面板组件 (Ctrl+K) -->
    <CommandPalette
      ref="paletteRef"
      :tabs="tabs"
      @select-tab="tab = $event"
    />
  </div>
</template>
