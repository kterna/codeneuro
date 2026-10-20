<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Ledger, AuditEvent } from '../../types/ledger'
import { apiService } from '../../api/client'

const props = defineProps<{
  ledger: Ledger
  projectId?: string
}>()

const additionalEvents = ref<AuditEvent[]>([])
const currentCursor = ref<number | null>(null)
const loadingMore = ref(false)
const loadError = ref('')
let loadSeq = 0

// 同步初始游标与事件
watch(
  () => [props.ledger, props.projectId],
  ([newLedger]) => {
    loadSeq++
    additionalEvents.value = []
    loadError.value = ''
    loadingMore.value = false
    currentCursor.value = (newLedger as Ledger)?.events_next_cursor ?? null
  },
  { immediate: true },
)

const allEvents = computed<AuditEvent[]>(() => {
  const map = new Map<number, AuditEvent>()
  for (const ev of props.ledger.events) {
    map.set(ev.sequence, ev)
  }
  for (const ev of additionalEvents.value) {
    map.set(ev.sequence, ev)
  }
  return Array.from(map.values()).sort((a, b) => b.sequence - a.sequence)
})

const loadedRange = computed(() => {
  if (!allEvents.value.length) return ''
  const maxSeq = allEvents.value[0].sequence
  const minSeq = allEvents.value[allEvents.value.length - 1].sequence
  return `已显示 ${allEvents.value.length} 条 · #${minSeq}–#${maxSeq}`
})

async function loadOlderEvents() {
  if (!props.projectId || currentCursor.value === null) return
  const currentSeq = ++loadSeq
  const currentPid = props.projectId
  loadingMore.value = true
  loadError.value = ''

  try {
    const res = await apiService.getEvents(currentPid, 100, currentCursor.value)
    if (currentSeq !== loadSeq || props.projectId !== currentPid) return
    if (res && res.items) {
      additionalEvents.value = [...additionalEvents.value, ...res.items]
      currentCursor.value = res.next_cursor
    }
  } catch (err: unknown) {
    if (currentSeq !== loadSeq || props.projectId !== currentPid) return
    loadError.value = (err as Error).message || String(err)
  } finally {
    if (currentSeq === loadSeq) {
      loadingMore.value = false
    }
  }
}

function formatTime(iso: string) {
  if (!iso) return '—'
  const d = new Date(iso)
  return isNaN(d.getTime()) ? iso : d.toLocaleString()
}

const actionNameMap: Record<string, string> = {
  'project.created': '注册项目',
  'task.created': '创建任务',
  'task.updated': '修改任务',
  'task.deleted': '删除任务',
  'task.paused': '暂停任务',
  'task.resumed': '恢复任务',
  'task.reopened': '重新激活任务',
  'task.transitioned': '更新任务状态',
  'task.completed': '完成任务',
  'requirement.submitted': '提交业务需求',
  'requirement.archived': '归档业务需求',
  'requirement.reopened': '恢复业务需求',
  'requirement.created': '创建业务需求',
  'requirement.updated': '修改业务需求',
  'requirement.deleted': '删除需求',
  'finding.recorded': '记录开发便签',
  'rule.created': '创建规则',
  'rule.rated': '规则评分',
  'rule.promoted': '升级为长期规则',
  'rule.observed': '记录规则草稿',
  'rule.evidence_attached': '附加规则证据',
  'rule.activate': '激活规则',
  'rule.revoke': '撤销规则',
  'rule.update': '更新规则',
  'rule.reduce_priority': '降低规则优先级',
  'issue.reported': '报告问题',
  'contract.proposed': '提出规则修改建议',
  'contract.updated': '修改规则',
  'contract.reviewed': '审阅规则修改',
  'context.delivered': '推送规则',
  'test.client_reported': '上报测试结果',
  'session.started': '开始导入历史会话',
  'session.closed': '结束导入历史会话',
  'task.history_imported': '导入任务历史',
  'finding.path_normalized_for_import': '导入时规范化便签路径',
  'finding.scope_corrected_for_import': '导入时修正便签归属',
  'rule.current_baseline_captured': '记录规则当前基线',
  'rule.path_normalized_for_import': '导入时规范化规则路径',
  'worktree.declaration_baselined': '登记工作区基线',
}

function formatAction(action: string): string {
  return actionNameMap[action] || '其他操作'
}

const detailKeyLabels: Record<string, string> = {
  id: '编号',
  project_id: '项目',
  task_id: '任务',
  rule_id: '规则',
  session_ids: '会话编号',
  reason: '原因',
  basis: '依据',
  version: '版本',
  source: '来源',
  historical_reconstruction: '历史补录',
  host_verified: '主机已验证',
  test_validation: '测试验证',
  original_task: '原任务',
  original_task_description: '原任务说明',
  original_finding: '原便签',
  original_record: '原记录',
  updated_record: '修改后记录',
  task_entries: '任务条目',
  entry_deliveries: '推送记录',
  entry_revisions: '修订记录',
  entry_rules: '关联规则',
}

function detailLabel(key: string): string {
  return detailKeyLabels[key] || key
}

function formatDetail(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) {
    if (!value.length) return '无'
    return value.map(item => (item !== null && typeof item === 'object' ? '1 项' : String(item))).join('、')
  }
  if (typeof value === 'object') return `共 ${Object.keys(value).length} 项`
  return String(value)
}
</script>

<template>
  <div class="activity-view-root">
    <div class="section-head">
      <div>
        <span class="caption">记录需求、任务、规则与验收变更。</span>
      </div>
      <span v-if="loadedRange" class="caption">{{ loadedRange }}</span>
    </div>

    <div v-if="!allEvents.length" class="empty">
      还没有任何操作记录。
    </div>

    <div v-else class="timeline-container">
      <div class="timeline-list">
        <article v-for="ev in allEvents" :key="ev.sequence" class="card timeline-row" :data-action="ev.action">
          <div class="card-head">
            <div class="action-actor-line">
              <span class="tag neutral font-mono">#{{ ev.sequence }}</span>
              <strong class="action-name" :data-action="ev.action">{{ formatAction(ev.action) }}</strong>
              <span v-if="ev.actor" class="caption">操作人：<code>{{ ev.actor }}</code></span>
            </div>
            <time class="muted">{{ formatTime(ev.created_at) }}</time>
          </div>

          <div class="timeline-meta">
            <span class="caption">对象：<code>{{ ev.entity_id }}</code></span>
          </div>

          <details v-if="ev.details && Object.keys(ev.details).length" class="event-details-box">
            <summary class="details-summary">
              <span>查看详情（{{ Object.keys(ev.details).length }} 项）</span>
            </summary>
            <dl class="details-list">
              <template v-for="(value, key) in ev.details" :key="key">
                <dt>{{ detailLabel(String(key)) }}</dt>
                <dd>{{ formatDetail(value) }}</dd>
              </template>
            </dl>
            <details class="details-raw">
              <summary class="details-summary">查看原始数据</summary>
              <pre class="details-pre"><code>{{ JSON.stringify(ev.details, null, 2) }}</code></pre>
            </details>
          </details>
        </article>
      </div>

      <!-- 分页加载更早记录 (解决 D20) -->
      <div class="timeline-pagination">
        <template v-if="currentCursor !== null">
          <button
            class="button primary"
            :disabled="loadingMore"
            @click="loadOlderEvents"
          >
            {{ loadingMore ? '正在加载…' : '加载更早的记录' }}
          </button>
        </template>
        <span v-else-if="allEvents.length > 0" class="caption">已到最早记录。</span>
        <div v-if="loadError" class="error-box" role="alert">{{ loadError }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.activity-view-root {
  display: flex;
  flex-direction: column;
  gap: 16px;
  height: 100%;
}

.timeline-container {
  display: flex;
  flex-direction: column;
  gap: 14px;
  overflow-y: auto;
  padding-bottom: 24px;
}

.timeline-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.timeline-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.action-actor-line {
  display: flex;
  align-items: center;
  gap: 8px;
}
.action-name {
  font-size: 13px;
  color: var(--gh-fg-default);
}

.timeline-meta {
  font-size: 12px;
}

.event-details-box {
  background: var(--gh-canvas-inset);
  border: 1px solid var(--gh-border-default);
  border-radius: 4px;
  padding: 6px 10px;
  margin-top: 4px;
}
.details-summary {
  font-size: 11px;
  color: var(--gh-fg-muted);
  cursor: pointer;
  user-select: none;
  font-family: var(--font-mono);
}
.details-summary:hover {
  color: var(--gh-accent-fg);
}
.details-list {
  display: grid;
  grid-template-columns: 110px 1fr;
  gap: 6px 10px;
  margin: 8px 0 0;
  font-size: 11px;
}

.details-list dt {
  color: var(--gh-fg-muted);
}

.details-list dd {
  margin: 0;
  color: var(--gh-fg-default);
  overflow-wrap: anywhere;
}

.details-raw {
  margin-top: 6px;
}

.details-pre {
  margin: 6px 0 0;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--gh-fg-muted);
  max-height: 200px;
  overflow-y: auto;
  border-top: 1px dashed var(--gh-border-default);
  padding-top: 6px;
}

.timeline-pagination {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 12px 0;
}
</style>
