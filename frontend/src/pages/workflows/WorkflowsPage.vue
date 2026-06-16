<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { apiRequest } from "@/api/client";
import type { DataTypeItem, NodeRun, PlatformJob, WorkflowRun } from "@/api/types";
import WorkflowGraph, { type GraphEdge, type GraphNode } from "@/components/WorkflowGraph.vue";
import PageHeader from "@/components/PageHeader.vue";
import { useAuthStore } from "@/stores/auth";
import { useUiStore } from "@/stores/ui";
import "@/styles/workflows.css";

interface WorkflowSummary {
  id: number;
  name: string;
  status: string;
  schedule_cron?: string | null;
  node_count: number;
}

interface WorkflowGraphData {
  workflow_id: number;
  name: string;
  status: string;
  schedule_cron?: string | null;
  nodes: GraphNode[];
  edges: GraphEdge[];
}

interface DataSourceItem {
  id: number;
  name: string;
  provider: string;
}

interface ValidateResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
}

const auth = useAuthStore();
const ui = useUiStore();

const workflows = ref<WorkflowSummary[]>([]);
const graph = ref<WorkflowGraphData | null>(null);
const draftGraph = ref<{ nodes: GraphNode[]; edges: GraphEdge[] } | null>(null);
const selectedId = ref<number | null>(null);
const workflowName = ref("");
const scheduleCron = ref("");
const runs = ref<WorkflowRun[]>([]);
const runsTotal = ref(0);
const runsSkip = ref(0);
const runsLimit = 30;
const selectedRunId = ref<number | null>(null);
const nodeRuns = ref<NodeRun[]>([]);
const nodeStatuses = ref<Record<string, string>>({});
const activeNodeId = ref<string | null>(null);
const job = ref<PlatformJob | null>(null);
const dataTypes = ref<DataTypeItem[]>([]);
const sources = ref<DataSourceItem[]>([]);
const validation = ref<ValidateResult | null>(null);
const asyncRun = ref(true);
const busy = ref(false);
const dirty = ref(false);
let pollTimer: number | undefined;

const isDraft = computed(() => graph.value?.status === "draft");
const isPublished = computed(() => graph.value?.status === "published");
const isEditable = computed(() => auth.isAdmin && isDraft.value);
const canvasNodes = computed(() => draftGraph.value?.nodes ?? graph.value?.nodes ?? []);
const canvasEdges = computed(() => draftGraph.value?.edges ?? graph.value?.edges ?? []);

const selectedNode = computed(() =>
  canvasNodes.value.find((n) => n.node_id === activeNodeId.value) ?? null,
);

const needsDataType = computed(
  () => selectedNode.value?.node_type === "collect" || selectedNode.value?.node_type === "quality",
);

onMounted(async () => {
  const [list, catalog, srcList] = await Promise.all([
    apiRequest<{ items: WorkflowSummary[] }>("/api/v1/workflows"),
    apiRequest<{ items: DataTypeItem[] }>("/api/v1/catalog/data-types"),
    apiRequest<{ items: DataSourceItem[] }>("/api/v1/sources?limit=100"),
  ]);
  workflows.value = list.items;
  dataTypes.value = catalog.items;
  sources.value = srcList.items;
  if (list.items.length) await selectWorkflow(list.items[0].id);
});

onUnmounted(() => stopPolling());

watch(selectedId, (id) => {
  if (id) void loadRuns(id);
});

async function selectWorkflow(id: number) {
  selectedId.value = id;
  selectedRunId.value = null;
  runsSkip.value = 0;
  nodeRuns.value = [];
  nodeStatuses.value = {};
  job.value = null;
  dirty.value = false;
  draftGraph.value = null;
  validation.value = null;
  await loadGraph(id);
  await loadRuns(id);
  await refreshValidation(id);
}

async function loadGraph(id: number) {
  graph.value = await apiRequest<WorkflowGraphData>(`/api/v1/workflows/${id}/graph`);
  workflowName.value = graph.value.name;
  scheduleCron.value = graph.value.schedule_cron ?? "";
}

async function refreshValidation(id: number) {
  validation.value = await apiRequest<ValidateResult>(
    `/api/v1/workflows/${id}/validate?for_publish=${isDraft.value}`,
  );
}

async function loadRuns(workflowId: number) {
  const data = await apiRequest<{ items: WorkflowRun[]; total: number }>(
    `/api/v1/workflows/${workflowId}/runs?skip=${runsSkip.value}&limit=${runsLimit}`,
  );
  runs.value = data.items;
  runsTotal.value = data.total;
  if (data.items.length && !selectedRunId.value) {
    await selectRun(data.items[0].id);
  }
}

function prevRunsPage() {
  if (runsSkip.value >= runsLimit) {
    runsSkip.value -= runsLimit;
    if (selectedId.value) void loadRuns(selectedId.value);
  }
}

function nextRunsPage() {
  if (runsSkip.value + runsLimit < runsTotal.value) {
    runsSkip.value += runsLimit;
    if (selectedId.value) void loadRuns(selectedId.value);
  }
}

async function selectRun(runId: number) {
  selectedRunId.value = runId;
  const run = runs.value.find((r) => r.id === runId);
  const nodes = await apiRequest<{ items: NodeRun[] }>(
    `/api/v1/workflows/runs/${runId}/nodes`,
  );
  nodeRuns.value = nodes.items;
  nodeStatuses.value = Object.fromEntries(nodes.items.map((n) => [n.node_id, n.status]));

  if (run?.job_id) {
    job.value = await apiRequest<PlatformJob>(`/api/v1/platform/jobs/${run.job_id}`);
  } else {
    job.value = null;
  }

  if (run && (run.status === "running" || run.status === "pending")) {
    startPolling(runId);
  } else {
    stopPolling();
  }
}

function startPolling(runId: number) {
  stopPolling();
  pollTimer = window.setInterval(() => void refreshRun(runId), 1500);
}

function stopPolling() {
  if (pollTimer) {
    window.clearInterval(pollTimer);
    pollTimer = undefined;
  }
}

async function refreshRun(runId: number) {
  try {
    const run = await apiRequest<WorkflowRun>(`/api/v1/workflows/runs/${runId}`);
    const idx = runs.value.findIndex((r) => r.id === runId);
    if (idx >= 0) runs.value[idx] = run;
    const nodes = await apiRequest<{ items: NodeRun[] }>(
      `/api/v1/workflows/runs/${runId}/nodes`,
    );
    nodeRuns.value = nodes.items;
    nodeStatuses.value = Object.fromEntries(nodes.items.map((n) => [n.node_id, n.status]));
    if (run.job_id) {
      job.value = await apiRequest<PlatformJob>(`/api/v1/platform/jobs/${run.job_id}`);
    }
    if (run.status !== "running" && run.status !== "pending") stopPolling();
  } catch {
    stopPolling();
  }
}

function onGraphChange(payload: { nodes: GraphNode[]; edges: GraphEdge[] }) {
  draftGraph.value = payload;
  dirty.value = true;
  if (selectedId.value) void refreshValidation(selectedId.value);
}

async function saveGraph() {
  if (!selectedId.value || !draftGraph.value) return;
  busy.value = true;
  try {
    graph.value = await apiRequest<WorkflowGraphData>(
      `/api/v1/workflows/${selectedId.value}/graph`,
      {
        method: "PUT",
        body: JSON.stringify(draftGraph.value),
      },
    );
    draftGraph.value = null;
    dirty.value = false;
    await refreshValidation(selectedId.value);
    ui.showMessage("图结构已保存", "success");
  } catch (e) {
    ui.showMessage(e instanceof Error ? e.message : String(e), "error");
  } finally {
    busy.value = false;
  }
}

async function saveNodeProps() {
  if (!selectedId.value || !selectedNode.value) return;
  busy.value = true;
  try {
    await apiRequest(`/api/v1/workflows/${selectedId.value}/nodes/${selectedNode.value.node_id}`, {
      method: "PATCH",
      body: JSON.stringify({
        label: selectedNode.value.label,
        data_type: selectedNode.value.data_type,
        source_id: selectedNode.value.source_id,
      }),
    });
    await loadGraph(selectedId.value);
    if (draftGraph.value) {
      const patched = draftGraph.value.nodes.find(
        (n) => n.node_id === selectedNode.value?.node_id,
      );
      if (patched && selectedNode.value) {
        patched.label = selectedNode.value.label;
        patched.data_type = selectedNode.value.data_type;
        patched.source_id = selectedNode.value.source_id;
      }
    }
    await refreshValidation(selectedId.value);
    ui.showMessage("节点已更新", "success");
  } catch (e) {
    ui.showMessage(e instanceof Error ? e.message : String(e), "error");
  } finally {
    busy.value = false;
  }
}

async function saveMeta() {
  if (!selectedId.value) return;
  busy.value = true;
  try {
    const res = await apiRequest<WorkflowSummary>(`/api/v1/workflows/${selectedId.value}`, {
      method: "PATCH",
      body: JSON.stringify({
        name: workflowName.value,
        schedule_cron: scheduleCron.value || null,
      }),
    });
    if (graph.value) {
      graph.value.name = res.name;
      graph.value.schedule_cron = res.schedule_cron;
    }
    const idx = workflows.value.findIndex((w) => w.id === selectedId.value);
    if (idx >= 0) workflows.value[idx] = { ...workflows.value[idx], ...res };
    ui.showMessage("元数据已保存", "success");
  } catch (e) {
    ui.showMessage(e instanceof Error ? e.message : String(e), "error");
  } finally {
    busy.value = false;
  }
}

async function triggerRun(skipGates = false) {
  if (!selectedId.value || !auth.isAdmin) return;
  busy.value = true;
  try {
    const params = new URLSearchParams();
    if (skipGates) params.set("skip_gates", "true");
    else if (!asyncRun.value) params.set("async_queue", "false");
    const q = params.toString() ? `?${params}` : "";
    const res = await apiRequest<{ run_id: number; job_id?: number; message: string }>(
      `/api/v1/workflows/${selectedId.value}/run${q}`,
      { method: "POST" },
    );
    ui.showMessage(res.message, "success");
    await loadRuns(selectedId.value);
    await selectRun(res.run_id);
  } catch (e) {
    ui.showMessage(e instanceof Error ? e.message : String(e), "error");
  } finally {
    busy.value = false;
  }
}

async function publishWorkflow() {
  if (!selectedId.value || !auth.isAdmin) return;
  await refreshValidation(selectedId.value);
  if (validation.value && !validation.value.valid) {
    ui.showMessage(`校验未通过: ${validation.value.errors.join("; ")}`, "error");
    return;
  }
  busy.value = true;
  try {
    const res = await apiRequest<{ message: string }>(
      `/api/v1/workflows/${selectedId.value}/publish`,
      { method: "POST" },
    );
    ui.showMessage(res.message, "success");
    await loadGraph(selectedId.value);
    draftGraph.value = null;
    dirty.value = false;
    await refreshValidation(selectedId.value);
  } catch (e) {
    ui.showMessage(e instanceof Error ? e.message : String(e), "error");
  } finally {
    busy.value = false;
  }
}

async function unpublishWorkflow() {
  if (!selectedId.value || !auth.isAdmin) return;
  busy.value = true;
  try {
    const res = await apiRequest<{ message: string }>(
      `/api/v1/workflows/${selectedId.value}/unpublish`,
      { method: "POST" },
    );
    ui.showMessage(res.message, "success");
    await loadGraph(selectedId.value);
    await refreshValidation(selectedId.value);
  } catch (e) {
    ui.showMessage(e instanceof Error ? e.message : String(e), "error");
  } finally {
    busy.value = false;
  }
}

async function cloneWorkflow() {
  if (!selectedId.value || !auth.isAdmin) return;
  busy.value = true;
  try {
    const res = await apiRequest<{ workflow_id: number; message: string }>(
      `/api/v1/workflows/${selectedId.value}/clone`,
      { method: "POST" },
    );
    ui.showMessage(res.message, "success");
    const list = await apiRequest<{ items: WorkflowSummary[] }>("/api/v1/workflows");
    workflows.value = list.items;
    await selectWorkflow(res.workflow_id);
  } catch (e) {
    ui.showMessage(e instanceof Error ? e.message : String(e), "error");
  } finally {
    busy.value = false;
  }
}

async function createWorkflow() {
  if (!auth.isAdmin) return;
  const name = window.prompt("新工作流名称", "新工作流");
  if (!name?.trim()) return;
  busy.value = true;
  try {
    const res = await apiRequest<{ workflow_id: number; message: string }>("/api/v1/workflows", {
      method: "POST",
      body: JSON.stringify({ name: name.trim() }),
    });
    ui.showMessage(res.message, "success");
    const list = await apiRequest<{ items: WorkflowSummary[] }>("/api/v1/workflows");
    workflows.value = list.items;
    await selectWorkflow(res.workflow_id);
  } catch (e) {
    ui.showMessage(e instanceof Error ? e.message : String(e), "error");
  } finally {
    busy.value = false;
  }
}

async function deleteWorkflow() {
  if (!selectedId.value || !auth.isAdmin || !isDraft.value) return;
  if (!window.confirm("确定删除此 draft 工作流？")) return;
  busy.value = true;
  try {
    const res = await apiRequest<{ message: string }>(
      `/api/v1/workflows/${selectedId.value}`,
      { method: "DELETE" },
    );
    ui.showMessage(res.message, "success");
    const list = await apiRequest<{ items: WorkflowSummary[] }>("/api/v1/workflows");
    workflows.value = list.items;
    if (list.items.length) await selectWorkflow(list.items[0].id);
    else {
      selectedId.value = null;
      graph.value = null;
    }
  } catch (e) {
    ui.showMessage(e instanceof Error ? e.message : String(e), "error");
  } finally {
    busy.value = false;
  }
}

function wfStatusBadge(status: string) {
  if (status === "published") return "badge--ok";
  if (status === "draft") return "badge--muted";
  return "badge--warn";
}

function runStatusBadge(status: string) {
  if (status === "success") return "badge--ok";
  if (status === "failed") return "badge--err";
  if (status === "running" || status === "pending") return "badge--warn";
  return "badge--muted";
}

function formatTime(iso?: string | null) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("zh-CN", { hour12: false });
}
</script>

<template>
  <div class="wf-page">
    <PageHeader title="工作流" description="DAG 编排 · 节点注册表 · Cron 调度 · 质检节点">
      <template v-if="auth.isAdmin" #actions>
        <div class="btn-group">
          <button type="button" class="btn btn--ghost btn--sm" :disabled="busy" @click="createWorkflow">
            新建
          </button>
          <button
            type="button"
            class="btn btn--primary btn--sm"
            :disabled="busy || !selectedId"
            @click="triggerRun(false)"
          >
            运行
          </button>
          <button
            type="button"
            class="btn btn--secondary btn--sm"
            :disabled="busy || !selectedId"
            @click="triggerRun(true)"
          >
            调试
          </button>
          <button
            type="button"
            class="btn btn--ghost btn--sm"
            :disabled="busy || !isDraft"
            @click="publishWorkflow"
          >
            发布
          </button>
          <button
            type="button"
            class="btn btn--ghost btn--sm"
            :disabled="busy || !isPublished"
            @click="unpublishWorkflow"
          >
            取消发布
          </button>
          <button
            type="button"
            class="btn btn--ghost btn--sm"
            :disabled="busy || !selectedId"
            @click="cloneWorkflow"
          >
            克隆
          </button>
          <button
            type="button"
            class="btn btn--ghost btn--sm wf-btn-danger"
            :disabled="busy || !isDraft"
            @click="deleteWorkflow"
          >
            删除
          </button>
          <button
            v-if="isEditable"
            type="button"
            class="btn btn--secondary btn--sm"
            :disabled="busy || !dirty"
            @click="saveGraph"
          >
            保存图
          </button>
        </div>
      </template>
    </PageHeader>

    <div class="page-toolbar">
      <label class="form-field">
        <span>工作流</span>
        <select
          class="input-w-md"
          :value="selectedId ?? ''"
          @change="selectWorkflow(Number(($event.target as HTMLSelectElement).value))"
        >
          <option v-for="w in workflows" :key="w.id" :value="w.id">{{ w.name }}</option>
        </select>
      </label>
      <label v-if="auth.isAdmin" class="form-field">
        <span>名称</span>
        <input v-model="workflowName" class="input-w-md" @change="saveMeta" />
      </label>
      <span v-if="graph" class="badge" :class="wfStatusBadge(graph.status)">{{ graph.status }}</span>
      <label v-if="auth.isAdmin" class="form-field">
        <span>Cron</span>
        <input
          v-model="scheduleCron"
          class="input-w-md"
          placeholder="0 16 * * 1-5"
          @change="saveMeta"
        />
      </label>
      <label v-if="auth.isAdmin" class="form-field wf-async-toggle">
        <input v-model="asyncRun" type="checkbox" />
        <span>异步队列</span>
      </label>
      <span v-if="isEditable" class="badge badge--muted">可拖拽编辑</span>
    </div>

    <div v-if="validation && (validation.errors.length || validation.warnings.length)" class="panel wf-validate-panel">
      <div class="panel__header">
        <span>DAG 校验</span>
        <span class="badge" :class="validation.valid ? 'badge--ok' : 'badge--err'">
          {{ validation.valid ? "通过" : "未通过" }}
        </span>
      </div>
      <div class="panel__body">
        <ul v-if="validation.errors.length" class="wf-validate-list wf-validate-list--err">
          <li v-for="(e, i) in validation.errors" :key="'e' + i">{{ e }}</li>
        </ul>
        <ul v-if="validation.warnings.length" class="wf-validate-list wf-validate-list--warn">
          <li v-for="(w, i) in validation.warnings" :key="'w' + i">{{ w }}</li>
        </ul>
      </div>
    </div>

    <div v-if="job" class="panel">
      <div class="panel__header">
        <span>执行进度</span>
        <span class="panel__header-count numeric">{{ job.progress }}%</span>
      </div>
      <div class="panel__body">
        <p class="progress-meta">
          <span>{{ job.message }}</span>
          <span class="badge" :class="runStatusBadge(job.status)">{{ job.status }}</span>
        </p>
        <div class="progress-bar">
          <div class="progress-bar__fill" :style="{ width: `${job.progress}%` }" />
        </div>
      </div>
    </div>

    <div class="wf-workspace">
      <div class="panel wf-canvas-panel">
        <div class="panel__header">
          <span>流程画布</span>
          <span v-if="graph" class="panel__header-count">{{ graph.name }}</span>
        </div>
        <div class="panel__body">
          <WorkflowGraph
            v-if="graph"
            :nodes="canvasNodes"
            :edges="canvasEdges"
            :node-statuses="nodeStatuses"
            :active-node-id="activeNodeId"
            :editable="isEditable"
            @select-node="activeNodeId = $event || null"
            @graph-change="onGraphChange"
          />
          <p v-else class="empty-state empty-state--compact">无工作流，点击「新建」创建</p>
        </div>
      </div>

      <div class="panel wf-side-panel">
        <div class="panel__header">
          <span>{{ selectedNode && isEditable ? "节点属性" : "节点状态" }}</span>
        </div>
        <div class="panel__body">
          <template v-if="selectedNode && isEditable">
            <div class="kv-list">
              <label class="form-field">
                <span>ID</span>
                <input :value="selectedNode.node_id" disabled />
              </label>
              <label class="form-field">
                <span>类型</span>
                <input :value="selectedNode.node_type" disabled />
              </label>
              <label class="form-field">
                <span>标签</span>
                <input v-model="selectedNode.label" />
              </label>
              <label v-if="needsDataType" class="form-field">
                <span>数据类型</span>
                <select v-model="selectedNode.data_type">
                  <option :value="null">— 选择 —</option>
                  <option v-for="t in dataTypes" :key="t.data_type" :value="t.data_type">
                    {{ t.label }}
                  </option>
                </select>
              </label>
              <label v-if="selectedNode.node_type === 'collect'" class="form-field">
                <span>数据源</span>
                <select v-model="selectedNode.source_id">
                  <option :value="null">— 选择 —</option>
                  <option v-for="s in sources" :key="s.id" :value="s.id">
                    {{ s.name }} ({{ s.provider }})
                  </option>
                </select>
              </label>
            </div>
            <button type="button" class="btn btn--primary btn--sm" :disabled="busy" @click="saveNodeProps">
              保存节点
            </button>
          </template>
          <div v-else-if="nodeRuns.length" class="wf-node-list">
            <div
              v-for="n in nodeRuns"
              :key="n.id"
              class="wf-node-item"
              :class="{ active: activeNodeId === n.node_id }"
              @click="activeNodeId = n.node_id"
            >
              <div>
                <div class="wf-node-item__label">{{ n.label || n.node_id }}</div>
                <div class="wf-node-item__type">{{ n.message || n.node_type }}</div>
              </div>
              <span class="badge" :class="runStatusBadge(n.status)">{{ n.status }}</span>
            </div>
          </div>
          <p v-else class="empty-state empty-state--compact">选择运行记录或节点</p>
        </div>
      </div>
    </div>

    <div class="panel wf-bottom-band">
      <div class="panel__header">
        <span>运行历史</span>
        <div class="btn-group">
          <span class="panel__header-count">{{ runsTotal }} 条</span>
          <button type="button" class="btn btn--ghost btn--sm" :disabled="runsSkip === 0" @click="prevRunsPage">
            上一页
          </button>
          <button
            type="button"
            class="btn btn--ghost btn--sm"
            :disabled="runsSkip + runsLimit >= runsTotal"
            @click="nextRunsPage"
          >
            下一页
          </button>
        </div>
      </div>
      <div class="panel__body panel__body--flush">
        <table v-if="runs.length" class="data-table">
          <thead>
            <tr>
              <th>Run</th>
              <th>状态</th>
              <th>触发</th>
              <th>Job</th>
              <th>开始</th>
              <th>结束</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="run in runs"
              :key="run.id"
              :class="{ 'row-active': selectedRunId === run.id }"
              @click="selectRun(run.id)"
            >
              <td class="numeric">#{{ run.id }}</td>
              <td>
                <span class="badge" :class="runStatusBadge(run.status)">{{ run.status }}</span>
              </td>
              <td>{{ run.trigger_type }}</td>
              <td class="numeric">{{ run.job_id ?? "—" }}</td>
              <td>{{ formatTime(run.started_at) }}</td>
              <td>{{ formatTime(run.finished_at) }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="empty-state empty-state--compact">暂无运行记录</p>
      </div>
    </div>
  </div>
</template>
