export type Project = {
  id: string
  name: string
}

export type TaskStatus = 'draft' | 'active' | 'paused' | 'testing' | 'completed'
export type RequirementStatus = 'draft' | 'active' | 'accepting' | 'completed'
export type Page<T> = { items: T[]; next_cursor: string | null }
export type VersionPage<T> = { items: T[]; next_cursor: number | null }

export type Task = {
  id: string
  project_id: string
  requirement_id: string
  title: string
  description: string
  acceptance_criteria: string
  status: TaskStatus
  version: number
  paused_from: 'active' | 'testing' | null
  verification_summary: string | null
  verification_report_ids: string[]
  archived_at: string | null
  deleted_at: string | null
}

export type Requirement = {
  id: string
  project_id: string
  title: string
  original_text: string
  text: string
  acceptance_criteria: string
  status: RequirementStatus
  version: number
  completion_summary: string | null
  archived_at: string | null
  deleted_at: string | null
  progress: { total: number; completed: number }
}
export type TaskSummary = Pick<Task, 'id' | 'project_id' | 'requirement_id' | 'title' | 'description' | 'status' | 'version' | 'archived_at'> & { truncated: boolean }
export type RequirementSummary = Pick<Requirement, 'id' | 'project_id' | 'title' | 'text' | 'status' | 'version' | 'archived_at' | 'progress'> & { truncated: boolean }
export type ResourceCounts = { total: number; working: number; completed: number; archived: number }

export type RulePriority = 'P0' | 'P1' | 'P2' | 'P3'
export type ValidationSpec =
  | { kind: 'review'; basis: string }
  | { kind: 'test'; checks: { id: string; clause_indexes: number[]; test_ids: string[] }[] }

export type Topic = {
  project_id: string
  key: string
  name: string
  description: string
  version: number
  status: 'active' | 'deleted'
  definition_locked: boolean
  can_delete?: boolean
  blocking_references?: Record<string, number>
}

export type TopicPage = {
  taxonomy_revision: number
  topic_query_enabled: boolean
  items: Topic[]
  next_cursor: string | null
}
export type RuleStatus = 'draft' | 'active' | 'revoked' | 'deprecated'

export type RuleSnapshot = {
  rule_id?: string
  version: number
  title: string
  points: string[]
  patterns: string[]
  priority: RulePriority
  topics: string[]
  is_global: boolean
  priority_reason: string
  validation_spec: ValidationSpec | null
  status: RuleStatus
  delivery_mode?: 'full' | 'card'
  applies_when?: string
}

export type Rule = {
  id: string
  title: string
  points: string[]
  patterns: string[]
  priority: RulePriority
  topics: string[]
  is_global: boolean
  priority_reason: string
  validation_spec: ValidationSpec | null
  task_id: string | null
  status: RuleStatus
  version: number
  delivery_mode: 'full' | 'card'
  applies_when: string
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
  topics: string[]
  is_global: boolean
  priority_reason: string
  validation_spec: ValidationSpec | null
  source_rule_id: string | null
  source_version: number | null
  delivery_mode: 'full' | 'card'
  applies_when: string
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
  p3: number
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
  target_path: string | null
  topics: string[]
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
  taxonomy: { taxonomy_revision: number; topic_query_enabled: boolean }
  topics: Topic[]
  topic_coverage: { rules: string[]; findings: string[] }
  tasks: TaskSummary[]
  tasks_next_cursor: string | null
  counts: { tasks: ResourceCounts; requirements: ResourceCounts }
  worktrees: Worktree[]
  requirements: RequirementSummary[]
  requirements_next_cursor: string | null
  rules: Rule[]
  proposals: Proposal[]
  findings?: Finding[]
  scope_density: ScopeDensity[]
  events: AuditEvent[]
  events_next_cursor?: number | null
}

export type TabId = 'overview' | 'tasks' | 'rules' | 'explorer' | 'review' | 'feedback' | 'activity' | 'settings'

export type TabItem = {
  id: TabId
  icon: string
  title: string
  subtitle: string
}
