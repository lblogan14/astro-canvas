/**
 * The seam between the app shell and the canvas library (design §10.1, R3 mitigation 1). The
 * Vue Flow implementation lives in `canvas/vueflow/` and is the only code importing `@vue-flow/*`;
 * everything else talks to the canvas through this interface.
 */
import { type InjectionKey, type Ref, type ShallowRef, inject, shallowRef } from 'vue'

export interface Point {
  x: number
  y: number
}

export interface FitViewOptions {
  /** Restrict to these node ids (default: every node). */
  nodeIds?: string[]
  padding?: number
  duration?: number
}

export interface CanvasAdapter {
  /** Current zoom level (reactive). */
  readonly zoom: Readonly<Ref<number>>
  fitView(options?: FitViewOptions): void
  zoomIn(): void
  zoomOut(): void
  /** Screen (client) coordinates → flow coordinates. */
  screenToFlow(point: Point): Point
  /** Flow coordinates → screen coordinates. */
  flowToScreen(point: Point): Point
  /** Flow coordinates of the centre of the visible viewport. */
  viewportCenter(): Point
  /** Replace the canvas selection. */
  selectNodes(ids: string[]): void
  /** Focus the canvas container so keyboard shortcuts apply. */
  focus(): void
}

export const CANVAS_ADAPTER_KEY: InjectionKey<Readonly<ShallowRef<CanvasAdapter | null>>> =
  Symbol('canvas-adapter')

/** LOD flag (true below the zoom threshold): nodes render placeholders (design §10.2). */
export const CANVAS_LOD_KEY: InjectionKey<Readonly<Ref<boolean>>> = Symbol('canvas-lod')

export const LOD_ZOOM_THRESHOLD = 0.4

const registry = shallowRef<CanvasAdapter | null>(null)

/** Register the live canvas (called by the Vue Flow implementation on mount/unmount). */
export function registerCanvasAdapter(adapter: CanvasAdapter | null): void {
  registry.value = adapter
}

/**
 * Access the mounted canvas from anywhere in the shell (toolbar, palette, shortcuts). Prefers an
 * injected adapter (for tests/embedding) and falls back to the module registry.
 */
export function useCanvasAdapter(): Readonly<ShallowRef<CanvasAdapter | null>> {
  return inject(CANVAS_ADAPTER_KEY, registry)
}
