/**
 * Measurement recording for the `perf` project.
 *
 * Every gate reports its number as well as passing, and the run leaves them in
 * `frontend/perf-report.json` — the nightly workflow keeps that as an artefact and
 * `docs/dev/performance.md` quotes the figures. `reset()` runs once per invocation from
 * `playwright.config.ts`'s `globalSetup`, so the file holds one run and never accumulates:
 * Playwright is free to give each spec file its own worker process, which rules out keeping the
 * report in memory.
 */
import fs from 'node:fs'
import os from 'node:os'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

const REPORT = fileURLToPath(new URL('../perf-report.json', import.meta.url))

interface Measurement {
  name: string
  value: number
  unit: string
  gate?: number
}

interface Report {
  recorded: string
  platform: string
  cpus: number
  measurements: Measurement[]
}

function empty(): Report {
  return {
    recorded: new Date().toISOString(),
    platform: `${os.type()} ${os.arch()}`,
    cpus: os.cpus().length,
    measurements: [],
  }
}

/** Start a fresh report; called once per `playwright test` from `globalSetup`. */
export default function reset(): void {
  fs.writeFileSync(REPORT, `${JSON.stringify(empty(), null, 2)}\n`, 'utf-8')
}

/** Record one number, print it, and keep it in `perf-report.json`. */
export function record(name: string, value: number, unit: string, gate?: number): number {
  let report: Report
  try {
    report = JSON.parse(fs.readFileSync(REPORT, 'utf-8')) as Report
  } catch {
    report = empty()
  }
  report.measurements = report.measurements.filter((m) => m.name !== name)
  report.measurements.push({
    name,
    value: Math.round(value * 1000) / 1000,
    ...(gate === undefined ? {} : { gate }),
    unit,
  })
  fs.writeFileSync(REPORT, `${JSON.stringify(report, null, 2)}\n`, 'utf-8')
  const shown = Math.abs(value) < 10 ? value.toPrecision(3) : value.toFixed(1)
  const against = gate === undefined ? '' : ` (gate ${gate} ${unit})`
  process.stdout.write(`PERF ${name}: ${shown} ${unit}${against}\n`)
  return value
}
