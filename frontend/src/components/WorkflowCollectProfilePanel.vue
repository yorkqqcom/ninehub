<script setup lang="ts">
import type { WorkflowCollectProfile } from "@/api/types";

defineProps<{
  profile: WorkflowCollectProfile | null;
  loading?: boolean;
  subtitle?: string | null;
}>();
</script>

<template>
  <section class="wf-collect-profile">
    <h3 class="wf-collect-profile__title">采集策略（平台 · 只读）</h3>
    <p v-if="subtitle" class="wf-collect-profile__subtitle muted">{{ subtitle }}</p>
    <p v-if="loading" class="muted">加载策略…</p>
    <div v-else-if="profile" class="kv-list kv-list--compact">
      <div class="kv-row">
        <span class="kv-row__label">模式</span>
        <code>{{ profile.collect_mode }}</code>
      </div>
      <div class="kv-row">
        <span class="kv-row__label">每轮 codes</span>
        <span class="numeric">{{ profile.max_codes_effective }}</span>
        <span
          v-if="
            profile.max_codes_stored != null &&
            profile.max_codes_stored !== profile.max_codes_effective
          "
          class="wf-stale-cap muted"
        >
          （override {{ profile.max_codes_stored }}）
        </span>
      </div>
      <div class="kv-row">
        <span class="kv-row__label">API 预算</span>
        <span class="numeric">{{ profile.max_api_calls_per_run }}/节点</span>
      </div>
      <div v-if="profile.rotation_enabled" class="kv-row">
        <span class="kv-row__label">轮转</span>
        <span>是 · {{ profile.rotation_codes_per_run }}/日</span>
      </div>
      <div v-if="profile.recent_periods" class="kv-row">
        <span class="kv-row__label">报告期</span>
        <span>最近 {{ profile.recent_periods }} 期</span>
      </div>
      <div v-if="profile.publish_lag_days" class="kv-row">
        <span class="kv-row__label">发布滞后</span>
        <span>T+{{ profile.publish_lag_days }}</span>
      </div>
      <ul v-if="profile.notes.length" class="wf-collect-profile__notes">
        <li v-for="(note, i) in profile.notes" :key="i">{{ note }}</li>
      </ul>
    </div>
    <p v-else class="muted">无法加载采集策略</p>
  </section>
</template>

<style scoped>
.wf-collect-profile {
  margin-top: var(--space-md);
  padding-top: var(--space-md);
  border-top: 1px solid var(--color-border);
}

.wf-collect-profile:first-child {
  margin-top: 0;
  padding-top: 0;
  border-top: none;
}

.wf-collect-profile__title {
  margin: 0 0 var(--space-xs);
  font-size: var(--font-size-md);
  font-weight: 600;
}

.wf-collect-profile__subtitle {
  margin: 0 0 var(--space-sm);
  font-size: var(--font-size-sm);
}

.wf-collect-profile__notes {
  margin: var(--space-sm) 0 0;
  padding-left: 1.2rem;
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}

.wf-stale-cap {
  font-size: var(--font-size-sm);
}
</style>
