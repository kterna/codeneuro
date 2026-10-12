export type Project = {
  id: string
  name: string
}

export type TaskStatus = 'draft' | 'active' | 'paused' | 'testing' | 'released' | 'archived'

export type Task = {
  id: string
  title: string
  description: string
  status: TaskStatus
  revision: number
}

export type RequirementStatus = 'active' | 'archived'

export type Requirement = {
  id: string
  task_id: string
  text: string
  status: RequirementStatus
  version: number
  summary: string | null
}

export type Rule = {
  id: string
  title: string
  points: string[]
  patterns: string[]
  priority: 'P0' | 'P1' | 'P2' | string
  task_id: string | null
  status: 'active' | 'revoked' | string
  origin_rule_id: string | null
  origin_version: number | null
  eval_count: number
  known_count: number
  avg_score: number | null
}

export type Worktree = {
  id: string
  machine_name: string
  platform: string
  workspace: string
  git_branch: string
}

export type ProposalStatus = 'pending' | 'applied' | 'rejected' | string

export type Proposal = {
  id: string
  target_rule_id: string
  target_version: number
  title: string
  points: string[]
  patterns: string[]
  reason: string
  status: ProposalStatus
  decision_reason: string | null
}

export type ScopeDensity = {
  scope: string
  p0: number
  p1: number
  p2: number
  long_term: number
  short_term: number
  rule_ids: string[]
}

export type AuditEvent = {
  sequence: number
  action: string
  entity_id: string
  created_at: string
}

export type Finding = {
  id: string
  project_id: string
  task_id: string
  session_id: string
  target_path: string
  text: string
  priority: string
  version: number
  status: string
}

export type Ledger = {
  tasks: Task[]
  worktrees: Worktree[]
  requirements: Requirement[]
  rules: Rule[]
  proposals: Proposal[]
  findings?: Finding[]
  scope_density: ScopeDensity[]
  events: AuditEvent[]
}

export type TabId = 'explorer' | 'tasks' | 'rules' | 'review' | 'feedback' | 'activity' | 'settings'

export type TabItem = {
  id: TabId
  icon: string
  title: string
  subtitle: string
}
