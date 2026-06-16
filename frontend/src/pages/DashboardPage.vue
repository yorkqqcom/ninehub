<script setup lang="ts">



import { computed, onMounted, ref } from "vue";



import { apiRequest } from "@/api/client";



import PageHeader from "@/components/PageHeader.vue";



import { useAuthStore } from "@/stores/auth";







const auth = useAuthStore();







const stats = ref({

  dataTypes: 0,

  tasks: 0,

  workflows: 0,

  proposals: 0,

  schemaReadyRate: null as number | null,

  activatedRate: null as number | null,

  driftCount: null as number | null,

});



const hasBrowseTypes = ref(false);



type PageResponse = { items: unknown[]; total?: number; browse_enabled?: boolean };







const allModules = [



  { name: "数据浏览", path: "/browse", desc: "L3 激活事实表分页查询", browseOnly: true },



  { name: "采集任务", path: "/tasks", desc: "catalog 驱动动态类型", adminOnly: true },



  { name: "工作流", path: "/workflows", desc: "DAG 编排与运行", adminOnly: false },



  { name: "TIA 工作台", path: "/tia", desc: "提案治理 · L3 流水线", adminOnly: true },



  { name: "质量监控", path: "/quality", desc: "规则引擎与报告", adminOnly: false },



  { name: "数据源", path: "/sources", desc: "Tushare / AkShare 配置", adminOnly: true },



  { name: "平台设置", path: "/settings", desc: "同步起始日 · 用户管理", adminOnly: true },



];







const modules = computed(() =>



  allModules.filter((m) => {

    if (m.browseOnly && !hasBrowseTypes.value) return false;

    return !m.adminOnly || auth.isAdmin;

  }),



);







onMounted(async () => {



  try {



    const [catalog, tasks, workflows, proposals, standards] = await Promise.allSettled([

      apiRequest<{ items: Array<{ browse_enabled: boolean }> }>("/api/v1/catalog/data-types"),

      auth.isAdmin

        ? apiRequest<PageResponse>("/api/v1/tasks?limit=1")

        : Promise.resolve({ items: [], total: 0 }),

      apiRequest<PageResponse>("/api/v1/workflows"),

      auth.isAdmin

        ? apiRequest<PageResponse>("/api/v1/tia/proposals?limit=1")

        : Promise.resolve({ items: [], total: 0 }),

      auth.isAdmin

        ? apiRequest<{ summary: { proposal_total: number; schema_ready_count: number; activated_count: number; drift_count?: number } }>(
            "/api/v1/catalog/data-standards?limit=1",
          )

        : Promise.resolve(null),

    ]);



    if (catalog.status === "fulfilled") {

      stats.value.dataTypes = catalog.value.items.length;

      hasBrowseTypes.value = catalog.value.items.some((i) => i.browse_enabled);

    }

    if (tasks.status === "fulfilled") {

      stats.value.tasks = tasks.value.total ?? tasks.value.items.length;

    }

    if (workflows.status === "fulfilled") {

      stats.value.workflows = workflows.value.total ?? workflows.value.items.length;

    }

    if (proposals.status === "fulfilled") {

      stats.value.proposals = proposals.value.total ?? proposals.value.items.length;

    }

    if (standards.status === "fulfilled" && standards.value?.summary) {

      const s = standards.value.summary;

      const total = s.proposal_total || 0;

      stats.value.schemaReadyRate = total

        ? Math.round((s.schema_ready_count / total) * 100)

        : null;

      stats.value.activatedRate = total

        ? Math.round((s.activated_count / total) * 100)

        : null;

      stats.value.driftCount = s.drift_count ?? null;

    }



  } catch {



    /* 概览统计非关键路径 */



  }



});



</script>







<template>



  <PageHeader



    title="平台概览"



    description="采集 · 浏览 · 治理 · 质检全链路"



  />







  <div class="stat-strip">



    <div class="stat-card">



      <p class="stat-card__label">数据类型</p>



      <p class="stat-card__value numeric">{{ stats.dataTypes || "—" }}</p>



    </div>



    <div class="stat-card">



      <p class="stat-card__label">采集任务</p>



      <p class="stat-card__value numeric">{{ stats.tasks || "—" }}</p>



    </div>



    <div class="stat-card">



      <p class="stat-card__label">工作流</p>



      <p class="stat-card__value numeric">{{ stats.workflows || "—" }}</p>



    </div>



    <div class="stat-card">



      <p class="stat-card__label">TIA 提案</p>



      <p class="stat-card__value numeric">{{ stats.proposals || "—" }}</p>



    </div>



    <div v-if="auth.isAdmin && stats.schemaReadyRate !== null" class="stat-card">



      <p class="stat-card__label">Schema 就绪率</p>



      <p class="stat-card__value numeric">{{ stats.schemaReadyRate }}%</p>



    </div>



    <div v-if="auth.isAdmin && stats.activatedRate !== null" class="stat-card">



      <p class="stat-card__label">L3 激活率</p>



      <p class="stat-card__value numeric">{{ stats.activatedRate }}%</p>



    </div>



    <div v-if="auth.isAdmin && stats.driftCount !== null" class="stat-card">



      <p class="stat-card__label">Schema 漂移</p>



      <p class="stat-card__value numeric">{{ stats.driftCount }}</p>



    </div>



  </div>







  <div class="panel">



    <div class="panel__header">功能模块</div>



    <div class="panel__body">



      <div class="module-grid">



        <RouterLink v-for="m in modules" :key="m.path" :to="m.path" class="module-card">



          <h2 class="module-card__title">{{ m.name }}</h2>



          <p class="module-card__desc">{{ m.desc }}</p>



          <span class="module-card__arrow">进入 →</span>



        </RouterLink>



      </div>



    </div>



  </div>



</template>


