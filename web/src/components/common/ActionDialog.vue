<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  title: string
  busy: boolean
  errorText: string
  isProjectModal: boolean
}>()

const emit = defineEmits<{
  (e: 'submit', data: { projectId?: string; projectName?: string; reason?: string }): void
}>()

const dialogRef = ref<HTMLDialogElement | null>(null)
const inputProjectId = ref('')
const inputProjectName = ref('')
const inputReason = ref('')

function open(initialReason = '') {
  inputProjectId.value = ''
  inputProjectName.value = ''
  inputReason.value = initialReason
  dialogRef.value?.showModal()
}

function close() {
  dialogRef.value?.close()
}

function handleSubmit() {
  if (props.isProjectModal) {
    emit('submit', {
      projectId: inputProjectId.value.trim(),
      projectName: inputProjectName.value.trim(),
    })
  } else {
    emit('submit', {
      reason: inputReason.value.trim(),
    })
  }
}

defineExpose({
  open,
  close,
})
</script>

<template>
  <dialog ref="dialogRef" id="editor">
    <form @submit.prevent="handleSubmit">
      <div class="dialog-head">
        <h2>{{ title }}</h2>
        <button type="button" aria-label="关闭窗口" @click="close">×</button>
      </div>

      <template v-if="isProjectModal">
        <label class="field">
          项目标识 (ID)
          <input
            id="new-project-id"
            v-model="inputProjectId"
            required
            maxlength="128"
            placeholder="例如：codeneuro-hub"
          />
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
