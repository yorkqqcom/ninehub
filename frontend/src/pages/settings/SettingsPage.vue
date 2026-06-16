<script setup lang="ts">
import { onMounted, ref } from "vue";
import { apiRequest, getApiBase } from "@/api/client";
import type { PageResponse, PlatformSettings, UserInfo } from "@/api/types";
import PageHeader from "@/components/PageHeader.vue";
import { useAuthStore } from "@/stores/auth";
import { useUiStore } from "@/stores/ui";

const auth = useAuthStore();
const ui = useUiStore();
const apiBase = ref(getApiBase() || window.location.origin);
const health = ref("—");
const apiOk = ref(false);
const settings = ref<PlatformSettings | null>(null);
const users = ref<UserInfo[]>([]);
const editDate = ref("");
const saving = ref(false);

onMounted(async () => {
  try {
    const res = await fetch(`${apiBase.value}/health`);
    apiOk.value = res.ok;
    health.value = JSON.stringify(await res.json());
  } catch {
    health.value = "无法连接";
  }
  if (auth.isAdmin) {
    await Promise.all([loadSettings(), loadUsers()]);
  }
});

async function loadSettings() {
  settings.value = await apiRequest<PlatformSettings>("/api/v1/platform/settings");
  editDate.value = settings.value.sync_start_date;
}

async function loadUsers() {
  const data = await apiRequest<PageResponse<UserInfo>>("/api/v1/auth/users?limit=100");
  users.value = data.items;
}

async function saveSettings() {
  saving.value = true;
  try {
    settings.value = await apiRequest<PlatformSettings>("/api/v1/platform/settings", {
      method: "PUT",
      body: JSON.stringify({ sync_start_date: editDate.value }),
    });
    ui.showMessage("配置已保存", "success");
  } catch (e) {
    ui.showMessage(e instanceof Error ? e.message : String(e), "error");
  } finally {
    saving.value = false;
  }
}

async function toggleUser(user: UserInfo) {
  await apiRequest(`/api/v1/auth/users/${user.id}`, {
    method: "PATCH",
    body: JSON.stringify({ is_active: !user.is_active }),
  });
  ui.showMessage(`用户 ${user.username} 已${user.is_active ? "禁用" : "启用"}`, "success");
  await loadUsers();
}
</script>

<template>
  <PageHeader title="平台设置" description="同步配置 · 用户管理 · 健康探测" />

  <div class="stat-strip">
    <div class="stat-card">
      <p class="stat-card__label">API 状态</p>
      <p class="stat-card__value">
        <span class="badge" :class="apiOk ? 'badge--ok' : 'badge--err'">
          {{ apiOk ? "在线" : "离线" }}
        </span>
      </p>
    </div>
    <div class="stat-card">
      <p class="stat-card__label">全局同步起始日</p>
      <p class="stat-card__value">{{ settings?.sync_start_date ?? "—" }}</p>
    </div>
  </div>

  <div v-if="auth.isAdmin" class="panel">
    <div class="panel__header">同步配置 (H-01)</div>
    <div class="panel__body page-toolbar">
      <label class="form-field">
        <span>sync_start_date</span>
        <input v-model="editDate" class="input-w-md" placeholder="2010-01-01" />
      </label>
      <button type="button" class="btn btn--primary" :disabled="saving" @click="saveSettings">
        保存
      </button>
      <span v-if="settings" class="badge badge--muted">
        环境默认: {{ settings.env_sync_start_date }}
      </span>
    </div>
  </div>

  <div v-if="auth.isAdmin" class="panel">
    <div class="panel__header">用户管理 (A-05)</div>
    <div class="panel__body panel__body--flush">
      <table v-if="users.length" class="data-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>用户名</th>
            <th>角色</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="u in users" :key="u.id">
            <td class="numeric">{{ u.id }}</td>
            <td>{{ u.username }}</td>
            <td>{{ u.role }}</td>
            <td>
              <span class="badge" :class="u.is_active ? 'badge--ok' : 'badge--err'">
                {{ u.is_active ? "启用" : "禁用" }}
              </span>
            </td>
            <td>
              <button type="button" class="btn btn--ghost btn--sm" @click="toggleUser(u)">
                {{ u.is_active ? "禁用" : "启用" }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <div class="panel">
    <div class="panel__header">连接信息</div>
    <div class="panel__body">
      <div class="kv-list">
        <div class="kv-row">
          <span class="kv-row__label">API Base</span>
          <span class="kv-row__value"><code>{{ apiBase }}</code></span>
        </div>
        <div class="kv-row">
          <span class="kv-row__label">Health</span>
          <span class="kv-row__value"><code>{{ health }}</code></span>
        </div>
      </div>
    </div>
  </div>
</template>
