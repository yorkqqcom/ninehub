<script setup lang="ts">
import type { NavIconName } from "@/config/navigation";

defineProps<{
  name: NavIconName;
  active?: boolean;
}>();
</script>

<template>
  <svg
    class="nav-icon"
    :class="{ 'nav-icon--active': active }"
    width="16"
    height="16"
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    aria-hidden="true"
  >
    <!-- dashboard -->
    <template v-if="name === 'dashboard'">
      <rect x="2" y="2" width="5" height="5" rx="1" stroke="currentColor" stroke-width="1.25" />
      <rect x="9" y="2" width="5" height="5" rx="1" stroke="currentColor" stroke-width="1.25" />
      <rect x="2" y="9" width="5" height="5" rx="1" stroke="currentColor" stroke-width="1.25" />
      <rect x="9" y="9" width="5" height="5" rx="1" stroke="currentColor" stroke-width="1.25" />
    </template>
    <!-- search -->
    <template v-else-if="name === 'search'">
      <circle cx="7" cy="7" r="4" stroke="currentColor" stroke-width="1.25" />
      <path d="M10 10L14 14" stroke="currentColor" stroke-width="1.25" stroke-linecap="round" />
    </template>
    <!-- table -->
    <template v-else-if="name === 'table'">
      <rect x="2" y="3" width="12" height="10" rx="1" stroke="currentColor" stroke-width="1.25" />
      <path d="M2 6.5H14M6 6.5V13" stroke="currentColor" stroke-width="1.25" />
    </template>
    <!-- task -->
    <template v-else-if="name === 'task'">
      <rect x="3" y="2" width="10" height="12" rx="1" stroke="currentColor" stroke-width="1.25" />
      <path d="M5.5 6L7 7.5L10.5 4" stroke="currentColor" stroke-width="1.25" stroke-linecap="round" />
      <path d="M5.5 10H10.5" stroke="currentColor" stroke-width="1.25" stroke-linecap="round" />
    </template>
    <!-- workflow -->
    <template v-else-if="name === 'workflow'">
      <circle cx="4" cy="4" r="1.75" stroke="currentColor" stroke-width="1.25" />
      <circle cx="12" cy="4" r="1.75" stroke="currentColor" stroke-width="1.25" />
      <circle cx="8" cy="12" r="1.75" stroke="currentColor" stroke-width="1.25" />
      <path d="M5.5 4.5H10.5M4.8 5.5L7.2 10.5M11.2 5.5L8.8 10.5" stroke="currentColor" stroke-width="1.25" />
    </template>
    <!-- database -->
    <template v-else-if="name === 'database'">
      <ellipse cx="8" cy="4" rx="5" ry="2" stroke="currentColor" stroke-width="1.25" />
      <path d="M3 4V12C3 13.1 5.2 14 8 14C10.8 14 13 13.1 13 12V4" stroke="currentColor" stroke-width="1.25" />
      <path d="M3 8C3 9.1 5.2 10 8 10C10.8 10 13 9.1 13 8" stroke="currentColor" stroke-width="1.25" />
    </template>
    <!-- shield -->
    <template v-else-if="name === 'shield'">
      <path
        d="M8 2L3 4V8C3 11 5.5 13.5 8 14.5C10.5 13.5 13 11 13 8V4L8 2Z"
        stroke="currentColor"
        stroke-width="1.25"
        stroke-linejoin="round"
      />
    </template>
    <!-- standards -->
    <template v-else-if="name === 'standards'">
      <path d="M4 2.5H10L12 4.5V13.5H4V2.5Z" stroke="currentColor" stroke-width="1.25" stroke-linejoin="round" />
      <path d="M7 6H9M7 8.5H9M7 11H9" stroke="currentColor" stroke-width="1.25" stroke-linecap="round" />
    </template>
    <!-- quality -->
    <template v-else-if="name === 'quality'">
      <path d="M8 2L9.5 6H14L10.5 8.5L12 13L8 10.5L4 13L5.5 8.5L2 6H6.5L8 2Z" stroke="currentColor" stroke-width="1.25" stroke-linejoin="round" />
    </template>
    <!-- settings -->
    <template v-else-if="name === 'settings'">
      <circle cx="8" cy="8" r="2" stroke="currentColor" stroke-width="1.25" />
      <path
        d="M8 2V3.5M8 12.5V14M2 8H3.5M12.5 8H14M4.2 4.2L5.3 5.3M10.7 10.7L11.8 11.8M11.8 4.2L10.7 5.3M5.3 10.7L4.2 11.8"
        stroke="currentColor"
        stroke-width="1.25"
        stroke-linecap="round"
      />
    </template>
  </svg>
</template>

<style scoped>
.nav-icon {
  flex-shrink: 0;
  width: var(--nav-icon-size);
  height: var(--nav-icon-size);
  color: var(--color-nav-icon);
}

.nav-icon--active {
  color: var(--color-nav-active-text);
}
</style>
