import type { Project, Ledger } from '../types/ledger'

export async function requestApi<T>(path: string, method = 'GET', body?: object): Promise<T> {
  const response = await fetch('/api' + path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  const data: unknown = await response.json()
  if (!response.ok) {
    const detail = (data as { detail?: { message?: string } | string }).detail
    throw new Error(typeof detail === 'string' ? detail : detail?.message || `请求失败 (${response.status})`)
  }
  return data as T
}

export function buildProjectPath(projectId: string, subPath: string): string {
  return `/projects/${encodeURIComponent(projectId)}/${subPath}`
}

export const apiService = {
  getProjects: () => requestApi<Project[]>('/projects'),

  createProject: (id: string, name: string) =>
    requestApi<Project>('/projects', 'POST', { id, name }),

  getLedger: (projectId: string) =>
    requestApi<Ledger>(buildProjectPath(projectId, 'ledger')),

  submitRequirement: (projectId: string, payload: { text: string; request_id: string; task_id?: string; title?: string }) =>
    requestApi(buildProjectPath(projectId, 'requirements'), 'POST', payload),

  archiveRequirement: (projectId: string, taskId: string, requirementId: string, expectedVersion: number, summary: string) =>
    requestApi(
      buildProjectPath(projectId, `tasks/${encodeURIComponent(taskId)}/requirements/${encodeURIComponent(requirementId)}/archive`),
      'POST',
      { expected_version: expectedVersion, summary },
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

  reviewProposal: (projectId: string, proposalId: string, approve: boolean, reason: string) =>
    requestApi(buildProjectPath(projectId, `proposals/${encodeURIComponent(proposalId)}/review`), 'POST', {
      approve,
      reason,
    }),
}
