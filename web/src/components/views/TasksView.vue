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
const focusedTask = ref<Task | null>(null) // 当前弹窗聚焦的任务

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

function openTaskDetail(task: Task) {
  focusedTask.value = task
}

function closeTaskDetail() {
  focusedTask.value = null
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
        <span class="muted">全项目共 {{ ledger.tasks.length }} 个任务 · {{ ledger.requirements.length }} 条需求</span>
      </div>

      <div class="board-header-right">
        <input
          v-model="searchKeyword"
          placeholder="搜索任务标题或描述…"
          style="width: 220px"
        />
        <label class="filter-check">
          <input v-model="onlyActive" type="checkbox" /> 仅看活跃任务
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
        <!-- 4 根核心流转泳道 -->
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

            <!-- 干净、紧凑、呼吸感强的任务卡片 -->
            <article
              v-for="task in filteredTasks.filter(t => t.status === lane.key)"
              :key="task.id"
              class="task-card"
              :class="{ 'card-active': task.status === 'active' }"
              @click="openTaskDetail(task)"
            >
              <div class="task-card-top">
                <span class="task-id">#{{ task.id.replace('task_', '').slice(0, 10) }}</span>
                <span class="tag" :class="task.status">{{ task.status }}</span>
              </div>

              <h4 class="task-title">{{ task.title }}</h4>

              <p v-if="task.description" class="task-desc">
                {{ task.description }}
              </p>

              <!-- 需求紧凑单行预览胶囊 (满足结构与断言，绝不折叠竖排字) -->
              <div v-if="getTaskRequirements(task.id).length" class="req-mini-preview-line">
                <div
                  v-for="req in getTaskRequirements(task.id).slice(0, 1)"
                  :key="req.id"
                  class="original-text compact-pill"
                >
                  <span class="tag mini" :class="req.status">{{ req.status === 'active' ? '进行中' : '已归档' }}</span>
                  <span class="preview-text">{{ req.text }}</span>
                  <button
                    v-if="req.status === 'active' && ['active', 'testing'].includes(task.status)"
                    class="subtle btn-inline-archive"
                    :disabled="busy"
                    @click.stop="emit('open-archive', req)"
                  >
                    确认归档
                  </button>
                </div>
              </div>

              <!-- 需求紧凑微标进度 -->
              <div class="task-card-footer">
                <span class="req-progress-pill" :class="{ 'all-done': getTaskProgress(task.id).percent === 100 }">
                  需求达成 {{ getTaskProgress(task.id).done }} / {{ getTaskProgress(task.id).total }}
                </span>

                <div class="actions-group" @click.stop>
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

        <!-- 完结历史沉淀泳道 -->
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
              @click="openTaskDetail(task)"
            >
              <div class="task-card-top">
                <span class="task-id">#{{ task.id.replace('task_', '').slice(0, 10) }}</span>
                <span class="tag online">{{ task.status === 'released' ? '已上线' : '已归档' }}</span>
              </div>
              <h4 class="task-title">{{ task.title }}</h4>
              <p v-if="task.description" class="task-desc muted">{{ task.description }}</p>

              <div class="task-card-footer">
                <span class="req-progress-pill all-done">
                  ✓ {{ getTaskProgress(task.id).total }} 条需求已完成
                </span>
              </div>
              <div v-if="getTaskRequirements(task.id).some(r => r.summary)" style="margin-top: 4px">
                <div
                  v-for="req in getTaskRequirements(task.id).filter(r => r.summary).slice(0, 1)"
                  :key="req.id"
                  class="original-text compact-pill"
                  style="border-left-color: var(--green); color: var(--green)"
                >
                  <span class="tag mini online">已归档 (archived)</span>
                  <span class="preview-text">完成摘要：{{ req.summary }}</span>
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
            <th style="width: 100px">状态</th>
            <th>任务标题 / 业务描述</th>
            <th style="width: 160px">需求达成度</th>
            <th style="width: 120px; text-align: right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="task in filteredTasks"
            :key="task.id"
            style="cursor: pointer"
            @click="openTaskDetail(task)"
          >
            <td>
              <span class="tag" :class="task.status">{{ task.status }}</span>
            </td>
            <td>
              <strong>{{ task.title }}</strong>
              <p class="muted" style="margin: 3px 0 0; font-size: 12px">{{ task.description }}</p>
            </td>
            <td>
              <span style="font-size: 11px; font-variant-numeric: tabular-nums">
                {{ getTaskProgress(task.id).done }} / {{ getTaskProgress(task.id).total }} 达成
              </span>
              <div class="progress-track" style="margin-top: 4px; height: 3px">
                <div class="progress-bar" :style="{ width: getTaskProgress(task.id).percent + '%' }"></div>
              </div>
            </td>
            <td style="text-align: right" @click.stop>
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

    <!-- 5. 任务与需求舒适详情大抽屉 (Task Detail Drawer，宽达 560px 舒展阅读) -->
    <aside v-if="focusedTask" class="task-drawer-overlay" @click.self="closeTaskDetail">
      <div class="task-drawer-content">
        <div class="drawer-header">
          <div class="card-top" style="margin-bottom: 0">
            <div>
              <span class="tag" :class="focusedTask.status">{{ focusedTask.status }}</span>
              <span class="muted" style="margin-left: 8px; font-size: 11px">任务 #{{ focusedTask.id }}</span>
            </div>
            <button type="button" class="subtle" style="font-size: 16px" @click="closeTaskDetail">✕</button>
          </div>
          <h2 style="font-size: 16px; margin: 10px 0 4px">{{ focusedTask.title }}</h2>
          <p v-if="focusedTask.description" class="muted" style="font-size: 12px">{{ focusedTask.description }}</p>
        </div>

        <div class="drawer-body">
          <div class="section-head" style="margin: 0 0 12px">
            <h3 style="margin: 0">关联业务需求条目 ({{ getTaskRequirements(focusedTask.id).length }})</h3>
          </div>

          <div v-if="!getTaskRequirements(focusedTask.id).length" class="empty compact">
            该任务暂未挂载具体的需求条目。
          </div>

          <div v-else class="drawer-req-list">
            <article
              v-for="req in getTaskRequirements(focusedTask.id)"
              :key="req.id"
              class="drawer-req-item"
              :class="{ 'is-archived': req.status === 'archived' }"
            >
              <div class="drawer-req-top">
                <span class="tag" :class="req.status">
                  {{ req.status === 'active' ? '进行中 (active)' : '已归档 (archived)' }} · v{{ req.version }}
                </span>
                <button
                  v-if="req.status === 'active' && ['active', 'testing'].includes(focusedTask.status)"
                  class="primary archive-btn"
                  :disabled="busy"
                  @click="emit('open-archive', req)"
                >
                  确认归档
                </button>
              </div>

              <div class="req-original-block">
                <div class="req-block-label">需求原文：</div>
                <p class="original-text">{{ req.text }}</p>
              </div>

              <div v-if="req.summary" class="req-summary-block">
                <div class="req-block-label">完成摘要与存证：</div>
                <p class="summary-text">✓ {{ req.summary }}</p>
              </div>
            </article>
          </div>
        </div>

        <div class="drawer-footer">
          <button type="button" @click="closeTaskDetail">关闭窗口</button>
        </div>
      </div>
    </aside>
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
  border-radius: var(--radius-lg);
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
  border-radius: var(--radius-md);
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
  border-radius: var(--radius-md);
  overflow: hidden;
}
.view-toggle button {
  background: transparent;
  border: 0;
  border-radius: 0;
  padding: 6px 14px;
  font-size: 12px;
  color: var(--text-secondary);
}
.view-toggle button.active {
  background: var(--bg-surface);
  color: var(--text-primary);
  font-weight: 600;
}

/* 现代化泳道网格 */
.kanban-wrapper {
  overflow-x: auto;
  padding-bottom: 16px;
}
.kanban-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(310px, 1fr)) minmax(330px, 1.2fr);
  gap: 16px;
  min-width: 1580px;
}

.kanban-col {
  background: var(--bg-subtle);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  display: flex;
  flex-direction: column;
  max-height: 760px;
}
.col-closed {
  background: rgba(10, 12, 19, 0.75);
  border-style: dashed;
}

.col-head {
  padding: 14px 16px;
  border-bottom: 1px solid var(--border-subtle);
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: rgba(255, 255, 255, 0.02);
  border-radius: var(--radius-lg) var(--radius-lg) 0 0;
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
  padding: 2px 8px;
  border-radius: 10px;
  color: var(--text-secondary);
}

.col-scroll {
  padding: 12px;
  overflow-y: auto;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.col-empty {
  padding: 36px 12px;
  text-align: center;
  color: var(--text-tertiary);
  font-size: 12px;
}

/* 核心：卡片高质感紧凑布局（告别臃肿长竹竿） */
.task-card {
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  cursor: pointer;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.15);
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
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
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

.req-mini-preview-line {
  margin-top: 4px;
}
.original-text.compact-pill {
  padding: 4px 8px;
  font-size: 11px;
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  border-left-width: 2px;
}
.preview-text {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.btn-inline-archive {
  padding: 1px 6px;
  font-size: 10px;
  color: var(--green);
  border: 1px solid var(--green-border);
  background: var(--green-bg);
  border-radius: 3px;
}

.task-card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 6px;
  border-top: 1px solid rgba(255, 255, 255, 0.04);
}

.req-progress-pill {
  font-size: 10px;
  color: var(--text-secondary);
  background: rgba(255, 255, 255, 0.05);
  padding: 2px 6px;
  border-radius: 4px;
}
.req-progress-pill.all-done {
  color: var(--green);
  background: var(--green-bg);
}

.actions-group {
  display: flex;
  gap: 4px;
}
.action-btn {
  padding: 2px 6px;
  font-size: 10px;
}

/* 详情抽屉遮罩与内容区 */
.task-drawer-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.65);
  backdrop-filter: blur(4px);
  z-index: 100;
  display: flex;
  justify-content: flex-end;
}
.task-drawer-content {
  width: min(600px, 94vw);
  background: var(--bg-overlay);
  border-left: 1px solid var(--border-strong);
  height: 100vh;
  display: flex;
  flex-direction: column;
  box-shadow: -10px 0 40px rgba(0, 0, 0, 0.7);
  animation: slideDrawer 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}
@keyframes slideDrawer {
  from { transform: translateX(100%); }
  to { transform: translateX(0); }
}

.drawer-header {
  padding: 24px;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--bg-subtle);
}
.drawer-body {
  padding: 24px;
  overflow-y: auto;
  flex: 1;
}
.drawer-footer {
  padding: 16px 24px;
  border-top: 1px solid var(--border-subtle);
  display: flex;
  justify-content: flex-end;
}

.drawer-req-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.drawer-req-item {
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-left: 3px solid var(--accent);
  border-radius: var(--radius-md);
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.drawer-req-item.is-archived {
  border-left-color: var(--green);
  opacity: 0.9;
}
.drawer-req-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.archive-btn {
  padding: 3px 8px;
  font-size: 11px;
}
.req-block-label {
  font-size: 10px;
  color: var(--text-tertiary);
  font-weight: 600;
  text-transform: uppercase;
  margin-bottom: 4px;
}
.summary-text {
  color: var(--green);
  font-size: 12px;
  margin: 0;
  line-height: 1.5;
}

/* 清单表格 */
.table-wrap {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
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
  color: var(--text-tertiary);
  text-transform: uppercase;
  font-size: 11px;
  font-weight: 600;
}
</style>
