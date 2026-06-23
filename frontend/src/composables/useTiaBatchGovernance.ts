import { computed, onUnmounted, ref } from "vue";
import { apiRequest } from "@/api/client";
import { useUiStore } from "@/stores/ui";

export const BATCH_GOVERNANCE_MAX = 100;
const STORAGE_KEY = "ninehub.tiaBatchJobs";

export type BatchGovernanceKind =
  | "approve"
  | "approve_activate"
  | "activate_l3"
  | "enable_browse";

export type BatchJobRow = {
  jobId: number;
  proposalId: number;
  apiName: string;
  status: string;
  progress: number;
  message: string;
  error?: string | null;
};

export type BatchSubmitError = {
  proposalId: number;
  apiName: string;
  error: string;
};

export type BatchOpState = {
  kind: BatchGovernanceKind;
  phase: "submitting" | "running" | "done";
  total: number;
  jobRows: BatchJobRow[];
  startedAt: number;
  submitErrors: BatchSubmitError[];
};

type StoredBatch = {
  kind: BatchGovernanceKind;
  jobRows: BatchJobRow[];
  startedAt: number;
  total: number;
};

const BATCH_KIND_LABELS: Record<BatchGovernanceKind, string> = {
  approve: "批量批准",
  approve_activate: "批量批准并激活",
  activate_l3: "批量 L3 激活",
  enable_browse: "批量开通查询",
};

export function batchKindLabel(kind: BatchGovernanceKind): string {
  return BATCH_KIND_LABELS[kind];
}

export function useTiaBatchGovernance(onRefresh?: () => Promise<void>) {
  const ui = useUiStore();
  const batchOp = ref<BatchOpState | null>(null);
  let batchPollTimer: number | undefined;

  const batchBusy = computed(
    () => batchOp.value !== null && batchOp.value.phase !== "done",
  );

  const batchProgressPct = computed(() => {
    const op = batchOp.value;
    if (!op?.jobRows.length) return 0;
    const weighted = op.jobRows.reduce((sum, row) => {
      if (row.status === "success" || row.status === "failed") return sum + 100;
      return sum + (row.progress ?? 0);
    }, 0);
    return Math.round(weighted / (op.jobRows.length * 100));
  });

  const batchSummary = computed(() => {
    const op = batchOp.value;
    if (!op) return null;
    const succeeded = op.jobRows.filter((r) => r.status === "success").length;
    const failed = op.jobRows.filter((r) => r.status === "failed").length;
    const running = op.jobRows.filter(
      (r) => r.status === "pending" || r.status === "running",
    ).length;
    const queued = Math.max(0, op.total - op.jobRows.length - op.submitErrors.length);
    return {
      succeeded,
      failed,
      running,
      queued,
      submitFailed: op.submitErrors.length,
    };
  });

  function stopBatchPolling() {
    if (batchPollTimer !== undefined) {
      window.clearInterval(batchPollTimer);
      batchPollTimer = undefined;
    }
  }

  function persistBatch() {
    const op = batchOp.value;
    if (!op || op.phase !== "running" || !op.jobRows.length) {
      localStorage.removeItem(STORAGE_KEY);
      return;
    }
    const payload: StoredBatch = {
      kind: op.kind,
      jobRows: op.jobRows,
      startedAt: op.startedAt,
      total: op.total,
    };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  }

  function restoreBatch() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const stored = JSON.parse(raw) as StoredBatch;
      if (!stored.jobRows?.length) {
        localStorage.removeItem(STORAGE_KEY);
        return;
      }
      if (Date.now() - stored.startedAt > 24 * 60 * 60 * 1000) {
        localStorage.removeItem(STORAGE_KEY);
        return;
      }
      const stillRunning = stored.jobRows.some(
        (r) => r.status === "pending" || r.status === "running",
      );
      if (!stillRunning) {
        localStorage.removeItem(STORAGE_KEY);
        return;
      }
      batchOp.value = {
        kind: stored.kind,
        phase: "running",
        total: stored.total,
        jobRows: stored.jobRows,
        startedAt: stored.startedAt,
        submitErrors: [],
      };
      startBatchJobPolling();
    } catch {
      localStorage.removeItem(STORAGE_KEY);
    }
  }

  async function pollBatchJobs() {
    const op = batchOp.value;
    if (!op || op.phase !== "running") return;

    for (const row of op.jobRows) {
      if (row.status === "success" || row.status === "failed") continue;
      try {
        const data = await apiRequest<{
          status: string;
          progress?: number;
          message?: string | null;
          error?: string | null;
        }>(`/api/v1/tia/scan/${row.jobId}`);
        row.status = data.status;
        row.progress = data.progress ?? 0;
        row.message = data.message ?? "";
        row.error = data.error ?? null;
      } catch {
        /* transient poll failure */
      }
    }

    persistBatch();
    const allDone = op.jobRows.every((r) => r.status === "success" || r.status === "failed");
    if (allDone) {
      await finishBatchOp();
    }
  }

  function startBatchJobPolling() {
    stopBatchPolling();
    void pollBatchJobs();
    batchPollTimer = window.setInterval(() => void pollBatchJobs(), 1500);
  }

  async function finishBatchOp() {
    const op = batchOp.value;
    if (!op) return;
    stopBatchPolling();
    op.phase = "done";
    localStorage.removeItem(STORAGE_KEY);

    const summary = batchSummary.value;
    const label = BATCH_KIND_LABELS[op.kind];
    if (summary && (summary.failed > 0 || summary.submitFailed > 0)) {
      ui.showMessage(
        `${label}：L3 成功 ${summary.succeeded}，失败 ${summary.failed}，提交失败 ${summary.submitFailed}`,
        summary.succeeded > 0 ? "info" : "error",
      );
    } else if (op.kind === "approve") {
      ui.showMessage(`已批准 ${op.total} 条`, "success");
    } else if (op.jobRows.length) {
      ui.showMessage(`${label}：${op.jobRows.length} 条 L3 后台执行完成`, "success");
    }

    if (onRefresh) await onRefresh();
  }

  function confirmBatch(kind: BatchGovernanceKind, count: number): boolean {
    if (count > BATCH_GOVERNANCE_MAX) {
      ui.showMessage(`单次最多 ${BATCH_GOVERNANCE_MAX} 条，请缩小选择范围`, "error");
      return false;
    }
    if (count <= 1) return true;
    const label = BATCH_KIND_LABELS[kind];
    const l3Note =
      kind === "approve_activate" || kind === "activate_l3"
        ? "\n\nL3 在后台执行（含 Preflight），整体约 1–3 分钟/条。"
        : "";
    return window.confirm(`即将对 ${count} 条提案执行「${label}」。${l3Note}\n\n确认继续？`);
  }

  function beginBatch(kind: BatchGovernanceKind, total: number) {
    batchOp.value = {
      kind,
      phase: "submitting",
      total,
      jobRows: [],
      startedAt: Date.now(),
      submitErrors: [],
    };
  }

  function startBatchFromJobs(
    kind: BatchGovernanceKind,
    items: Array<{ proposalId: number; jobId: number; apiName: string }>,
    total: number,
    submitErrors: BatchSubmitError[],
  ) {
    if (!items.length) {
      batchOp.value = {
        kind,
        phase: "done",
        total,
        jobRows: [],
        startedAt: Date.now(),
        submitErrors,
      };
      void finishBatchOp();
      return;
    }
    batchOp.value = {
      kind,
      phase: "running",
      total,
      jobRows: items.map((item) => ({
        jobId: item.jobId,
        proposalId: item.proposalId,
        apiName: item.apiName,
        status: "pending",
        progress: 0,
        message: "Queued",
      })),
      startedAt: Date.now(),
      submitErrors,
    };
    persistBatch();
    startBatchJobPolling();
  }

  async function runBatchApprove(
    ids: number[],
    meta: Map<number, string>,
    autoActivate: boolean,
  ): Promise<boolean> {
    const kind: BatchGovernanceKind = autoActivate ? "approve_activate" : "approve";
    if (!confirmBatch(kind, ids.length)) return false;
    beginBatch(kind, ids.length);
    try {
      const data = await apiRequest<{
        items: unknown[];
        activate_job_ids: number[];
      }>("/api/v1/tia/proposals/batch-review", {
        method: "POST",
        body: JSON.stringify({
          proposal_ids: ids,
          status: "approved",
          note: autoActivate ? "batch approved+activate via UI" : "batch approved via UI",
          auto_activate: autoActivate,
        }),
      });
      if (autoActivate && data.activate_job_ids.length) {
        const jobItems = data.activate_job_ids.map((jobId, idx) => ({
          proposalId: ids[idx]!,
          jobId,
          apiName: meta.get(ids[idx]!) ?? `#${ids[idx]}`,
        }));
        startBatchFromJobs(kind, jobItems, ids.length, []);
        ui.showMessage(`已受理 ${jobItems.length} 条 L3 激活（后台执行）`, "success");
      } else {
        batchOp.value = {
          kind,
          phase: "done",
          total: ids.length,
          jobRows: [],
          startedAt: Date.now(),
          submitErrors: [],
        };
        await finishBatchOp();
        batchOp.value = null;
      }
      return true;
    } catch (e) {
      batchOp.value = null;
      ui.showMessage(e instanceof Error ? e.message : String(e), "error");
      return false;
    }
  }

  async function runBatchActivateL3(
    ids: number[],
    meta: Map<number, string>,
  ): Promise<boolean> {
    const kind: BatchGovernanceKind = "activate_l3";
    if (!confirmBatch(kind, ids.length)) return false;
    beginBatch(kind, ids.length);
    try {
      const data = await apiRequest<{
        succeeded: number;
        failed: number;
        items: Array<{
          proposal_id: number;
          success: boolean;
          job_id?: number;
          error?: string;
        }>;
      }>("/api/v1/tia/proposals/batch-activate", {
        method: "POST",
        body: JSON.stringify({ proposal_ids: ids }),
      });
      const submitErrors = data.items
        .filter((item) => !item.success)
        .map((item) => ({
          proposalId: item.proposal_id,
          apiName: meta.get(item.proposal_id) ?? `#${item.proposal_id}`,
          error: item.error ?? "失败",
        }));
      const jobItems = data.items
        .filter((item) => item.success && item.job_id != null)
        .map((item) => ({
          proposalId: item.proposal_id,
          jobId: item.job_id!,
          apiName: meta.get(item.proposal_id) ?? `#${item.proposal_id}`,
        }));
      startBatchFromJobs(kind, jobItems, ids.length, submitErrors);
      if (data.failed) {
        ui.showMessage(
          `已排队 ${data.succeeded} 条，提交失败 ${data.failed} 条`,
          data.succeeded > 0 ? "info" : "error",
        );
      } else {
        ui.showMessage(`已排队 ${data.succeeded} 个 L3 激活任务`, "success");
      }
      return true;
    } catch (e) {
      batchOp.value = null;
      ui.showMessage(e instanceof Error ? e.message : String(e), "error");
      return false;
    }
  }

  async function runBatchEnableBrowse(
    ids: number[],
    meta: Map<number, string>,
  ): Promise<boolean> {
    const kind: BatchGovernanceKind = "enable_browse";
    if (!confirmBatch(kind, ids.length)) return false;
    beginBatch(kind, ids.length);
    try {
      const data = await apiRequest<{
        succeeded: number;
        failed: number;
        errors: Array<{ proposal_id: number; error: string }>;
      }>("/api/v1/tia/proposals/batch-enable-browse", {
        method: "POST",
        body: JSON.stringify({ proposal_ids: ids }),
      });
      batchOp.value = {
        kind,
        phase: "done",
        total: ids.length,
        jobRows: [],
        startedAt: Date.now(),
        submitErrors: data.errors.map((item) => ({
          proposalId: item.proposal_id,
          apiName: meta.get(item.proposal_id) ?? `#${item.proposal_id}`,
          error: item.error,
        })),
      };
      if (data.failed) {
        ui.showMessage(
          `开通 ${data.succeeded} 条，跳过 ${data.failed} 条`,
          data.succeeded > 0 ? "info" : "error",
        );
      } else {
        ui.showMessage(`已批量开通数据查询 ${data.succeeded} 条`, "success");
      }
      if (onRefresh) await onRefresh();
      batchOp.value = null;
      return true;
    } catch (e) {
      batchOp.value = null;
      ui.showMessage(e instanceof Error ? e.message : String(e), "error");
      return false;
    }
  }

  async function runSingleL3Job(
    proposalId: number,
    apiName: string,
    activatePath: string,
    successMessage = "L3 激活已提交",
  ): Promise<boolean> {
    if (batchBusy.value) {
      ui.showMessage("另有批处理任务进行中，请稍候", "error");
      return false;
    }
    beginBatch("activate_l3", 1);
    try {
      const data = await apiRequest<{ job_id: number }>(activatePath, { method: "POST" });
      startBatchFromJobs(
        "activate_l3",
        [{ proposalId, jobId: data.job_id, apiName }],
        1,
        [],
      );
      ui.showMessage(successMessage, "success");
      return true;
    } catch (e) {
      batchOp.value = null;
      ui.showMessage(e instanceof Error ? e.message : String(e), "error");
      return false;
    }
  }

  async function retryBatchFailed(): Promise<boolean> {
    const op = batchOp.value;
    if (!op || op.phase !== "done") return false;
    const failedIds = op.jobRows
      .filter((row) => row.status === "failed")
      .map((row) => row.proposalId);
    if (!failedIds.length) {
      ui.showMessage("没有可重试的失败项", "error");
      return false;
    }
    const meta = new Map(failedIds.map((id) => {
      const row = op.jobRows.find((r) => r.proposalId === id);
      return [id, row?.apiName ?? `#${id}`] as const;
    }));
    batchOp.value = null;
    return runBatchActivateL3(failedIds, meta);
  }

  function dismissBatchPanel() {
    if (batchOp.value?.phase === "done") {
      batchOp.value = null;
    }
  }

  onUnmounted(() => stopBatchPolling());

  return {
    batchOp,
    batchBusy,
    batchProgressPct,
    batchSummary,
    batchKindLabel,
    restoreBatch,
    dismissBatchPanel,
    retryBatchFailed,
    runBatchApprove,
    runBatchActivateL3,
    runBatchEnableBrowse,
    runSingleL3Job,
  };
}
