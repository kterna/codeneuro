import { ref } from 'vue'
import type { Ledger, Project } from '../types/ledger'
import { apiService, ApiError } from '../api/client'

export function useLedgerData() {
  const projects = ref<Project[]>([])
  const projectId = ref('')
  const ledger = ref<Ledger | null>(null)
  const loading = ref(false)
  const busy = ref(false)
  const error = ref('')
  const notice = ref('')
  const connectionStatus = ref<'connecting' | 'connected' | 'disconnected'>('connecting')

  let projectEpoch = 0
  let actionSeq = 0
  const activeActionTokens = new Set<number>()

  let ledgerSeq = 0
  let ledgerAbortCtrl: AbortController | null = null

  function startAction() {
    const token = ++actionSeq
    activeActionTokens.add(token)
    busy.value = true
    return token
  }

  function finishAction(token: number, capturedProjectEpoch: number) {
    if (capturedProjectEpoch === projectEpoch) {
      activeActionTokens.delete(token)
      busy.value = activeActionTokens.size > 0
    }
  }

  function resetProjectContext() {
    projectEpoch++
    activeActionTokens.clear()
    busy.value = false
    error.value = ''
    notice.value = ''
  }

  function fail(cause: unknown) {
    const err = cause as Error
    error.value = err.message || String(cause)
    if (cause instanceof ApiError) {
      if (cause.isNetworkError || cause.status === 0 || cause.status >= 502) {
        connectionStatus.value = 'disconnected'
      } else {
        connectionStatus.value = 'connected'
      }
    } else {
      connectionStatus.value = 'disconnected'
    }
  }

  async function loadLedger(id: string, isBackground = false) {
    if (!id) return
    const thisSeq = ++ledgerSeq
    if (!isBackground) {
      loading.value = true
      error.value = ''
      ledger.value = null
    }

    if (ledgerAbortCtrl) {
      ledgerAbortCtrl.abort()
    }
    ledgerAbortCtrl = new AbortController()

    try {
      const data = await apiService.getLedger(id, ledgerAbortCtrl.signal)
      if (thisSeq === ledgerSeq) {
        ledger.value = data
        connectionStatus.value = 'connected'
      }
    } catch (cause: unknown) {
      if ((cause as { name?: string }).name === 'AbortError') return
      if (thisSeq === ledgerSeq) {
        fail(cause)
      }
    } finally {
      if (thisSeq === ledgerSeq && !isBackground) {
        loading.value = false
      }
    }
  }

  return {
    projects,
    projectId,
    ledger,
    loading,
    busy,
    error,
    notice,
    connectionStatus,
    getProjectEpoch: () => projectEpoch,
    startAction,
    finishAction,
    resetProjectContext,
    fail,
    loadLedger,
  }
}
