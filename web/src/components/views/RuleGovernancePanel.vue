<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { apiService } from '../../api/client'
import type { Rule, RulePriority } from '../../types/ledger'
import GhTag from '../ui/GhTag.vue'

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

const governanceBadge = computed(() => {
  if (props.rule.validation_spec) {
    if (props.rule.status === 'draft') {
      return {
        label: props.rule.validation_spec.kind === 'review' ? '规范审阅候选' : '测试验证候选',
        variant: 'purple' as const,
      }
    }
    if (props.rule.validation_spec.kind === 'review') {
      return {
        label: '规范审阅依据',
        variant: 'accent' as const,
      }
    } else {
      return {
        label: '测试验证计划',
        variant: 'purple' as const,
      }
    }
  }
  return {
    label: '存量规范治理',
    variant: 'neutral' as const,
  }
})

watch(() => props.rule, rule => {
  topics.value = rule.topics.join(', ')
  patterns.value = rule.patterns.join('\n')
  priority.value = rule.priority
  isGlobal.value = rule.is_global
  priorityReason.value = rule.priority_reason
  reason.value = error.value = ''
}, { immediate: true })

async function submit(approve: boolean) {
  if (!reason.value.trim()) {
    error.value = '请填写审阅依据与理由。'
    return
  }
  busy.value = true
  error.value = ''
  try {
    if (!props.rule.validation_spec) {
      await apiService.classifyLegacyRule(props.projectId, props.rule, {
        topics: topics.value.split(',').map(s => s.trim()).filter(Boolean),
        patterns: patterns.value.split('\n').map(s => s.trim()).filter(Boolean),
        priority: priority.value,
        is_global: isGlobal.value,
        priority_reason: priorityReason.value,
        reason: reason.value,
      })
    } else {
      await apiService.reviewTaskRule(props.projectId, props.rule, approve, reason.value)
    }
    emit('refresh')
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="governance-panel">
    <!-- 面板标题与类型标识 -->
    <div class="gov-header">
      <div class="gov-title-row">
        <h4 class="gov-title">规则成立依据与规范治理</h4>
        <GhTag :variant="governanceBadge.variant">
          {{ governanceBadge.label }}
        </GhTag>
      </div>
    </div>

    <!-- 验证规格展示 (如有结构化依据) -->
    <div v-if="rule.validation_spec" class="spec-container">
      <div class="spec-header">
        <span class="caption">验证规格 (Validation Spec)</span>
        <code class="spec-kind-tag">{{ rule.validation_spec.kind }}</code>
      </div>
      <pre class="spec-code-block">{{ JSON.stringify(rule.validation_spec, null, 2) }}</pre>
    </div>

    <!-- 优先级依据展示 (如有既定依据) -->
    <div v-if="rule.priority_reason" class="priority-reason-banner">
      <span class="priority-label">优先级依据：</span>
      <span class="priority-text">{{ rule.priority_reason }}</span>
    </div>

    <!-- 存量规范人工治理表单 -->
    <template v-if="!rule.validation_spec && ['active', 'draft'].includes(rule.status)">
      <div class="gov-notice-callout">
        <span class="notice-icon" aria-hidden="true">💡</span>
        <p class="caption notice-text">
          存量分类审阅：确认本规则作为规范的依据与适用范围，不代表已经运行测试。可测试的新主张应由 Agent 建立验证候选。
        </p>
      </div>

      <div class="gov-form-grid">
        <!-- 业务主题 -->
        <label class="gov-field-group">
          <span class="field-title">
            已登记主题 key（逗号分隔）
            <span class="field-help">必须是已登记的主题标识</span>
          </span>
          <input
            v-model="topics"
            :disabled="busy"
            placeholder="例如 frontend-layout, esign-ca"
            class="gh-input font-mono"
          />
        </label>

        <!-- 优先级选择 -->
        <label class="gov-field-group">
          <span class="field-title">优先级</span>
          <select v-model="priority" :disabled="busy" class="gh-select">
            <option v-for="p in ['P0', 'P1', 'P2', 'P3']" :key="p" :value="p">{{ p }}</option>
          </select>
        </label>

        <!-- 全局适用勾选 -->
        <div class="gov-field-group full-width">
          <label class="gov-checkbox-label">
            <input v-model="isGlobal" type="checkbox" :disabled="busy" />
            <span class="checkbox-text">明确适用于项目所有操作（不是“重要”的同义词）</span>
          </label>
        </div>

        <!-- 真实检索路径 -->
        <label class="gov-field-group full-width">
          <span class="field-title">
            真实检索路径（每行一个，可留空）
            <span class="field-help">匹配 glob 模式；若留空则代表按主题/全局召回</span>
          </span>
          <textarea
            v-model="patterns"
            :disabled="busy"
            rows="2"
            placeholder="例如：&#10;src/components/**&#10;web/views/*.vue"
            class="gh-textarea font-mono"
          />
        </label>

        <!-- P0 损害与适用边界 (仅当选择 P0 时展示) -->
        <label v-if="priority === 'P0'" class="gov-field-group full-width p0-alert-group">
          <span class="field-title p0-title">
            <span>P0 损害与适用边界</span>
            <span class="field-help-p0">必须阐明可能造成的严重不可逆资损或灾难性后果</span>
          </span>
          <textarea
            v-model="priorityReason"
            :disabled="busy"
            rows="2"
            placeholder="详述本规则违反时引发的不可逆生产资损、安全合规红线或系统瘫痪边界…"
            class="gh-textarea p0-textarea"
          />
        </label>
      </div>
    </template>

    <!-- 审阅理由与操作提交 -->
    <template v-if="(!rule.validation_spec && ['active', 'draft'].includes(rule.status)) || (rule.status === 'draft' && rule.validation_spec?.kind === 'review')">
      <div class="gov-review-submit-section">
        <label class="gov-field-group full-width">
          <span class="field-title">
            规范依据与审阅理由
            <span class="field-required">* 必须登记人工审阅判定依据</span>
          </span>
          <textarea
            v-model="reason"
            :disabled="busy"
            rows="2"
            placeholder="说明确认该规范生效的背景、人类决策依据或事实核验记录…"
            class="gh-textarea"
          />
        </label>

        <div class="gov-actions-toolbar">
          <button
            type="button"
            class="primary btn-submit-gov"
            :disabled="busy"
            @click="submit(true)"
          >{{ rule.validation_spec ? '批准该版本规范' : '确认存量分类与规范依据' }}</button>

          <button
            v-if="rule.validation_spec"
            type="button"
            class="danger btn-reject-gov"
            :disabled="busy"
            @click="submit(false)"
          >记录不批准意见</button>
        </div>
      </div>
    </template>

    <div v-else-if="rule.validation_spec?.kind === 'test'" class="test-kind-callout">
      <span class="callout-icon" aria-hidden="true">🧪</span>
      <p class="caption callout-text">由宿主上报真实测试项，再关联验证计划；界面审批不能替代测试。</p>
    </div>

    <!-- 错误反馈提示 -->
    <p v-if="error" class="error-box" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.governance-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
  background: var(--gh-canvas-subtle);
  border: 1px solid var(--gh-border-default);
  border-radius: 6px;
  padding: 16px;
}

.gov-header {
  border-bottom: 1px solid var(--gh-border-muted);
  padding-bottom: 10px;
}

.gov-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
}

.gov-title {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--gh-fg-default);
}

/* 规格代码卡片 */
.spec-container {
  background: var(--gh-canvas-inset);
  border: 1px solid var(--gh-border-default);
  border-radius: 6px;
  overflow: hidden;
}

.spec-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 12px;
  background: var(--gh-canvas-subtle);
  border-bottom: 1px solid var(--gh-border-muted);
}

.spec-kind-tag {
  font-size: 11px;
  color: var(--gh-accent-fg);
  font-family: var(--font-mono);
}

.spec-code-block {
  margin: 0;
  padding: 10px 12px;
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.45;
  color: var(--gh-fg-default);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  max-height: 180px;
  overflow-y: auto;
}

/* 优先级依据条 */
.priority-reason-banner {
  background: var(--gh-attention-subtle);
  border: 1px solid rgba(187, 128, 9, 0.35);
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 12px;
  color: var(--gh-attention-fg);
  display: flex;
  gap: 6px;
}

.priority-label {
  font-weight: 600;
  flex-shrink: 0;
}

.priority-text {
  word-break: break-word;
}

/* 存量治理提示 */
.gov-notice-callout {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  background: var(--gh-canvas-inset);
  border: 1px solid var(--gh-border-muted);
  border-radius: 6px;
  padding: 8px 12px;
}

.notice-icon {
  font-size: 14px;
  line-height: 1.4;
}

.notice-text {
  margin: 0;
  font-size: 11px;
  color: var(--gh-fg-muted);
  line-height: 1.45;
}

/* 表单布局 */
.gov-form-grid {
  display: grid;
  grid-template-columns: 1fr 140px;
  gap: 12px;
}

.gov-field-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.gov-field-group.full-width {
  grid-column: 1 / -1;
}

.field-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--gh-fg-default);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.field-help {
  font-size: 11px;
  font-weight: normal;
  color: var(--gh-fg-muted);
}

.field-required {
  font-size: 11px;
  font-weight: normal;
  color: var(--gh-danger-fg);
}

.gov-checkbox-label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--gh-fg-default);
  cursor: pointer;
  user-select: none;
}

.checkbox-text {
  line-height: 1.4;
}

/* P0 危险警告 */
.p0-alert-group {
  background: var(--gh-danger-subtle);
  border: 1px solid rgba(248, 81, 73, 0.4);
  border-radius: 6px;
  padding: 10px 12px;
}

.p0-title {
  color: var(--gh-danger-fg);
}

.field-help-p0 {
  font-size: 11px;
  font-weight: normal;
  color: var(--gh-danger-fg);
  opacity: 0.9;
}

.p0-textarea {
  border-color: rgba(248, 81, 73, 0.5) !important;
}

/* 审阅操作区 */
.gov-review-submit-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
  border-top: 1px solid var(--gh-border-muted);
  padding-top: 12px;
}

.gov-actions-toolbar {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

.test-kind-callout {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--gh-canvas-inset);
  border: 1px solid var(--gh-border-muted);
  border-radius: 6px;
}

.callout-icon {
  font-size: 14px;
}

.callout-text {
  margin: 0;
  font-size: 11px;
  color: var(--gh-fg-muted);
}

.font-mono {
  font-family: var(--font-mono);
}
</style>
