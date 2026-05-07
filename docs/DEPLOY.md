# Deploy — Order Flow

> **Stack**: Railway (backend FastAPI + Celery) + Vercel (frontend Vite/React) + Supabase (DB ya en producción)
>
> **Sin dominio propio** — usaremos los subdominios free (`*.up.railway.app`, `*.vercel.app`).

## 0. Pre-requisitos

- ✅ Cuenta Railway (railway.app) con login GitHub
- ✅ Cuenta Vercel (vercel.com) con login GitHub
- ✅ Repo `0xgprd/pedidoflow` en GitHub con CI verde
- ✅ Supabase ya activo (DB + Auth ya configurados)

---

## 1. Backend → Railway

### 1.1 Crear proyecto

1. https://railway.app/new → **"Deploy from GitHub repo"**
2. Selecciona `0xgprd/pedidoflow`
3. Railway crea un servicio. Antes de que empiece a buildear, ve a **Settings**:
   - **Root Directory**: `apps/api`
   - (deja Builder en `Nixpacks` — autodetecta el `nixpacks.toml`)

### 1.2 Variables de entorno

En **Variables**, copia y pega estas (los valores los tienes en tu `.env` local):

| Variable | Valor |
|---|---|
| `APP_ENV` | `production` |
| `APP_DEBUG` | `false` |
| `APP_SECRET_KEY` | una cadena aleatoria larga (genérala con `openssl rand -hex 32`) |
| `DATABASE_URL` | el mismo de tu `.env` (Session pooler Supabase) |
| `SUPABASE_URL` | `https://rrdqeckozwbosfflpeez.supabase.co` |
| `SUPABASE_ANON_KEY` | `sb_publishable_O9YfG_UJhCRe1jSXPnVfXg_SiWrxA34` |
| `AUTH_ALLOW_TENANT_HEADER_FALLBACK` | `false` (importante: en prod sin fallback legacy) |
| `ANTHROPIC_API_KEY` | tu key real |
| `MISTRAL_API_KEY` | tu key real |
| `MS_GRAPH_TENANT_ID` | `common` |
| `MS_GRAPH_CLIENT_ID` | `df645015-0749-450e-9749-be598b75ae99` |
| `MS_GRAPH_CLIENT_SECRET` | el secret real |
| `MS_GRAPH_REDIRECT_URI` | `https://<TU-RAILWAY-URL>/api/v1/integrations/outlook/callback` (lo rellenas tras el paso 1.4) |
| `MS_GRAPH_POST_CALLBACK_URL` | `https://<TU-VERCEL-URL>/integrations` (tras el paso 2.4) |
| `CELERY_TASK_ALWAYS_EAGER` | `true` (modo MVP sin worker separado) |
| `CORS_ALLOW_ORIGINS` | `https://<TU-VERCEL-URL>` (tras el paso 2.4) |

### 1.3 Deploy

Railway buildea automáticamente al guardar variables. Tarda ~3-5 min la primera vez.

El `startCommand` de [railway.json](apps/api/railway.json) ejecuta `alembic upgrade head` antes de arrancar el servidor — aplica migraciones pendientes sin intervención.

### 1.4 Generar dominio público

**Settings → Networking → Generate Domain** → te da algo como `orderflow-api-production.up.railway.app`.

⚠️ Vuelve a **Variables** y actualiza `MS_GRAPH_REDIRECT_URI` con esta URL real.

### 1.5 Verificar

```
curl https://<TU-RAILWAY-URL>/api/v1/health
# {"status":"ok","version":"0.0.1","timestamp":"..."}
```

### 1.6 Actualizar Azure App (Outlook OAuth)

En el panel de Azure (https://portal.azure.com → App registrations → tu app `df645015-...`):
- **Authentication → Redirect URIs**: añadir `https://<TU-RAILWAY-URL>/api/v1/integrations/outlook/callback`
- (Mantén el de localhost para dev)

---

## 2. Frontend → Vercel

### 2.1 Importar proyecto

1. https://vercel.com/new → **Import Git Repository**
2. Selecciona `0xgprd/pedidoflow`
3. **Configure Project**:
   - **Root Directory**: `apps/web`
   - Framework: Vite (auto-detectado, sino selecciona)
   - Build Command: `pnpm build` (auto desde `vercel.json`)
   - Output Directory: `dist` (auto)

### 2.2 Variables de entorno

| Variable | Valor |
|---|---|
| `VITE_SUPABASE_URL` | `https://rrdqeckozwbosfflpeez.supabase.co` |
| `VITE_SUPABASE_ANON_KEY` | `sb_publishable_O9YfG_UJhCRe1jSXPnVfXg_SiWrxA34` |
| `VITE_API_URL` | `https://<TU-RAILWAY-URL>` (del paso 1.4) |

### 2.3 Deploy

Click **Deploy**. Tarda ~2 min.

### 2.4 URL pública

Vercel te da algo como `pedidoflow.vercel.app` o `0xgprd-pedidoflow.vercel.app`.

⚠️ Vuelve al panel **Railway → Variables** y actualiza:
- `CORS_ALLOW_ORIGINS` → `https://<TU-VERCEL-URL>`
- `MS_GRAPH_POST_CALLBACK_URL` → `https://<TU-VERCEL-URL>/integrations`

(Railway re-deploya automáticamente al cambiar variables.)

### 2.5 Verificar

Abre `https://<TU-VERCEL-URL>` → debería cargar la landing.
Click "Iniciar sesión" → entra con tu cuenta de Quimilock → ve a la bandeja.

---

## 3. Supabase Auth — actualizar redirects

En **Supabase → Authentication → URL Configuration**:
- **Site URL**: `https://<TU-VERCEL-URL>`
- **Redirect URLs**: añadir `https://<TU-VERCEL-URL>/**`

(Mantén `http://localhost:5173` para dev.)

---

## 4. Flujo de auto-deploy

A partir de aquí, cada `git push` a `main`:
1. CI corre en GitHub Actions (lint + tests)
2. Railway detecta el push y redeploya el backend
3. Vercel detecta el push y redeploya el frontend
4. `alembic upgrade head` corre en cada deploy backend (idempotente)

Si CI falla, Railway/Vercel **siguen desplegando** salvo que configures un check de status. Para evitar deploys con tests rotos, en cada plataforma:
- Railway → Settings → Deploy → "Wait for CI" (si está disponible)
- Vercel → Settings → Git → "Ignore Build Step" → script que checkea el commit status

(No crítico para MVP — confiamos en que el dev no haga push si CI rojo.)

---

## 5. Costes esperados (MVP)

| Servicio | Plan | Coste |
|---|---|---|
| Railway | Hobby | ~$5/mes (1 servicio web ligero) |
| Vercel | Hobby | $0 (free tier indefinido para proyectos personales) |
| Supabase | Free | $0 (hasta 500MB DB + 50K MAU + 1GB storage) |
| Anthropic API | Pago por uso | ~$0.05–0.20 por pedido procesado |
| Mistral OCR | Pago por uso | ~$1 / 1000 páginas |
| **Total fijo** | | **~$5/mes** + uso variable |

Cuando Quimilock procese ~100 pedidos/mes: total ~$15-25/mes.

---

## 6. Próximos pasos tras el deploy

- [ ] Probar el flujo completo (signup → onboarding → upload PDF → revisión → aprobar) en producción
- [ ] Activar verificación email obligatoria en Supabase (panel Authentication)
- [ ] Comprar dominio propio (orderflow.app, app.orderflow.es) cuando haya cliente nº 2
- [ ] Worker Celery separado (otro servicio Railway) cuando vuelvas a Redis y dejes de usar `EAGER`
- [ ] Sentry para errores en producción
