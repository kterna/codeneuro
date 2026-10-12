<script setup lang="ts">
import type { Project, TabId, TabItem } from '../../types/ledger'

defineProps<{
  projects: Project[]
  currentProjectId: string
  tabs: readonly TabItem[]
  currentTab: TabId
  errorText: string
}>()

const emit = defineEmits<{
  (e: 'select-project', id: string): void
  (e: 'open-create-project'): void
  (e: 'delete-current-project'): void
  (e: 'select-tab', tab: TabId): void
  (e: 'open-palette'): void
}>()
</script>

<template>
  <aside class="sidebar">
    <a class="brand" href="/app/" aria-label="CodeNeuro 首页">
      <span class="brand-mark">C</span>
      <span>CodeNeuro<small>工程治理工作台</small></span>
    </a>

    <label class="caption" for="project">当前项目</label>
    <select
      id="project"
      :value="currentProjectId"
      aria-label="当前项目"
      @change="emit('select-project', ($event.target as HTMLSelectElement).value)"
    >
      <option v-if="!projects.length" value="">暂无项目</option>
      <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
    </select>
    <div style="display: flex; gap: 6px; margin-top: 6px">
      <button id="new-project" class="subtle" style="flex: 1; text-align: center" @click="emit('open-create-project')">＋ 注册项目</button>
      <button
        v-if="currentProjectId"
        class="subtle"
        style="color: var(--red); padding: 6px 8px"
        title="删除当前选中的项目"
        @click="emit('delete-current-project')"
      >
        🗑
      </button>
    </div>

    <nav id="navigation" aria-label="工作台导航">
      <button
        v-for="item in tabs"
        :key="item.id"
        :class="{ active: currentTab === item.id }"
        @click="emit('select-tab', item.id)"
      >
        <span class="nav-icon">{{ item.icon }}</span>
        {{ item.title }}
      </button>
    </nav>

    <div class="aside-foot">
      <button id="open-palette" class="palette-trigger" @click="emit('open-palette')">
        全局命令 <kbd>Ctrl K</kbd>
      </button>
      <span id="health" role="status">
        {{ errorText ? '● 服务连接异常' : '● 系统已连接' }}
      </span>
      <p>规则明确可依，变更具备完整证据链。</p>
    </div>
  </aside>
</template>
