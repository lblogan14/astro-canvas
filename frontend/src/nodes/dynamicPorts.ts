/**
 * Ports a node declares in its own parameters (the code node), mirroring
 * `astro_canvas.sdk.ports.effective_ports` on the server.
 *
 * The registry spec of such a node carries no ports at all — only a `dynamic_ports` declaration
 * naming the two params that hold them. Both sides derive the ports from the same document
 * values, so an edge the canvas allows is an edge the compiler wires.
 */
import type { NodeDoc, NodeSpec, PortSpec } from '@/api/types'

export const ANY_TYPE = 'astro.Any'

const IDENTIFIER = /^[A-Za-z_][A-Za-z0-9_]*$/

export function isValidPortName(name: string): boolean {
  return IDENTIFIER.test(name)
}

/** Port specs from one declaring param value; malformed or duplicate entries are dropped. */
export function declaredPorts(value: unknown): PortSpec[] {
  if (!Array.isArray(value)) return []
  const out: PortSpec[] = []
  const seen = new Set<string>()
  for (const item of value) {
    let name = ''
    let type = ANY_TYPE
    let description = ''
    let required = true
    if (typeof item === 'string') {
      name = item.trim()
    } else if (item && typeof item === 'object') {
      const record = item as Record<string, unknown>
      name = typeof record['name'] === 'string' ? record['name'].trim() : ''
      if (typeof record['type'] === 'string' && record['type']) type = record['type']
      if (typeof record['description'] === 'string') description = record['description']
      if (typeof record['required'] === 'boolean') required = record['required']
    }
    if (!isValidPortName(name) || seen.has(name)) continue
    seen.add(name)
    out.push({ name, type, description, required, lazy: false })
  }
  return out
}

/**
 * The spec one node instance behaves as: the registry spec, plus the ports its params declare.
 * Returns the same object for a node without `dynamic_ports`, so memoised callers stay stable.
 */
export function applyDynamicPorts(spec: NodeSpec, node: NodeDoc | undefined): NodeSpec {
  const dynamic = spec.dynamic_ports
  if (!dynamic) return spec
  const params = (node?.params ?? {}) as Record<string, unknown>
  const inputs = dynamic.inputs
    ? [...spec.inputs, ...declaredPorts(params[dynamic.inputs])]
    : spec.inputs
  const outputs = dynamic.outputs
    ? [...spec.outputs, ...declaredPorts(params[dynamic.outputs])]
    : spec.outputs
  if (inputs === spec.inputs && outputs === spec.outputs) return spec
  return { ...spec, inputs, outputs }
}

/** True when the spec's ports come from its params, so a per-instance spec is needed. */
export function hasDynamicPorts(spec: NodeSpec | undefined): boolean {
  return Boolean(spec?.dynamic_ports)
}
