/**
 * Vitest setup: jsdom has no `matchMedia`, and uPlot calls it at import time (device pixel
 * ratio). Any component that pulls a chart in transitively would otherwise fail to import.
 */
if (typeof window !== 'undefined' && typeof window.matchMedia !== 'function') {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
}
