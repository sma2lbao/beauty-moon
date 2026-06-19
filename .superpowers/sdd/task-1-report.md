# Task 1 Report

## Files changed
- apps/luna-corpus-web/package.json
- apps/luna-corpus-web/vite.config.ts
- apps/luna-corpus-web/tsconfig.json
- apps/luna-corpus-web/src/test/setup.ts
- apps/luna-corpus-web/src/test/smoke.test.ts
- package-lock.json

## Commands run
- `pnpm nx test luna-corpus-web` — FAIL: initial invocation failed because Nx could not find target `test` before the harness existed.
- `pnpm add -D -F luna-corpus-web vitest jsdom @testing-library/react @testing-library/user-event @testing-library/jest-dom` — FAIL: pnpm 7.9.1 on Node v22.22.3 failed metadata fetches with `ERR_INVALID_THIS`.
- `npm install --workspace apps/luna-corpus-web --save-dev vitest jsdom @testing-library/react @testing-library/user-event @testing-library/jest-dom` — PASS: installed dependencies and updated `package-lock.json`.
- `pnpm nx test luna-corpus-web` — FAIL: Vitest harness ran but exited non-zero because no test files existed.
- `pnpm nx test luna-corpus-web` — PASS: 1 test file passed after adding smoke test. Vite emitted deprecation warnings from the React plugin.
- `pnpm nx lint luna-corpus-web` — PASS: 0 errors, 2 existing Fast Refresh warnings in `badge.tsx` and `button.tsx`.
- `pnpm nx build luna-corpus-web` — FAIL: Vite config `test` property was not typed when importing `defineConfig` from `vite`.
- `pnpm nx build luna-corpus-web` — PASS after importing `defineConfig` from `vitest/config`.
- `pnpm nx test luna-corpus-web` — PASS: 1 test file passed. Vite emitted deprecation warnings from the React plugin.
- `pnpm nx lint luna-corpus-web` — PASS: 0 errors, 2 existing Fast Refresh warnings in `badge.tsx` and `button.tsx`.

## Commit hash
- Pending

## Concerns
- The repository uses `package-lock.json`, not `pnpm-lock.yaml`; dependency installation with the requested pnpm command failed due to pnpm 7.9.1 metadata fetch errors under Node v22.22.3, so npm workspaces were used to update the existing npm lockfile.
- Vitest runs successfully but prints Vite React plugin deprecation warnings about `esbuild`/`optimizeDeps.esbuildOptions`; these warnings are from upstream plugin behavior and not introduced by the smoke test itself.
- Lint passes but continues to report two pre-existing Fast Refresh warnings in `apps/luna-corpus-web/src/components/ui/badge.tsx` and `apps/luna-corpus-web/src/components/ui/button.tsx`.
