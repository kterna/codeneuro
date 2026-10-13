<script setup lang="ts">
import { ref, nextTick } from 'vue'
import type { TaskStatus } from '../../types/ledger'

const props = withDefaults(defineProps<{
  title: string
  busy: boolean
  errorText: string
  isProjectModal?: boolean
  isTransitionModal?: boolean
  availableStatuses?: TaskStatus[]
}>(), {
  isProjectModal: false,
  isTransitionModal: false,
  availableStatuses: () => [],
})

const emit = defineEmits<{
  (e: 'submit', data: { projectId?: string; projectName?: string; reason?: string; targetStatus?: TaskStatus }): void
}>()

const dialogRef = ref<HTMLDialogElement | null>(null)
const inputProjectId = ref('')
const inputProjectName = ref('')
const inputReason = ref('')
const selectedStatus = ref<TaskStatus>('active')
let previousActiveElement: HTMLElement | null = null
let parentDialogEl: HTMLElement | null = null
let openFocusTimer: ReturnType<typeof setTimeout> | null = null

function open(initialReason = '', defaultStatus: TaskStatus = 'active') {
  if (openFocusTimer) {
    clearTimeout(openFocusTimer)
    openFocusTimer = null
  }
  const activeEl = document.activeElement as HTMLElement | null
  previousActiveElement = activeEl
  parentDialogEl = activeEl ? (activeEl.closest('[role="dialog"], dialog') as HTMLElement | null) : null

  inputProjectId.value = ''
  inputProjectName.value = ''
  inputReason.value = initialReason
  selectedStatus.value = defaultStatus
  dialogRef.value?.showModal()

  // Focus the first input, tracking timer so close can invalidate it
  openFocusTimer = setTimeout(() => {
    openFocusTimer = null
    if (!dialogRef.value?.open) return
    const el = dialogRef.value?.querySelector('input:not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled])') as HTMLElement | null
    el?.focus()
  }, 50)
}

function close() {
  if (openFocusTimer) {
    clearTimeout(openFocusTimer)
    openFocusTimer = null
  }
  dialogRef.value?.close()

  nextTick(() => {
    const isConnected = previousActiveElement && document.body.contains(previousActiveElement)
    const isDisabled = previousActiveElement
      ? ((previousActiveElement as any).disabled || previousActiveElement.getAttribute('aria-disabled') === 'true')
      : false

    if (isConnected && !isDisabled && typeof previousActiveElement?.focus === 'function') {
      previousActiveElement.focus()
    } else if (parentDialogEl && document.body.contains(parentDialogEl)) {
      const focusable = parentDialogEl.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [tabindex]:not([tabindex="-1"]):not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled])'
      )
      if (focusable.length && typeof focusable[0].focus === 'function') {
        focusable[0].focus()
      } else if (typeof parentDialogEl.focus === 'function') {
        parentDialogEl.focus()
      }
    }
  })
}

function handleSubmit() {
  if (props.isProjectModal) {
    emit('submit', {
      projectId: inputProjectId.value.trim(),
      projectName: inputProjectName.value.trim(),
    })
  } else if (props.isTransitionModal) {
    emit('submit', {
      reason: inputReason.value.trim(),
      targetStatus: selectedStatus.value,
    })
  } else {
    emit('submit', {
      reason: inputReason.value.trim(),
    })
  }
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    e.preventDefault()
    close()
  }
}

function statusDisplayName(st: TaskStatus): string {
  switch (st) {
    case 'draft': return '待开始'
    case 'active': return '进行中'
    case 'testing': return '待验证'
    case 'released': return '已发布'
    case 'archived': return '已归档'
    case 'paused': return '已暂停'
    default: return st
  }
}

defineExpose({
  open,
  close,
})
</script>

<template>
  <dialog
    ref="dialogRef"
    id="editor"
    aria-labelledby="dialog-title"
    role="dialog"
    aria-modal="true"
    @keydown="handleKeydown"
  >
    <form @submit.prevent="handleSubmit">
      <div class="dialog-head">
        <h2 id="dialog-title">{{ title }}</h2>
        <button type="button" aria-label="关闭窗口" @click="close">×</button>
      </div>

      <template v-if="isProjectModal">
        <label class="field">
          项目标识
          <input
            id="new-project-id"
            v-model="inputProjectId"
            required
            maxlength="128"
            pattern="^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"
            title="只能以字母或数字开头，可包含字母、数字、下划线与短横线，长度 1-128"
            placeholder="例如：codeneuro-hub"
          />
          <small class="caption">以字母/数字开头，支持 _ 和 -，禁止包含空格或斜杠</small>
        </label>
        <label class="field">
          项目名称
          <input
            id="new-project-name"
            v-model="inputProjectName"
            required
            maxlength="500"
            placeholder="例如：CodeNeuro 核心工程服务"
          />
        </label>
      </template>

      <template v-else-if="isTransitionModal">
        <label class="field">
          目标状态
          <select v-model="selectedStatus" required>
            <option v-for="st in availableStatuses" :key="st" :value="st">
              {{ statusDisplayName(st) }}
            </option>
          </select>
        </label>
        <label class="field">
          流转说明与依据
          <textarea
            v-model="inputReason"
            required
            placeholder="请输入状态转换的原因或依据（例如：测试验证通过，准予发布上线）…"
          ></textarea>
        </label>
      </template>

      <template v-else>
        <label class="field">
          处理依据与说明
          <textarea
            v-model="inputReason"
            required
            placeholder="请输入具体的完成摘要、审阅结论或调整依据（例如：已通过集成测试验证）…"
          ></textarea>
        </label>
      </template>

      <div v-if="errorText" id="editor-error" role="alert">{{ errorText }}</div>

      <footer>
        <button type="button" @click="close">取消</button>
        <button type="submit" class="primary" :disabled="busy">保存</button>
      </footer>
    </form>
  </dialog>
</template>
