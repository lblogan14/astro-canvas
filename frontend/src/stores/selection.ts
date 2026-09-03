import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

/** Selected node and edge ids on the canvas (mirrors Vue Flow's selection). */
export const useSelectionStore = defineStore('selection', () => {
  const nodeIds = ref<string[]>([])
  const edgeIds = ref<string[]>([])

  const nodeSet = computed(() => new Set(nodeIds.value))
  const primaryNodeId = computed(() => nodeIds.value[nodeIds.value.length - 1] ?? null)
  const isEmpty = computed(() => nodeIds.value.length === 0 && edgeIds.value.length === 0)

  function set(nodes: string[], edges: string[] = []): void {
    nodeIds.value = [...new Set(nodes)]
    edgeIds.value = [...new Set(edges)]
  }

  function selectNode(id: string, additive = false): void {
    if (additive) {
      if (!nodeSet.value.has(id)) nodeIds.value = [...nodeIds.value, id]
    } else {
      nodeIds.value = [id]
      edgeIds.value = []
    }
  }

  function toggleNode(id: string): void {
    nodeIds.value = nodeSet.value.has(id)
      ? nodeIds.value.filter((n) => n !== id)
      : [...nodeIds.value, id]
  }

  function clear(): void {
    nodeIds.value = []
    edgeIds.value = []
  }

  /** Drop ids that no longer exist in the document. */
  function prune(existingNodes: (id: string) => boolean, existingEdges: (id: string) => boolean) {
    const nodes = nodeIds.value.filter(existingNodes)
    const edges = edgeIds.value.filter(existingEdges)
    if (nodes.length !== nodeIds.value.length) nodeIds.value = nodes
    if (edges.length !== edgeIds.value.length) edgeIds.value = edges
  }

  return {
    nodeIds,
    edgeIds,
    nodeSet,
    primaryNodeId,
    isEmpty,
    set,
    selectNode,
    toggleNode,
    clear,
    prune,
  }
})
