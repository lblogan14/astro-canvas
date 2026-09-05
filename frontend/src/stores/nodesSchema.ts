import { computed, ref, shallowRef } from 'vue'
import { defineStore } from 'pinia'

import { api, errorMessage } from '@/api/client'
import type { NodeSpec, PackRecord, PortTypeSpec } from '@/api/types'
import { isTypeCompatible } from '@/canvas/compat'

export interface CategoryNode {
  /** Full path, e.g. `Spectra/Transform`. */
  path: string
  label: string
  children: CategoryNode[]
  nodes: NodeSpec[]
}

export type SchemaStatus = 'idle' | 'loading' | 'ready' | 'error'

function buildCategories(specs: readonly NodeSpec[]): CategoryNode[] {
  const root: CategoryNode = { path: '', label: '', children: [], nodes: [] }
  for (const spec of specs) {
    const parts = spec.category.split('/').filter(Boolean)
    let cursor = root
    let path = ''
    for (const part of parts) {
      path = path ? `${path}/${part}` : part
      let child = cursor.children.find((c) => c.label === part)
      if (!child) {
        child = { path, label: part, children: [], nodes: [] }
        cursor.children.push(child)
      }
      cursor = child
    }
    cursor.nodes.push(spec)
  }
  const sort = (node: CategoryNode): void => {
    node.children.sort((a, b) => a.label.localeCompare(b.label))
    node.nodes.sort((a, b) => a.name.localeCompare(b.name))
    node.children.forEach(sort)
  }
  sort(root)
  return root.children
}

/** Node types, port types and packs from `/api/nodes`, `/api/types`, `/api/packs`. */
export const useNodesSchemaStore = defineStore('nodesSchema', () => {
  const specs = shallowRef<NodeSpec[]>([])
  const types = shallowRef<PortTypeSpec[]>([])
  const packs = shallowRef<PackRecord[]>([])
  const status = ref<SchemaStatus>('idle')
  const error = ref<string | null>(null)

  const byId = computed<Record<string, NodeSpec>>(() =>
    Object.fromEntries(specs.value.map((s) => [s.id, s])),
  )
  const typeById = computed<Record<string, PortTypeSpec>>(() =>
    Object.fromEntries(types.value.map((t) => [t.id, t])),
  )
  const categories = computed(() => buildCategories(specs.value))
  const isReady = computed(() => status.value === 'ready')

  async function load(): Promise<void> {
    status.value = 'loading'
    error.value = null
    try {
      const [nodes, portTypes, packList] = await Promise.all([
        api.getNodes(),
        api.getTypes(),
        api.getPacks(),
      ])
      specs.value = nodes
      types.value = portTypes
      packs.value = packList
      status.value = 'ready'
    } catch (err) {
      error.value = errorMessage(err)
      status.value = 'error'
    }
  }

  function spec(typeId: string): NodeSpec | undefined {
    return byId.value[typeId]
  }

  function portType(typeId: string): PortTypeSpec | undefined {
    return typeById.value[typeId]
  }

  function compatible(source: string, target: string): boolean {
    return isTypeCompatible(source, target, typeById.value)
  }

  /** Node types with at least one input port accepting `sourceType` (for filtered quick-add). */
  function acceptingInput(sourceType: string): NodeSpec[] {
    return specs.value.filter(
      (s) =>
        s.inputs.some((p) => compatible(sourceType, p.type)) ||
        s.params.some((p) => p.linkable && compatible(sourceType, p.link_type)),
    )
  }

  return {
    specs,
    types,
    packs,
    status,
    error,
    byId,
    typeById,
    categories,
    isReady,
    load,
    spec,
    portType,
    compatible,
    acceptingInput,
  }
})
