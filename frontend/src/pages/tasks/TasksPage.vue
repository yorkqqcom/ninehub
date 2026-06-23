<script setup lang="ts">
import { onMounted, ref } from "vue";
import { apiRequest } from "@/api/client";
import type { CollectConfig, PageResponse, SyncTask } from "@/api/types";
import PageHeader from "@/components/PageHeader.vue";
import { useAuthStore } from "@/stores/auth";
import { useUiStore } from "@/stores/ui";

const auth = useAuthStore();
const ui = useUiStore();
const tasks = ref<SyncTask[]>([]);
const selectedTaskId = ref<number | null>(null);
const runs = ref<Array<Record<string, unknown>>>([]);
const running = ref(false);

const collectConfig = ref<CollectConfig | null>(null);
const paramRows = ref<Array<{ key: string; value: string }>>([]);
const savingParams = ref(false);
const paramsTaskId = ref<number | null>(null);

onMounted(() => void loadTasks());

async function loadTasks() {
  if (!auth.isAdmin) return;
  const data = await apiRequest<PageResponse<SyncTask>>("/api/v1/tasks?limit=100");
  tasks.value = data.items;
}

async function loadRuns(taskId: number) {
  selectedTaskId.value = taskId;
  const data = await apiRequest<PageResponse<Record<string, unknown>>>(
    `/api/v1/tasks/${taskId}/runs`,
  );
  runs.value = data.items;
}

async function loadCollectConfig(taskId: number) {
  paramsTaskId.value = taskId;
  selectedTaskId.value = taskId;
  collectConfig.value = await apiRequest<CollectConfig>(
    `/api/v1/tasks/${taskId}/collect-config`,
  );
  const overrides = collectConfig.value.task_overrides || {};
  paramRows.value = Object.entries(overrides).map(([key, value]) => ({
    key,
    value: String(value ?? ""),
  }));
  if (paramRows.value.length === 0) {
    paramRows.value = [{ key: "", value: "" }];
  }
}

function addParamRow() {
  paramRows.value.push({ key: "", value: "" });
}

function removeParamRow(index: number) {
  paramRows.value.splice(index, 1);
  if (paramRows.value.length === 0) {
    paramRows.value = [{ key: "", value: "" }];
  }
}

function buildOverrides(): Record<string, string> {
  const out: Record<string, string> = {};
  for (const row of paramRows.value) {
    const key = row.key.trim();
    if (!key) continue;
    out[key] = row.value;
  }
  return out;
}

async function saveCollectParams() {
  if (paramsTaskId.value == null) return;
  savingParams.value = true;
  try {
    const overrides = buildOverrides();
    await apiRequest<SyncTask>(`/api/v1/tasks/${paramsTaskId.value}`, {
      method: "PUT",
      body: JSON.stringify({ collect_params: overrides }),
    });
    ui.showMessage("采集参数已保存", "success");
    await loadCollectConfig(paramsTaskId.value);
    await loadTasks();
  } catch (e) {
    ui.showMessage(e instanceof Error ? e.message : String(e), "error");
  } finally {
    savingParams.value = false;
  }
}

async function resetCollectParams() {
  if (paramsTaskId.value == null) return;
  savingParams.value = true;
  try {
    await apiRequest<SyncTask>(`/api/v1/tasks/${paramsTaskId.value}`, {
      method: "PUT",
      body: JSON.stringify({ collect_params: {} }),
    });
    ui.showMessage("已恢复默认参数", "success");
    await loadCollectConfig(paramsTaskId.value);
    await loadTasks();
  } catch (e) {
    ui.showMessage(e instanceof Error ? e.message : String(e), "error");
  } finally {
    savingParams.value = false;
  }
}

async function runTask(taskId: number) {
  running.value = true;
  try {
    const res = await apiRequest<{ run_id: number; message: string }>(
      `/api/v1/tasks/${taskId}/run`,
      { method: "POST" },
    );
    ui.showMessage(`已触发 run #${res.run_id}`, "success");
    await loadRuns(taskId);
  } catch (e) {
    ui.showMessage(e instanceof Error ? e.message : String(e), "error");
  } finally {
    running.value = false;
  }
}

function statusBadge(status: string) {
  if (status === "active" || status === "success") return "badge--ok";
  if (status === "failed" || status === "error") return "badge--err";
  if (status === "running" || status === "pending") return "badge--warn";
  return "badge--muted";
}

function formatParams(params: Record<string, unknown> | undefined) {
  if (!params || Object.keys(params).length === 0) return "—";
  return JSON.stringify(params);
}
</script>

<template>
  <PageHeader title="采集任务" description="catalog 动态类型 · 执行日志 · 采集参数" />

  <div v-if="!auth.isAdmin" class="panel">
    <div class="panel__body empty-state empty-state--compact">只读账号无法管理任务</div>
  </div>

  <template v-else>
    <div class="panel">
      <div class="panel__header">
        <span>任务列表</span>
        <span class="panel__header-count">{{ tasks.length }} 个</span>
      </div>
      <div class="panel__body panel__body--flush">
        <table v-if="tasks.length" class="data-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>类型</th>
              <th>TIA 提案</th>
              <th>数据源</th>
              <th>状态</th>
              <th>调度</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="task in tasks"
              :key="task.id"
              :class="{ 'row-active': selectedTaskId === task.id }"
            >
              <td class="numeric">{{ task.id }}</td>
              <td>{{ task.data_type_label }}</td>
              <td>
                <RouterLink
                  v-if="task.proposal_id"
                  :to="{ name: 'tia', query: { proposal: String(task.proposal_id) } }"
                  class="table-link"
                >
                  #{{ task.proposal_id }}
                </RouterLink>
                <span v-else-if="task.tia_api_name" class="table-sub">{{ task.tia_api_name }}</span>
                <span v-else class="table-sub">—</span>
              </td>
              <td class="table-sub">
                <template v-if="task.source_name">{{ task.source_name }}</template>
                <span v-else class="badge badge--warn">未绑定</span>
              </td>
              <td>
                <span class="badge" :class="statusBadge(task.status)">{{ task.status }}</span>
              </td>
              <td class="table-sub">{{ task.schedule_cron || "—" }}</td>
              <td>
                <div class="btn-group">
                  <button
                    type="button"
                    class="btn btn--ghost btn--sm"
                    @click="loadCollectConfig(task.id)"
                  >
                    参数
                  </button>
                  <button type="button" class="btn btn--ghost btn--sm" @click="loadRuns(task.id)">
                    日志
                  </button>
                  <button
                    type="button"
                    class="btn btn--primary btn--sm"
                    :disabled="running"
                    @click="runTask(task.id)"
                  >
                    执行
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="empty-state empty-state--compact">暂无任务</p>
      </div>
    </div>

    <div v-if="collectConfig && paramsTaskId" class="panel">
      <div class="panel__header">
        <span>采集参数</span>
        <span class="panel__header-count">Task #{{ paramsTaskId }}</span>
      </div>
      <div class="panel__body collect-params">
        <div class="collect-params__meta">
          <p v-if="collectConfig.api_name">
            API <code>{{ collectConfig.api_name }}</code>
            · 模式 <code>{{ collectConfig.collect_mode }}</code>
            <span v-if="collectConfig.collect_pattern">
              · 模板 {{ collectConfig.collect_pattern }}
            </span>
          </p>
          <p v-else class="table-sub">非 TIA 类型，无法解析默认探针参数</p>
          <p v-if="collectConfig.runtime_keys.length" class="table-sub">
            运行时注入（不可编辑）：{{ collectConfig.runtime_keys.join(", ") }}
          </p>
        </div>

        <div class="collect-params__readonly">
          <div>
            <span class="collect-params__label">默认参数</span>
            <code class="collect-params__code">{{ formatParams(collectConfig.default_params) }}</code>
          </div>
          <div>
            <span class="collect-params__label">有效参数（合并后）</span>
            <code class="collect-params__code">{{
              formatParams(collectConfig.effective_params)
            }}</code>
          </div>
        </div>

        <div class="collect-params__editor">
          <span class="collect-params__label">任务覆盖</span>
          <div
            v-for="(row, index) in paramRows"
            :key="index"
            class="collect-params__row"
          >
            <input
              v-model="row.key"
              class="input input-w-sm"
              placeholder="参数名"
              aria-label="参数名"
            />
            <input
              v-model="row.value"
              class="input input-w-md"
              placeholder="值（如 SSE、L、空=全市场）"
              aria-label="参数值"
            />
            <button
              type="button"
              class="btn btn--ghost btn--sm"
              aria-label="删除参数行"
              @click="removeParamRow(index)"
            >
              删除
            </button>
          </div>
          <div class="btn-group">
            <button type="button" class="btn btn--ghost btn--sm" @click="addParamRow">
              添加参数
            </button>
            <button
              type="button"
              class="btn btn--primary btn--sm"
              :disabled="savingParams"
              @click="saveCollectParams"
            >
              保存
            </button>
            <button
              type="button"
              class="btn btn--ghost btn--sm"
              :disabled="savingParams"
              @click="resetCollectParams"
            >
              恢复默认
            </button>
          </div>
          <ul v-if="Object.keys(collectConfig.param_hints).length" class="collect-params__hints">
            <li v-for="(hint, key) in collectConfig.param_hints" :key="key">
              <code>{{ key }}</code> — {{ hint }}
            </li>
          </ul>
        </div>
      </div>
    </div>

    <div v-if="selectedTaskId" class="panel">
      <div class="panel__header">
        <span>执行日志</span>
        <span class="panel__header-count">Task #{{ selectedTaskId }}</span>
      </div>
      <div class="panel__body panel__body--flush">
        <table v-if="runs.length" class="data-table">
          <thead>
            <tr>
              <th>Run</th>
              <th>状态</th>
              <th>消息</th>
              <th class="col-num">行数</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="run in runs" :key="run.id as number">
              <td class="numeric">{{ run.id }}</td>
              <td>
                <span class="badge" :class="statusBadge(String(run.status))">
                  {{ run.status }}
                </span>
              </td>
              <td>{{ run.message || run.error || "—" }}</td>
              <td class="numeric col-num">{{ run.rows_upserted }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="empty-state empty-state--compact">暂无执行记录</p>
      </div>
    </div>
  </template>
</template>

<style scoped>
.collect-params {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.collect-params__meta p {
  margin: 0 0 0.35rem;
}

.collect-params__readonly {
  display: grid;
  gap: 0.75rem;
}

@media (min-width: 768px) {
  .collect-params__readonly {
    grid-template-columns: 1fr 1fr;
  }
}

.collect-params__label {
  display: block;
  font-size: 0.8125rem;
  color: var(--color-text-secondary);
  margin-bottom: 0.35rem;
}

.collect-params__code {
  display: block;
  padding: 0.5rem 0.65rem;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  font-size: 0.8125rem;
  word-break: break-all;
}

.collect-params__row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
  margin-bottom: 0.5rem;
}

.collect-params__hints {
  margin: 0.75rem 0 0;
  padding-left: 1.1rem;
  font-size: 0.8125rem;
  color: var(--color-text-secondary);
}

.collect-params__hints code {
  color: var(--color-text);
}
</style>
