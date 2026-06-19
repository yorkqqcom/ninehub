<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";
import NavIcon from "@/components/nav/NavIcon.vue";
import SidebarLink from "@/components/nav/SidebarLink.vue";
import { isNavActive } from "@/composables/useNavigation";
import type { NavItem } from "@/config/navigation";
import { useUiStore } from "@/stores/ui";

const props = defineProps<{
  item: NavItem;
}>();

const route = useRoute();
const ui = useUiStore();

const storageKey = computed(() => `ninehub.nav.expanded.${props.item.name}`);

function readExpanded(): boolean {
  const stored = localStorage.getItem(storageKey.value);
  if (stored !== null) {
    return stored === "true";
  }
  return props.item.children?.some((c) => isNavActive(route, c)) ?? true;
}

const expanded = ref(readExpanded());

const children = computed(() => props.item.children?.filter((c) => c.to) ?? []);

const parentActive = computed(() => isNavActive(route, props.item));

const defaultChildTo = computed(() => children.value[0]?.to ?? "/");

watch(
  () => route.fullPath,
  () => {
    if (parentActive.value && !ui.sidebarCollapsed) {
      expanded.value = true;
    }
  },
);

function toggleExpanded() {
  expanded.value = !expanded.value;
  localStorage.setItem(storageKey.value, String(expanded.value));
}
</script>

<template>
  <div
    class="app-sidebar__nav-group"
    :class="{
      'app-sidebar__nav-group--expanded': expanded,
      'app-sidebar__nav-group--active': parentActive,
      'app-sidebar__nav-group--collapsed': ui.sidebarCollapsed,
    }"
  >
    <RouterLink
      v-if="ui.sidebarCollapsed"
      :to="defaultChildTo"
      class="app-sidebar__link app-sidebar__link--collapsed app-sidebar__parent"
      :class="{ active: parentActive }"
      :title="item.label"
      :aria-current="parentActive ? 'page' : undefined"
    >
      <NavIcon :name="item.icon" :active="parentActive" />
    </RouterLink>
    <button
      v-else
      type="button"
      class="app-sidebar__link app-sidebar__parent"
      :class="{ active: parentActive }"
      :aria-expanded="expanded"
      @click="toggleExpanded"
    >
      <NavIcon :name="item.icon" :active="parentActive" />
      <span class="app-sidebar__label">{{ item.label }}</span>
      <svg
        class="app-sidebar__chevron"
        width="12"
        height="12"
        viewBox="0 0 12 12"
        fill="none"
        aria-hidden="true"
      >
        <path
          d="M4 2.5L8 6L4 9.5"
          stroke="currentColor"
          stroke-width="1.25"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
      </svg>
    </button>

    <div v-if="!ui.sidebarCollapsed && expanded" class="app-sidebar__submenu">
      <SidebarLink
        v-for="child in children"
        :key="child.name"
        :to="child.to!"
        :label="child.label"
        :icon="child.icon"
        :active="isNavActive(route, child)"
        sub
      />
    </div>

    <div v-if="ui.sidebarCollapsed" class="app-sidebar__flyout" role="menu">
      <div class="app-sidebar__flyout-title">{{ item.label }}</div>
      <SidebarLink
        v-for="child in children"
        :key="child.name"
        :to="child.to!"
        :label="child.label"
        :icon="child.icon"
        :active="isNavActive(route, child)"
      />
    </div>
  </div>
</template>

<style scoped>
.app-sidebar__nav-group {
  position: relative;
}

.app-sidebar__parent {
  width: 100%;
  text-align: left;
  background: transparent;
  border: none;
  cursor: pointer;
  font-family: inherit;
}

.app-sidebar__chevron {
  flex-shrink: 0;
  margin-left: auto;
  color: var(--color-text-muted);
  transition: transform var(--transition-fast);
}

.app-sidebar__nav-group--expanded .app-sidebar__chevron {
  transform: rotate(90deg);
}

.app-sidebar__submenu {
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.app-sidebar__flyout {
  display: none;
  position: absolute;
  left: calc(100% + var(--space-xs));
  top: 0;
  min-width: 160px;
  padding: var(--space-xs);
  background: var(--color-surface-elevated);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  box-shadow: var(--color-shadow-elevated);
  z-index: 100;
}

.app-sidebar__flyout-title {
  padding: var(--space-xs) var(--space-md);
  font-size: 11px;
  font-weight: 600;
  color: var(--color-nav-section);
}

.app-sidebar__nav-group--collapsed:hover .app-sidebar__flyout,
.app-sidebar__nav-group--collapsed:focus-within .app-sidebar__flyout {
  display: block;
}
</style>
