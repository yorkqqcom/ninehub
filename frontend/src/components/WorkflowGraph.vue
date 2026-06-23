<script setup lang="ts">
import { Background } from "@vue-flow/background";
import { VueFlow, type Connection, type NodeDragEvent, type NodeMouseEvent } from "@vue-flow/core";
import { ref, watch } from "vue";

export interface GraphNode {
  node_id: string;
  node_type: string;
  label?: string | null;
  position_x: number;
  position_y: number;
  data_type?: string | null;
  source_id?: number | null;
}

export interface GraphEdge {
  source_node_id: string;
  target_node_id: string;
}

const props = defineProps<{
  nodes: GraphNode[];
  edges: GraphEdge[];
  nodeStatuses?: Record<string, string>;
  activeNodeId?: string | null;
  editable?: boolean;
}>();

const emit = defineEmits<{
  "select-node": [nodeId: string];
  "graph-change": [payload: { nodes: GraphNode[]; edges: GraphEdge[] }];
}>();

interface FlowNodeItem {
  id: string;
  label?: string;
  position: { x: number; y: number };
  class?: string;
  draggable?: boolean;
  connectable?: boolean;
}

interface FlowEdgeItem {
  id: string;
  source: string;
  target: string;
  animated?: boolean;
}

const flowNodes = ref<FlowNodeItem[]>([]);
const flowEdges = ref<FlowEdgeItem[]>([]);

const NODE_TYPE_LABELS: Record<string, string> = {
  gate: "交易日",
  collect: "采集",
  quality: "质检",
};

function toFlowNodes(nodes: GraphNode[]): FlowNodeItem[] {
  return nodes.map((n) => {
    const status = props.nodeStatuses?.[n.node_id];
    const statusClass = status ? `wf-node--status-${status}` : "";
    const activeClass = props.activeNodeId === n.node_id ? "wf-node--active" : "";
    const sub =
      (n.node_type === "collect" || n.node_type === "quality") && n.data_type
        ? `\n${n.data_type}`
        : "";
    const typeLabel = NODE_TYPE_LABELS[n.node_type] ?? n.node_type;
    return {
      id: n.node_id,
      label: `${n.label || typeLabel}${sub}`,
      position: { x: n.position_x, y: n.position_y },
      class: `wf-node wf-node--${n.node_type} ${statusClass} ${activeClass}`.trim(),
      draggable: props.editable,
      connectable: props.editable,
    };
  });
}

function toFlowEdges(edges: GraphEdge[]): FlowEdgeItem[] {
  const running = Object.values(props.nodeStatuses ?? {}).includes("running");
  return edges.map((e) => ({
    id: `${e.source_node_id}-${e.target_node_id}`,
    source: e.source_node_id,
    target: e.target_node_id,
    animated: running,
  }));
}

function emitGraph() {
  const nodes: GraphNode[] = flowNodes.value.map((n) => {
    const orig = props.nodes.find((x) => x.node_id === n.id);
    return {
      node_id: n.id,
      node_type: orig?.node_type ?? "collect",
      label: orig?.label,
      position_x: n.position.x,
      position_y: n.position.y,
      data_type: orig?.data_type,
      source_id: orig?.source_id,
    };
  });
  const edges: GraphEdge[] = flowEdges.value.map((e) => ({
    source_node_id: e.source,
    target_node_id: e.target,
  }));
  emit("graph-change", { nodes, edges });
}

watch(
  () => [props.nodes, props.edges, props.nodeStatuses, props.activeNodeId, props.editable],
  () => {
    flowNodes.value = toFlowNodes(props.nodes);
    flowEdges.value = toFlowEdges(props.edges);
  },
  { immediate: true, deep: true },
);

function onNodeClick(ev: NodeMouseEvent) {
  emit("select-node", ev.node.id);
}

function onDragStop({ node }: NodeDragEvent) {
  if (!props.editable) return;
  flowNodes.value = flowNodes.value.map((n) =>
    n.id === node.id ? { ...n, position: { ...node.position } } : n,
  );
  emitGraph();
}

function onConnect(conn: Connection) {
  if (!props.editable || !conn.source || !conn.target) return;
  const id = `${conn.source}-${conn.target}`;
  if (flowEdges.value.some((e) => e.id === id)) return;
  flowEdges.value = [
    ...flowEdges.value,
    { id, source: conn.source, target: conn.target },
  ];
  emitGraph();
}

function addNode(nodeType: string) {
  if (!props.editable) return;
  const id = `${nodeType}-${Date.now()}`;
  const count = flowNodes.value.length;
  const origNodes = props.nodes.length ? props.nodes : [];
  const newNode: GraphNode = {
    node_id: id,
    node_type: nodeType,
    label: NODE_TYPE_LABELS[nodeType] ?? nodeType,
    position_x: 80 + (count % 4) * 180,
    position_y: 80 + Math.floor(count / 4) * 120,
    data_type: nodeType !== "gate" ? null : undefined,
    source_id: nodeType === "collect" ? null : undefined,
  };
  flowNodes.value = [
    ...flowNodes.value,
    ...toFlowNodes([newNode]),
  ];
  const merged = [...origNodes, newNode];
  emit("graph-change", {
    nodes: merged,
    edges: flowEdges.value.map((e) => ({
      source_node_id: e.source,
      target_node_id: e.target,
    })),
  });
  emit("select-node", id);
}

function removeActiveNode() {
  if (!props.editable || !props.activeNodeId) return;
  const id = props.activeNodeId;
  flowNodes.value = flowNodes.value.filter((n) => n.id !== id);
  flowEdges.value = flowEdges.value.filter((e) => e.source !== id && e.target !== id);
  emitGraph();
  emit("select-node", "");
}

function removeActiveEdge() {
  if (!props.editable || !props.activeNodeId) return;
  const removed = flowEdges.value.filter(
    (e) => e.target === props.activeNodeId || e.source === props.activeNodeId,
  );
  if (!removed.length) return;
  const removeIds = new Set(removed.map((e) => e.id));
  flowEdges.value = flowEdges.value.filter((e) => !removeIds.has(e.id));
  emitGraph();
}
</script>

<template>
  <div class="wf-canvas-wrap">
    <div v-if="editable" class="wf-palette">
      <span class="wf-palette__label">添加节点</span>
      <button type="button" class="btn btn--ghost btn--sm" @click="addNode('gate')">Gate</button>
      <button type="button" class="btn btn--ghost btn--sm" @click="addNode('collect')">采集</button>
      <button type="button" class="btn btn--ghost btn--sm" @click="addNode('quality')">质检</button>
      <button
        type="button"
        class="btn btn--ghost btn--sm wf-palette__danger"
        :disabled="!activeNodeId"
        @click="removeActiveNode"
      >
        删节点
      </button>
      <button
        type="button"
        class="btn btn--ghost btn--sm wf-palette__danger"
        :disabled="!activeNodeId"
        @click="removeActiveEdge"
      >
        删连线
      </button>
    </div>
    <div class="wf-canvas">
      <VueFlow
        :nodes="flowNodes"
        :edges="flowEdges"
        :nodes-draggable="editable"
        :nodes-connectable="editable"
        fit-view-on-init
        @node-click="onNodeClick"
        @node-drag-stop="onDragStop"
        @connect="onConnect"
      >
        <Background :gap="16" :size="1" />
      </VueFlow>
    </div>
  </div>
</template>

<style scoped>
.wf-canvas-wrap {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
  height: 100%;
  min-height: 280px;
}

.wf-palette {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-xs);
}

.wf-palette__label {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
  margin-right: var(--space-xs);
}

.wf-palette__danger:not(:disabled) {
  color: var(--color-rise);
}

.wf-canvas {
  flex: 1;
  width: 100%;
  min-height: 240px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
  background: var(--color-surface-muted);
}

:deep(.vue-flow__node) {
  padding: 6px 10px;
  border-radius: var(--radius-sm);
  border: 2px solid var(--color-border-strong);
  background: var(--color-surface);
  color: var(--color-text);
  font-size: var(--font-size-sm);
  line-height: 1.35;
  white-space: pre-line;
  min-width: 88px;
  text-align: center;
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
}

:deep(.vue-flow__node-default) {
  color: var(--color-text);
  background-color: var(--color-surface);
}

:deep(.wf-node--gate) {
  border-color: var(--color-warn-text);
}

:deep(.wf-node--collect) {
  border-color: var(--color-primary);
}

:deep(.wf-node--quality) {
  border-color: var(--color-wf-quality);
}

:deep(.wf-node--active) {
  box-shadow: 0 0 0 2px var(--color-primary-muted);
}

:deep(.wf-node--status-pending) {
  opacity: 0.75;
}

:deep(.wf-node--status-running) {
  border-color: var(--color-primary);
  animation: wf-pulse 1.2s ease-in-out infinite;
}

:deep(.wf-node--status-success) {
  border-color: var(--color-fall);
  background: var(--color-ok-bg);
  color: var(--color-ok-text);
}

:deep(.wf-node--status-failed) {
  border-color: var(--color-rise);
  background: var(--color-err-bg);
  color: var(--color-err-text);
}

:deep(.wf-node--status-skipped) {
  border-style: dashed;
  opacity: 0.65;
}

@keyframes wf-pulse {
  0%,
  100% {
    box-shadow: 0 0 0 0 var(--color-wf-pulse);
  }
  50% {
    box-shadow: 0 0 0 6px transparent;
  }
}
</style>
