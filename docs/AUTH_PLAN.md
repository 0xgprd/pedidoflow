# Plan de Auth + Login (Fase 2)

> Estado: **PENDIENTE** — propuesta para la próxima iteración.
> Decisión a tomar: Clerk vs auth propio con FastAPI Users.

## Contexto

Order Flow es multi-tenant: cada cliente (PYME industrial) accede a su propio
espacio en `/inbox`, `/memory`, `/catalog`, etc. Hoy (MVP) el frontend pasa
manualmente un header `X-Tenant-Id` que se selecciona desde un banner.

Para Fase 2 necesitamos que cada cliente:
1. Se registre con email + contraseña (auto-onboarding sin intervención manual).
2. Inicie sesión y mantenga la sesión (cookie segura o JWT).
3. Vea SOLO los datos de su tenant — el `tenant_id` se deriva del usuario logueado, no de un header manipulable.
4. Pueda recuperar contraseña, cambiar email, eventualmente activar MFA.
5. (Más adelante) invitar a compañeros del mismo tenant con rol (admin/operador/viewer).

## Opción A — Clerk (recomendada)

**Por qué**:
- Las credenciales ya están en `.env.example` (`CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`).
- Componentes React listos: `<SignIn />`, `<SignUp />`, `<UserButton />`, `<OrganizationSwitcher />` — multi-tenant nativo via "Organizations".
- Free tier: 10.000 MAU. A coste cero hasta cliente nº 50–100.
- Reset password, verificación email, MFA, social login: cero código por mi parte.
- JWT firmado por Clerk → middleware FastAPI valida con clave pública (JWKS).

**Coste de integración**: ~2–3 días.

**Tareas**:
1. **Frontend**:
   - Instalar `@clerk/clerk-react`.
   - Envolver `<App />` en `<ClerkProvider>`.
   - Ruta `/sign-in`, `/sign-up`, `/sign-out`.
   - `<SignedIn>` / `<SignedOut>` para proteger las páginas.
   - Mapear `useAuth().getToken()` → header `Authorization: Bearer <jwt>` en `lib/api.ts`.
   - `<OrganizationSwitcher>` reemplaza el `TenantBanner` actual.
2. **Backend**:
   - Dep `python-jose[cryptography]` + `httpx` para fetch JWKS.
   - Nuevo `app/core/auth.py` con `verify_clerk_jwt(token)` cacheando JWKS.
   - Cambiar `get_current_tenant_id()` en `app/api/deps.py`:
     - Quitar lectura de `X-Tenant-Id`.
     - Leer `Authorization: Bearer ...`, validar JWT, extraer `org_id` (= `tenant_id`).
   - Webhook `POST /api/v1/webhooks/clerk` para sincronizar:
     - `organization.created` → crear `Tenant` row.
     - `organization.deleted` → soft-delete o cascade.
3. **Migración**:
   - Mapear los `Tenant.id` actuales a `Clerk.org_id` (poner `Tenant.clerk_org_id` como columna).
   - El usuario admin del MVP (Quimilock) crea su organización en Clerk y la vincula al tenant existente.

**Riesgos**:
- Vendor lock-in. Mitigación: la lógica de negocio sigue agnóstica; sustituir Clerk = reescribir solo `auth.py` + componentes de login.
- Caída de Clerk = caída del login. Aceptable para MVP B2B (uptime histórico ~99.9%).

## Opción B — Auth propio (FastAPI Users + bcrypt)

**Por qué NO** (salvo razón fuerte):
- Tendrás que mantener: hashing de passwords, verificación de email, reset password, rate limit, sesiones, eventualmente MFA.
- El primer fallo de seguridad (filtración de hashes, token reuse) lo pagas tú.
- Tiempo de desarrollo: ~1.5 semanas vs 2–3 días con Clerk.

**Cuándo sí** consideraríamos esta opción:
- Compliance estricto (datos no salen de servidor europeo bajo nuestra gestión exclusiva — RGPD agresivo).
- Cliente paga >20€/mes ahorrar costes Clerk a escala >5.000 MAU.

**Coste de integración**: ~6–8 días con todas las features mínimas (email verif + reset + sesiones).

## Decisión propuesta

**Empezar con Clerk** (Opción A). Si en 12 meses crecemos >5.000 MAU y el coste duele, evaluamos migración a auth propio (sería 1 semana de trabajo más en ese momento).

## Cambios fuera del alcance de esta fase (para más adelante)

- Roles dentro de un tenant (admin/operador/viewer).
- SSO empresarial (SAML, Google Workspace).
- Audit log de acciones sensibles (aprobación, cambio de catálogo).
- 2FA obligatorio para tenants enterprise.

## Checklist antes de empezar

- [ ] Crear cuenta Clerk en https://clerk.com (Gabriel).
- [ ] Crear "Application" en el dashboard, copiar `pk_test_...` y `sk_test_...` a `.env`.
- [ ] Activar "Organizations" en Application settings (multi-tenant).
- [ ] Configurar redirect URIs de dev: `http://localhost:5173/sign-in`, `/sign-up`, `/`.
- [ ] (Opcional) Configurar dominio personalizado para email transaccional.
