<script setup lang="ts">
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import PageHeader from "@/components/PageHeader.vue";
import DataStandardsPanel from "@/components/tia/DataStandardsPanel.vue";
import SchemaMaintenanceDrawer from "@/components/tia/SchemaMaintenanceDrawer.vue";

const route = useRoute();
const router = useRouter();
const panelRef = ref<InstanceType<typeof DataStandardsPanel> | null>(null);

const schemaMaintenanceProposalId = ref<number | null>(null);
const schemaMaintenanceApiName = ref("");

const initialApi = computed(() => {
  const api = route.query.api;
  return typeof api === "string" && api.trim() ? api.trim() : null;
});

function openProposal(proposalId: number) {
  void router.push({ name: "tia", query: { proposal: String(proposalId) } });
}

function openSchemaMaintenance(proposalId: number, apiName: string) {
  schemaMaintenanceProposalId.value = proposalId;
  schemaMaintenanceApiName.value = apiName;
}

function closeSchemaMaintenance() {
  schemaMaintenanceProposalId.value = null;
  schemaMaintenanceApiName.value = "";
}

async function onSchemaMaintenanceApplied() {
  await panelRef.value?.reload();
}
</script>

<template>
  <PageHeader title="数据标准" description="命名规范 · Schema 覆盖 · 漂移检测" />

  <DataStandardsPanel
    ref="panelRef"
    :initial-api="initialApi"
    :on-open-proposal="openProposal"
    :on-open-schema-maintenance="openSchemaMaintenance"
  />

  <SchemaMaintenanceDrawer
    :proposal-id="schemaMaintenanceProposalId"
    :api-name="schemaMaintenanceApiName"
    @close="closeSchemaMaintenance"
    @applied="onSchemaMaintenanceApplied"
  />
</template>
