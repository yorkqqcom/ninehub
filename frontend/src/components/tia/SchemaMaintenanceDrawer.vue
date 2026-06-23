<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { apiRequest } from "@/api/client";
import WorkflowCollectProfilePanel from "@/components/WorkflowCollectProfilePanel.vue";
import type { SchemaApplyResult, SchemaPlan, WorkflowCollectProfile } from "@/api/types";
import { useUiStore } from "@/stores/ui";

const props = defineProps<{
  proposalId: number | null;
  apiName?: string;
}>();

const emit = defineEmits<{
  close: [];
  applied: [];
}>();

const ui = useUiStore();
const open = computed(() => props.proposalId != null);
const loading = ref(false);
const applying = ref(false);
const plan = ref<SchemaPlan | null>(null);
const workflowProfile = ref<WorkflowCollectProfile | null>(null);
const confirmRisk = ref(false);

async function loadPlan() {
  if (props.proposalId == null) return;
  loading.value = true;
  plan.value = null;
  workflowProfile.value = null;
  confirmRisk.value = false;
  try {
    plan.value = await apiRequest<SchemaPlan>(
      `/api/v1/tia/proposals/${props.proposalId}/schema-plan`,
    );
    const api = props.apiName || plan.value.api_name;
    if (api) {
      try {
        workflowProfile.value = await apiRequest<WorkflowCollectProfile>(
          `/api/v1/workflows/collect-profile?data_type=tushare_${encodeURIComponent(api)}&batch_mode=daily`,
        );
      } catch {
        workflowProfile.value = null;
      }
    }
  } catch (e) {
    ui.showMessage(e instanceof Error ? e.message : "加载 Schema 计划失败", "error");
    emit("close");
  } finally {
    loading.value = false;
  }
}

watch(
  () => props.proposalId,
  (id) => {
    if (id != null) void loadPlan();
  },
  { immediate: true },
);

const canApplyColumns = computed(
  () => plan.value?.available_modes.includes("columns") ?? false,
);
const canApplyKeys = computed(
  () => plan.value?.available_modes.includes("unique_keys") ?? false,
);
const canApplyAll = computed(() => canApplyColumns.value && canApplyKeys.value);

const applyDisabled = computed(() => {
  if (!plan.value?.has_drift) return true;
  if (plan.value.needs_confirm_risk && !confirmRisk.value) return true;
  if (plan.value.ddl_errors.length > 0) return true;
  return false;
});

async function apply(modes: string[]) {
  if (props.proposalId == null || applyDisabled.value) return;
  applying.value = true;
  try {
    const result = await apiRequest<SchemaApplyResult>(
      `/api/v1/tia/proposals/${props.proposalId}/schema-apply`,
      {
        method: "POST",
        body: JSON.stringify({ modes, confirm_risk: confirmRisk.value }),
      },
    );
    const keys = result.unique_keys_after?.join(", ") || "—";
    ui.showMessage(
      `Schema 已应用：模式 ${result.modes_applied.join("+")}；唯一键 ${keys}`,
      "success",
    );
    emit("applied");
    emit("close");
  } catch (e) {
    ui.showMessage(e instanceof Error ? e.message : "Schema 应用失败", "error");
  } finally {
    applying.value = false;
  }
}

function copySnippet() {
  const snippet = plan.value?.registry_hint.registry_snippet;
  if (!snippet) return;
  void navigator.clipboard.writeText(snippet);
  ui.showMessage("已复制 registry 登记片段", "success");
}
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="schema-drawer-backdrop" @click.self="emit('close')">
      <aside class="schema-drawer panel" role="dialog" aria-labelledby="schema-drawer-title">
        <header class="panel__header schema-drawer__header">
          <div>
            <h2 id="schema-drawer-title" class="schema-drawer__title">Schema 运维</h2>
            <p v-if="apiName || plan?.api_name" class="schema-drawer__subtitle">
              {{ apiName || plan?.api_name }}
              <span v-if="plan?.table_name" class="muted"> · {{ plan.table_name }}</span>
            </p>
          </div>
          <button type="button" class="btn btn--ghost btn--sm" @click="emit('close')">关闭</button>
        </header>

        <div class="panel__body schema-drawer__body">
          <p v-if="loading" class="muted">加载预览…</p>

          <template v-else-if="plan">
            <div v-if="!plan.has_drift" class="schema-drawer__banner schema-drawer__banner--ok">
              当前 Schema 与 catalog/registry 一致，无需变更。
            </div>

            <WorkflowCollectProfilePanel
              v-if="workflowProfile"
              :profile="workflowProfile"
              :subtitle="`${apiName || plan?.api_name || ''} · 工作流日批`"
            />

            <section v-if="plan.columns_drift" class="schema-drawer__section">
              <h3 class="schema-drawer__section-title">列与映射</h3>
              <div class="kv-list kv-list--compact">
                <div class="kv-row">
                  <span class="kv-row__label">列（前）</span>
                  <code>{{ plan.columns_before.join(", ") || "—" }}</code>
                </div>
                <div class="kv-row">
                  <span class="kv-row__label">列（后）</span>
                  <code>{{ plan.columns_after.join(", ") || "—" }}</code>
                </div>
                <div v-if="plan.columns_added.length" class="kv-row">
                  <span class="kv-row__label">新增</span>
                  <span class="badge badge--ok">{{ plan.columns_added.join(", ") }}</span>
                </div>
                <div v-if="plan.columns_dropped.length" class="kv-row">
                  <span class="kv-row__label">删除</span>
                  <span class="badge badge--err">{{ plan.columns_dropped.join(", ") }}</span>
                </div>
                <div
                  v-if="plan.collect_mode_before !== plan.collect_mode_after"
                  class="kv-row"
                >
                  <span class="kv-row__label">采集模式</span>
                  <span>
                    {{ plan.collect_mode_before ?? "—" }} → {{ plan.collect_mode_after ?? "—" }}
                  </span>
                </div>
              </div>
              <ul v-if="plan.mapping_changes.length" class="schema-drawer__list">
                <li v-for="m in plan.mapping_changes" :key="m.api_field">
                  <code>{{ m.api_field }}</code>: {{ m.before ?? "—" }} → {{ m.after ?? "—" }}
                </li>
              </ul>
            </section>

            <section v-if="plan.keys_drift || plan.unique_keys_before.length" class="schema-drawer__section">
              <h3 class="schema-drawer__section-title">唯一键</h3>
              <div class="kv-list kv-list--compact">
                <div class="kv-row">
                  <span class="kv-row__label">当前</span>
                  <code>{{ plan.unique_keys_before.join(", ") || "—" }}</code>
                </div>
                <div class="kv-row">
                  <span class="kv-row__label">Registry</span>
                  <code>{{ plan.unique_keys_registry.join(", ") || "—" }}</code>
                </div>
              </div>
              <div
                v-if="!plan.registry_registered"
                class="schema-drawer__banner schema-drawer__banner--warn"
              >
                <p>该 API 未在 <code>unique_key_registry.py</code> 登记，须先改代码再同步唯一键。</p>
                <pre class="schema-drawer__snippet">{{ plan.registry_hint.registry_snippet }}</pre>
                <button type="button" class="btn btn--ghost btn--sm" @click="copySnippet">
                  复制登记片段
                </button>
              </div>
            </section>

            <section v-if="plan.warnings.length" class="schema-drawer__section">
              <h3 class="schema-drawer__section-title">风险与校验</h3>
              <ul class="schema-drawer__warnings">
                <li v-for="(w, i) in plan.warnings" :key="i">{{ w }}</li>
              </ul>
              <ul v-if="plan.ddl_errors.length" class="schema-drawer__warnings schema-drawer__warnings--err">
                <li v-for="(e, i) in plan.ddl_errors" :key="'e' + i">{{ e }}</li>
              </ul>
              <label v-if="plan.needs_confirm_risk" class="schema-drawer__confirm">
                <input v-model="confirmRisk" type="checkbox" />
                我已了解删列/唯一键变更风险（表内 {{ plan.row_count }} 行）
              </label>
            </section>

            <footer class="schema-drawer__actions">
              <button
                type="button"
                class="btn btn--secondary btn--sm"
                :disabled="!canApplyColumns || applyDisabled || applying"
                @click="apply(['columns'])"
              >
                {{ applying ? "应用中…" : "应用列对齐" }}
              </button>
              <button
                type="button"
                class="btn btn--secondary btn--sm"
                :disabled="!canApplyKeys || applyDisabled || applying"
                @click="apply(['unique_keys'])"
              >
                同步唯一键
              </button>
              <button
                type="button"
                class="btn btn--primary btn--sm"
                :disabled="!canApplyAll || applyDisabled || applying"
                @click="apply(['columns', 'unique_keys'])"
              >
                全部应用
              </button>
            </footer>
          </template>
        </div>
      </aside>
    </div>
  </Teleport>
</template>

<style scoped>
.schema-drawer-backdrop {
  position: fixed;
  inset: 0;
  z-index: 1000;
  background: var(--color-overlay);
  display: flex;
  justify-content: flex-end;
}

.schema-drawer {
  width: min(520px, 100vw);
  height: 100%;
  display: flex;
  flex-direction: column;
  border-radius: 0;
  box-shadow: var(--color-shadow-drawer);
}

.schema-drawer__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-md);
}

.schema-drawer__title {
  margin: 0;
  font-size: var(--font-size-lg);
  font-weight: 600;
}

.schema-drawer__subtitle {
  margin: 4px 0 0;
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}

.schema-drawer__body {
  flex: 1;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: var(--space-lg);
}

.schema-drawer__section-title {
  margin: 0 0 var(--space-sm);
  font-size: var(--font-size-md);
  font-weight: 600;
}

.schema-drawer__banner {
  padding: var(--space-sm) var(--space-md);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-sm);
}

.schema-drawer__banner--ok {
  background: var(--color-row-active);
  border: 1px solid var(--color-border);
}

.schema-drawer__banner--warn {
  background: var(--color-warn-bg);
  border: 1px solid var(--color-border);
}

.schema-drawer__snippet {
  margin: var(--space-sm) 0;
  padding: var(--space-sm);
  font-size: var(--font-size-sm);
  overflow-x: auto;
  background: var(--color-surface-muted);
  border-radius: var(--radius-sm);
}

.schema-drawer__list,
.schema-drawer__warnings {
  margin: var(--space-sm) 0 0;
  padding-left: 1.25rem;
  font-size: var(--font-size-sm);
}

.schema-drawer__warnings--err {
  color: var(--color-err-text);
}

.schema-drawer__confirm {
  display: flex;
  align-items: flex-start;
  gap: var(--space-sm);
  margin-top: var(--space-md);
  font-size: var(--font-size-sm);
  cursor: pointer;
}

.schema-drawer__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-sm);
  margin-top: auto;
  padding-top: var(--space-md);
  border-top: 1px solid var(--color-border);
}
</style>
