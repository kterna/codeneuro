<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import type { Ledger, Requirement, RequirementSummary, Task, TaskSummary } from '../../types/ledger'
import { apiService } from '../../api/client'
import GhDrawer from '../ui/GhDrawer.vue'

const props = defineProps<{ projectId: string; ledger: Ledger }>()
const emit = defineEmits<{ (e: 'refresh'): void }>()
const requirements = ref<RequirementSummary[]>([])
const requirementCursor = ref<string | null>(null)
const selectedId = ref('')
const selected = ref<Requirement | null>(null)
const tasks = ref<TaskSummary[]>([])
const taskCursor = ref<string | null>(null)
const loadingMoreTasks = ref(false)
const focusedTask = ref<Task | null>(null)
const busy = ref(false)
const loading = ref(false)
const error = ref('')
const notice = ref('')
const newRequirement = ref({ title: '', text: '', acceptance_criteria: '' })
const newTask = ref({ title: '', description: '', acceptance_criteria: '' })
const requirementRequest = ref(crypto.randomUUID())
const taskRequest = ref(crypto.randomUUID())
watch(newRequirement, () => { requirementRequest.value = crypto.randomUUID() }, { deep: true })
watch([newTask, selectedId], () => { taskRequest.value = crypto.randomUUID() }, { deep: true })
let alive = true
let listSequence = 0
let selectionSequence = 0
let taskSequence = 0
const abort = new AbortController()
onUnmounted(() => { alive = false; abort.abort() })

const labels: Record<string, string> = {
  draft: '待开始', active: '进行中', testing: '待验证', paused: '已暂停', accepting: '待整体验收', completed: '已完成',
}
const canWork = computed(() => selected.value && !selected.value.archived_at && selected.value.status !== 'completed')
const relatedRules = computed(() => props.ledger.rules.filter(rule => rule.task_id === focusedTask.value?.id))
const relatedFindings = computed(() => props.ledger.findings?.filter(item => item.task_id === focusedTask.value?.id) ?? [])
const history = ref<(Requirement | Task)[]>([])
const historyCursor = ref<number | null>(null)
const historyTarget = ref<{ kind: 'requirements' | 'tasks'; id: string } | null>(null)
let historySequence = 0

type EditAction = {
  kind: 'requirements' | 'tasks'
  target: Requirement | Task
  title: string
  changes: Record<string, unknown>
  edit?: boolean
  remove?: boolean
}
const action = ref<EditAction | null>(null)
const actionReason = ref('')
const actionSummary = ref('')
const editTitle = ref('')
const editText = ref('')
const editAcceptance = ref('')

function failed(cause: unknown) {
  if (alive && (cause as Error).name !== 'AbortError') error.value = (cause as Error).message
}

async function loadRequirements(more = false) {
  const sequence = ++listSequence
  const page = await apiService.getRequirements(props.projectId, more ? requirementCursor.value : null, abort.signal)
  if (!alive || sequence !== listSequence) return
  requirements.value = more ? [...requirements.value, ...page.items] : page.items
  requirementCursor.value = page.next_cursor
}

async function selectRequirement(id: string) {
  const sequence = ++selectionSequence
  ++taskSequence
  ++historySequence
  loadingMoreTasks.value = false
  selectedId.value = id
  selected.value = null
  tasks.value = []
  taskCursor.value = null
  focusedTask.value = null
  historyTarget.value = null
  error.value = ''
  loading.value = true
  try {
    const [detail, page] = await Promise.all([
      apiService.getRequirement(props.projectId, id, abort.signal),
      apiService.getTasks(props.projectId, id, null, abort.signal),
    ])
    if (!alive || sequence !== selectionSequence) return
    selected.value = detail
    tasks.value = page.items
    taskCursor.value = page.next_cursor
  } catch (cause) { failed(cause) }
  finally { if (alive && sequence === selectionSequence) loading.value = false }
}

async function loadMoreTasks() {
  if (loadingMoreTasks.value || !taskCursor.value) return
  const id = selectedId.value
  const sequence = selectionSequence
  loadingMoreTasks.value = true
  try {
    const page = await apiService.getTasks(props.projectId, id, taskCursor.value, abort.signal)
    if (!alive || selectedId.value !== id || sequence !== selectionSequence) return
    tasks.value = [...tasks.value, ...page.items]
    taskCursor.value = page.next_cursor
  } catch (cause) { failed(cause) }
  finally { if (alive && sequence === selectionSequence) loadingMoreTasks.value = false }
}

async function openTask(id: string) {
  const sequence = ++taskSequence
  const parent = selectedId.value
  try {
    const detail = await apiService.getTask(props.projectId, id, abort.signal)
    if (alive && sequence === taskSequence && parent === selectedId.value) focusedTask.value = detail
  } catch (cause) { failed(cause) }
}

async function refreshView() {
  try {
    await loadRequirements()
    const id = selectedId.value
    if (id) {
      const sequence = ++selectionSequence
      const [detail, page] = await Promise.all([
        apiService.getRequirement(props.projectId, id, abort.signal),
        apiService.getTasks(props.projectId, id, null, abort.signal),
      ])
      if (!alive || selectedId.value !== id || sequence !== selectionSequence) return
      if (detail.deleted_at) { selected.value = null; selectedId.value = ''; tasks.value = []; loading.value = false; return }
      selected.value = detail
      loading.value = false
      loadingMoreTasks.value = false
      tasks.value = page.items
      taskCursor.value = page.next_cursor
      if (focusedTask.value) await openTask(focusedTask.value.id)
    }
  } catch (cause) { failed(cause) }
}
watch(() => props.ledger, () => { void refreshView() })
onMounted(() => { void refreshView() })

async function createRequirement() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    const result = await apiService.createRequirement(props.projectId, { ...newRequirement.value }, requirementRequest.value)
    if (!alive) return
    newRequirement.value = { title: '', text: '', acceptance_criteria: '' }
    await loadRequirements()
    await selectRequirement(result.id)
    notice.value = '需求已创建，可以分别添加子任务。'
    emit('refresh')
  } catch (cause) { failed(cause) }
  finally { if (alive) busy.value = false }
}

async function createTask() {
  if (busy.value || !selected.value) return
  busy.value = true
  error.value = ''
  try {
    const status = selected.value.status === 'draft' ? 'draft' : 'active'
    await apiService.createTask(props.projectId, selected.value.id, { ...newTask.value, status }, taskRequest.value)
    if (!alive) return
    newTask.value = { title: '', description: '', acceptance_criteria: '' }
    await refreshView()
    notice.value = '子任务已创建。'
    emit('refresh')
  } catch (cause) { failed(cause) }
  finally { if (alive) busy.value = false }
}

function openAction(kind: EditAction['kind'], target: Requirement | Task, title: string,
                    changes: Record<string, unknown> = {}, edit = false, remove = false) {
  if (busy.value) return
  action.value = { kind, target: { ...target }, title, changes, edit, remove }
  actionReason.value = ''
  actionSummary.value = ''
  editTitle.value = target.title
  editText.value = 'text' in target ? target.text : target.description
  editAcceptance.value = target.acceptance_criteria
  error.value = ''
}

async function submitAction() {
  const current = action.value
  if (!current || busy.value) return
  busy.value = true
  error.value = ''
  const changes = { ...current.changes }
  if (current.edit) {
    changes.title = editTitle.value
    changes[current.kind === 'requirements' ? 'text' : 'description'] = editText.value
    changes.acceptance_criteria = editAcceptance.value
  }
  if (changes.status === 'completed') {
    changes[current.kind === 'requirements' ? 'completion_summary' : 'verification_summary'] = actionSummary.value
  }
  try {
    const reason = current.kind === 'requirements' && changes.status === 'completed'
      ? `用户在工作台明确确认整体验收通过：${actionReason.value}` : actionReason.value
    if (current.kind === 'requirements') {
      if (current.remove) await apiService.deleteRequirement(props.projectId, current.target.id, current.target.version, reason)
      else await apiService.updateRequirement(props.projectId, current.target.id, current.target.version, changes, reason)
    } else {
      if (current.remove) await apiService.deleteTask(props.projectId, current.target.id, current.target.version, reason)
      else await apiService.updateTask(props.projectId, current.target.id, current.target.version, changes, reason)
    }
    if (!alive) return
    action.value = null
    if (current.remove && current.kind === 'tasks') focusedTask.value = null
    await refreshView()
    notice.value = `${current.title}已保存。`
    emit('refresh')
  } catch (cause) { failed(cause) }
  finally { if (alive) busy.value = false }
}

async function showHistory(kind: EditAction['kind'], id: string, more = false) {
  const sequence = ++historySequence
  try {
    const page = await apiService.getVersions(props.projectId, kind, id, more ? historyCursor.value : null)
    if (!alive || sequence !== historySequence) return
    historyTarget.value = { kind, id }
    history.value = more ? [...history.value, ...page.items] : page.items
    historyCursor.value = page.next_cursor
  } catch (cause) { failed(cause) }
}
</script>

<template>
  <div class="task-workspace">
    <div v-if="error" role="alert" class="error">{{ error }}</div>
    <div v-if="notice" role="status" class="caption">{{ notice }}</div>
    <details class="resource-panel">
      <summary>＋ 新建业务需求</summary>
      <form @submit.prevent="createRequirement">
        <fieldset :disabled="busy">
          <label class="field">需求名称<input v-model="newRequirement.title" required maxlength="500" placeholder="例如：规则推送记录可按会话回溯" /></label>
          <label class="field">整体目标<textarea v-model="newRequirement.text" required rows="3" /></label>
          <label class="field">整体验收要求<textarea v-model="newRequirement.acceptance_criteria" rows="2" /></label>
          <button class="primary" type="submit">创建需求</button>
        </fieldset>
      </form>
    </details>
    <div class="resource-layout">
      <aside class="resource-panel requirement-list" aria-label="业务需求列表">
        <div class="row"><h2>业务需求</h2><button :disabled="busy" @click="refreshView">刷新</button></div>
        <p v-if="!requirements.length" class="muted">暂无需求。</p>
        <button
          v-for="item in requirements"
          :key="item.id"
          class="requirement-item"
          :class="{ selected: selectedId === item.id }"
          :disabled="busy"
          @click="selectRequirement(item.id)"
        >
          <div class="req-item-head">
            <strong class="req-title">{{ item.title }}</strong>
            <span class="req-badge" :class="'status-' + item.status">
              {{ labels[item.status] }}<template v-if="item.archived_at"> · 归档</template>
            </span>
          </div>
          <div class="req-item-meta">
            <span class="req-progress">已验证 {{ item.progress.completed }} / {{ item.progress.total }}</span>
          </div>
          <div class="req-desc muted">{{ item.text }}{{ item.truncated ? '…' : '' }}</div>
        </button>
        <button v-if="requirementCursor" :disabled="busy" @click="loadRequirements(true).catch(failed)">加载更多需求</button>
      </aside>
      <section class="resource-panel requirement-detail" aria-label="需求详情">
        <p v-if="loading">正在读取需求…</p>
        <div v-else-if="!selected" class="empty-state-box">
          <div class="empty-icon">📋</div>
          <p class="empty-title">未选择业务需求</p>
          <p class="empty-desc">请选择业务需求查看详情。</p>
        </div>
        <template v-else>
          <div class="row"><h2>{{ selected.title }}</h2><span>{{ labels[selected.status] }} · v{{ selected.version }}</span></div>
          <p v-if="selected.archived_at" class="caption">已归档；恢复归档后才能继续修改。</p>
          <p class="body-text">{{ selected.text }}</p>
          <h3>整体验收要求</h3><p class="body-text">{{ selected.acceptance_criteria || '尚未填写' }}</p>
          <p>已验证子任务：{{ selected.progress.completed }} / {{ selected.progress.total }}</p>
          <p v-if="selected.completion_summary" class="body-text">验收结论：{{ selected.completion_summary }}</p>
          <div class="actions">
            <template v-if="!selected.archived_at">
              <button v-if="selected.status === 'draft'" @click="openAction('requirements', selected, '开始需求', { status: 'active' })">开始需求</button>
              <button v-if="selected.status === 'accepting'" class="primary" @click="openAction('requirements', selected, '确认整体验收通过', { status: 'completed' })">确认整体验收通过</button>
              <button v-if="selected.status === 'accepting'" @click="openAction('requirements', selected, '退回继续处理', { status: 'active' })">验收未通过</button>
              <button v-if="selected.status === 'active' && selected.progress.total > 0 && selected.progress.completed === selected.progress.total"
                      @click="openAction('requirements', selected, '重新提交整体验收', { status: 'accepting' })">提交整体验收</button>
              <button v-if="selected.status === 'completed'" @click="openAction('requirements', selected, '重开需求', { status: 'active' })">重开需求</button>
              <button v-else @click="openAction('requirements', selected, '修改需求', {}, true)">修改需求</button>
              <button @click="openAction('requirements', selected, '归档需求', { archived: true })">归档</button>
              <button v-if="!selected.progress.total" @click="openAction('requirements', selected, '删除需求', {}, false, true)">删除</button>
            </template>
            <button v-else @click="openAction('requirements', selected, '恢复归档需求', { archived: false })">恢复归档</button>
            <button @click="showHistory('requirements', selected.id)">版本历史</button>
          </div>
          <p v-if="selected.status === 'accepting'" class="acceptance-note">子任务已分别验证完成，请确认整体验收结果。</p>
          <h3>子任务</h3>
          <p v-if="!tasks.length" class="muted">暂无子任务。</p>
          <table v-else class="tasks-table">
            <thead><tr><th>任务</th><th>状态</th><th>版本</th></tr></thead>
            <tbody><tr v-for="item in tasks" :key="item.id">
              <td><button class="subtle" @click="openTask(item.id)">{{ item.title }}</button></td>
              <td>{{ labels[item.status] }}{{ item.archived_at ? ' · 已归档' : '' }}</td><td>{{ item.version }}</td>
            </tr></tbody>
          </table>
          <button v-if="taskCursor" :disabled="busy || loadingMoreTasks" @click="loadMoreTasks">加载更多子任务</button>
          <details v-if="canWork" class="new-task">
            <summary>＋ 添加子任务</summary>
            <form @submit.prevent="createTask"><fieldset :disabled="busy">
              <label class="field">任务名称<input v-model="newTask.title" required maxlength="500" placeholder="例如：新增按目录查规则接口" /></label>
              <label class="field">实现范围<textarea v-model="newTask.description" rows="3" /></label>
              <label class="field">验证要求<textarea v-model="newTask.acceptance_criteria" rows="2" /></label>
              <button class="primary" type="submit">创建子任务</button>
            </fieldset></form>
          </details>
        </template>
      </section>
    </div>
    <GhDrawer :model-value="!!focusedTask" :title="focusedTask?.title" content-class="task-detail" width="min(680px, 94vw)" @update:model-value="value => { if (!value) focusedTask = null }">
      <template v-if="focusedTask">
        <p>{{ labels[focusedTask.status] }} · v{{ focusedTask.version }} · 所属需求：{{ selected?.title }}</p>
        <h3>实现范围</h3><p class="body-text">{{ focusedTask.description || '尚未填写' }}</p>
        <h3>验证要求</h3><p class="body-text">{{ focusedTask.acceptance_criteria || '尚未填写' }}</p>
        <p v-if="focusedTask.verification_summary" class="body-text">验证结论：{{ focusedTask.verification_summary }}</p>
        <p v-if="focusedTask.verification_report_ids.length" class="body-text">报告：{{ focusedTask.verification_report_ids.join(', ') }}</p>
        <div class="actions">
          <template v-if="canWork && !focusedTask.archived_at && !focusedTask.deleted_at">
            <button v-if="focusedTask.status === 'draft' && selected?.status !== 'draft'" @click="openAction('tasks', focusedTask, '开始任务', { status: 'active' })">开始任务</button>
            <button v-if="focusedTask.status === 'active'" @click="openAction('tasks', focusedTask, '提交验证', { status: 'testing' })">开发完成，提交验证</button>
            <button v-if="focusedTask.status === 'testing'" class="primary" @click="openAction('tasks', focusedTask, '确认子任务验证通过', { status: 'completed' })">验证通过</button>
            <button v-if="focusedTask.status === 'testing' || focusedTask.status === 'completed'" @click="openAction('tasks', focusedTask, '退回开发', { status: 'active' })">退回开发</button>
            <button v-if="['active', 'testing'].includes(focusedTask.status)" @click="openAction('tasks', focusedTask, '暂停任务', { status: 'paused' })">暂停</button>
            <button v-if="focusedTask.status === 'paused'" @click="openAction('tasks', focusedTask, '恢复任务', { status: focusedTask.paused_from })">恢复</button>
            <button v-if="['draft', 'active'].includes(focusedTask.status)" @click="openAction('tasks', focusedTask, '修改任务', {}, true)">修改任务</button>
            <button @click="openAction('tasks', focusedTask, '删除子任务', {}, false, true)">删除</button>
          </template>
          <button v-if="selected && !selected.archived_at && !focusedTask.deleted_at"
                  @click="openAction('tasks', focusedTask, focusedTask.archived_at ? '恢复归档任务' : '归档任务', { archived: !focusedTask.archived_at })">{{ focusedTask.archived_at ? '恢复归档' : '归档' }}</button>
          <button @click="showHistory('tasks', focusedTask.id)">版本历史</button>
        </div>
        <h3>任务规则</h3><p v-if="!relatedRules.length" class="muted">暂无任务规则。</p>
        <details v-for="rule in relatedRules" :key="rule.id"><summary>{{ rule.title }} · {{ rule.status }}</summary><ul><li v-for="point in rule.points" :key="point">{{ point }}</li></ul></details>
        <h3>相关便签</h3><p v-if="!relatedFindings.length" class="muted">暂无便签。</p>
        <p v-for="finding in relatedFindings" :key="finding.id" class="body-text">{{ finding.text }} · {{ finding.status }}</p>
      </template>
    </GhDrawer>
    <GhDrawer :model-value="!!action" :title="action?.title" content-class="task-action" @update:model-value="value => { if (!value && !busy) action = null }">
      <form v-if="action" @submit.prevent="submitAction"><fieldset :disabled="busy">
        <p>{{ action.target.title }} · 基于版本 {{ action.target.version }}</p>
        <p v-if="action.remove" class="caption">保留历史，删除不代表完成。</p>
        <template v-if="action.edit">
          <label class="field">名称<input v-model="editTitle" required maxlength="500" /></label>
          <label class="field">说明<textarea v-model="editText" rows="5" :required="action.kind === 'requirements'" /></label>
          <label class="field">验收要求<textarea v-model="editAcceptance" rows="3" /></label>
        </template>
        <label v-if="action.changes.status === 'completed'" class="field">{{ action.kind === 'requirements' ? '整体验收结论' : '验证方式与结果' }}<textarea v-model="actionSummary" required rows="4" /></label>
        <label class="field">操作原因<textarea v-model="actionReason" required rows="3" /></label>
        <div v-if="error" role="alert" class="error">{{ error }}</div>
        <button class="primary" type="submit">{{ busy ? '保存中…' : action.title }}</button>
      </fieldset></form>
    </GhDrawer>
    <GhDrawer :model-value="!!historyTarget" title="版本历史" content-class="resource-history" @update:model-value="value => { if (!value) { historyTarget = null; historySequence++ } }">
      <details v-for="item in history" :key="item.version"><summary>v{{ item.version }} · {{ labels[item.status] }}{{ item.archived_at ? ' · 归档' : '' }}{{ item.deleted_at ? ' · 删除' : '' }}</summary>
        <p class="body-text">{{ 'text' in item ? item.text : item.description }}</p><p class="body-text">{{ item.acceptance_criteria }}</p>
        <p class="body-text">{{ 'text' in item ? item.completion_summary : item.verification_summary }}</p>
      </details>
      <button v-if="historyCursor && historyTarget" @click="showHistory(historyTarget.kind, historyTarget.id, true)">加载更多版本</button>
    </GhDrawer>
  </div>
</template>

<style scoped>
.task-workspace { display: flex; flex-direction: column; gap: 16px; }
.resource-layout { display: grid; grid-template-columns: minmax(280px, 32%) 1fr; gap: 16px; align-items: start; }
.resource-panel { border: 1px solid var(--gh-border-default); border-radius: 8px; background: var(--gh-canvas-default); padding: 16px; min-width: 0; }
.requirement-item {
  display: flex;
  flex-direction: column;
  gap: 8px;
  text-align: left;
  width: 100%;
  margin: 8px 0;
  white-space: normal;
  overflow-wrap: anywhere;
  padding: 12px 14px;
  background: var(--gh-canvas-subtle);
  border: 1px solid var(--gh-border-default);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
}
.requirement-item:hover {
  border-color: var(--gh-border-muted);
  background: var(--gh-surface-card);
}
.requirement-item.selected {
  border-color: var(--gh-accent-fg);
  background: rgba(56, 139, 253, 0.08);
}
.req-item-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}
.req-title {
  font-size: 13px;
  font-weight: 600;
  line-height: 1.4;
  color: var(--gh-fg-default);
}
.req-badge {
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 10px;
  background: var(--gh-canvas-inset);
  border: 1px solid var(--gh-border-default);
  color: var(--gh-fg-muted);
  white-space: nowrap;
  flex-shrink: 0;
}
.req-badge.status-active {
  color: var(--gh-accent-fg);
  border-color: rgba(56, 139, 253, 0.4);
  background: var(--gh-accent-subtle);
}
.req-badge.status-completed {
  color: var(--gh-success-fg);
  border-color: rgba(46, 160, 67, 0.4);
  background: rgba(46, 160, 67, 0.15);
}
.req-badge.status-accepting {
  color: var(--gh-attention-fg);
  border-color: rgba(210, 153, 34, 0.4);
  background: rgba(210, 153, 34, 0.15);
}
.req-badge.status-draft {
  color: var(--gh-fg-subtle);
}
.req-item-meta {
  display: flex;
  align-items: center;
  gap: 8px;
}
.req-progress {
  font-size: 11px;
  color: var(--gh-fg-muted);
  font-family: var(--font-mono);
}
.req-desc {
  font-size: 12px;
  line-height: 1.5;
  color: var(--gh-fg-muted);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-overflow: ellipsis;
  word-break: break-word;
}
.empty-state-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 48px 24px;
  color: var(--gh-fg-muted);
}
.empty-icon {
  font-size: 32px;
  margin-bottom: 12px;
  opacity: 0.8;
}
.empty-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--gh-fg-default);
  margin: 0 0 6px;
}
.empty-desc {
  font-size: 12px;
  max-width: 360px;
  margin: 0;
  line-height: 1.6;
}
.row, .actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.row { justify-content: space-between; }
.actions { margin: 16px 0; }
h2 { font-size: 17px; margin: 0 0 8px; }
h3 { font-size: 14px; margin: 20px 0 8px; }
.body-text { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.6; }
fieldset { border: 0; padding: 0; margin: 12px 0; min-width: 0; }
.field { display: flex; flex-direction: column; gap: 6px; margin-bottom: 12px; }
input, textarea { width: 100%; box-sizing: border-box; }
.tasks-table { width: 100%; border-collapse: collapse; }
.tasks-table th, .tasks-table td { text-align: left; padding: 10px 8px; border-bottom: 1px solid var(--gh-border-default); }
.acceptance-note { padding: 12px; border-left: 3px solid var(--gh-accent-fg); background: var(--gh-canvas-subtle); }
.new-task { margin-top: 20px; }
summary { cursor: pointer; padding: 8px 0; }
@media (max-width: 800px) { .resource-layout { grid-template-columns: 1fr; } }
</style>
