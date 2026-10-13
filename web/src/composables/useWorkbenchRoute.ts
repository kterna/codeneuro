import { ref, onMounted, onUnmounted } from 'vue'
import type { TabId, TabItem } from '../types/ledger'

export function useWorkbenchRoute(
  tabs: readonly TabItem[],
  onRouteMatch?: (projId: string, tabId?: TabId) => void
) {
  const tab = ref<TabId>('explorer')

  function parseLocationFromUrl(): { projId?: string; tabId?: TabId } {
    const hash = window.location.hash.replace(/^#\/?/, '')
    const parts = hash.split('/')
    let projId: string | undefined
    let tabId: TabId | undefined

    if (parts[0] === 'projects' && parts[1]) {
      projId = decodeURIComponent(parts[1])
      if (parts[2] && tabs.some(t => t.id === parts[2])) {
        tabId = parts[2] as TabId
      }
    } else if (parts[0] && parts[0] !== 'projects') {
      if (tabs.some(t => t.id === parts[0])) {
        tabId = parts[0] as TabId
      } else {
        projId = decodeURIComponent(parts[0])
        if (parts[1] && tabs.some(t => t.id === parts[1])) {
          tabId = parts[1] as TabId
        }
      }
    }
    return { projId, tabId }
  }

  function syncUrl(projectId: string, push = false) {
    if (!projectId) return
    const newHash = `#/projects/${encodeURIComponent(projectId)}/${tab.value}`
    if (window.location.hash !== newHash) {
      if (push) {
        window.history.pushState(null, '', newHash)
      } else {
        window.history.replaceState(null, '', newHash)
      }
    }
  }

  function handleHashChange() {
    const { projId, tabId: parsedTabId } = parseLocationFromUrl()
    if (parsedTabId) {
      tab.value = parsedTabId
    }
    if (projId && onRouteMatch) {
      onRouteMatch(projId, parsedTabId)
    }
  }

  onMounted(() => {
    window.addEventListener('hashchange', handleHashChange)
  })

  onUnmounted(() => {
    window.removeEventListener('hashchange', handleHashChange)
  })

  return {
    tab,
    parseLocationFromUrl,
    syncUrl,
  }
}
