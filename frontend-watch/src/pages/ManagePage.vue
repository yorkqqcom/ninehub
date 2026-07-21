<template>
  <div>
    <div class="panel">
      <div class="row" style="justify-content: space-between">
        <h2 style="margin: 0">盯盘管理</h2>
        <div class="row">
          <span class="muted">revision {{ profile?.config_revision ?? 0 }}</span>
          <button class="btn btn--primary" type="button" :disabled="!profile" @click="toggleEnabled">
            {{ profile?.enabled ? "关闭盯盘" : "启用盯盘" }}
          </button>
          <button class="btn btn--secondary" type="button" :disabled="!profile" @click="clearCooldown">
            清除冷却
          </button>
          <button class="btn btn--secondary" type="button" @click="saveConfig">保存配置</button>
        </div>
      </div>
      <div class="row" style="margin-top: 12px">
        <label class="muted">配置</label>
        <select v-model="selectedProfileId" @change="onProfileSelect">
          <option v-for="p in profiles" :key="p.id" :value="p.id">
            {{ p.name }}{{ p.enabled ? " · 启用" : "" }}
          </option>
        </select>
        <input v-model="newProfileName" class="input-w-sm" style="width: 8rem" placeholder="新名称" />
        <button
          class="btn btn--secondary"
          type="button"
          :disabled="profiles.length >= 5"
          @click="createProfile"
        >
          新建
        </button>
        <span v-if="profiles.length >= 5" class="muted">已达上限 5</span>
      </div>
      <p v-if="msg" class="muted">{{ msg }}</p>
      <p v-if="err" class="err-text">{{ err }}</p>
    </div>

    <div class="panel">
      <h2>标的</h2>
      <div class="row">
        <input
          v-model="newSymbol"
          placeholder="600519 或 600519.SH"
          @keyup.enter="addTarget"
        />
        <button class="btn btn--primary" type="button" @click="addTarget">添加</button>
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th>代码</th>
            <th>启用</th>
            <th>备注</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <tr v-for="(t, idx) in targets" :key="t.symbol">
            <td>{{ t.symbol }}</td>
            <td><input v-model="t.enabled" type="checkbox" @change="markDirty" /></td>
            <td><input v-model="t.note" @input="markDirty" /></td>
            <td>
              <button class="btn btn--danger btn--sm" type="button" @click="removeTarget(idx)">删</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="panel">
      <h2>规则（简易）</h2>
      <div class="row">
        <label class="muted">轮询间隔(秒)</label>
        <input
          v-model.number="pollInterval"
          class="input-w-sm"
          type="number"
          min="3"
          max="3600"
          @input="markDirty"
        />
      </div>
      <div class="row" style="margin-top: 12px">
        <select v-model="ruleType">
          <option value="pct_change_from_pre_close">相对昨收涨跌幅</option>
          <option value="pct_change_from_open">相对开盘涨跌幅</option>
          <option value="pct_change_from_ref">相对参考价涨跌幅</option>
          <option value="last_price">最新价</option>
          <option value="amplitude">振幅</option>
          <option value="volume_ratio">量比(增量)</option>
          <option value="price_velocity">涨速</option>
        </select>
        <select v-model="direction">
          <option value="above">高于</option>
          <option value="below">低于</option>
        </select>
        <input v-model.number="threshold" type="number" step="0.01" />
        <template v-if="ruleType === 'pct_change_from_ref'">
          <label class="muted">参考价</label>
          <input v-model.number="refPrice" type="number" step="0.01" min="0.01" />
        </template>
        <template v-if="ruleType === 'price_velocity'">
          <label class="muted">窗口(秒)</label>
          <input v-model.number="windowSeconds" class="input-w-sm" type="number" min="1" />
        </template>
        <template v-if="ruleType === 'volume_ratio'">
          <label class="muted">窗口(秒)</label>
          <input v-model.number="volumeWindowSeconds" class="input-w-sm" type="number" min="1" />
        </template>
        <select v-model="cooldownMode">
          <option value="interval">间隔冷却</option>
          <option value="session">当日仅一次</option>
        </select>
        <input
          v-model.number="cooldownSeconds"
          class="input-w-sm"
          type="number"
          min="0"
          title="冷却秒数"
        />
        <span class="muted">{{ thresholdHint }}</span>
        <button class="btn btn--primary" type="button" @click="addRule">添加规则并绑定全部标的</button>
      </div>

      <div class="row" style="margin-top: 12px">
        <label class="muted">组合规则</label>
        <select v-model="compositeOp">
          <option value="and">AND</option>
          <option value="or">OR</option>
        </select>
        <select v-model="childA">
          <option value="">子规则 A</option>
          <option v-for="r in basicRules" :key="r.rule_id" :value="r.rule_id">{{ r.name }}</option>
        </select>
        <select v-model="childB">
          <option value="">子规则 B</option>
          <option v-for="r in basicRules" :key="'b-' + r.rule_id" :value="r.rule_id">
            {{ r.name }}
          </option>
        </select>
        <label class="muted">时段 after</label>
        <input v-model="tfAfter" class="input-w-sm" placeholder="09:30" />
        <label class="muted">before</label>
        <input v-model="tfBefore" class="input-w-sm" placeholder="15:00" />
        <label class="muted">
          <input v-model="suppressChild" type="checkbox" />
          组合触发时抑制子规则
        </label>
        <button
          class="btn btn--primary"
          type="button"
          :disabled="basicRules.length < 2"
          @click="addComposite"
        >
          添加组合
        </button>
        <span class="muted">同日 HH:MM，勿跨午夜</span>
      </div>

      <table class="data-table" style="margin-top: 12px">
        <thead>
          <tr>
            <th>规则</th>
            <th>类型</th>
            <th>条件</th>
            <th>冷却</th>
            <th />
          </tr>
        </thead>
        <tbody>
          <tr v-for="(r, idx) in rules" :key="r.rule_id">
            <td>{{ r.name }}</td>
            <td>{{ r.kind }}</td>
            <td class="muted">
              <template v-if="r.kind === 'basic'">
                {{ r.condition?.rule_type }} {{ r.condition?.direction }}
                {{ r.condition?.threshold }}
                <template v-if="r.condition?.extra_json?.ref_price">
                  ref={{ r.condition.extra_json.ref_price }}
                </template>
              </template>
              <template v-else>
                {{ r.operator }} [{{ (r.children || []).join(", ") }}]
                <template v-if="r.time_filter">
                  · {{ r.time_filter.after || "" }}–{{ r.time_filter.before || "" }}
                </template>
              </template>
            </td>
            <td class="muted">{{ r.cooldown_mode }} / {{ r.cooldown_seconds }}s</td>
            <td>
              <button class="btn btn--danger btn--sm" type="button" @click="removeRule(idx)">删</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { onBeforeRouteLeave } from "vue-router";
import { apiRequest, ApiError } from "@/api/client";

type Target = { symbol: string; enabled: boolean; note: string };
type TimeFilter = { after?: string; before?: string };
type Rule = {
  rule_id: string;
  kind: string;
  name: string;
  enabled: boolean;
  cooldown_seconds: number;
  cooldown_mode: string;
  condition?: {
    rule_type: string;
    direction: string;
    threshold: number;
    extra_json?: Record<string, unknown>;
  };
  children?: string[];
  operator?: string;
  time_filter?: TimeFilter | null;
  suppress_child_independent_when_composite?: boolean;
};
type Binding = {
  binding_id: string;
  rule_id: string;
  scope: { type: string; symbols?: string[] };
  enabled: boolean;
};
type Profile = {
  id: number;
  name: string;
  enabled: boolean;
  config_revision: number;
  config_json: {
    poll_interval_seconds?: number;
    targets?: Target[];
    rule_catalog?: Rule[];
    bindings?: Binding[];
  };
};

const profiles = ref<Profile[]>([]);
const selectedProfileId = ref<number | null>(null);
const profile = ref<Profile | null>(null);
const targets = ref<Target[]>([]);
const rules = ref<Rule[]>([]);
const bindings = ref<Binding[]>([]);
const pollInterval = ref(10);
const dirty = ref(false);

const newSymbol = ref("");
const newProfileName = ref("");
const ruleType = ref("pct_change_from_pre_close");
const direction = ref("above");
const threshold = ref(0.03);
const refPrice = ref(0);
const windowSeconds = ref(60);
const volumeWindowSeconds = ref(60);
const cooldownMode = ref("interval");
const cooldownSeconds = ref(300);

const compositeOp = ref("and");
const childA = ref("");
const childB = ref("");
const tfAfter = ref("");
const tfBefore = ref("");
const suppressChild = ref(true);

const msg = ref("");
const err = ref("");

const basicRules = computed(() => rules.value.filter((r) => r.kind === "basic"));

const thresholdHint = computed(() => {
  if (ruleType.value === "price_velocity") return "阈值≈每秒涨跌幅小数";
  if (ruleType.value === "volume_ratio") return "阈值为比值";
  if (ruleType.value === "last_price") return "阈值为价格";
  return "涨跌幅类为小数（0.03=3%）";
});

function markDirty() {
  dirty.value = true;
}

function normalizeSymbol(raw: string): string {
  const t = raw.trim().toUpperCase();
  if (/^\d{6}\.(SH|SZ)$/.test(t)) return t;
  if (/^\d{6}$/.test(t)) {
    if (/^[569]/.test(t)) return `${t}.SH`;
    if (/^[03]/.test(t)) return `${t}.SZ`;
  }
  throw new Error("无效代码");
}

function hydrate(p: Profile) {
  profile.value = p;
  selectedProfileId.value = p.id;
  const cfg = p.config_json || {};
  targets.value = (cfg.targets || []).map((t) => ({
    symbol: t.symbol,
    enabled: t.enabled !== false,
    note: t.note || "",
  }));
  rules.value = structuredClone(cfg.rule_catalog || []);
  bindings.value = structuredClone(cfg.bindings || []);
  pollInterval.value = cfg.poll_interval_seconds || 10;
  dirty.value = false;
}

async function loadProfiles(preferId?: number | null) {
  err.value = "";
  const list = await apiRequest<Profile[]>("/api/v1/watch/profiles");
  profiles.value = list;
  let p: Profile | undefined;
  const want = preferId ?? selectedProfileId.value;
  if (want != null) p = list.find((x) => Number(x.id) === Number(want));
  if (!p) p = list[0];
  if (!p) {
    p = await apiRequest<Profile>("/api/v1/watch/profiles/ensure-default", { method: "POST" });
    profiles.value = await apiRequest<Profile[]>("/api/v1/watch/profiles");
  }
  hydrate(p);
}

function confirmLeaveDirty(): boolean {
  if (!dirty.value) return true;
  return window.confirm("有未保存修改，切换将丢失，是否继续？");
}

async function onProfileSelect() {
  const id = Number(selectedProfileId.value);
  if (!confirmLeaveDirty()) {
    selectedProfileId.value = profile.value?.id ?? null;
    return;
  }
  const p = profiles.value.find((x) => Number(x.id) === id);
  if (p) hydrate(p);
}

async function createProfile() {
  if (!confirmLeaveDirty()) return;
  err.value = "";
  const name = (newProfileName.value || "profile").trim().slice(0, 128);
  try {
    const created = await apiRequest<Profile>("/api/v1/watch/profiles", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    newProfileName.value = "";
    await loadProfiles(created.id);
    msg.value = `已创建 ${created.name}`;
  } catch (e) {
    err.value = e instanceof ApiError ? e.message : "创建失败";
  }
}

function removeTarget(idx: number) {
  targets.value.splice(idx, 1);
  markDirty();
}

function addTarget() {
  try {
    const symbol = normalizeSymbol(newSymbol.value);
    if (targets.value.some((t) => t.symbol === symbol)) return;
    targets.value.push({ symbol, enabled: true, note: "" });
    newSymbol.value = "";
    markDirty();
  } catch (e) {
    err.value = e instanceof Error ? e.message : "无效代码";
  }
}

function addRule() {
  err.value = "";
  if (ruleType.value === "pct_change_from_ref") {
    if (!(Number(refPrice.value) > 0)) {
      err.value = "相对参考价规则须填写参考价";
      return;
    }
  }
  const id = `r_${Date.now()}_${Math.floor(Math.random() * 1e6)}`;
  const extra: Record<string, unknown> = {};
  if (ruleType.value === "pct_change_from_ref") {
    extra.ref_price = Number(refPrice.value);
  }
  if (ruleType.value === "price_velocity") {
    extra.window_seconds = Number(windowSeconds.value) || 60;
  }
  if (ruleType.value === "volume_ratio") {
    extra.volume_window_seconds = Number(volumeWindowSeconds.value) || 60;
  }
  const name = `${ruleType.value}_${direction.value}_${threshold.value}`;
  rules.value.push({
    rule_id: id,
    kind: "basic",
    name,
    enabled: true,
    cooldown_seconds: Number(cooldownSeconds.value) || 0,
    cooldown_mode: cooldownMode.value,
    condition: {
      rule_type: ruleType.value,
      direction: direction.value,
      threshold: Number(threshold.value),
      extra_json: extra,
    },
  });
  bindings.value.push({
    binding_id: `b_${id}`,
    rule_id: id,
    scope: { type: "targets" },
    enabled: true,
  });
  markDirty();
}

function addComposite() {
  err.value = "";
  if (!childA.value || !childB.value || childA.value === childB.value) {
    err.value = "请选择两个不同的 basic 子规则";
    return;
  }
  const id = `c_${Date.now()}_${Math.floor(Math.random() * 1e6)}`;
  const tf: TimeFilter = {};
  if (tfAfter.value.trim()) tf.after = tfAfter.value.trim();
  if (tfBefore.value.trim()) tf.before = tfBefore.value.trim();
  const rule: Rule = {
    rule_id: id,
    kind: "composite",
    name: `composite_${compositeOp.value}`,
    enabled: true,
    cooldown_seconds: Number(cooldownSeconds.value) || 0,
    cooldown_mode: cooldownMode.value,
    operator: compositeOp.value,
    children: [childA.value, childB.value],
    suppress_child_independent_when_composite: suppressChild.value,
  };
  if (tf.after || tf.before) rule.time_filter = tf;
  rules.value.push(rule);
  bindings.value.push({
    binding_id: `b_${id}`,
    rule_id: id,
    scope: { type: "targets" },
    enabled: true,
  });
  markDirty();
}

function removeRule(idx: number) {
  const rid = rules.value[idx]?.rule_id;
  if (!rid) return;
  rules.value.splice(idx, 1);
  bindings.value = bindings.value.filter((b) => b.rule_id !== rid);

  // Cascade: drop from composite children; remove composites with <2 children
  const dropComposite: string[] = [];
  for (const r of rules.value) {
    if (r.kind !== "composite" || !r.children) continue;
    r.children = r.children.filter((c) => c !== rid);
    if (r.children.length < 2) dropComposite.push(r.rule_id);
  }
  if (dropComposite.length) {
    rules.value = rules.value.filter((r) => !dropComposite.includes(r.rule_id));
    bindings.value = bindings.value.filter((b) => !dropComposite.includes(b.rule_id));
  }
  markDirty();
}

async function saveConfig() {
  if (!profile.value) return;
  msg.value = "";
  err.value = "";
  try {
    const body = {
      expected_revision: profile.value.config_revision,
      config_json: {
        poll_interval_seconds: pollInterval.value,
        targets: targets.value,
        rule_catalog: rules.value,
        bindings: bindings.value,
      },
    };
    const updated = await apiRequest<Profile>(`/api/v1/watch/profiles/${profile.value.id}/config`, {
      method: "PUT",
      body: JSON.stringify(body),
    });
    const idx = profiles.value.findIndex((p) => p.id === updated.id);
    if (idx >= 0) profiles.value[idx] = updated;
    else profiles.value.push(updated);
    hydrate(updated);
    msg.value = "已保存";
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) {
      err.value = "配置已被修改，请刷新后重试";
      if (window.confirm("revision 冲突：是否从服务器重新加载当前配置？（本地未保存修改将丢失）")) {
        dirty.value = false;
        await loadProfiles(profile.value.id);
        msg.value = "已从服务器重新加载";
        err.value = "";
      }
    } else {
      err.value = e instanceof ApiError ? e.message : "保存失败";
    }
  }
}

async function toggleEnabled() {
  if (!profile.value) return;
  err.value = "";
  try {
    const updated = await apiRequest<Profile>(
      `/api/v1/watch/profiles/${profile.value.id}/set-enabled`,
      {
        method: "POST",
        body: JSON.stringify({ enabled: !profile.value.enabled }),
      },
    );
    // Only patch enabled — full hydrate would wipe unsaved local edits
    const idx = profiles.value.findIndex((p) => p.id === updated.id);
    if (idx >= 0) {
      profiles.value[idx] = { ...profiles.value[idx], enabled: updated.enabled };
    }
    profile.value = { ...profile.value, enabled: updated.enabled };
    msg.value = updated.enabled ? "已启用" : "已关闭";
  } catch (e) {
    err.value = e instanceof ApiError ? e.message : "操作失败";
  }
}

async function clearCooldown() {
  if (!profile.value) return;
  err.value = "";
  try {
    await apiRequest(`/api/v1/watch/profiles/${profile.value.id}/clear-cooldown`, { method: "POST" });
    msg.value = "冷却已清除";
  } catch (e) {
    err.value = e instanceof ApiError ? e.message : "清除失败";
  }
}

onMounted(() => {
  void loadProfiles();
});

onBeforeRouteLeave(() => {
  if (!dirty.value) return true;
  return window.confirm("有未保存修改，离开将丢失，是否继续？");
});
</script>
