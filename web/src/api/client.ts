import type {
  Project, Ledger, ScopeTreeResponse, InspectResponse, EventsResponse, TaskStatus,
  Topic, TopicPage, RulePriority, Rule
} from '../types/ledger'

export class ApiError extends Error {
  status: number
  statusText: string
  detail: unknown
  isNetworkError: boolean

  constructor(message: string, status = 0, statusText = '', detail: unknown = null, isNetworkError = false) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.statusText = statusText
    this.detail = detail
    this.isNetworkError = isNetworkError
  }
}

export async function requestApi<T>(path: string, method = 'GET', body?: object, signal?: AbortSignal): Promise<T> {
  let response: Response
  try {
    response = await fetch('/api' + path, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal,
    })
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw err
    }
    const msg = err instanceof Error ? err.message : String(err)
    throw new ApiError(`网络连接失败: ${msg}`, 0, '', null, true)
  }

  const contentType = response.headers.get('content-type') || ''
  const isJson = contentType.includes('application/json')

  let rawText = ''
  try {
    rawText = await response.text()
  } catch (err: unknown) {
    throw new ApiError(`读取响应失败 (${response.status})`, response.status, response.statusText)
  }

  let data: unknown = null
  if (rawText.trim() && isJson) {
    try {
      data = JSON.parse(rawText)
    } catch {
      data = null
    }
  }

  if (!response.ok) {
    let message = `请求失败 (${response.status})`
    if (data && typeof data === 'object') {
      const errObj = data as Record<string, unknown>
      if (typeof errObj.detail === 'string') {
        message = errObj.detail
      } else if (errObj.detail && typeof errObj.detail === 'object') {
        const detailRecord = errObj.detail as Record<string, unknown>
        message = (detailRecord.message as string) || (detailRecord.error as string) || JSON.stringify(errObj.detail)
      } else if (typeof errObj.message === 'string') {
        message = errObj.message
      }
    } else if (rawText.trim()) {
      // Plain text or HTML error
      if (rawText.includes('<html') || rawText.includes('<!DOCTYPE')) {
        message = `服务器错误 (${response.status}): ${response.statusText || '内部异常'}`
      } else {
        message = rawText.trim().slice(0, 300)
      }
    }
    throw new ApiError(message, response.status, response.statusText, data)
  }

  if (!rawText.trim()) {
    return null as T
  }

  if (isJson && data !== null) {
    return data as T
  }

  return rawText as unknown as T
}

export function buildProjectPath(projectId: string, subPath: string): string {
  return `/projects/${encodeURIComponent(projectId)}/${subPath}`
}

export const apiService = {
  getProjects: (signal?: AbortSignal) =>
    requestApi<Project[]>('/projects', 'GET', undefined, signal),

  createProject: (id: string, name: string) =>
    requestApi<Project>('/projects', 'POST', { id, name }),

  deleteProject: (id: string) =>
    requestApi<{ deleted: boolean; id: string }>(`/projects/${encodeURIComponent(id)}`, 'DELETE'),

  getLedger: (projectId: string, signal?: AbortSignal) =>
    requestApi<Ledger>(buildProjectPath(projectId, 'ledger'), 'GET', undefined, signal),

  getScopeTree: (projectId: string, worktreeId?: string | null, signal?: AbortSignal) => {
    const query = worktreeId ? `?worktree_id=${encodeURIComponent(worktreeId)}` : ''
    return requestApi<ScopeTreeResponse>(buildProjectPath(projectId, `tree${query}`), 'GET', undefined, signal)
  },

  inspectPath: (projectId: string, path: string, priorities: RulePriority[], taskId?: string | null, signal?: AbortSignal) => {
    let query = `?path=${encodeURIComponent(path)}` + priorities.map(p => `&priorities=${encodeURIComponent(p)}`).join('')
    if (taskId) {
      query += `&task_id=${encodeURIComponent(taskId)}`
    }
    return requestApi<InspectResponse>(buildProjectPath(projectId, `inspect${query}`), 'GET', undefined, signal)
  },

  getEvents: (projectId: string, limit = 100, before?: number | null, signal?: AbortSignal) => {
    let query = `?limit=${limit}`
    if (before) {
      query += `&before=${before}`
    }
    return requestApi<EventsResponse>(buildProjectPath(projectId, `events${query}`), 'GET', undefined, signal)
  },

  submitRequirement: (projectId: string, payload: { text: string; request_id: string; task_id?: string; title?: string }) =>
    requestApi(buildProjectPath(projectId, 'requirements'), 'POST', payload),

  archiveRequirement: (projectId: string, taskId: string, requirementId: string, expectedVersion: number, summary: string) =>
    requestApi(
      buildProjectPath(projectId, `tasks/${encodeURIComponent(taskId)}/requirements/${encodeURIComponent(requirementId)}/archive`),
      'POST',
      { expected_version: expectedVersion, summary },
    ),

  reopenRequirement: (projectId: string, taskId: string, requirementId: string, expectedVersion: number, reason: string) =>
    requestApi(
      buildProjectPath(projectId, `tasks/${encodeURIComponent(taskId)}/requirements/${encodeURIComponent(requirementId)}/reopen`),
      'POST',
      { expected_version: expectedVersion, reason },
    ),

  pauseTask: (projectId: string, taskId: string, expectedRevision: number, reason: string) =>
    requestApi(buildProjectPath(projectId, `tasks/${encodeURIComponent(taskId)}/pause`), 'POST', {
      expected_revision: expectedRevision,
      reason,
    }),

  resumeTask: (projectId: string, taskId: string, expectedRevision: number, reason: string) =>
    requestApi(buildProjectPath(projectId, `tasks/${encodeURIComponent(taskId)}/resume`), 'POST', {
      expected_revision: expectedRevision,
      reason,
    }),

  transitionTask: (projectId: string, taskId: string, expectedRevision: number, status: TaskStatus, reason: string) =>
    requestApi(buildProjectPath(projectId, `tasks/${encodeURIComponent(taskId)}/transition`), 'POST', {
      expected_revision: expectedRevision,
      status,
      reason,
    }),

  getTopics: (projectId: string, query = '', includeDeleted = false, cursor?: string | null, signal?: AbortSignal) => {
    const params = new URLSearchParams({ query, include_deleted: String(includeDeleted) })
    if (cursor) params.set('cursor', cursor)
    return requestApi<TopicPage>(buildProjectPath(projectId, `topics?${params}`), 'GET', undefined, signal)
  },

  getTopic: (projectId: string, key: string) =>
    requestApi<Topic>(buildProjectPath(projectId, `topics/${encodeURIComponent(key)}?include_usage=true`)),

  createTopic: (projectId: string, payload: { key: string; name: string; description: string; reason: string }) =>
    requestApi<Topic>(buildProjectPath(projectId, 'topics'), 'POST', payload),

  updateTopic: (projectId: string, key: string, payload: { expected_version: number; name: string; description?: string; reason: string }) =>
    requestApi<Topic>(buildProjectPath(projectId, `topics/${encodeURIComponent(key)}`), 'PATCH', payload),

  deleteTopic: (projectId: string, key: string, expectedVersion: number, reason: string) =>
    requestApi<Topic>(buildProjectPath(projectId, `topics/${encodeURIComponent(key)}`), 'DELETE', { expected_version: expectedVersion, reason }),

  enableTopics: (projectId: string, expectedRevision: number, reason: string) =>
    requestApi(buildProjectPath(projectId, 'topics/enable'), 'POST', { expected_revision: expectedRevision, reason }),

  reviewTaskRule: (projectId: string, rule: Rule, approve: boolean, reason: string) =>
    requestApi(buildProjectPath(projectId, `rules/${encodeURIComponent(rule.id)}/review`), 'POST', { expected_version: rule.version, approve, reason }),

  classifyLegacyRule: (projectId: string, rule: Rule, payload: { topics: string[]; patterns: string[]; priority: RulePriority; is_global: boolean; priority_reason: string; reason: string }) =>
    requestApi(buildProjectPath(projectId, `rules/${encodeURIComponent(rule.id)}/classify`), 'POST', { ...payload, expected_version: rule.version }),

  updateFinding: (projectId: string, id: string, expectedVersion: number, topics: string[], resolve: boolean, reason: string) =>
    requestApi(buildProjectPath(projectId, `findings/${encodeURIComponent(id)}`), 'PATCH', { expected_version: expectedVersion, topics, resolve, reason }),

  reviewProposal: (projectId: string, proposalId: string, approve: boolean, reason: string) =>
    requestApi(buildProjectPath(projectId, `proposals/${encodeURIComponent(proposalId)}/review`), 'POST', {
      approve,
      reason,
    }),
}
