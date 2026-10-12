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

const currentProject = computed(() => {
  return props.projects.find(p => p.id === props.currentProjectId) || null
})

const currentWorktree = computed(() => {
  return props.ledger?.worktrees?.[0] || null
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
      <span class="caption">查看项目元数据、在不同工程之间快速切换，或执行安全级别的数据管理</span>
    </div>

    <!-- 1. 当前项目基本概览 -->
    <section v-if="currentProject" class="settings-card">
      <div class="card-section-title">
        <h3>当前项目基础信息</h3>
        <span class="caption">已连接并激活中的工程上下文</span>
      </div>

      <div class="project-meta-grid">
        <div class="meta-field">
          <label>项目名称 (Display Name)</label>
          <div class="meta-value-text">{{ currentProject.name }}</div>
        </div>
        <div class="meta-field">
          <label>项目唯一标识 (Project ID)</label>
          <div class="meta-value-code"><code>{{ currentProject.id }}</code></div>
        </div>
        <div class="meta-field" style="grid-column: span 2">
          <label>绑定的本地代码工作区 (Workspace Path)</label>
          <div class="meta-value-code">
            <code>{{ currentWorktree?.workspace || '未关联本地磁盘路径 (通过 MCP 客户端上报)' }}</code>
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
          <h3>已登记的所有工程项目 ({{ projects.length }})</h3>
          <span class="caption">支持在多个项目知识库之间随时无缝切换</span>
        </div>
        <button class="primary" type="button" @click="emit('open-create-project')">
          ＋ 注册新项目
        </button>
      </div>

      <div style="margin: 14px 0 10px">
        <input
          v-model="searchFilter"
          placeholder="按项目名称或 ID 快速搜索…"
          style="max-width: 360px"
        />
      </div>

      <div class="projects-table-wrap">
        <table class="projects-table">
          <thead>
            <tr>
              <th style="width: 160px">项目唯一 ID</th>
              <th>项目显示名称</th>
              <th style="width: 100px; text-align: center">当前状态</th>
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

    <!-- 3. 危险操作区 (Danger Zone) —— 工业级删除保护 -->
    <section v-if="currentProject" class="danger-zone-card">
      <div class="danger-header">
        <span class="danger-icon">⚠️</span>
        <div>
          <h3>危险操作区 (Danger Zone)</h3>
          <p class="danger-warning-text">
            删除项目属于不可撤销的破坏性操作。该项目下的全部任务看板、业务需求、规矩契约、开发避坑便签及审计日志都将被物理级联抹除。
          </p>
        </div>
      </div>

      <div class="danger-action-box">
        <div class="danger-instruction">
          若确认要彻底删除项目 <strong>{{ currentProject.name }}</strong>，请在下方文本框中完整键入该项目唯一 ID：
          <code class="confirm-target-id">{{ currentProject.id }}</code>
        </div>

        <div class="danger-form-row">
          <input
            v-model="confirmInputId"
            :placeholder="`输入完整项目 ID: ${currentProject.id}`"
            class="danger-confirm-input"
          />
          <button
            class="btn-danger-confirm"
            type="button"
            :disabled="!isDeleteButtonUnlocked || busy"
            @click="handleDelete"
          >
            {{ busy ? '正在清理…' : '我已确认，彻底删除此项目' }}
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
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  overflow: hidden;
  margin-top: 12px;
}

.projects-table {
  width: 100%;
  border-collapse: collapse;
}

.projects-table th, .projects-table td {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-subtle);
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
