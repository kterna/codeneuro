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

export type RulePriority = 'P0' | 'P1' | 'P2'
export type RuleCategory = 'business' | 'security' | 'gotcha'
export type RuleStatus = 'draft' | 'active' | 'revoked' | 'deprecated'

export type RuleSnapshot = {
  rule_id?: string
  version: number
  title: string
  points: string[]
  patterns: string[]
  priority: RulePriority
  category: RuleCategory
  status: RuleStatus
}

export type Rule = {
  id: string
  title: string
  points: string[]
  patterns: string[]
  priority: RulePriority
  category?: RuleCategory
  task_id: string | null
  status: RuleStatus
  version?: number
  origin_rule_id: string | null
  origin_version: number | null
  delivery_count?: number
  eval_count: number
  known_count: number
  avg_score: number | null
}

export type Worktree = {
  id: string
  actor_id?: string
  machine_name: string
  platform: string
  workspace: string
  git_branch: string
}

export type ProposalStatus = 'pending' | 'approved' | 'rejected'

export type Proposal = {
  id: string
  target_rule_id: string
  target_version: number
  title: string
  points: string[]
  patterns: string[]
  priority?: RulePriority
  category?: RuleCategory
  reason: string
  status: ProposalStatus
  decision_reason: string | null
  reviewer_id?: string | null
  target_snapshot?: RuleSnapshot | null
  current_target_version?: number | null
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
  actor?: string
  action: string
  entity_id: string
  details?: Record<string, unknown>
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

export type ScopeTreeNode = {
  path: string
  is_dir: boolean
  rule_ids: string[]
}

export type ScopeTreeResponse = {
  source: string
  workspace: string | null
  worktree_id: string | null
  tree: ScopeTreeNode[]
}

export type InspectResponse = {
  path: string
  task_id: string | null
  rule_ids: string[]
  source: string
  preview: boolean
}

export type EventsResponse = {
  items: AuditEvent[]
  next_cursor: number | null
}

export type Ledger = {
  project_id?: string
  tasks: Task[]
  worktrees: Worktree[]
  requirements: Requirement[]
  rules: Rule[]
  proposals: Proposal[]
  findings?: Finding[]
  scope_density: ScopeDensity[]
  events: AuditEvent[]
  events_next_cursor?: number | null
}

export type TabId = 'explorer' | 'tasks' | 'rules' | 'review' | 'feedback' | 'activity' | 'settings'

export type TabItem = {
  id: TabId
  icon: string
  title: string
  subtitle: string
}
