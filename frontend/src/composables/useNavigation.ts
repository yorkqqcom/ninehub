import { computed, onMounted, ref } from "vue";
import { useRoute, type RouteLocationNormalizedLoaded } from "vue-router";
import { apiRequest } from "@/api/client";
import {
  NAV_GROUPS,
  flattenNavItems,
  moduleCardPath,
  type NavGroup,
  type NavItem,
} from "@/config/navigation";
import { useAuthStore } from "@/stores/auth";

const hasBrowseTypes = ref<boolean | null>(null);
let browseFetchPromise: Promise<void> | null = null;

function isItemVisible(item: NavItem, isAdmin: boolean, browseEnabled: boolean): boolean {
  if (item.adminOnly && !isAdmin) {
    return false;
  }
  if (item.browseOnly && !browseEnabled) {
    return false;
  }
  if (item.children?.length) {
    return item.children.some((child) => isItemVisible(child, isAdmin, browseEnabled));
  }
  return Boolean(item.to);
}

function filterVisibleItems(
  items: NavItem[],
  isAdmin: boolean,
  browseEnabled: boolean,
): NavItem[] {
  return items
    .filter((item) => isItemVisible(item, isAdmin, browseEnabled))
    .map((item) => {
      if (!item.children?.length) {
        return item;
      }
      return {
        ...item,
        children: item.children.filter((child) =>
          isItemVisible(child, isAdmin, browseEnabled),
        ),
      };
    });
}

export function isNavActive(
  route: RouteLocationNormalizedLoaded,
  item: NavItem,
): boolean {
  if (item.children?.length) {
    return item.children.some((child) => isNavActive(route, child));
  }
  return route.name === item.name;
}

async function fetchBrowseTypes(): Promise<void> {
  if (hasBrowseTypes.value !== null) {
    return;
  }
  if (browseFetchPromise) {
    await browseFetchPromise;
    return;
  }
  browseFetchPromise = (async () => {
    try {
      const data = await apiRequest<{ items: Array<{ browse_enabled: boolean }> }>(
        "/api/v1/catalog/data-types",
      );
      hasBrowseTypes.value = data.items.some((i) => i.browse_enabled);
    } catch {
      hasBrowseTypes.value = false;
    }
  })();
  await browseFetchPromise;
}

export function useNavigation() {
  const auth = useAuthStore();
  const route = useRoute();

  const browseEnabled = computed(() => hasBrowseTypes.value === true);

  const visibleGroups = computed((): NavGroup[] => {
    const enabled = browseEnabled.value;
    return NAV_GROUPS.map((group) => ({
      section: group.section,
      items: filterVisibleItems(group.items, auth.isAdmin, enabled),
    })).filter((group) => group.items.length > 0);
  });

  const dashboardModules = computed(() =>
    flattenNavItems(visibleGroups.value)
      .filter((item) => item.name !== "dashboard")
      .map((item) => ({
        name: item.label,
        path: moduleCardPath(item),
        desc: item.desc ?? "",
      })),
  );

  function matchNavActive(item: NavItem): boolean {
    return isNavActive(route, item);
  }

  onMounted(async () => {
    if (!auth.role) {
      try {
        await auth.hydrate();
      } catch {
        return;
      }
    }
    await fetchBrowseTypes();
  });

  return {
    visibleGroups,
    dashboardModules,
    browseEnabled,
    hasBrowseTypes,
    matchNavActive,
  };
}

/** Set browse cache from external callers (e.g. dashboard stats fetch). */
export function setBrowseTypesEnabled(enabled: boolean): void {
  hasBrowseTypes.value = enabled;
}

/** Read cached browse state without triggering fetch. */
export function getBrowseTypesCached(): boolean | null {
  return hasBrowseTypes.value;
}

/** Ensure browse types are loaded (shared singleton fetch). */
export async function ensureBrowseTypesLoaded(): Promise<boolean> {
  await fetchBrowseTypes();
  return hasBrowseTypes.value === true;
}
