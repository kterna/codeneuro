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
  return `第 #${minSeq} 至 #${maxSeq} 号事件（共 ${allEvents.value.length} 条已载入）`
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
  'task.deleted': '删除任务（保留历史）',
  'task.paused': '暂停任务',
  'task.resumed': '恢复任务',
  'task.reopened': '重新激活任务',
  'task.transitioned': '流转任务状态',
  'task.completed': '完成任务',
  'requirement.submitted': '录入业务需求',
  'requirement.archived': '归档业务需求',
  'requirement.reopened': '恢复业务需求',
  'requirement.created': '创建业务需求',
  'requirement.updated': '修订业务需求',
  'requirement.deleted': '删除业务需求（保留历史）',
  'finding.recorded': '记录开发便签',
  'rule.created': '创建规则',
  'rule.rated': '规则评分',
  'rule.promoted': '提升为长期规则',
  'rule.observed': '记录规则草稿',
  'rule.evidence_attached': '附加规则证据',
  'rule.activate': '激活规则',
  'rule.revoke': '撤销规则',
  'rule.update': '更新规则',
  'rule.reduce_priority': '降低规则优先级',
  'issue.reported': '报告问题',
  'contract.proposed': '提交契约提案',
  'contract.updated': '更新契约',
  'contract.reviewed': '审阅契约',
  'context.delivered': '下发上下文',
  'test.client_reported': '客户端上报测试',
  'session.started': '历史会话开始',
  'session.closed': '历史会话关闭',
}

function formatAction(action: string): string {
  return actionNameMap[action] || action
}
</script>

<template>
  <div class="activity-view-root">
    <div class="section-head">
      <div>
        <h2>变更审计流水</h2>
        <span class="caption">每一次需求与子任务推进、整体验收、规则演进均在同一事务持久化留存</span>
      </div>
      <span v-if="loadedRange" class="caption font-mono">{{ loadedRange }}</span>
    </div>

    <div v-if="!allEvents.length" class="empty">
      暂无审计事件记录。
    </div>

    <div v-else class="timeline-container">
      <div class="timeline-list">
        <article v-for="ev in allEvents" :key="ev.sequence" class="card timeline-row" :data-action="ev.action">
          <div class="card-head">
            <div class="action-actor-line">
              <span class="tag neutral font-mono">#{{ ev.sequence }}</span>
              <strong class="action-name" :data-action="ev.action">{{ formatAction(ev.action) }}</strong>
              <span v-if="ev.actor" class="caption">操作者: <code>{{ ev.actor }}</code></span>
            </div>
            <time class="muted">{{ formatTime(ev.created_at) }}</time>
          </div>

          <div class="timeline-meta">
            <span class="caption">目标实体：<code>{{ ev.entity_id }}</code></span>
          </div>

          <div v-if="ev.details && Object.keys(ev.details).length" class="event-details-box">
            <span class="caption">事务详情：</span>
            <pre class="details-pre"><code>{{ JSON.stringify(ev.details, null, 2) }}</code></pre>
          </div>
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
            {{ loadingMore ? '正在载入…' : '加载更早历史' }}
          </button>
          <span class="caption">从游标 #{{ currentCursor }} 之前继续加载</span>
        </template>
        <span v-else-if="allEvents.length > 0" class="caption">已加载至最早审计记录。</span>
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
.details-pre {
  margin: 4px 0 0;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--gh-fg-muted);
  max-height: 120px;
  overflow-y: auto;
}

.timeline-pagination {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 12px 0;
}
</style>
