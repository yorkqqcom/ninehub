<template>
  <div class="panel">
    <div class="row" style="justify-content: space-between">
      <h2 style="margin: 0">告警</h2>
      <button class="btn btn--secondary" type="button" @click="load">刷新</button>
    </div>
    <p class="muted">共 {{ total }} 条（保留窗内）</p>
    <table class="data-table">
      <thead>
        <tr>
          <th>时间</th>
          <th>类型</th>
          <th>代码</th>
          <th>规则</th>
          <th>详情</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="a in items" :key="a.id">
          <td>{{ fmtTime(a.created_at) }}</td>
          <td>{{ a.event_type }}</td>
          <td>{{ a.symbol || "—" }}</td>
          <td>{{ a.rule_id || "—" }}</td>
          <td class="muted">{{ a.payload_json?.message || JSON.stringify(a.payload_json) }}</td>
        </tr>
        <tr v-if="!items.length">
          <td colspan="5" class="muted">暂无告警</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { apiRequest } from "@/api/client";

type Alert = {
  id: number;
  event_type: string;
  symbol: string;
  rule_id: string;
  payload_json: { message?: string };
  created_at?: string;
};

const items = ref<Alert[]>([]);
const total = ref(0);
let refreshTimer: number | null = null;

function fmtTime(raw?: string) {
  if (!raw) return "—";
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return raw;
  return d.toLocaleString("zh-CN", { hour12: false });
}

async function load() {
  const data = await apiRequest<{ items: Alert[]; total: number }>(
    "/api/v1/watch/alerts?skip=0&limit=100",
  );
  items.value = data.items || [];
  total.value = data.total || 0;
}

onMounted(() => {
  void load();
  refreshTimer = window.setInterval(() => void load(), 30000);
});

onUnmounted(() => {
  if (refreshTimer != null) window.clearInterval(refreshTimer);
});
</script>
