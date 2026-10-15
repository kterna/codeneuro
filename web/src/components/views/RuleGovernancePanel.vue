<script setup lang="ts">
import { ref, watch } from 'vue'
import { apiService } from '../../api/client'
import type { Rule, RulePriority } from '../../types/ledger'

const props = defineProps<{ projectId: string; rule: Rule }>()
const emit = defineEmits<{ (e: 'refresh'): void }>()
const topics = ref('')
const patterns = ref('')
const priority = ref<RulePriority>('P1')
const isGlobal = ref(false)
const priorityReason = ref('')
const reason = ref('')
const busy = ref(false)
const error = ref('')
watch(() => props.rule, rule => {
  topics.value = rule.topics.join(', ')
  patterns.value = rule.patterns.join('\n')
  priority.value = rule.priority
  isGlobal.value = rule.is_global
  priorityReason.value = rule.priority_reason
  reason.value = error.value = ''
}, { immediate: true })
async function submit(approve: boolean) {
  if (!reason.value.trim()) { error.value = '请填写审阅依据与理由。'; return }
  busy.value = true
  error.value = ''
  try {
    if (!props.rule.validation_spec) {
      await apiService.classifyLegacyRule(props.projectId, props.rule, {
        topics: topics.value.split(',').map(s => s.trim()).filter(Boolean),
        patterns: patterns.value.split('\n').map(s => s.trim()).filter(Boolean),
        priority: priority.value, is_global: isGlobal.value,
        priority_reason: priorityReason.value, reason: reason.value,
      })
    } else {
      await apiService.reviewTaskRule(props.projectId, props.rule, approve, reason.value)
    }
    emit('refresh')
  } catch (e) { error.value = e instanceof Error ? e.message : String(e) }
  finally { busy.value = false }
}
</script>

<template>
  <section class="governance-panel">
    <h4>规则成立依据</h4>
    <pre v-if="rule.validation_spec">{{ JSON.stringify(rule.validation_spec, null, 2) }}</pre>
    <p v-if="rule.priority_reason">优先级依据：{{ rule.priority_reason }}</p>
    <template v-if="!rule.validation_spec && ['active', 'draft'].includes(rule.status)">
      <p class="caption">存量分类审阅：确认本规则作为规范的依据与适用范围，不代表已经运行测试。可测试的新主张应由 Agent 建立验证候选。</p>
      <label>已登记主题 key（逗号分隔）<input v-model="topics" :disabled="busy" /></label>
      <label>真实检索路径（每行一个，可留空）<textarea v-model="patterns" :disabled="busy" /></label>
      <label>优先级<select v-model="priority" :disabled="busy"><option v-for="p in ['P0', 'P1', 'P2', 'P3']" :key="p">{{ p }}</option></select></label>
      <label><input v-model="isGlobal" type="checkbox" :disabled="busy" />明确适用于项目所有操作（不是“重要”的同义词）</label>
      <label v-if="priority === 'P0'">P0 损害与适用边界<textarea v-model="priorityReason" :disabled="busy" /></label>
    </template>
    <template v-if="(!rule.validation_spec && ['active', 'draft'].includes(rule.status)) || (rule.status === 'draft' && rule.validation_spec?.kind === 'review')">
      <label>规范依据与审阅理由<textarea v-model="reason" :disabled="busy" /></label>
      <button type="button" :disabled="busy" @click="submit(true)">{{ rule.validation_spec ? '批准该版本规范' : '确认存量分类与规范依据' }}</button>
      <button v-if="rule.validation_spec" type="button" :disabled="busy" @click="submit(false)">记录不批准意见</button>
    </template>
    <p v-else-if="rule.validation_spec?.kind === 'test'" class="caption">由宿主上报真实测试项，再关联验证计划；界面审批不能替代测试。</p>
    <p v-if="error" class="error-box" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.governance-panel { display: flex; flex-direction: column; gap: 10px; }
label { display: flex; flex-direction: column; gap: 4px; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; }
</style>
