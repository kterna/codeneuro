<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Ledger, Requirement, Task, TaskStatus } from '../../types/ledger'

const props = defineProps<{
  ledger: Ledger
  busy: boolean
}>()

const emit = defineEmits<{
  (e: 'submit-demand', payload: { text: string; taskId?: string }): void
  (e: 'open-archive', req: Requirement): void
  (e: 'open-pause', task: Task): void
  (e: 'open-resume', task: Task): void
}>()

const demand = ref('')
const selectedTaskId = ref('')
const viewMode = ref<'swimlane' | 'list'>('swimlane')
const searchKeyword = ref('')
const onlyActive = ref(false)

const activeLanes: { key: TaskStatus; label: string; dotCls: string }[] = [
  { key: 'draft', label: '待开始 (Draft)', dotCls: 'draft' },
  { key: 'active', label: '进行中 (Active)', dotCls: 'active' },
  { key: 'paused', label: '已暂停 (Paused)', dotCls: 'paused' },
  { key: 'testing', label: '测试验证 (Testing)', dotCls: 'testing' },
]

function escaped(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

const matchedTasks = computed(() => {
  const text = demand.value.trim()
  if (!text) return []
  return props.ledger.tasks.filter(
    task => ['active', 'testing'].includes(task.status) && new RegExp(escaped(task.title), 'i').test(text),
  )
})

function handleSubmit() {
  const text = demand.value.trim()
  if (!text) return
  const chosen = selectedTaskId.value || (matchedTasks.value.length === 1 ? matchedTasks.value[0].id : undefined)
  emit('submit-demand', { text, taskId: chosen })
  demand.value = ''
  selectedTaskId.value = ''
}

const filteredTasks = computed(() => {
  return props.ledger.tasks.filter(t => {
    if (onlyActive.value && !['active', 'testing', 'paused'].includes(t.status)) return false
    if (searchKeyword.value.trim()) {
      const q = searchKeyword.value.toLowerCase()
      if (!t.title.toLowerCase().includes(q) && !(t.description || '').toLowerCase().includes(q)) return false
    }
    return true
  })
})

function getTaskRequirements(taskId: string): Requirement[] {
  return props.ledger.requirements.filter(r => r.task_id === taskId)
}

function getTaskProgress(taskId: string) {
  const reqs = getTaskRequirements(taskId)
  if (!reqs.length) return { total: 0, done: 0, percent: 0 }
  const done = reqs.filter(r => r.status === 'archived').length
  return { total: reqs.length, done, percent: Math.round((done / reqs.length) * 100) }
}
</script>

<template>
  <div class="tasks-workbench">
    <!-- 1. 原文需求输入卡片 -->
    <section class="intake-panel">
      <div class="intake-title">
        <h2>录入业务需求</h2>
        <span class="caption">输入业务需求原文，自动关联任务并作为执行约束下发给 Agent</span>
      </div>

      <div class="intake-form">
        <textarea
          id="demand-text"
          v-model="demand"
          rows="3"
          placeholder="请输入业务需求原文，例如：在结算服务中增加对超期图纸的自动退回与提醒逻辑…"
          @input="selectedTaskId = ''"
        ></textarea>

        <!-- 候选任务匹配提示 -->
        <div v-if="matchedTasks.length > 1" class="match-box">
          <p class="muted"><strong>检测到多个候选任务，请明确选择归属：</strong></p>
          <div class="choices-row">
            <label v-for="t in matchedTasks" :key="t.id" class="choice-label">
              <input v-model="selectedTaskId" type="radio" :value="t.id" />
              <span>{{ t.title }}</span>
            </label>
          </div>
        </div>
        <div v-else-if="matchedTasks.length === 1" class="match-hint">
          ✓ 将自动归入已有任务：<strong>{{ matchedTasks[0].title }}</strong>
        </div>

        <div class="intake-footer">
          <button
            class="primary"
            :disabled="busy || !demand.trim() || (matchedTasks.length > 1 && !selectedTaskId)"
            @click="handleSubmit"
          >
            {{ busy ? '正在提交…' : '提交原文需求' }}
          </button>
        </div>
      </div>
    </section>

    <!-- 2. 看板控制栏 -->
    <div class="board-header">
      <div class="board-header-left">
        <h2>任务看板与需求流转</h2>
        <span class="muted">共 {{ ledger.tasks.length }} 个任务 · {{ ledger.requirements.length }} 条需求</span>
      </div>

      <div class="board-header-right">
        <input
          v-model="searchKeyword"
          placeholder="搜索任务标题或描述…"
          style="width: 200px"
        />
        <label class="filter-check">
          <input v-model="onlyActive" type="checkbox" /> 仅看进行中
        </label>
        <div class="view-toggle">
          <button
            type="button"
            :class="{ active: viewMode === 'swimlane' }"
            @click="viewMode = 'swimlane'"
          >
            泳道看板
          </button>
          <button
            type="button"
            :class="{ active: viewMode === 'list' }"
            @click="viewMode = 'list'"
          >
            清单列表
          </button>
        </div>
      </div>
    </div>

    <!-- 3. 高质感现代化泳道看板视图 -->
    <div v-if="viewMode === 'swimlane'" class="kanban-wrapper">
      <div class="kanban-grid">
        <!-- 4 根活跃流转泳道 -->
        <div
          v-for="lane in activeLanes"
          :key="lane.key"
          class="kanban-col"
        >
          <div class="col-head">
            <div class="col-title">
              <span class="status-dot" :class="lane.dotCls"></span>
              <h3>{{ lane.label }}</h3>
            </div>
            <span class="badge-count">{{ filteredTasks.filter(t => t.status === lane.key).length }}</span>
          </div>

          <div class="col-scroll">
            <div
              v-if="!filteredTasks.filter(t => t.status === lane.key).length"
              class="col-empty"
            >
              暂无任务
            </div>

            <article
              v-for="task in filteredTasks.filter(t => t.status === lane.key)"
              :key="task.id"
              class="task-card"
              :class="{ 'card-active': task.status === 'active' }"
            >
              <div class="task-card-top">
                <span class="task-id">#{{ task.id.replace('task_', '').slice(0, 10) }}</span>
                <span class="tag" :class="task.status">{{ task.status }}</span>
              </div>

              <h4 class="task-title">{{ task.title }}</h4>

              <p v-if="task.description" class="task-desc">
                {{ task.description }}
              </p>

              <!-- 进度条 -->
              <div v-if="getTaskRequirements(task.id).length" class="card-progress">
                <div class="progress-info">
                  <span>需求达成</span>
                  <strong>{{ getTaskProgress(task.id).done }} / {{ getTaskProgress(task.id).total }}</strong>
                </div>
                <div class="progress-track">
                  <div class="progress-bar" :style="{ width: getTaskProgress(task.id).percent + '%' }"></div>
                </div>
              </div>

              <!-- 关联的具体需求条目 -->
              <div v-if="getTaskRequirements(task.id).length" class="task-reqs-box">
                <div
                  v-for="req in getTaskRequirements(task.id)"
                  :key="req.id"
                  class="req-pill"
                >
                  <div class="req-pill-header">
                    <span class="tag" :class="req.status">{{ req.status === 'active' ? '进行中 (active)' : '已归档 (archived)' }} · v{{ req.version }}</span>
                    <button
                      v-if="req.status === 'active' && ['active', 'testing'].includes(task.status)"
                      class="subtle archive-btn"
                      :disabled="busy"
                      @click="emit('open-archive', req)"
                    >
                      确认归档
                    </button>
                  </div>
                  <p class="original-text">{{ req.text }}</p>
                  <p v-if="req.summary" class="muted req-summary">完成摘要：{{ req.summary }}</p>
                </div>
              </div>

              <!-- 卡片底部动作 -->
              <div class="task-card-footer">
                <span class="muted" style="font-size: 10px">修订版本 #{{ task.revision }}</span>
                <div class="actions-group">
                  <button
                    v-if="['active', 'testing'].includes(task.status)"
                    class="subtle action-btn"
                    :disabled="busy"
                    @click="emit('open-pause', task)"
                  >
                    暂停
                  </button>
                  <button
                    v-if="task.status === 'paused'"
                    class="subtle action-btn"
                    :disabled="busy"
                    @click="emit('open-resume', task)"
                  >
                    恢复
                  </button>
                </div>
              </div>
            </article>
          </div>
        </div>

        <!-- 完结历史泳道 (合并发布与归档) -->
        <div class="kanban-col col-closed">
          <div class="col-head">
            <div class="col-title">
              <span class="status-dot dot-closed"></span>
              <h3>已完结历史 (Closed)</h3>
            </div>
            <span class="badge-count">
              {{ filteredTasks.filter(t => ['released', 'archived'].includes(t.status)).length }}
            </span>
          </div>

          <div class="col-scroll">
            <div
              v-if="!filteredTasks.filter(t => ['released', 'archived'].includes(t.status)).length"
              class="col-empty"
            >
              暂无已完结任务
            </div>

            <article
              v-for="task in filteredTasks.filter(t => ['released', 'archived'].includes(t.status))"
              :key="task.id"
              class="task-card card-closed"
            >
              <div class="task-card-top">
                <span class="task-id">#{{ task.id.replace('task_', '').slice(0, 10) }}</span>
                <span class="tag online">{{ task.status === 'released' ? '已上线' : '已归档' }}</span>
              </div>
              <h4 class="task-title">{{ task.title }}</h4>
              <p v-if="task.description" class="task-desc muted">{{ task.description }}</p>

              <div v-if="getTaskRequirements(task.id).length" class="task-reqs-box" style="margin-top: 6px">
                <div
                  v-for="req in getTaskRequirements(task.id)"
                  :key="req.id"
                  class="req-pill"
                  style="border-left-color: var(--green)"
                >
                  <div class="req-pill-header" style="margin-bottom: 2px">
                    <span class="tag" :class="req.status">{{ req.status === 'active' ? '进行中' : '已归档 (archived)' }} · v{{ req.version }}</span>
                  </div>
                  <p class="original-text" style="font-size: 11px">{{ req.text }}</p>
                  <p v-if="req.summary" class="muted req-summary">完成摘要：{{ req.summary }}</p>
                </div>
              </div>
            </article>
          </div>
        </div>
      </div>
    </div>

    <!-- 4. 清单列表模式 -->
    <div v-else class="table-wrap">
      <table class="rules-table">
        <thead>
          <tr>
            <th style="width: 90px">状态</th>
            <th>任务标题 / 业务描述</th>
            <th style="width: 140px">需求达成度</th>
            <th style="width: 100px; text-align: right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="task in filteredTasks" :key="task.id">
            <td>
              <span class="tag" :class="task.status">{{ task.status }}</span>
            </td>
            <td>
              <strong>{{ task.title }}</strong>
              <p class="muted" style="margin: 3px 0 0; font-size: 12px">{{ task.description }}</p>
              <div v-if="getTaskRequirements(task.id).length" style="margin-top: 8px">
                <div v-for="r in getTaskRequirements(task.id)" :key="r.id" class="original-text" style="font-size: 11px; margin: 4px 0">
                  {{ r.text }} <span v-if="r.summary" class="muted">({{ r.summary }})</span>
                </div>
              </div>
            </td>
            <td>
              <span style="font-size: 11px; font-variant-numeric: tabular-nums">
                {{ getTaskProgress(task.id).done }} / {{ getTaskProgress(task.id).total }}
              </span>
              <div class="progress-track" style="margin-top: 4px; height: 3px">
                <div class="progress-bar" :style="{ width: getTaskProgress(task.id).percent + '%' }"></div>
              </div>
            </td>
            <td style="text-align: right">
              <button
                v-if="['active', 'testing'].includes(task.status)"
                class="subtle action-btn"
                :disabled="busy"
                @click="emit('open-pause', task)"
              >
                暂停
              </button>
              <button
                v-if="task.status === 'paused'"
                class="subtle action-btn"
                :disabled="busy"
                @click="emit('open-resume', task)"
              >
                恢复
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.tasks-workbench {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

/* 需求录入面板 */
.intake-panel {
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 20px 24px;
}
.intake-title h2 {
  font-size: 15px;
  margin: 0;
}
.intake-form {
  margin-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.intake-footer {
  display: flex;
  justify-content: flex-end;
}
.match-box {
  background: var(--bg-subtle);
  padding: 10px 14px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle);
}
.choices-row {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 6px;
}
.choice-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  cursor: pointer;
}
.match-hint {
  color: var(--green);
  font-size: 12px;
}

/* 控制栏 */
.board-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 2px;
}
.board-header-left h2 {
  font-size: 16px;
  margin: 0;
}
.board-header-left .muted {
  font-size: 11px;
}
.board-header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.filter-check {
  font-size: 12px;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}
.view-toggle {
  display: flex;
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  overflow: hidden;
}
.view-toggle button {
  background: transparent;
  border: 0;
  border-radius: 0;
  padding: 6px 12px;
  font-size: 12px;
  color: var(--text-secondary);
}
.view-toggle button.active {
  background: var(--bg-surface);
  color: var(--text-primary);
  font-weight: 600;
}

/* 看板网格布局 */
.kanban-wrapper {
  overflow-x: auto;
  padding-bottom: 16px;
}
.kanban-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(290px, 1fr)) minmax(320px, 1.2fr);
  gap: 16px;
  min-width: 1480px;
}

/* 单根泳道 */
.kanban-col {
  background: var(--bg-subtle);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  max-height: 780px;
}
.col-closed {
  background: rgba(10, 12, 18, 0.7);
  border-style: dashed;
}
.col-head {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-subtle);
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: rgba(255, 255, 255, 0.02);
  border-radius: 8px 8px 0 0;
}
.col-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.col-title h3 {
  font-size: 12px;
  font-weight: 600;
  margin: 0;
  letter-spacing: 0.02em;
}
.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--text-tertiary);
}
.status-dot.active { background: var(--green); box-shadow: 0 0 6px rgba(16, 185, 129, 0.5); }
.status-dot.paused { background: var(--amber); }
.status-dot.testing { background: var(--blue); }
.status-dot.dot-closed { background: var(--text-tertiary); }

.badge-count {
  font-size: 11px;
  font-family: var(--font-mono);
  background: var(--bg-surface);
  padding: 2px 7px;
  border-radius: 10px;
  color: var(--text-secondary);
}

.col-scroll {
  padding: 12px;
  overflow-y: auto;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.col-empty {
  padding: 36px 12px;
  text-align: center;
  color: var(--text-tertiary);
  font-size: 12px;
}

/* 任务卡片 */
.task-card {
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
  transition: all 0.15s ease;
}
.task-card:hover {
  border-color: var(--border-hover);
  transform: translateY(-1px);
}
.card-active {
  border-left: 3px solid var(--green);
}
.card-closed {
  opacity: 0.85;
}
.task-card-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.task-id {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-tertiary);
}
.task-title {
  font-size: 13px;
  font-weight: 600;
  margin: 0;
  line-height: 1.45;
  color: var(--text-primary);
}
.task-desc {
  font-size: 11px;
  line-height: 1.5;
  color: var(--text-secondary);
  margin: 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* 进度条 */
.card-progress {
  background: rgba(0, 0, 0, 0.2);
  padding: 6px 10px;
  border-radius: 4px;
}
.progress-info {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  color: var(--text-tertiary);
  margin-bottom: 4px;
}
.progress-track {
  height: 4px;
  background: rgba(255, 255, 255, 0.08);
  border-radius: 2px;
  overflow: hidden;
}
.progress-bar {
  height: 100%;
  background: var(--green);
  border-radius: 2px;
}

/* 需求条目列表 */
.task-reqs-box {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.req-pill {
  background: rgba(0, 0, 0, 0.25);
  border-left: 2px solid var(--accent);
  padding: 8px 10px;
  border-radius: 4px;
}
.req-pill-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}
.archive-btn {
  padding: 2px 6px;
  font-size: 10px;
  color: var(--green);
}
.req-summary {
  font-size: 10px;
  margin: 4px 0 0;
}

/* 底部操作 */
.task-card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 8px;
  border-top: 1px solid var(--border-subtle);
}
.actions-group {
  display: flex;
  gap: 6px;
}
.action-btn {
  padding: 3px 8px;
  font-size: 10px;
}

/* 表格包装 */
.table-wrap {
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  overflow: hidden;
}
.rules-table {
  width: 100%;
  border-collapse: collapse;
}
.rules-table th, .rules-table td {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-subtle);
  font-size: 12px;
}
.rules-table th {
  background: var(--bg-subtle);
  font-weight: 600;
  color: var(--text-tertiary);
  text-transform: uppercase;
  font-size: 11px;
  letter-spacing: 0.03em;
}
</style>
