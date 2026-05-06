# Pedidoflow Web

Frontend React + Vite + TypeScript + Tailwind + shadcn/ui.

## Setup

```bash
pnpm install        # o npm install / yarn install
pnpm dev            # http://localhost:5173
```

El dev server proxea `/api/*` a `http://localhost:8000` (backend FastAPI).

## Build

```bash
pnpm build          # output → dist/
pnpm preview        # serve build local
```

## shadcn/ui

Para añadir componentes shadcn:
```bash
pnpm dlx shadcn@latest add card input table dialog
```

## Estructura

- `src/main.tsx` — entrypoint + router
- `src/App.tsx` — routes
- `src/components/Layout.tsx` — sidebar + outlet
- `src/components/ui/` — primitivos shadcn
- `src/pages/` — pantallas (Home, Inbox, Catalog)
- `src/lib/api.ts` — cliente HTTP
- `src/lib/utils.ts` — `cn()` helper
