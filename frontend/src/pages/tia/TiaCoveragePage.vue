<script setup lang="ts">
import PageHeader from "@/components/PageHeader.vue";
import CatalogCoveragePanel from "@/components/tia/CatalogCoveragePanel.vue";
</script>

<template>
  <PageHeader title="官网覆盖" description="本地 catalog 与 Tushare 官方索引对照" />
  <CatalogCoveragePanel />
</template>
