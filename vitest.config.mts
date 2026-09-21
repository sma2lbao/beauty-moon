import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    projects: [
      '**/vite.config.{mjs,js,ts,mts}',
      '**/vitest.config.{mjs,js,ts,mts}',
      // apps 下以各自的 vitest.config 为准，跳过其 vite.config，避免同名项目冲突
      '!apps/*/vite.config.{mjs,js,ts,mts}',
      '!vitest.config.{mjs,js,ts,mts}',
      '!vite.config.{mjs,js,ts,mts}',
    ],
  },
});
