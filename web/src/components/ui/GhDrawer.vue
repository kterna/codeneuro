<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    title?: string
    subtitle?: string
    width?: string
    ariaLabel?: string
    ariaLabelledby?: string
    overlayClass?: string
    contentClass?: string
    dataStatus?: string
  }>(),
  {
    modelValue: false,
    title: '',
    subtitle: '',
    width: 'min(580px, 94vw)',
    ariaLabel: '抽屉详情',
    ariaLabelledby: undefined,
    overlayClass: '',
    contentClass: '',
    dataStatus: undefined,
  }
)

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'close'): void
}>()

const drawerRef = ref<HTMLElement | null>(null)
const closeBtnRef = ref<HTMLButtonElement | null>(null)
let previousActiveElement: HTMLElement | null = null

function close() {
  emit('update:modelValue', false)
  emit('close')
}

function getFocusableElements(): HTMLElement[] {
  if (!drawerRef.value) return []
  return Array.from(
    drawerRef.value.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [tabindex]:not([tabindex="-1"]):not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled])'
    )
  )
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    e.preventDefault()
    close()
    return
  }

  if (e.key === 'Tab' && drawerRef.value) {
    const focusable = getFocusableElements()
    if (!focusable.length) {
      e.preventDefault()
      return
    }

    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    const active = document.activeElement as HTMLElement | null

    // 如果焦点在容器自身 (tabindex=-1) 或抽屉外部：
    if (!active || !drawerRef.value.contains(active) || active === drawerRef.value) {
      e.preventDefault()
      if (e.shiftKey) {
        last.focus()
      } else {
        first.focus()
      }
      return
    }

    if (e.shiftKey && active === first) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && active === last) {
      e.preventDefault()
      first.focus()
    }
  }
}

watch(
  () => props.modelValue,
  (val) => {
    if (val) {
      previousActiveElement = document.activeElement as HTMLElement | null
      nextTick(() => {
        if (!drawerRef.value) return
        // 优先聚焦自定义 header 中的关闭按钮或通用关闭按钮
        const preferredCloseBtn = drawerRef.value.querySelector<HTMLElement>(
          'button[aria-label="关闭窗口"], button[aria-label="关闭抽屉"], .close-btn'
        )
        if (preferredCloseBtn && typeof preferredCloseBtn.focus === 'function') {
          preferredCloseBtn.focus()
          return
        }

        const focusable = getFocusableElements()
        if (focusable.length && typeof focusable[0].focus === 'function') {
          focusable[0].focus()
        } else {
          drawerRef.value.focus()
        }
      })
    } else if (previousActiveElement && typeof previousActiveElement.focus === 'function') {
      previousActiveElement.focus()
      previousActiveElement = null
    }
  }
)

onMounted(() => {
  if (props.modelValue) {
    previousActiveElement = document.activeElement as HTMLElement | null
  }
})

onUnmounted(() => {
  if (previousActiveElement && typeof previousActiveElement.focus === 'function') {
    previousActiveElement.focus()
  }
})
</script>

<template>
  <Teleport to="body">
    <Transition name="drawer-fade">
      <div
        v-if="modelValue"
        class="gh-drawer-overlay"
        :class="overlayClass"
        role="dialog"
        aria-modal="true"
        :aria-label="ariaLabelledby ? undefined : ariaLabel"
        :aria-labelledby="ariaLabelledby"
        :data-status="dataStatus"
        @click.self="close"
        @keydown="handleKeydown"
      >
        <aside
          ref="drawerRef"
          class="gh-drawer-content"
          :class="contentClass"
          tabindex="-1"
          :style="{ width }"
        >
          <header class="drawer-header">
            <slot name="header">
              <div class="card-top" style="margin-bottom: 0">
                <div>
                  <h3 v-if="title" style="margin: 0; font-size: 15px">{{ title }}</h3>
                  <p v-if="subtitle" class="muted" style="margin: 4px 0 0; font-size: 11px">{{ subtitle }}</p>
                </div>
                <button
                  ref="closeBtnRef"
                  type="button"
                  class="subtle close-btn"
                  aria-label="关闭窗口"
                  @click="close"
                >✕</button>
              </div>
            </slot>
          </header>

          <main class="drawer-body">
            <slot />
          </main>

          <footer v-if="$slots.footer" class="drawer-footer">
            <slot name="footer">
              <button type="button" @click="close">关闭</button>
            </slot>
          </footer>
        </aside>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.gh-drawer-overlay {
  position: fixed;
  inset: 0;
  background: rgba(1, 4, 9, 0.65);
  backdrop-filter: blur(2px);
  z-index: 100;
  display: flex;
  justify-content: flex-end;
}

.gh-drawer-content {
  background: var(--gh-canvas-overlay);
  border-left: 1px solid var(--gh-border-default);
  height: 100vh;
  box-shadow: -8px 0 24px rgba(1, 4, 9, 0.6);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
  outline: none;
  animation: slideDrawer 0.18s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes slideDrawer {
  from { transform: translateX(100%); }
  to { transform: translateX(0); }
}

.drawer-fade-enter-active,
.drawer-fade-leave-active {
  transition: opacity 0.18s ease;
}

.drawer-fade-enter-from,
.drawer-fade-leave-to {
  opacity: 0;
}

.drawer-header {
  padding: 16px 20px;
  border-bottom: 1px solid var(--gh-border-default);
  background: var(--gh-canvas-subtle);
  flex-shrink: 0;
  margin-bottom: 0 !important;
  width: 100% !important;
  display: block;
}

.drawer-body {
  flex: 1;
  padding: 20px;
  overflow-y: auto;
  min-height: 0;
}

.drawer-footer {
  padding: 14px 20px;
  border-top: 1px solid var(--gh-border-default);
  background: var(--gh-canvas-subtle);
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  flex-shrink: 0;
}

.close-btn {
  font-size: 16px;
  padding: 4px 8px;
  cursor: pointer;
}
</style>
