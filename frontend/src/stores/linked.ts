/**
 * The one linked selection shared by dashboard views (design 8.4).
 *
 * There is deliberately a *single* selection: a wavelength range dragged on a spectrum, or the
 * rows picked in a table. It carries the set of nodes it is linked across — the upstream closure
 * of the view that made it — and a view only reacts when its own upstream set intersects that,
 * which is what "views sharing the same upstream node" means in practice.
 *
 * The selection is view state, never document state: it is not undoable and never saved.
 */
import { computed, ref, shallowRef } from 'vue'
import { defineStore } from 'pinia'

import { intersects } from '@/modes/linked'

export interface RangeSelection {
  kind: 'range'
  /** Axis name for display (`wave`, `z`, …); views map it onto their own x axis. */
  axis: string
  lo: number
  hi: number
}

export interface RowSelection {
  kind: 'rows'
  rows: number[]
  /** Axis values of those rows, so a curve can mark them without reading the table. */
  values: number[]
  column: string | null
}

export type LinkedSelection = RangeSelection | RowSelection

export const useLinkedStore = defineStore('linked', () => {
  /** View id that made the selection. */
  const source = ref<string | null>(null)
  const group = shallowRef<Set<string>>(new Set())
  const selection = shallowRef<LinkedSelection | null>(null)

  const isActive = computed(() => selection.value !== null)

  function setRange(viewId: string, nodes: Iterable<string>, axis: string, lo: number, hi: number) {
    if (!Number.isFinite(lo) || !Number.isFinite(hi) || lo === hi) {
      clear()
      return
    }
    source.value = viewId
    group.value = new Set(nodes)
    selection.value = { kind: 'range', axis, lo: Math.min(lo, hi), hi: Math.max(lo, hi) }
  }

  function setRows(
    viewId: string,
    nodes: Iterable<string>,
    rows: readonly number[],
    values: readonly number[] = [],
    column: string | null = null,
  ) {
    if (rows.length === 0) {
      clear()
      return
    }
    source.value = viewId
    group.value = new Set(nodes)
    selection.value = { kind: 'rows', rows: [...rows], values: [...values], column }
  }

  function clear(): void {
    source.value = null
    group.value = new Set()
    selection.value = null
  }

  /** Whether a view whose upstream closure is `nodes` shares a node with the selection. */
  function linked(nodes: Iterable<string>): boolean {
    return selection.value !== null && intersects(nodes, group.value)
  }

  /** The selection as seen by a view, or `null` when that view is not linked to it. */
  function selectionFor(nodes: Iterable<string>): LinkedSelection | null {
    return linked(nodes) ? selection.value : null
  }

  function isSource(viewId: string): boolean {
    return source.value === viewId
  }

  return {
    source,
    group,
    selection,
    isActive,
    setRange,
    setRows,
    clear,
    linked,
    selectionFor,
    isSource,
  }
})
