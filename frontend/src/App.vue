<script setup lang="ts">
import { RouterView } from "vue-router";
import ToastMessage from "@/components/ToastMessage.vue";
</script>

<template>
  <RouterView />
  <ToastMessage />
</template>
