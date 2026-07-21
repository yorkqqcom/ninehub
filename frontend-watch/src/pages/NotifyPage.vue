<template>
  <div>
    <div class="page-header">
      <div>
        <h1 class="page-header__title">Hermes 外发</h1>
        <p class="page-header__desc">
          将盯盘 quote_alert 推送到 Hermes Gateway Webhook（须 admin；URL 与 Secret 成对）
        </p>
      </div>
    </div>

    <div v-if="!auth.isAdmin" class="panel">
      <p class="muted">当前账号无管理员权限，无法配置平台级 Hermes 外发。</p>
    </div>

    <div v-else class="panel">
      <h2>Webhook 配置</h2>
      <p class="muted webhook-hint">
        配置写入平台 settings（DB 优先，环境变量回退）。Secret 留空表示保留原值。
      </p>
      <div class="row form-wrap">
        <label class="field">
          <span class="muted">Webhook URL</span>
          <input
            v-model="webhookUrl"
            class="input-w-lg"
            type="url"
            placeholder="http://127.0.0.1:8644/webhooks/ninehub-watch"
            autocomplete="off"
          />
        </label>
        <label class="field">
          <span class="muted">Secret</span>
          <input
            v-model="webhookSecret"
            class="input-w-md"
            type="password"
            :placeholder="
              settings?.watch_alert_webhook_secret_configured ? '留空保留原密钥' : 'HMAC secret'
            "
            autocomplete="new-password"
          />
        </label>
        <label class="field">
          <span class="muted">签名版本</span>
          <select v-model="webhookVersion" class="input-w-sm">
            <option value="v2">v2（推荐）</option>
            <option value="v1">v1（旧网关）</option>
          </select>
        </label>
      </div>
      <div class="row" style="margin-top: 12px; gap: 8px; flex-wrap: wrap">
        <span class="pill" :class="settings?.watch_alert_webhook_active_source === 'none' ? '' : 'pill--ok'">
          生效来源: {{ sourceLabel(settings?.watch_alert_webhook_active_source) }}
        </span>
        <span v-if="settings?.env_watch_alert_webhook_configured" class="pill">env 已配置</span>
        <span v-if="settings?.watch_alert_webhook_secret_configured" class="pill">
          Secret {{ settings.watch_alert_webhook_secret_masked }}
        </span>
      </div>
      <div class="row" style="margin-top: 16px">
        <button
          class="btn btn--primary"
          type="button"
          :disabled="saving"
          aria-label="保存 Hermes 外发配置"
          @click="saveWebhook"
        >
          保存外发配置
        </button>
        <button
          class="btn btn--secondary"
          type="button"
          :disabled="
            testing ||
            saving ||
            !settings ||
            settings.watch_alert_webhook_active_source === 'none'
          "
          aria-label="发送 Hermes webhook 测试"
          @click="testWebhook"
        >
          发送测试
        </button>
        <button
          class="btn btn--ghost"
          type="button"
          :disabled="saving || testing"
          aria-label="清空 Hermes 外发配置"
          @click="clearWebhook"
        >
          清空配置
        </button>
      </div>
      <p v-if="msg" class="muted" style="margin-top: 12px">{{ msg }}</p>
      <p v-if="err" class="err-text">{{ err }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import { apiRequest } from "@/api/client";
import { useAuthStore } from "@/stores/auth";

type PlatformSettings = {
  watch_alert_webhook_url: string | null;
  watch_alert_webhook_secret_masked: string | null;
  watch_alert_webhook_secret_configured: boolean;
  watch_alert_webhook_signature_version: string;
  watch_alert_webhook_active_source: "db" | "env" | "none";
  env_watch_alert_webhook_configured: boolean;
};

const auth = useAuthStore();
const settings = ref<PlatformSettings | null>(null);
const webhookUrl = ref("");
const webhookSecret = ref("");
const webhookVersion = ref<"v1" | "v2">("v2");
const saving = ref(false);
const testing = ref(false);
const msg = ref("");
const err = ref("");

function sourceLabel(source: string | undefined) {
  if (source === "db") return "数据库";
  if (source === "env") return "环境变量";
  return "未配置";
}

function syncForm(data: PlatformSettings) {
  webhookUrl.value = data.watch_alert_webhook_url ?? "";
  webhookSecret.value = "";
  webhookVersion.value =
    data.watch_alert_webhook_signature_version === "v1" ? "v1" : "v2";
}

async function loadSettings() {
  settings.value = await apiRequest<PlatformSettings>("/api/v1/platform/settings");
  syncForm(settings.value);
}

async function saveWebhook() {
  if (!auth.isAdmin || saving.value) return;
  saving.value = true;
  msg.value = "";
  err.value = "";
  try {
    const body: Record<string, string> = {
      watch_alert_webhook_url: webhookUrl.value.trim(),
      watch_alert_webhook_signature_version: webhookVersion.value,
    };
    const secret = webhookSecret.value.trim();
    if (secret) body.watch_alert_webhook_secret = secret;
    settings.value = await apiRequest<PlatformSettings>("/api/v1/platform/settings", {
      method: "PUT",
      body: JSON.stringify(body),
    });
    syncForm(settings.value);
    msg.value = "外发配置已保存";
  } catch (e) {
    err.value = e instanceof Error ? e.message : String(e);
  } finally {
    saving.value = false;
  }
}

async function clearWebhook() {
  if (!auth.isAdmin || saving.value) return;
  if (!window.confirm("确认清空 Hermes 外发配置？（将回退到环境变量）")) return;
  saving.value = true;
  msg.value = "";
  err.value = "";
  try {
    settings.value = await apiRequest<PlatformSettings>("/api/v1/platform/settings", {
      method: "PUT",
      body: JSON.stringify({ watch_alert_webhook_clear: true }),
    });
    syncForm(settings.value);
    msg.value = "外发配置已清空";
  } catch (e) {
    err.value = e instanceof Error ? e.message : String(e);
  } finally {
    saving.value = false;
  }
}

async function testWebhook() {
  if (!auth.isAdmin || testing.value) return;
  testing.value = true;
  msg.value = "";
  err.value = "";
  try {
    const data = await apiRequest<{
      ok: boolean;
      status_code: number | null;
      active_source: string;
      detail: string;
    }>("/api/v1/platform/watch-alert-webhook/test", { method: "POST" });
    if (data.ok) {
      msg.value = `测试成功（${data.active_source} · HTTP ${data.status_code}）`;
    } else {
      err.value = `测试失败：${data.detail}`;
    }
  } catch (e) {
    err.value = e instanceof Error ? e.message : String(e);
  } finally {
    testing.value = false;
  }
}

onMounted(async () => {
  try {
    if (!auth.role) await auth.hydrateMe();
    if (auth.isAdmin) await loadSettings();
  } catch (e) {
    err.value = e instanceof Error ? e.message : String(e);
  }
});
</script>

<style scoped>
.webhook-hint {
  margin: 0 0 12px;
}
.form-wrap {
  align-items: flex-end;
  flex-wrap: wrap;
  gap: 12px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.input-w-md {
  min-width: 200px;
  max-width: 280px;
}
.input-w-lg {
  min-width: 280px;
  max-width: 420px;
}
.pill {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid var(--color-border);
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}
.pill--ok {
  border-color: var(--color-ok-border, var(--color-border));
  color: var(--color-ok-text, var(--color-text));
}
</style>
