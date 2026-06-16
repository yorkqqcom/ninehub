<script setup lang="ts">
import { useUiStore } from "@/stores/ui";

const ui = useUiStore();
</script>

<template>
  <div
    v-if="ui.message"
    class="toast"
    :class="`toast--${ui.message.kind}`"
    role="status"
  >
    {{ ui.message.text }}
  </div>
</template>
