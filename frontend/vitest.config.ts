import { fileURLToPath } from 'node:url'
import { mergeConfig, defineConfig, configDefaults } from 'vitest/config'
import viteConfig from './vite.config'

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      exclude: [...configDefaults.exclude, 'e2e/**'],
      root: fileURLToPath(new URL('./', import.meta.url)),
      coverage: {
        provider: 'v8',
        include: ['src/stores/**/*.ts', 'src/api/**/*.ts', 'src/canvas/*.ts', 'src/nodes/**/*.ts'],
        exclude: ['src/**/__tests__/**', 'src/api/schema.d.ts', 'src/api/types.ts'],
        reporter: ['text', 'lcov'],
        thresholds: { statements: 80, branches: 80, functions: 80, lines: 80 },
      },
    },
  }),
)
