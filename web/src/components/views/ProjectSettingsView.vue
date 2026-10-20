<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Ledger, Project } from '../../types/ledger'
import TopicsPanel from './TopicsPanel.vue'
import GhTag from '../ui/GhTag.vue'

const props = defineProps<{
  projects: Project[]
  currentProjectId: string
  ledger: Ledger | null
  busy: boolean
}>()

const emit = defineEmits<{
  (e: 'select-project', id: string): void
  (e: 'open-create-project'): void
  (e: 'delete-project', id: string): void
  (e: 'refresh'): void
}>()

const confirmInputId = ref('')
const searchFilter = ref('')
const selectedWorktreeId = ref('')

const currentProject = computed(() => {
  return props.projects.find(p => p.id === props.currentProjectId) || null
})

const availableWorktrees = computed(() => {
  return props.ledger?.worktrees || []
})

const selectedWorktree = computed(() => {
  if (!selectedWorktreeId.value) return null
  return availableWorktrees.value.find(w => w.id === selectedWorktreeId.value) || null
})

const filteredProjects = computed(() => {
  const q = searchFilter.value.trim().toLowerCase()
  if (!q) return props.projects
  return props.projects.filter(p => p.name.toLowerCase().includes(q) || p.id.toLowerCase().includes(q))
})

const isDeleteButtonUnlocked = computed(() => {
  return confirmInputId.value.trim() === props.currentProjectId && Boolean(props.currentProjectId)
})

function handleDelete() {
  if (!isDeleteButtonUnlocked.value) return
  emit('delete-project', props.currentProjectId)
  confirmInputId.value = ''
}
</script>

<template>
  <div class="settings-view">
    <!-- 1. 当前项目基本概览 -->
    <section v-if="currentProject" class="settings-section-card">
      <div class="card-section-header">
        <div class="header-title-wrap">
          <span class="header-icon" aria-hidden="true">🏛️</span>
          <div>
            <h3 class="card-title">当前项目基础信息</h3>
          </div>
        </div>
      </div>

      <div class="project-meta-grid">
        <div class="meta-field">
          <label>项目名称</label>
          <div class="meta-value-text">{{ currentProject.name }}</div>
        </div>
        <div class="meta-field">
          <label>项目标识</label>
          <div class="meta-value-code"><code>{{ currentProject.id }}</code></div>
        </div>

        <div class="meta-field full-row">
          <label>工作区记录（共 {{ availableWorktrees.length }} 处）</label>
          <div class="worktree-selector-row">
            <select v-model="selectedWorktreeId" aria-label="选择工作区" class="gh-select worktree-select">
              <option value="">-- 请选择工作区 --</option>
              <option v-for="wt in availableWorktrees" :key="wt.id" :value="wt.id">
                [{{ wt.platform }}] {{ wt.machine_name }} · {{ wt.workspace }}
              </option>
            </select>
          </div>

          <div v-if="selectedWorktree" class="worktree-detail-panel">
            <div class="worktree-meta-columns">
              <div><strong>机器：</strong>{{ selectedWorktree.machine_name }}</div>
              <div><strong>运行平台：</strong>{{ selectedWorktree.platform }}</div>
              <div><strong>Git 分支：</strong>{{ selectedWorktree.git_branch || '未声明' }}</div>
              <div><strong>上报人：</strong>{{ selectedWorktree.actor_id || '未上报' }}</div>
            </div>
            <div class="worktree-path-row">
              <strong>客户端路径：</strong><code>{{ selectedWorktree.workspace }}</code>
            </div>
          </div>
          <div v-else class="caption worktree-caption">
            工作区路径由 AI 客户端上报，服务端不扫描本机目录。
          </div>
        </div>
      </div>

      <!-- 核心指标摘要卡片 -->
      <div class="stats-overview-bar">
        <div class="stat-pill">
          <span>任务总数</span>
          <strong>{{ ledger?.counts.tasks.total ?? 0 }} 个</strong>
        </div>
        <div class="stat-pill">
          <span>业务需求</span>
          <strong>{{ ledger?.counts.requirements.total ?? 0 }} 条</strong>
        </div>
        <div class="stat-pill">
          <span>生效规则</span>
          <strong>{{ ledger?.rules.filter(r => r.status === 'active').length ?? 0 }} 条</strong>
        </div>
        <div class="stat-pill">
          <span>开发便签</span>
          <strong>{{ ledger?.findings?.length ?? 0 }} 条</strong>
        </div>
      </div>
    </section>

    <!-- 2. 业务主题管理面板 -->
    <TopicsPanel
      v-if="ledger && currentProjectId"
      :key="currentProjectId"
      :project-id="currentProjectId"
      :ledger="ledger"
      @refresh="emit('refresh')"
    />

    <!-- 3. 全部工程项目列表与快速切换 -->
    <section class="settings-section-card">
      <div class="card-section-header">
        <div class="header-title-wrap">
          <span class="header-icon" aria-hidden="true">🗂️</span>
          <div>
            <h3 class="card-title">已登记项目（{{ projects.length }}）</h3>
          </div>
        </div>
        <button class="primary btn-create-proj" type="button" @click="emit('open-create-project')">
          ＋ 注册新项目
        </button>
      </div>

      <div class="project-search-toolbar">
        <input
          v-model="searchFilter"
          placeholder="按项目名称或标识快速搜索…"
          class="gh-input project-search-input"
        />
      </div>

      <div class="projects-table-wrap">
        <table class="projects-table">
          <thead>
            <tr>
              <th style="width: 180px">项目标识</th>
              <th>项目名称</th>
              <th style="width: 110px; text-align: center">状态</th>
              <th style="width: 140px; text-align: right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="p in filteredProjects"
              :key="p.id"
              :class="{ 'is-current-row': p.id === currentProjectId }"
            >
              <td>
                <code class="proj-id-code">{{ p.id }}</code>
              </td>
              <td>
                <strong class="proj-name-text">{{ p.name }}</strong>
              </td>
              <td style="text-align: center">
                <GhTag v-if="p.id === currentProjectId" variant="success">当前激活</GhTag>
                <span v-else class="muted proj-standby-text">待机</span>
              </td>
              <td style="text-align: right">
                <button
                  v-if="p.id !== currentProjectId"
                  class="subtle btn-switch"
                  type="button"
                  :disabled="busy"
                  @click="emit('select-project', p.id)"
                >
                  切换至此项目 →
                </button>
                <span v-else class="muted" style="font-size: 11px">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- 4. 危险操作区 (Danger Zone) -->
    <section v-if="currentProject" class="danger-zone-card">
      <div class="danger-header">
        <span class="danger-icon" aria-hidden="true">⚠️</span>
        <div class="danger-title-wrap">
          <h3 class="danger-title">删除项目</h3>
          <p class="danger-warning-text">
            此操作不可撤销。删除后，该项目下的任务、需求、规则、便签及操作记录都会被一并删除。
          </p>
        </div>
      </div>

      <div class="danger-action-box">
        <div class="danger-instruction">
          删除项目「{{ currentProject.name }}」前，请输入项目标识：
          <code class="confirm-target-id">{{ currentProject.id }}</code>
        </div>

        <div class="danger-form-row">
          <input
            v-model="confirmInputId"
            :placeholder="`请输入项目标识 ${currentProject.id}`"
            class="gh-input danger-confirm-input font-mono"
          />
          <button
            class="btn-danger-confirm"
            type="button"
            :disabled="!isDeleteButtonUnlocked || busy"
            @click="handleDelete"
          >
            {{ busy ? '正在删除…' : '确认彻底删除此项目' }}
          </button>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.settings-view {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.head-title-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.settings-section-card {
  background: var(--gh-canvas-subtle);
  border: 1px solid var(--gh-border-default);
  border-radius: 8px;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.card-section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid var(--gh-border-muted);
  padding-bottom: 12px;
}

.header-title-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
}

.header-icon {
  font-size: 18px;
}

.card-title {
  font-size: 14px;
  font-weight: 600;
  margin: 0;
  color: var(--gh-fg-default);
}

/* 项目元信息栅格 */
.project-meta-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  padding: 14px;
  background: var(--gh-canvas-default);
  border: 1px solid var(--gh-border-default);
  border-radius: 6px;
}

.meta-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.meta-field.full-row {
  grid-column: 1 / -1;
}

.meta-field label {
  font-size: 11px;
  font-weight: 600;
  color: var(--gh-fg-muted);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.meta-value-text {
  font-size: 14px;
  font-weight: 600;
  color: var(--gh-fg-default);
}

.meta-value-code code {
  font-size: 12px;
  color: var(--gh-accent-fg);
  font-family: var(--font-mono);
  background: var(--gh-canvas-inset);
  padding: 2px 8px;
  border-radius: 4px;
  border: 1px solid var(--gh-border-muted);
}

/* 工作区展开面板 */
.worktree-selector-row {
  margin-top: 4px;
}

.worktree-select {
  width: 100%;
  max-width: 480px;
}

.worktree-detail-panel {
  margin-top: 8px;
  padding: 10px 12px;
  background: var(--gh-canvas-inset);
  border: 1px solid var(--gh-border-muted);
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 12px;
}

.worktree-meta-columns {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
}

.worktree-path-row {
  font-size: 12px;
  color: var(--gh-fg-default);
}

.worktree-path-row code {
  color: var(--gh-accent-fg);
  font-family: var(--font-mono);
}

.worktree-caption {
  margin-top: 6px;
  line-height: 1.4;
}

/* 核心统计卡片 */
.stats-overview-bar {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

@media (max-width: 768px) {
  .stats-overview-bar {
    grid-template-columns: repeat(2, 1fr);
  }
}

.stat-pill {
  background: var(--gh-canvas-default);
  border: 1px solid var(--gh-border-default);
  padding: 10px 14px;
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  transition: all 0.12s ease;
}

.stat-pill span {
  font-size: 11px;
  color: var(--gh-fg-muted);
  text-transform: uppercase;
}

.stat-pill strong {
  font-size: 16px;
  font-weight: 600;
  color: var(--gh-fg-default);
  font-family: var(--font-mono);
}

/* 项目表格 */
.project-search-toolbar {
  display: flex;
  align-items: center;
}

.project-search-input {
  max-width: 360px;
  width: 100%;
}

.projects-table-wrap {
  border: 1px solid var(--gh-border-default);
  border-radius: 6px;
  max-height: 280px;
  overflow-y: auto;
  background: var(--gh-canvas-default);
}

.projects-table {
  width: 100%;
  border-collapse: collapse;
}

.projects-table th {
  background: var(--gh-canvas-subtle);
  position: sticky;
  top: 0;
  z-index: 5;
  padding: 8px 12px;
  border-bottom: 1px solid var(--gh-border-default);
  font-size: 11px;
  text-transform: uppercase;
  font-weight: 600;
  color: var(--gh-fg-muted);
  text-align: left;
}

.projects-table td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--gh-border-muted);
  font-size: 12px;
  vertical-align: middle;
}

.projects-table tr.is-current-row {
  background: var(--gh-accent-subtle);
}

.proj-id-code {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--gh-accent-fg);
}

.proj-name-text {
  color: var(--gh-fg-default);
}

.proj-standby-text {
  font-size: 11px;
}

.btn-switch {
  font-size: 11px;
  padding: 4px 10px;
  color: var(--gh-accent-fg);
}

.btn-switch:hover {
  background: var(--gh-surface-card-hover);
}

/* 危险操作区 (Danger Zone) */
.danger-zone-card {
  background: var(--gh-canvas-subtle);
  border: 1px solid var(--gh-danger-fg);
  border-left: 4px solid var(--gh-danger-fg);
  border-radius: 8px;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.danger-header {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.danger-icon {
  font-size: 22px;
  line-height: 1;
}

.danger-title-wrap {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.danger-title {
  font-size: 14px;
  color: var(--gh-danger-fg);
  margin: 0;
  font-weight: 600;
}

.danger-warning-text {
  font-size: 12px;
  color: var(--gh-fg-muted);
  line-height: 1.5;
  margin: 0;
}

.danger-action-box {
  padding: 14px;
  background: var(--gh-canvas-default);
  border: 1px solid var(--gh-border-muted);
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.danger-instruction {
  font-size: 12px;
  color: var(--gh-fg-default);
  line-height: 1.5;
}

.confirm-target-id {
  background: var(--gh-danger-subtle);
  border: 1px solid rgba(248, 81, 73, 0.4);
  color: var(--gh-danger-fg);
  padding: 2px 6px;
  border-radius: 4px;
  font-family: var(--font-mono);
  font-weight: 600;
}

.danger-form-row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.danger-confirm-input {
  flex: 1;
  min-width: 240px;
  max-width: 380px;
}

.btn-danger-confirm {
  background: var(--gh-danger-emphasis);
  border: 1px solid rgba(248, 81, 73, 0.4);
  color: #fff;
  font-weight: 600;
  padding: 6px 16px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.12s ease;
}

.btn-danger-confirm:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.btn-danger-confirm:not(:disabled):hover {
  background: var(--scale-red-5);
  box-shadow: 0 0 8px rgba(248, 81, 73, 0.4);
}

.font-mono {
  font-family: var(--font-mono);
}
</style>
