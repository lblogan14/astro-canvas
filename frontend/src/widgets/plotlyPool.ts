/**
 * Guard on the number of live Plotly WebGL contexts (design §10.2: at most 6). Views register
 * when they draw; when a seventh arrives, the least recently used view is asked to pause (it
 * purges its plot and shows a "click to resume" placeholder).
 */
export const MAX_PLOTLY_INSTANCES = 6

interface Entry {
  id: number
  pause: () => void
  lastUsed: number
}

const live = new Map<number, Entry>()
let seq = 0

export function nextPlotlyId(): number {
  seq += 1
  return seq
}

/** Register a view as live; may pause another view to stay under the limit. Returns `true`. */
export function acquirePlotly(id: number, pause: () => void): boolean {
  live.set(id, { id, pause, lastUsed: Date.now() })
  while (live.size > MAX_PLOTLY_INSTANCES) {
    let oldest: Entry | null = null
    for (const entry of live.values()) {
      if (entry.id !== id && (!oldest || entry.lastUsed < oldest.lastUsed)) oldest = entry
    }
    if (!oldest) break
    live.delete(oldest.id)
    oldest.pause()
  }
  return true
}

export function touchPlotly(id: number): void {
  const entry = live.get(id)
  if (entry) entry.lastUsed = Date.now()
}

export function releasePlotly(id: number): void {
  live.delete(id)
}

export function livePlotlyCount(): number {
  return live.size
}

/** Test helper. */
export function resetPlotlyPool(): void {
  live.clear()
  seq = 0
}

type PlotlyModule = typeof import('plotly.js-dist-min')
let plotlyPromise: Promise<PlotlyModule> | null = null

/** Lazy-load Plotly (about 3.5 MB) only when a full-size view opens. */
export function loadPlotly(): Promise<PlotlyModule> {
  if (!plotlyPromise) {
    plotlyPromise = import('plotly.js-dist-min').then((m) => (m.default ?? m) as PlotlyModule)
  }
  return plotlyPromise
}

/** Test helper: inject a fake Plotly module. */
export function setPlotlyModule(module: PlotlyModule | null): void {
  plotlyPromise = module ? Promise.resolve(module) : null
}
