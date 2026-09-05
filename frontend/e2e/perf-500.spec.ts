import { expect, test } from './fixtures'

import { createWorkflow, deleteWorkflow, openWorkflow, syntheticWorkflow } from './helpers'

/**
 * 500-node synthetic workflow: pans and zooms must stay fluid (≥ 55 fps measured with
 * requestAnimationFrame while the canvas is driven programmatically) and nodes below zoom 0.4
 * render LOD placeholders. A Playwright trace is recorded for inspection.
 */
test('500-node workflow pans and zooms at 55 fps or better with LOD placeholders', async ({
  page,
  request,
  context,
}) => {
  test.slow()
  const doc = syntheticWorkflow(500)
  await createWorkflow(request, doc)
  await context.tracing.start({ screenshots: false, snapshots: false })
  try {
    await openWorkflow(page, doc.id)
    // Only visible nodes are mounted; the document still holds all 500.
    await expect.poll(async () => page.locator('.vue-flow__node').count()).toBeGreaterThan(0)

    const canvas = page.getByTestId('canvas')
    const box = (await canvas.boundingBox())!
    const cx = box.x + box.width / 2
    const cy = box.y + box.height / 2

    await page.evaluate(() => {
      const w = window as unknown as { __frames: number; __stop: boolean }
      w.__frames = 0
      w.__stop = false
      const tick = (): void => {
        w.__frames += 1
        if (!w.__stop) requestAnimationFrame(tick)
      }
      requestAnimationFrame(tick)
    })
    const started = Date.now()

    // Pan with the mouse across the canvas a few times.
    for (let i = 0; i < 4; i += 1) {
      await page.mouse.move(cx - 200, cy)
      await page.mouse.down()
      await page.mouse.move(cx + 200, cy + 60, { steps: 20 })
      await page.mouse.up()
    }
    // Zoom out and back in with the wheel.
    for (let i = 0; i < 12; i += 1) await page.mouse.wheel(0, 120)
    await expect(canvas).toHaveAttribute('data-lod', 'true')
    for (let i = 0; i < 12; i += 1) await page.mouse.wheel(0, -120)

    const elapsedMs = Date.now() - started
    const frames = await page.evaluate(() => {
      const w = window as unknown as { __frames: number; __stop: boolean }
      w.__stop = true
      return w.__frames
    })
    const fps = (frames / elapsedMs) * 1000
    test.info().annotations.push({ type: 'fps', description: fps.toFixed(1) })
    expect(fps).toBeGreaterThanOrEqual(55)
  } finally {
    await context.tracing.stop({ path: test.info().outputPath('perf-500-trace.zip') })
    await deleteWorkflow(request, doc.id)
  }
})
