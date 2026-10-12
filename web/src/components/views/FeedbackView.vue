<script setup lang="ts">
import type { Ledger } from '../../types/ledger'

defineProps<{
  ledger: Ledger
}>()
</script>

<template>
  <div>
    <div class="section-head">
      <h2>规则效用反馈分布</h2>
      <span class="caption">查看 Agent 对规则的真实反馈评分（0=已掌握知识、1=不相关噪音、5=核心必需；均分排除 0 分）</span>
    </div>
    <div class="grid">
      <article v-for="rule in ledger.rules" :key="rule.id" class="card">
        <div class="card-top">
          <h3>{{ rule.title }}</h3>
          <span class="tag" :class="rule.priority.toLowerCase()">{{ rule.priority }}</span>
        </div>
        <div class="distribution" style="margin: 12px 0">
          <div class="score-cell filled" title="效用均分">{{ rule.avg_score ?? '—' }}</div>
          <span class="muted" style="margin-left: 8px">
            被 Agent 引用 {{ rule.eval_count }} 次 · 标记已知 {{ rule.known_count }} 次
          </span>
        </div>
        <small class="muted">管辖路径：<code>{{ rule.patterns.join(' · ') }}</code></small>
      </article>
    </div>

    <div class="section-head" style="margin-top: 35px">
      <h2>开发避坑便签 (Findings / Gotchas)</h2>
      <span class="caption">Agent 在排查自愈复杂问题后沉淀的模块便签，同任务后续访问相关路径时自动警示</span>
    </div>
    <div v-if="!ledger.findings?.length" class="empty">
      当前任务暂无待审阅的避坑便签。
    </div>
    <div v-else class="grid">
      <article v-for="f in ledger.findings" :key="f.id" class="card">
        <div class="card-top">
          <h3>{{ f.target_path }}</h3>
          <span class="tag warning">{{ f.status }}</span>
        </div>
        <p>{{ f.text }}</p>
        <small class="muted">来源任务：{{ f.task_id }} · 版本 v{{ f.version }}</small>
      </article>
    </div>

    <div class="section-head" style="margin-top: 35px">
      <h2>已登记工作区实例 (Worktree Instances)</h2>
      <span class="caption">客户端环境声明 · 稳定 Worktree ID 隔离</span>
    </div>
    <div v-if="!ledger.worktrees.length" class="empty">
      暂无已连接的工作区实例。
    </div>
    <div v-else class="grid">
      <article v-for="wt in ledger.worktrees" :key="wt.id" class="card">
        <div class="card-top">
          <h3>{{ wt.machine_name }}</h3>
          <span class="tag">{{ wt.platform }}</span>
        </div>
        <p><code>{{ wt.workspace }}</code></p>
        <div class="definition">
          <dt>Git 分支：</dt>
          <dd>{{ wt.git_branch || '未上报' }}</dd>
          <dt>实例标识：</dt>
          <dd><code>{{ wt.id }}</code></dd>
        </div>
      </article>
    </div>
  </div>
</template>
