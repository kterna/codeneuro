<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Ledger, Project } from '../../types/ledger'

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
    <div class="section-head">
      <h2>项目管理与全局设置</h2>
      <span class="caption">查看项目元数据、切换工程或管理数据</span>
    </div>

    <!-- 1. 当前项目基本概览 -->
    <section v-if="currentProject" class="settings-card">
      <div class="card-section-title">
        <h3>当前项目基础信息</h3>
        <span class="caption">已连接并激活中的工程上下文</span>
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
        <div class="meta-field" style="grid-column: span 2">
          <label>工作区声明 (共 {{ availableWorktrees.length }} 处)</label>
          <div style="margin-top: 6px">
            <select v-model="selectedWorktreeId" aria-label="选择工作区声明" style="width: 100%; max-width: 480px">
              <option value="">-- 请选择工作区声明 --</option>
              <option v-for="wt in availableWorktrees" :key="wt.id" :value="wt.id">
                [{{ wt.platform }}] {{ wt.machine_name }} · {{ wt.workspace }}
              </option>
            </select>
          </div>

          <div v-if="selectedWorktree" class="panel" style="margin-top: 10px; background: var(--gh-canvas-inset)">
            <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; font-size: 12px">
              <div><strong>机器节点：</strong>{{ selectedWorktree.machine_name }}</div>
              <div><strong>运行平台：</strong>{{ selectedWorktree.platform }}</div>
              <div><strong>Git 分支：</strong>{{ selectedWorktree.git_branch || '未声明' }}</div>
              <div><strong>声明上报者：</strong>{{ selectedWorktree.actor_id || '未声明' }}</div>
            </div>
            <div style="margin-top: 6px; font-size: 12px">
              <strong>客户端路径：</strong><code>{{ selectedWorktree.workspace }}</code>
            </div>
          </div>
          <div v-else class="caption" style="margin-top: 6px">
            请选择工作区声明查看详情。说明：工作区路径由客户端声明，服务端不扫描本机同名路径。
          </div>
        </div>
      </div>

      <div class="stats-overview-bar">
        <div class="stat-pill">
          <span>任务流转</span>
          <strong>{{ ledger?.tasks.length ?? 0 }} 个</strong>
        </div>
        <div class="stat-pill">
          <span>业务需求</span>
          <strong>{{ ledger?.requirements.length ?? 0 }} 条</strong>
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

    <!-- 2. 全部工程项目列表与快速切换 -->
    <section class="settings-card">
      <div class="card-section-title" style="display: flex; justify-content: space-between; align-items: center">
        <div>
          <h3>已登记工程项目 ({{ projects.length }})</h3>
          <span class="caption">支持在不同项目之间快速切换</span>
        </div>
        <button class="primary" type="button" @click="emit('open-create-project')">
          ＋ 注册新项目
        </button>
      </div>

      <div style="margin: 14px 0 10px">
        <input
          v-model="searchFilter"
          placeholder="按项目名称或标识快速搜索…"
          style="max-width: 360px"
        />
      </div>

      <div class="projects-table-wrap">
        <table class="projects-table">
          <thead>
            <tr>
              <th style="width: 160px">项目标识</th>
              <th>项目名称</th>
              <th style="width: 100px; text-align: center">状态</th>
              <th style="width: 120px; text-align: right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="p in filteredProjects"
              :key="p.id"
              :class="{ 'is-current-row': p.id === currentProjectId }"
            >
              <td>
                <code>{{ p.id }}</code>
              </td>
              <td>
                <strong>{{ p.name }}</strong>
              </td>
              <td style="text-align: center">
                <span v-if="p.id === currentProjectId" class="tag active">当前激活</span>
                <span v-else class="muted" style="font-size: 11px">待机</span>
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

    <!-- 3. 危险操作区 -->
    <section v-if="currentProject" class="danger-zone-card">
      <div class="danger-header">
        <span class="danger-icon">⚠️</span>
        <div>
          <h3>删除项目</h3>
          <p class="danger-warning-text">
            此操作不可撤销。删除后，该项目下的任务、需求、规则、便签及审计流水都将被一并删除。
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
            class="danger-confirm-input"
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
  gap: 24px;
}

.settings-card {
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 24px;
}

.card-section-title h3 {
  font-size: 14px;
  margin: 0;
}

.project-meta-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-top: 16px;
  padding: 16px;
  background: var(--bg-subtle);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
}

.meta-field label {
  display: block;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  color: var(--text-tertiary);
  margin-bottom: 4px;
}

.meta-value-text {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.meta-value-code code {
  font-size: 12px;
  color: #c4b5fd;
}

.stats-overview-bar {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-top: 16px;
}

.stat-pill {
  background: var(--bg-subtle);
  border: 1px solid var(--border-subtle);
  padding: 10px 14px;
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.stat-pill span {
  font-size: 10px;
  color: var(--text-tertiary);
  text-transform: uppercase;
}

.stat-pill strong {
  font-size: 16px;
  color: var(--text-primary);
}

/* 项目表格 */
.projects-table-wrap {
  border: 1px solid var(--gh-border-default);
  border-radius: 6px;
  max-height: 260px;
  overflow-y: auto;
  margin-top: 12px;
  background: var(--gh-canvas-subtle);
}

.projects-table {
  width: 100%;
  border-collapse: collapse;
}

.projects-table th {
  background: #161b22;
  position: sticky;
  top: 0;
  z-index: 5;
}

.projects-table th, .projects-table td {
  padding: 10px 14px;
  border-bottom: 1px solid var(--gh-border-muted);
  font-size: 12px;
}

.projects-table th {
  background: var(--bg-subtle);
  color: var(--text-tertiary);
  font-size: 11px;
  text-transform: uppercase;
  font-weight: 600;
}

.projects-table tr.is-current-row {
  background: rgba(139, 92, 246, 0.05);
}

.btn-switch {
  color: var(--accent);
  font-size: 11px;
  padding: 4px 8px;
}
.btn-switch:hover {
  background: var(--accent-subtle);
}

/* 危险操作区 (Danger Zone) */
.danger-zone-card {
  background: rgba(244, 63, 94, 0.03);
  border: 1px solid var(--red-border);
  border-radius: 8px;
  padding: 24px;
}

.danger-header {
  display: flex;
  align-items: flex-start;
  gap: 14px;
}

.danger-icon {
  font-size: 24px;
}

.danger-header h3 {
  font-size: 15px;
  color: #fda4af;
  margin: 0 0 4px;
}

.danger-warning-text {
  font-size: 12px;
  color: #fca5a5;
  line-height: 1.6;
  margin: 0;
}

.danger-action-box {
  margin-top: 18px;
  padding: 16px;
  background: var(--bg-subtle);
  border: 1px solid rgba(244, 63, 94, 0.2);
  border-radius: 6px;
}

.danger-instruction {
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 12px;
  line-height: 1.6;
}

.confirm-target-id {
  background: rgba(244, 63, 94, 0.15);
  border: 1px solid var(--red-border);
  color: #fda4af;
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 600;
}

.danger-form-row {
  display: flex;
  gap: 12px;
}

.danger-confirm-input {
  flex: 1;
  max-width: 380px;
  border-color: var(--border-subtle);
}

.btn-danger-confirm {
  background: var(--red);
  border: 1px solid #e11d48;
  color: #fff;
  font-weight: 600;
  padding: 8px 16px;
}

.btn-danger-confirm:disabled {
  opacity: 0.35;
  cursor: not-allowed;
  background: rgba(255, 255, 255, 0.1);
  border-color: transparent;
  color: var(--text-tertiary);
}

.btn-danger-confirm:not(:disabled):hover {
  background: #e11d48;
  box-shadow: 0 0 10px rgba(244, 63, 94, 0.4);
}
</style>
