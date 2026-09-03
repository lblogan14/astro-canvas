export { default as UPlotLine } from './uPlotLine.vue'
export { default as PlotlyView } from './PlotlyView.vue'
export { default as ImageView } from './ImageView.vue'
export { default as DataTable } from './DataTable.vue'
export { default as KeyValueTile } from './KeyValueTile.vue'
export { formatKvValue } from './formatValue'
export type { PlotlyFigure } from './PlotlyView.vue'
export type { TableHead } from './DataTable.vue'
export {
  type SpectrumSeries,
  seriesFromFrame,
  seriesFromSummary,
  toVelocity,
  axisLabel,
  fluxRange,
} from './spectrumSeries'
export {
  MAX_PLOTLY_INSTANCES,
  acquirePlotly,
  releasePlotly,
  livePlotlyCount,
  resetPlotlyPool,
  loadPlotly,
  setPlotlyModule,
} from './plotlyPool'
