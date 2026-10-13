import { ref } from 'vue'

export type ThemeMode = 'dark' | 'light' | 'auto'

const THEME_KEY = 'codeneuro-theme'

const currentTheme = ref<ThemeMode>(
  (localStorage.getItem(THEME_KEY) as ThemeMode) || 'dark'
)

function resolveTheme(mode: ThemeMode): 'dark' | 'light' {
  if (mode === 'auto') {
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches
      ? 'dark'
      : 'light'
  }
  return mode
}

export function useTheme() {
  function applyTheme(mode: ThemeMode) {
    currentTheme.value = mode
    localStorage.setItem(THEME_KEY, mode)
    const resolved = resolveTheme(mode)
    document.documentElement.setAttribute('data-theme', resolved)
  }

  function initTheme() {
    applyTheme(currentTheme.value)
  }

  return {
    theme: currentTheme,
    setTheme: applyTheme,
    initTheme,
  }
}
