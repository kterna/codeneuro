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

const taskLabels: Record<TaskStatus, string> = {
  draft: '草案',
  active: '进行中',
  paused: '已暂停',
  testing: '测试中',
  released: '已发布',
  archived: '已归档',
}

const laneStatuses: TaskStatus[] = ['draft', 'active', 'paused', 'testing', 'released', 'archived']

const demand = ref('')
const selectedTaskId = ref('')
const viewMode = ref<'swimlane' | 'list'>('swimlane')

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
</script>

<template>
  <div>
    <!-- 需求录入面板 -->
    <div class="panel demand-panel" style="margin-bottom: 22px">
      <div class="section-head" style="margin-top: 0">
        <h2>录入业务需求</h2>
        <span class="caption">输入业务需求原文，系统将自动关联匹配的任务，作为执行约束下发给 Agent</span>
      </div>
      <label class="field">
        需求原文描述
        <textarea
          id="demand-text"
          v-model="demand"
          rows="4"
          placeholder="请输入业务需求原文，例如：在结算服务中增加对超期图纸的自动退回与提醒逻辑…"
          @input="selectedTaskId = ''"
        ></textarea>
      </label>

      <!-- 智能正则匹配关联任务 -->
      <div v-if="matchedTasks.length > 1" class="panel" style="background: var(--surface)">
        <p><strong>检测到多个候选任务，请明确选择归属任务：</strong></p>
        <label v-for="t in matchedTasks" :key="t.id" class="choice">
          <input v-model="selectedTaskId" type="radio" :value="t.id" />
          {{ t.title }} <span class="muted">({{ taskLabels[t.status] || t.status }})</span>
        </label>
      </div>
      <p v-else-if="matchedTasks.length === 1" class="muted">
        将自动归入已有任务：<strong>{{ matchedTasks[0].title }}</strong>
      </p>
      <p v-else-if="demand.trim()" class="muted">
        未匹配已有活跃任务，将基于首句摘要自动创建新任务。
      </p>

      <div class="toolbar" style="margin-bottom: 0; margin-top: 10px">
        <button
          class="primary"
          :disabled="busy || !demand.trim() || (matchedTasks.length > 1 && !selectedTaskId)"
          @click="handleSubmit"
        >
          {{ busy ? '提交中…' : '提交原文需求' }}
        </button>
      </div>
    </div>

    <!-- 看板与视图切换栏 -->
    <div class="section-head">
      <h2>任务流转看板</h2>
      <div class="toolbar" style="margin: 0">
        <button
          :class="{ primary: viewMode === 'swimlane' }"
          @click="viewMode = 'swimlane'"
        >
          泳道看板
        </button>
        <button
          :class="{ primary: viewMode === 'list' }"
          @click="viewMode = 'list'"
        >
          列表视图
        </button>
      </div>
    </div>

    <!-- 6 泳道横向看板视图 -->
    <div v-if="viewMode === 'swimlane'" class="swimlanes">
      <section
        v-for="statusKey in laneStatuses"
        :key="statusKey"
        class="lane"
        :data-status="statusKey"
      >
        <div class="lane-head">
          <h2>{{ taskLabels[statusKey] }}</h2>
          <span class="tag">{{ ledger.tasks.filter(t => t.status === statusKey).length }}</span>
        </div>

        <div v-if="!ledger.tasks.filter(t => t.status === statusKey).length" class="empty compact">
          暂无任务
        </div>
        <div v-else>
          <article
            v-for="task in ledger.tasks.filter(t => t.status === statusKey)"
            :key="task.id"
            class="card"
            style="margin-bottom: 12px"
          >
            <div class="card-top">
              <h3>{{ task.title }}</h3>
              <span class="tag" :class="task.status">{{ taskLabels[task.status] || task.status }}</span>
            </div>
            <p class="task-description muted">{{ task.description || '无任务说明' }}</p>

            <!-- 挂载的需求列表 -->
            <div
              v-for="req in ledger.requirements.filter(r => r.task_id === task.id)"
              :key="req.id"
              class="row"
              style="padding: 8px 0"
            >
              <div class="tags" style="margin: 0 0 4px">
                <span class="tag" :class="req.status">{{ req.status === 'active' ? '进行中 (active)' : '已归档 (archived)' }} · v{{ req.version }}</span>
              </div>
              <p class="original-text" style="font-size: 11px">{{ req.text }}</p>
              <p v-if="req.summary" class="muted" style="font-size: 11px">
                完成摘要：{{ req.summary }}
              </p>
              <button
                v-if="req.status === 'active' && ['active', 'testing'].includes(task.status)"
                class="subtle"
                style="padding: 4px 8px; font-size: 11px; margin-top: 4px"
                :disabled="busy"
                @click="emit('open-archive', req)"
              >
                确认归档
              </button>
            </div>

            <!-- 任务状态操作 -->
            <div class="actions">
              <button
                v-if="['active', 'testing'].includes(task.status)"
                :disabled="busy"
                @click="emit('open-pause', task)"
              >
                暂停任务
              </button>
              <button
                v-if="task.status === 'paused'"
                :disabled="busy"
                @click="emit('open-resume', task)"
              >
                恢复任务
              </button>
            </div>
          </article>
        </div>
      </section>
    </div>

    <!-- 列表视图 -->
    <div v-else class="grid">
      <article v-for="task in ledger.tasks" :key="task.id" class="card">
        <div class="card-top">
          <h3>{{ task.title }}</h3>
          <div class="tags">
            <span class="tag" :class="task.status">{{ taskLabels[task.status] || task.status }}</span>
            <span class="tag">修订版本 #{{ task.revision }}</span>
          </div>
        </div>
        <p>{{ task.description || '无详细描述' }}</p>

        <div class="toolbar">
          <button
            v-if="['active', 'testing'].includes(task.status)"
            :disabled="busy"
            @click="emit('open-pause', task)"
          >
            暂停任务
          </button>
          <button
            v-if="task.status === 'paused'"
            :disabled="busy"
            @click="emit('open-resume', task)"
          >
            恢复任务
          </button>
        </div>

        <div class="section-head" style="margin: 14px 0 8px">
          <h3 style="margin: 0">关联业务需求条目 ({{ ledger.requirements.filter(r => r.task_id === task.id).length }})</h3>
        </div>
        <div
          v-for="req in ledger.requirements.filter(r => r.task_id === task.id)"
          :key="req.id"
          class="row"
        >
          <div class="card-top">
            <span class="tag" :class="req.status">{{ req.status === 'active' ? '进行中 (active)' : '已归档 (archived)' }} · v{{ req.version }}</span>
            <button
              v-if="req.status === 'active' && ['active', 'testing'].includes(task.status)"
              :disabled="busy"
              @click="emit('open-archive', req)"
            >
              确认归档
            </button>
          </div>
          <p class="original-text">{{ req.text }}</p>
          <p v-if="req.summary" class="muted">完成摘要：{{ req.summary }}</p>
        </div>
      </article>
    </div>
  </div>
</template>
