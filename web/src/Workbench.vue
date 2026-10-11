<script setup lang="ts">
import { computed, ref } from 'vue'

type Project = { id: string; name: string }
type Task = { id: string; title: string; description: string; status: string; revision: number }
type Requirement = { id: string; task_id: string; text: string; status: string; version: number; summary: string | null }
type Rule = { id: string; title: string; points: string[]; patterns: string[]; priority: string; task_id: string | null; status: string; origin_rule_id: string | null; origin_version: number | null; eval_count: number; known_count: number; avg_score: number | null }
type Event = { sequence: number; action: string; entity_id: string; created_at: string; details: Record<string, unknown> }
type Worktree = { id: string; machine_name: string; platform: string; workspace: string; repo_identity: string | null; git_branch: string }
type Proposal = { id: string; target_rule_id: string; target_version: number; title: string; points: string[]; patterns: string[]; reason: string; status: string; decision_reason: string | null }
type ScopeDensity = { scope: string; p0: number; p1: number; p2: number; long_term: number; short_term: number; rule_ids: string[] }
type Ledger = { tasks: Task[]; worktrees: Worktree[]; requirements: Requirement[]; rules: Rule[]; proposals: Proposal[]; scope_density: ScopeDensity[]; events: Event[] }

const token = ref('')
const projects = ref<Project[]>([])
const projectId = ref('')
const newProjectId = ref('')
const newProjectName = ref('')
const ledger = ref<Ledger | null>(null)
const demand = ref('')
const selectedTask = ref('')
const error = ref('')
const busy = ref(false)
const requestId = ref('')

async function api<T>(path: string, method = 'GET', body?: object): Promise<T> {
  const response = await fetch('/api' + path, {
    method,
    headers: { Authorization: 'Bearer ' + token.value, ...(body ? { 'Content-Type': 'application/json' } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  })
  const data: unknown = await response.json()
  if (!response.ok) {
    const detail = (data as {detail?: {message?: string} | string}).detail
    throw new Error(typeof detail === 'string' ? detail : detail?.message || `请求失败 (${response.status})`)
  }
  return data as T
}

async function connect() {
  error.value = ''
  try {
    projects.value = await api<Project[]>('/projects')
    if (!projects.value.some(p => p.id === projectId.value)) projectId.value = projects.value[0]?.id || ''
    await refresh()
  } catch (cause) { error.value = (cause as Error).message }
}

async function registerProject() {
  error.value = ''
  try {
    const project = await api<Project>('/projects', 'POST', {
      id: newProjectId.value.trim(), name: newProjectName.value.trim(),
    })
    await connect()
    projectId.value = project.id
    await refresh()
  } catch (cause) { error.value = (cause as Error).message }
}

async function refresh() {
  if (!projectId.value) { ledger.value = null; return }
  error.value = ''
  try { ledger.value = await api<Ledger>(`/projects/${encodeURIComponent(projectId.value)}/ledger`) }
  catch (cause) { error.value = (cause as Error).message }
}

function escaped(value: string): string { return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') }
const matches = computed(() => {
  const text = demand.value.trim()
  if (!text || !ledger.value) return []
  return ledger.value.tasks.filter(task =>
    ['active', 'testing'].includes(task.status) && new RegExp(escaped(task.title), 'i').test(text))
})
const active = computed(() => ledger.value?.requirements.filter(r => r.status === 'active') || [])
const contracts = computed(() => ledger.value?.rules.filter(r => r.task_id === null && r.status === 'active') || [])

async function submit() {
  if (!projectId.value || !demand.value.trim() || (matches.value.length > 1 && !selectedTask.value)) return
  busy.value = true; error.value = ''
  requestId.value ||= crypto.randomUUID()
  const chosen = selectedTask.value || (matches.value.length === 1 ? matches.value[0].id : '')
  try {
    await api(`/projects/${encodeURIComponent(projectId.value)}/requirements`, 'POST', {
      text: demand.value, request_id: requestId.value,
      ...(chosen ? { task_id: chosen } : { title: demand.value.trim().split(/[。.!?\n]/)[0].slice(0, 80) }),
    })
    demand.value = ''; selectedTask.value = ''; requestId.value = ''
    await refresh()
  } catch (cause) { error.value = (cause as Error).message }
  finally { busy.value = false }
}

async function changeTask(task: Task, action: 'pause' | 'resume') {
  const reason = window.prompt(action === 'pause' ? '暂停原因' : '恢复原因')
  if (!reason?.trim()) return
  busy.value = true; error.value = ''
  try {
    await api(`/projects/${encodeURIComponent(projectId.value)}/tasks/${encodeURIComponent(task.id)}/${action}`,
      'POST', { expected_revision: task.revision, reason })
    await refresh()
  } catch (cause) { error.value = (cause as Error).message }
  finally { busy.value = false }
}

async function review(proposal: Proposal, approve: boolean) {
  const reason = window.prompt(approve ? '批准原因（按显示条款更新长期契约）' : '拒绝原因')
  if (!reason?.trim()) return
  busy.value = true; error.value = ''
  try {
    await api(`/projects/${encodeURIComponent(projectId.value)}/proposals/${encodeURIComponent(proposal.id)}/review`,
      'POST', { approve, reason })
    await refresh()
  } catch (cause) { error.value = (cause as Error).message }
  finally { busy.value = false }
}

async function archive(item: Requirement) {
  const summary = window.prompt('请输入确认完成的摘要（CodeNeuro 不运行测试）')
  if (!summary?.trim()) return
  busy.value = true; error.value = ''
  try {
    await api(`/projects/${encodeURIComponent(projectId.value)}/tasks/${encodeURIComponent(item.task_id)}/requirements/${encodeURIComponent(item.id)}/archive`, 'POST', {
      expected_version: item.version, summary,
    })
    await refresh()
  } catch (cause) { error.value = (cause as Error).message }
  finally { busy.value = false }
}
</script>

<template>
  <div class="shell">
    <header class="masthead">
      <div><p class="eyebrow">CODENEURO / KNOWLEDGE HUB</p><h1>认知资产工作台</h1></div>
      <p class="caption">任务、原文需求与长期规则由数据库统一管理。编码与测试由 Coding Agent 执行。</p>
    </header>
    <section class="connect" aria-label="连接 Hub">
      <label>访问凭据 <input id="hub-token" v-model="token" type="password" autocomplete="off" placeholder="项目或人类管理员 Token" /></label>
      <button @click="connect">连接</button>
      <label v-if="projects.length">项目 <select v-model="projectId" @change="refresh"><option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option></select></label>
      <button v-if="ledger" class="ghost" @click="refresh">刷新</button>
    </section>
    <section v-if="token && !projects.length" class="connect" aria-label="登记项目">
      <label>项目 ID <input id="new-project-id" v-model="newProjectId" placeholder="已在 Hub 授权范围内的 ID" /></label>
      <label>项目名称 <input id="new-project-name" v-model="newProjectName" placeholder="显示名称" /></label>
      <button :disabled="!newProjectId.trim() || !newProjectName.trim()" @click="registerProject">登记项目</button>
    </section>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <main v-if="ledger" class="workspace">
      <section class="panel intake"><p class="eyebrow">01 / 需求输入</p><h2>下一件要完成的事</h2>
        <textarea id="demand-text" v-model="demand" @input="requestId = ''; selectedTask = ''" rows="5" placeholder="保留原始需求，不需要填写 Task ID"></textarea>
        <div v-if="matches.length > 1" class="choices"><p>匹配到多个任务，请明确选择：</p>
          <label v-for="task in matches" :key="task.id"><input v-model="selectedTask" type="radio" :value="task.id" />{{ task.title }}</label>
        </div>
        <p v-else-if="matches.length === 1" class="hint">将关联到已有任务：{{ matches[0].title }}</p>
        <p v-else-if="demand.trim()" class="hint">未匹配已有任务，将建立新任务。</p>
        <button :disabled="busy || !demand.trim() || (matches.length > 1 && !selectedTask)" @click="submit">提交原文需求</button>
      </section>
      <section class="panel"><p class="eyebrow">02 / 任务与原始需求</p><h2>待完成需求 <span>{{ active.length }}</span></h2>
        <div v-if="!ledger.tasks.length" class="empty">暂无任务</div>
        <article v-for="task in ledger.tasks" :key="task.id" class="item"><div class="row"><strong>{{ task.title }}</strong><span class="badge">{{ task.status }}</span></div><p>{{ task.description }}</p>
          <button v-if="task.status === 'active' || task.status === 'testing'" class="ghost" :disabled="busy" @click="changeTask(task, 'pause')">暂停任务</button>
          <button v-if="task.status === 'paused'" class="ghost" :disabled="busy" @click="changeTask(task, 'resume')">恢复任务</button>
          <div v-for="r in ledger.requirements.filter(item => item.task_id === task.id)" :key="r.id" class="requirement">
            <span class="badge">{{ r.status }} · v{{ r.version }}</span><p>{{ r.text }}</p>
            <p v-if="r.summary" class="hint">完成摘要：{{ r.summary }}</p>
            <button v-if="r.status === 'active' && ['active','testing'].includes(task.status)" class="ghost" :disabled="busy" @click="archive(r)">确认归档</button>
          </div>
        </article>
      </section>
      <section class="panel"><p class="eyebrow">03 / 长期认知</p><h2>项目契约 <span>{{ contracts.length }}</span></h2>
        <div v-if="!contracts.length" class="empty">尚无已生效的长期规则</div>
        <article v-for="rule in contracts" :key="rule.id" class="item"><div class="row"><strong>{{ rule.title }}</strong><span class="badge priority">{{ rule.priority }}</span></div>
          <p v-for="(point, i) in rule.points" :key="i">{{ point }}</p>
          <p class="hint">作用域：{{ rule.patterns.join(' · ') }} · 效用均分：{{ rule.avg_score ?? '—' }} · 反馈 {{ rule.eval_count }}（已知 {{ rule.known_count }}）</p>
          <p v-if="rule.origin_rule_id" class="hint">来自 {{ rule.origin_rule_id }}@{{ rule.origin_version }}</p>
        </article>
      </section>
      <section class="panel"><p class="eyebrow">04 / 规则作用域密度</p><h2>模块约束视图</h2>
        <div v-if="!ledger.scope_density.length" class="empty">暂无活跃规则；未推断不存在的代码目录。</div>
        <article v-for="scope in ledger.scope_density" :key="scope.scope" class="item">
          <div class="row"><strong>{{ scope.scope }}</strong><span class="badge" :class="{ priority: scope.p0 }">P0 {{ scope.p0 }} · P1 {{ scope.p1 }} · P2 {{ scope.p2 }}</span></div>
          <p class="hint">长期 {{ scope.long_term }} · 当前任务 {{ scope.short_term }} · {{ scope.rule_ids.length }} 条规则</p>
        </article>
      </section>
      <section class="panel"><p class="eyebrow">05 / 契约人工审阅</p><h2>待决议建议 <span>{{ ledger.proposals.filter(item => item.status === 'pending').length }}</span></h2>
        <div v-if="!ledger.proposals.length" class="empty">暂无长期契约变更提案</div>
        <article v-for="proposal in ledger.proposals" :key="proposal.id" class="item">
          <div class="row"><strong>{{ proposal.title }}</strong><span class="badge">{{ proposal.status }}</span></div>
          <p>目标 {{ proposal.target_rule_id }}@{{ proposal.target_version }} · {{ proposal.reason }}</p>
          <p v-for="(point, i) in proposal.points" :key="i">{{ point }}</p>
          <p class="hint">范围：{{ proposal.patterns.join(' · ') }}</p>
          <p v-if="proposal.decision_reason" class="hint">审阅结论：{{ proposal.decision_reason }}</p>
          <template v-if="proposal.status === 'pending'"><button :disabled="busy" @click="review(proposal, true)">批准变更</button> <button class="ghost" :disabled="busy" @click="review(proposal, false)">拒绝</button></template>
        </article>
      </section>
      <section class="panel"><p class="eyebrow">06 / 工作区身份</p><h2>已登记 Worktree <span>{{ ledger.worktrees.length }}</span></h2>
        <div v-if="!ledger.worktrees.length" class="empty">尚无 Agent 工作区会话；不模拟在线状态。</div>
        <article v-for="worktree in ledger.worktrees" :key="worktree.id" class="item">
          <div class="row"><strong>{{ worktree.machine_name }}</strong><span class="badge">{{ worktree.platform }}</span></div>
          <p>{{ worktree.workspace }}</p><p class="hint">分支：{{ worktree.git_branch || '未上报' }} · 身份：客户端声明</p>
        </article>
      </section>
      <section class="panel timeline"><p class="eyebrow">07 / 可追溯账本</p><h2>最近事件</h2>
        <div v-if="!ledger.events.length" class="empty">暂无事件</div>
        <article v-for="event in ledger.events" :key="event.sequence" class="event"><span>{{ event.action }}</span><code>{{ event.entity_id }}</code><time>{{ event.created_at }}</time></article>
      </section>
    </main>
    <div v-else class="standby">输入凭据连接 Hub，开始查看实际项目数据。</div>
  </div>
</template>
