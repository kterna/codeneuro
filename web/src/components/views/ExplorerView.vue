<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Ledger } from '../../types/ledger'

const props = defineProps<{
  ledger: Ledger
}>()

const selectedScope = ref(props.ledger.scope_density[0]?.scope || '')

const activeScopeRules = computed(() => {
  if (!selectedScope.value) return []
  const targetScope = props.ledger.scope_density.find(s => s.scope === selectedScope.value)
  if (!targetScope) return []
  return props.ledger.rules.filter(r => targetScope.rule_ids.includes(r.id))
})
</script>

<template>
  <div>
    <div class="section-head">
      <h2>规则作用域与目录覆盖</h2>
      <span class="caption">选择特定的代码路径模式，查看该目录所适用的工程规范与核心约束</span>
    </div>

    <div v-if="!ledger.scope_density.length" class="empty">
      当前项目尚未配置任何针对代码路径的规则作用域。
    </div>

    <div v-else class="split-view">
      <!-- 左侧：作用域路径模式列表 -->
      <div class="tree-pane">
        <div class="pane-title">
          <h2>作用域模式 (Scope Patterns)</h2>
          <span class="muted">{{ ledger.scope_density.length }} 个受控路径</span>
        </div>
        <div class="tree-content">
          <div
            v-for="s in ledger.scope_density"
            :key="s.scope"
            class="tree-file"
            :class="{ selected: selectedScope === s.scope }"
            @click="selectedScope = s.scope"
          >
            <span class="tree-name">{{ s.scope }}</span>
            <div class="tree-counts">
              <span v-if="s.p0" class="p0">P0:{{ s.p0 }}</span>
              <span v-if="s.p1" class="p1">P1:{{ s.p1 }}</span>
              <span v-if="s.long_term" class="long">长期:{{ s.long_term }}</span>
              <span v-if="s.short_term" class="task">任务:{{ s.short_term }}</span>
            </div>
          </div>
        </div>
        <div class="tree-legend">
          <span>P0 强制核心规范</span>
          <span>P1 任务约束规范</span>
          <span>长期 跨任务通用</span>
          <span>任务 仅本任务有效</span>
        </div>
      </div>

      <!-- 右侧：所选作用域的生效规则列表 -->
      <div class="focus-pane">
        <div class="focus-path">
          <strong>作用域模式：</strong><code>{{ selectedScope }}</code>
        </div>
        <div class="breadcrumbs">
          <span>当前作用域下共有 {{ activeScopeRules.length }} 条生效规则</span>
          <span>Agent 访问该路径文件时将自动提取</span>
        </div>

        <div v-if="!activeScopeRules.length" class="empty compact">
          请在左侧选择一个作用域模式以查看详细规则。
        </div>
        <div v-else>
          <article
            v-for="rule in activeScopeRules"
            :key="rule.id"
            class="focus-rule"
            :class="rule.priority.toLowerCase()"
          >
            <div class="card-top">
              <h3>{{ rule.title }}</h3>
              <div class="tags">
                <span class="tag" :class="rule.priority.toLowerCase()">
                  {{ rule.priority === 'P0' ? 'P0 强制核心规范' : rule.priority === 'P1' ? 'P1 任务约束规范' : 'P2 架构建议' }}
                </span>
                <span class="tag" :class="rule.status">{{ rule.status === 'active' ? '生效中' : '已停用' }}</span>
                <span class="tag">{{ rule.task_id ? '任务短期规则' : '长期契约' }}</span>
              </div>
            </div>
            <ul style="margin: 10px 0; padding-left: 18px; line-height: 1.7">
              <li v-for="(point, i) in rule.points" :key="i">{{ point }}</li>
            </ul>
            <div class="definition">
              <dt>管辖文件模式：</dt>
              <dd><code>{{ rule.patterns.join(' · ') }}</code></dd>
              <dt>使用与反馈：</dt>
              <dd>
                已被引用 {{ rule.eval_count }} 次 · 标记已知 {{ rule.known_count }} 次 · 效用均分：{{ rule.avg_score ?? '—' }}
              </dd>
            </div>
          </article>
        </div>
      </div>
    </div>
  </div>
</template>
