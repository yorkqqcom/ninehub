<script setup lang="ts">

import { computed, onMounted, ref, watch } from "vue";

import { apiRequest } from "@/api/client";

import type { DataSource, PageResponse } from "@/api/types";

import PageHeader from "@/components/PageHeader.vue";

import { useAuthStore } from "@/stores/auth";

import { useUiStore } from "@/stores/ui";



const auth = useAuthStore();

const ui = useUiStore();

const sources = ref<DataSource[]>([]);

const form = ref({

  name: "",

  provider: "tushare",

  token: "",

  account_points: 120 as number | "",

  max_calls_per_minute: "" as number | "",

});

const editingId = ref<number | null>(null);

const verifying = ref(false);

const saving = ref(false);



const isTushare = computed(() => form.value.provider === "tushare");



const canSave = computed(() => {

  if (!form.value.name.trim()) return false;

  if (isTushare.value) {

    const hasToken = Boolean(form.value.token.trim()) || editingId.value !== null;

    const pts = Number(form.value.account_points);

    if (!hasToken && (form.value.account_points === "" || Number.isNaN(pts) || pts < 0)) {

      return false;

    }

    if (hasToken && form.value.account_points !== "" && (Number.isNaN(pts) || pts < 0)) {

      return false;

    }

  }

  const maxCalls = form.value.max_calls_per_minute;

  if (

    isTushare.value &&

    maxCalls !== "" &&

    (Number.isNaN(Number(maxCalls)) || Number(maxCalls) < 1)

  ) {

    return false;

  }

  return true;

});



const tierHint = computed(() => {

  const pts = Number(form.value.account_points) || 0;

  if (pts >= 5000) return "5000+ 积分 → 约 500 次/分钟";

  if (pts >= 2000) return "2000+ 积分 → 约 200 次/分钟";

  if (pts >= 120) return "120+ 积分 → 约 50 次/分钟";

  return "请填写 Tushare 账户积分，或选择预设档位";

});



onMounted(() => void loadSources());

watch(
  () => form.value.provider,
  (provider) => {
    if (provider === "akshare") {
      form.value.account_points = "";
      form.value.max_calls_per_minute = "";
    } else if (form.value.account_points === "") {
      form.value.account_points = 120;
    }
  },
);



async function loadSources() {

  const data = await apiRequest<PageResponse<DataSource>>("/api/v1/sources?limit=100");

  sources.value = data.items;

}



function buildConfig() {

  const config: Record<string, unknown> = {};

  if (form.value.token.trim()) config.token = form.value.token.trim();

  if (isTushare.value) {

    const pts = Number(form.value.account_points);

    if (!Number.isNaN(pts)) config.account_points = pts;

    const maxCalls = Number(form.value.max_calls_per_minute);

    if (form.value.max_calls_per_minute !== "" && !Number.isNaN(maxCalls)) {

      config.max_calls_per_minute = maxCalls;

    }

  }

  return config;

}



function resetForm() {

  form.value = {

    name: "",

    provider: "tushare",

    token: "",

    account_points: 120,

    max_calls_per_minute: "",

  };

  editingId.value = null;

}



async function saveSource() {

  if (!auth.isAdmin || !canSave.value || saving.value) return;

  saving.value = true;

  try {

    const payload = {

      name: form.value.name.trim(),

      provider: form.value.provider,

      config: buildConfig(),

    };

    if (editingId.value) {

      await apiRequest(`/api/v1/sources/${editingId.value}`, {

        method: "PUT",

        body: JSON.stringify(payload),

      });

      ui.showMessage("数据源已更新", "success");

    } else {

      await apiRequest("/api/v1/sources", {

        method: "POST",

        body: JSON.stringify(payload),

      });

      ui.showMessage("数据源已创建", "success");

    }

    resetForm();

    await loadSources();

  } catch (e) {

    ui.showMessage(e instanceof Error ? e.message : String(e), "error");

  } finally {

    saving.value = false;

  }

}



function startEdit(source: DataSource) {

  editingId.value = source.id;

  form.value = {

    name: source.name,

    provider: source.provider,

    token: "",

    account_points: source.config.account_points ?? source.quota?.account_points ?? 120,

    max_calls_per_minute: source.config.max_calls_per_minute ?? "",

  };

}



async function verifySource(sourceId: number, provider: string) {

  verifying.value = true;

  try {

    const res = await apiRequest<{

      ok: boolean;

      message: string;

      quota?: DataSource["quota"];

    }>("/api/v1/sources/verify", {

      method: "POST",

      body: JSON.stringify({ source_id: sourceId, provider }),

    });

    const quotaMsg = res.quota

      ? ` · 积分 ${res.quota.account_points} · ${res.quota.max_calls_per_minute} 次/分`

      : "";

    ui.showMessage(res.message + quotaMsg, res.ok ? "success" : "error");

  } catch (e) {

    ui.showMessage(e instanceof Error ? e.message : String(e), "error");

  } finally {

    verifying.value = false;

  }

}



async function deleteSource(id: number) {

  if (!confirm("确认删除该数据源？")) return;

  await apiRequest(`/api/v1/sources/${id}`, { method: "DELETE" });

  ui.showMessage("已删除", "success");

  if (editingId.value === id) resetForm();

  await loadSources();

}



function setPointsPreset(points: number) {

  form.value.account_points = points;

  form.value.max_calls_per_minute = "";

}

</script>



<template>

  <PageHeader

    title="数据源"

    description="Tushare 须配置账户积分与频次上限；可按档位预设"

  />



  <div v-if="auth.isAdmin" class="panel">

    <div class="panel__header">{{ editingId ? "编辑数据源" : "新建数据源" }}</div>

    <div class="panel__body page-toolbar">

      <label class="form-field">

        <span>名称</span>

        <input v-model="form.name" class="input-w-md" placeholder="Tushare 主账号" required />

      </label>

      <label class="form-field">

        <span>提供商</span>

        <select v-model="form.provider" class="input-w-md">

          <option value="tushare">Tushare</option>

          <option value="akshare">AkShare</option>

        </select>

      </label>

      <label class="form-field">

        <span>Token</span>

        <input

          v-model="form.token"

          class="input-w-lg"

          type="password"

          :placeholder="editingId ? '留空保留原 token' : '留空则用环境变量'"

        />

      </label>

      <template v-if="isTushare">

        <label class="form-field">

          <span>账户积分</span>

          <input

            v-model.number="form.account_points"

            class="input-w-sm numeric"

            type="number"

            min="0"

            placeholder="120"

          />

        </label>

        <label class="form-field">

          <span>频次上限/分</span>

          <input

            v-model.number="form.max_calls_per_minute"

            class="input-w-sm numeric"

            type="number"

            min="1"

            placeholder="自动推导"

          />

        </label>

        <div class="btn-group">

          <button type="button" class="btn btn--ghost btn--sm" @click="setPointsPreset(120)">

            120

          </button>

          <button type="button" class="btn btn--ghost btn--sm" @click="setPointsPreset(2000)">

            2000

          </button>

          <button type="button" class="btn btn--ghost btn--sm" @click="setPointsPreset(5000)">

            5000

          </button>

        </div>

      </template>

      <button type="button" class="btn btn--primary" :disabled="!canSave || saving" @click="saveSource">

        {{ saving ? "保存中…" : editingId ? "保存" : "创建" }}

      </button>

      <button v-if="editingId" type="button" class="btn btn--ghost" @click="resetForm">

        取消

      </button>

    </div>

    <p v-if="isTushare" class="panel__hint">{{ tierHint }}</p>

  </div>



  <div class="panel">

    <div class="panel__header">

      <span>数据源列表</span>

      <span class="panel__header-count">{{ sources.length }} 个</span>

    </div>

    <div class="panel__body panel__body--flush">

      <table v-if="sources.length" class="data-table">

        <thead>

          <tr>

            <th>ID</th>

            <th>名称</th>

            <th>提供商</th>

            <th>Token</th>

            <th>账户积分</th>

            <th>频次/分</th>

            <th>状态</th>

            <th v-if="auth.isAdmin">操作</th>

          </tr>

        </thead>

        <tbody>

          <tr v-for="s in sources" :key="s.id">

            <td class="numeric">{{ s.id }}</td>

            <td>{{ s.name }}</td>

            <td>{{ s.provider }}</td>

            <td><code>{{ s.config.token || "—" }}</code></td>

            <td class="numeric">

              <template v-if="s.provider === 'tushare' && s.quota">

                {{ s.quota.account_points }}

                <span v-if="!s.quota.account_points_from_source" class="badge badge--muted">

                  环境变量

                </span>

              </template>

              <span v-else>—</span>

            </td>

            <td class="numeric">

              {{ s.provider === "tushare" && s.quota ? s.quota.max_calls_per_minute : "—" }}

            </td>

            <td><span class="badge badge--ok">{{ s.status }}</span></td>

            <td v-if="auth.isAdmin">

              <div class="btn-group">

                <button type="button" class="btn btn--ghost btn--sm" @click="startEdit(s)">

                  编辑

                </button>

                <button

                  type="button"

                  class="btn btn--ghost btn--sm"

                  :disabled="verifying"

                  @click="verifySource(s.id, s.provider)"

                >

                  校验

                </button>

                <button type="button" class="btn btn--ghost btn--sm" @click="deleteSource(s.id)">

                  删除

                </button>

              </div>

            </td>

          </tr>

        </tbody>

      </table>

      <p v-else class="empty-state empty-state--compact">暂无数据源</p>

    </div>

  </div>

</template>



<style scoped>

.panel__hint {

  padding: 0 1rem 1rem;

  margin: 0;

  font-size: 0.875rem;

  color: var(--color-text-muted, #888);

}

</style>


