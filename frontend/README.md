# Frontend

Vite + React + TypeScript UI for the checkout pricing engine.

## Setup

```bash
npm install
```

## Scripts

| Command                | Purpose                              |
| ---------------------- | ------------------------------------ |
| `npm run dev`          | Dev server with HMR                  |
| `npm run build`        | Type-check and production build      |
| `npm run lint`         | ESLint                               |
| `npm run format`       | Prettier, write mode                 |
| `npm run format:check` | Prettier, check only (CI gate)       |
| `npm run typecheck`    | `tsc --noEmit` on app + node configs |

CI gate (per `docs/clean-code-enforcement.md`): `build`, `lint`, `format:check`, and `typecheck` must all exit 0.

## Structure

- `src/styles/tokens.css` — design tokens (colors, fonts, spacing scale); components use these custom properties only.
- `src/index.css` — base styles, mobile-first.
- `public/products/` — product photos, one `<SKU>.jpg` per catalog item, resolved by convention (no per-SKU list in code). CC-licensed; attribution in `public/products/CREDITS.md`.
