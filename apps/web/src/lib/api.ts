/**
 * Cliente HTTP simple hacia la API Pedidoflow.
 * En dev usamos el proxy de Vite (/api → http://localhost:8000).
 *
 * Auth: cada request inyecta `Authorization: Bearer <jwt>` leído del session
 * actual de Supabase. Si no hay session, intenta el fallback X-Tenant-Id legacy
 * (para compat con tests / flujos antiguos).
 */

import { supabase } from "@/lib/supabase";

const BASE_URL = import.meta.env.VITE_API_URL ?? "";

// === Legacy: X-Tenant-Id (sólo dev/migración, mientras quede el banner) ===
const TENANT_STORAGE_KEY = "pedidoflow.tenant_id";

/**
 * Devuelve un identificador "tenant activo" para los guards síncronos en páginas.
 * Prioridad:
 *  1. Si hay session de Supabase en localStorage → devuelve "supabase" (placeholder
 *     truthy — el tenant real lo resuelve el backend desde el JWT).
 *  2. Tenant legacy seleccionado manualmente.
 *  3. null.
 *
 * Para el header HTTP usar `authHeaders()`.
 */
export function getTenantId(): string | null {
  if (hasSupabaseSession()) return "supabase";
  return localStorage.getItem(TENANT_STORAGE_KEY);
}

function hasSupabaseSession(): boolean {
  if (typeof window === "undefined") return false;
  // El SDK de Supabase guarda el session bajo `sb-<projectRef>-auth-token`
  // (o variantes). Detectamos cualquier clave que contenga `-auth-token`.
  for (let i = 0; i < window.localStorage.length; i++) {
    const key = window.localStorage.key(i);
    if (key && key.includes("-auth-token")) {
      const raw = window.localStorage.getItem(key);
      if (raw && raw.length > 50) return true;
    }
  }
  return false;
}

export function setTenantId(id: string): void {
  localStorage.setItem(TENANT_STORAGE_KEY, id);
}

export function clearTenantId(): void {
  localStorage.removeItem(TENANT_STORAGE_KEY);
}

async function authHeaders(): Promise<Record<string, string>> {
  // Prioridad 1: JWT de Supabase
  const { data } = await supabase.auth.getSession();
  if (data.session?.access_token) {
    return { Authorization: `Bearer ${data.session.access_token}` };
  }
  // Prioridad 2 (legacy): X-Tenant-Id
  const tenantId = getTenantId();
  return tenantId ? { "X-Tenant-Id": tenantId } : {};
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isFormData = init?.body instanceof FormData;
  const auth = await authHeaders();
  const res = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
      ...auth,
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export interface HealthResponse {
  status: string;
  version: string;
  timestamp: string;
}

export type DocumentStatus =
  | "pending"
  | "processing"
  | "extracted"
  | "failed"
  | "approved"
  | "rejected";

export type DocumentSource = "upload" | "email";
export type DocumentType = "pedido" | "oferta" | "desconocido";
export type MatchStrategy =
  | "exact_offer_number"
  | "client_lines_similarity"
  | "manual";

export interface ExtractedCliente {
  nombre: string | null;
  cif_nif: string | null;
  numero_iva: string | null;
  direccion_entrega: string | null;
  direccion_facturacion: string | null;
  contacto_email: string | null;
}

export interface ExtractedPedido {
  numero_pedido_cliente: string | null;
  numero_oferta: string | null;
  fecha_pedido: string | null;
  fecha_entrega_solicitada: string | null;
  moneda: string | null;
  observaciones: string | null;
}

export interface ExtractedLinea {
  referencia: string | null;
  descripcion: string;
  cantidad: number;
  unidad: string | null;
  precio_unitario: number | null;
  importe_linea: number | null;
}

export interface ExtractedTotales {
  subtotal_ht: number | null;
  /** null = no mencionado · 0 = mencionado sin coste · >0 = importe en € */
  transporte: number | null;
  iva: number | null;
  total_ttc: number | null;
}

export type Confianza = "alta" | "media" | "baja";

export interface CustomField {
  name: string;
  value: string | null;
  source_text: string | null;
}

export interface ExtractionData {
  cliente: ExtractedCliente;
  pedido: ExtractedPedido;
  lineas: ExtractedLinea[];
  totales: ExtractedTotales;
  confianza_global: Confianza;
  notas_extraccion: string | null;
  source_texts?: Record<string, string | null>;
  validation?: ValidationResult;
  workflow?: WorkflowEvaluation;
  /** Campos custom dinámicos extraídos por Claude según TenantField. Plano: {key: valor}. */
  custom?: Record<string, string | null>;
  /** Campos custom añadidos manualmente por el revisor desde el PDF. */
  custom_fields?: CustomField[];
}

export interface DocumentRead {
  id: string;
  tenant_id: string;
  source: DocumentSource;
  status: DocumentStatus;
  document_type: DocumentType;
  pdf_key: string;
  original_filename: string | null;
  source_email: string | null;
  extracted_json: ExtractionData | null;
  extraction_error: string | null;
  created_at: string;
  updated_at: string;
  processed_at: string | null;
}

/** Item ligero de la lista — sin extracted_json (10-50× menos payload). */
export interface DocumentListItem {
  id: string;
  tenant_id: string;
  source: DocumentSource;
  status: DocumentStatus;
  document_type: DocumentType;
  original_filename: string | null;
  source_email: string | null;
  extraction_error: string | null;
  has_blocking_issues: boolean;
  has_discrepancies: boolean;
  /** null para no-pedidos. true = tiene oferta vinculada. false = pedido sin oferta. */
  has_offer_link: boolean | null;
  created_at: string;
  updated_at: string;
  processed_at: string | null;
  email_received_at: string | null;
}

export interface ComparisonLine {
  reference: string;
  in_offer: { cantidad: number | null; precio_unitario: number | null; descripcion: string | null };
  in_order: { cantidad: number | null; precio_unitario: number | null; descripcion: string | null };
  issues: string[]; // "price_changed" | "qty_changed"
}

export interface ComparisonOnlySide {
  reference: string;
  cantidad: number | null;
  precio_unitario: number | null;
  descripcion: string | null;
}

export interface ComparisonResult {
  lines_in_both: ComparisonLine[];
  lines_only_in_order: ComparisonOnlySide[];
  lines_only_in_offer: ComparisonOnlySide[];
  summary: {
    common: number;
    added_in_order: number;
    removed_from_offer: number;
    price_discrepancies: number;
    qty_discrepancies: number;
  };
}

export interface DocumentLinkRead {
  id: string;
  tenant_id: string;
  order_document_id: string;
  offer_document_id: string;
  match_strategy: MatchStrategy;
  match_score: number;
  comparison_result: ComparisonResult | null;
  created_at: string;
  updated_at: string;
}

export interface TenantRead {
  id: string;
  name: string;
  slug: string;
  is_active: boolean;
}

export const api = {
  health: () => request<HealthResponse>("/api/v1/health"),

  listTenants: () => request<TenantRead[]>("/api/v1/tenants"),
  createTenant: (payload: { name: string; slug: string }) =>
    request<TenantRead>("/api/v1/tenants", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  listDocuments: (params?: { status?: DocumentStatus; type?: DocumentType }) => {
    const qs = new URLSearchParams();
    if (params?.status) qs.set("status", params.status);
    if (params?.type) qs.set("type", params.type);
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return request<DocumentListItem[]>(`/api/v1/documents${suffix}`);
  },
  getDocument: (id: string) => request<DocumentRead>(`/api/v1/documents/${id}`),
  getDocumentPdfBytes: async (id: string): Promise<Uint8Array> => {
    const res = await fetch(`${BASE_URL}/api/v1/documents/${id}/pdf`, {
      headers: await authHeaders(),
    });
    if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
    const buf = await res.arrayBuffer();
    return new Uint8Array(buf);
  },
  uploadDocument: (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    return request<DocumentRead>("/api/v1/documents", {
      method: "POST",
      body: formData,
    });
  },
  patchExtracted: (id: string, extracted_json: ExtractionData) =>
    request<DocumentRead>(`/api/v1/documents/${id}/extracted`, {
      method: "PATCH",
      body: JSON.stringify({ extracted_json }),
    }),
  patchStatus: (id: string, status: DocumentStatus, reason?: string) =>
    request<DocumentRead>(`/api/v1/documents/${id}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status, reason }),
    }),
  reclassify: (onlyUnknown = true) =>
    request<{
      inspected: number;
      changed: number;
      by_type: Record<DocumentType, number>;
      relinked: number;
    }>(`/api/v1/documents/reclassify?only_unknown=${onlyUnknown}`, {
      method: "POST",
      body: "{}",
    }),
  revalidate: (onlyExtracted = false) =>
    request<{
      inspected: number;
      updated: number;
      blocking_now: number;
      blocking_before: number;
      new_blocks: number;
      cleared_blocks: number;
    }>(`/api/v1/documents/revalidate?only_extracted=${onlyExtracted}`, {
      method: "POST",
      body: "{}",
    }),
  patchDocumentType: (id: string, document_type: DocumentType) =>
    request<DocumentRead>(`/api/v1/documents/${id}/type`, {
      method: "PATCH",
      body: JSON.stringify({ document_type }),
    }),

  // ---- Document links (pedido ↔ oferta) ----
  getDocumentLink: (id: string) =>
    request<DocumentLinkRead | null>(`/api/v1/documents/${id}/link`),
  linkOfferManually: (orderId: string, offerId: string) =>
    request<DocumentLinkRead>(`/api/v1/documents/${orderId}/link`, {
      method: "POST",
      body: JSON.stringify({ offer_document_id: offerId }),
    }),
  unlinkOffer: async (orderId: string): Promise<void> => {
    const res = await fetch(`${BASE_URL}/api/v1/documents/${orderId}/link`, {
      method: "DELETE",
      headers: await authHeaders(),
    });
    if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  },
  autoLinkOffer: (orderId: string) =>
    request<DocumentLinkRead | null>(`/api/v1/documents/${orderId}/auto-link`, {
      method: "POST",
      body: "{}",
    }),

  // ---- Concepts (diccionario aliases→campo per-tenant + globales) ----
  listConcepts: () => request<ConceptRead[]>("/api/v1/concepts"),
  listSchemaFields: () => request<SchemaField[]>("/api/v1/concepts/schema-fields"),
  createConcept: (payload: ConceptCreate) =>
    request<ConceptRead>("/api/v1/concepts", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateConcept: (id: string, payload: ConceptUpdate) =>
    request<ConceptRead>(`/api/v1/concepts/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deleteConcept: async (id: string): Promise<void> => {
    const res = await fetch(`${BASE_URL}/api/v1/concepts/${id}`, {
      method: "DELETE",
      headers: await authHeaders(),
    });
    if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  },
  addConceptAlias: (id: string, text: string) =>
    request<ConceptRead>(`/api/v1/concepts/${id}/aliases`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),

  // ---- Linked orders (oferta → pedidos vinculados) ----
  listLinkedOrders: (offerId: string) =>
    request<DocumentLinkRead[]>(`/api/v1/documents/${offerId}/linked-orders`),
};

// =============================================================================
// Concept types
// =============================================================================

export interface ConceptRead {
  id: string;
  tenant_id: string | null;  // null = global
  name: string;
  code: string | null;
  field_path: string | null;  // null = concepto libre (sustitución de valores)
  aliases: string[];
  hits: number;
  created_at: string;
  updated_at: string;
}

export interface ConceptCreate {
  name: string;
  code?: string | null;
  field_path?: string | null;
  aliases?: string[];
  is_global?: boolean;
}

export interface ConceptUpdate {
  name?: string;
  code?: string | null;
  field_path?: string | null;
  aliases?: string[];
  is_global?: boolean;
}

export interface SchemaField {
  path: string;     // ej: "cliente.nombre" o "custom.horario_entrega"
  label: string;    // ej: "Nombre"
  group: string;    // ej: "Cliente"
  is_custom?: boolean;
  /** Sólo si is_custom=true: id del TenantField subyacente (para borrar). */
  tenant_field_id?: string;
}

// =============================================================================
// Tenant fields (campos custom dinámicos por tenant)
// =============================================================================

export interface TenantFieldRead {
  id: string;
  tenant_id: string;
  group: string;          // "Cliente" | "Pedido" | "Totales"
  key: string;            // snake_case
  label: string;
  description: string | null;
  order: number;
  field_path: string;     // "custom.<key>"
  created_at: string;
  updated_at: string;
}

export interface TenantFieldCreate {
  group: string;
  label: string;
  key?: string | null;
  description?: string | null;
  order?: number;
}

export interface TenantFieldUpdate {
  label?: string;
  description?: string | null;
  order?: number;
}

export const tenantFieldsApi = {
  list: () => request<TenantFieldRead[]>("/api/v1/tenant-fields"),
  create: (payload: TenantFieldCreate) =>
    request<TenantFieldRead>("/api/v1/tenant-fields", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  update: (id: string, payload: TenantFieldUpdate) =>
    request<TenantFieldRead>(`/api/v1/tenant-fields/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  remove: async (id: string): Promise<void> => {
    const res = await fetch(`${BASE_URL}/api/v1/tenant-fields/${id}`, {
      method: "DELETE",
      headers: await authHeaders(),
    });
    if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  },
};

// =============================================================================
// Email integrations (Outlook)
// =============================================================================

export type IntegrationProvider = "outlook" | "gmail";
export type IntegrationStatus =
  | "pending"
  | "active"
  | "expired"
  | "error"
  | "disabled";

export interface EmailIntegrationRead {
  id: string;
  tenant_id: string;
  provider: IntegrationProvider;
  email: string;
  display_name: string | null;
  status: IntegrationStatus;
  watched_folder_id: string | null;
  watched_folder_name: string | null;
  last_polled_at: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

// =============================================================================
// Catalog items (precios mínimos)
// =============================================================================

export interface CatalogItemRead {
  id: string;
  tenant_id: string;
  reference: string;
  description: string | null;
  unit: string | null;
  min_price: string | null; // Decimal serializado como string
  list_price: string | null;
  currency: string;
  active: boolean;
  notes: string | null;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

export interface CatalogItemCreate {
  reference: string;
  description?: string | null;
  unit?: string | null;
  min_price?: string | null;
  list_price?: string | null;
  currency?: string;
  active?: boolean;
  notes?: string | null;
}

export interface CatalogItemUpdate {
  reference?: string;
  description?: string | null;
  unit?: string | null;
  min_price?: string | null;
  list_price?: string | null;
  currency?: string;
  active?: boolean;
  notes?: string | null;
}

export interface CatalogUploadResult {
  created: number;
  updated: number;
  skipped: number;
  errors: string[];
}

export const catalogApi = {
  list: (params?: { search?: string; active_only?: boolean }) => {
    const qs = new URLSearchParams();
    if (params?.search) qs.set("search", params.search);
    if (params?.active_only !== undefined) qs.set("active_only", String(params.active_only));
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return request<CatalogItemRead[]>(`/api/v1/catalog-items${suffix}`);
  },
  upsert: (payload: CatalogItemCreate) =>
    request<CatalogItemRead>("/api/v1/catalog-items", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  update: (id: string, payload: CatalogItemUpdate) =>
    request<CatalogItemRead>(`/api/v1/catalog-items/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  remove: async (id: string): Promise<void> => {
    const res = await fetch(`${BASE_URL}/api/v1/catalog-items/${id}`, {
      method: "DELETE",
      headers: await authHeaders(),
    });
    if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  },
  uploadCsv: async (file: File): Promise<CatalogUploadResult> => {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch(`${BASE_URL}/api/v1/catalog-items/upload`, {
      method: "POST",
      body: formData,
      headers: await authHeaders(),
    });
    if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
    return (await res.json()) as CatalogUploadResult;
  },
};

// =============================================================================
// Validation results (en extracted_json)
// =============================================================================

export type ValidationLevel = "ok" | "warning" | "blocking" | "unknown";

export interface ValidationLine {
  line_index: number;
  reference: string | null;
  actual_price: number | null;
  level: ValidationLevel;
  message: string;
  min_price: number | null;
}

export interface ValidationSummary {
  blocking: number;
  warnings: number;
  ok: number;
  unknown: number;
  total_lines: number;
}

export interface ValidationResult {
  summary: ValidationSummary;
  lines: ValidationLine[];
}

// =============================================================================
// Dashboard stats
// =============================================================================

export interface DashboardStats {
  documents: {
    total: number;
    by_status: Record<DocumentStatus, number>;
    by_type: Record<DocumentType, number>;
    last_7d: number;
    last_30d: number;
  };
  needs_review: {
    count: number;
    blocked_by_rules: number;
    with_validation_blocking: number;
  };
  approval_rate: {
    approved_30d: number;
    rejected_30d: number;
    rate: number | null;
  };
  linking: {
    pedidos_with_offer: number;
    pedidos_without_offer: number;
  };
  amounts: {
    approved_total_30d: number;
    currency: string;
  };
  rules: {
    active_count: number;
    total_count: number;
    top_5: { id: string; name: string; hits: number }[];
  };
  catalog: {
    items_count: number;
    items_without_min_price: number;
  };
  recent_documents: {
    id: string;
    original_filename: string | null;
    status: DocumentStatus;
    document_type: DocumentType;
    created_at: string;
  }[];
}

export const dashboardApi = {
  stats: () => request<DashboardStats>("/api/v1/dashboard/stats"),
};

// =============================================================================
// Workflow rules (motor de reglas dinámicas estilo Airtable)
// =============================================================================

export type RuleAction = "block" | "warn" | "set_status" | "add_note";
export type RuleScope = "all" | "pedido" | "oferta";
export type RuleOperator =
  | "lt" | "lte" | "gt" | "gte" | "eq" | "neq"
  | "contains" | "not_contains" | "equals" | "not_equals" | "matches"
  | "exists" | "not_exists" | "is_null" | "is_not_null";

export interface RuleCondition {
  field: string;
  operator: RuleOperator;
  value?: string | number | boolean | null;
  case_insensitive?: boolean;
}

export interface WorkflowRuleRead {
  id: string;
  tenant_id: string;
  name: string;
  description: string | null;
  enabled: boolean;
  priority: number;
  scope: RuleScope;
  conditions: RuleCondition[];
  action: RuleAction;
  action_params: Record<string, unknown>;
  hits: number;
  created_at: string;
  updated_at: string;
}

export interface WorkflowRuleCreate {
  name: string;
  description?: string | null;
  enabled?: boolean;
  priority?: number;
  scope?: RuleScope;
  conditions: RuleCondition[];
  action?: RuleAction;
  action_params?: Record<string, unknown>;
}

export interface WorkflowEvaluation {
  blocked: boolean;
  blocking_rules: { rule_id: string; name: string; message: string }[];
  warnings: { rule_id: string; name: string; message: string }[];
  notes: { rule_id: string; name: string; message: string }[];
  status_overrides: { rule_id: string; status: string; name: string; message: string }[];
  rules_evaluated: number;
  rules_matched: string[];
}

export const rulesApi = {
  list: () => request<WorkflowRuleRead[]>("/api/v1/workflow-rules"),
  create: (payload: WorkflowRuleCreate) =>
    request<WorkflowRuleRead>("/api/v1/workflow-rules", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  update: (id: string, payload: Partial<WorkflowRuleCreate>) =>
    request<WorkflowRuleRead>(`/api/v1/workflow-rules/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  remove: async (id: string): Promise<void> => {
    const res = await fetch(`${BASE_URL}/api/v1/workflow-rules/${id}`, {
      method: "DELETE",
      headers: await authHeaders(),
    });
    if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  },
  test: (
    rule: WorkflowRuleCreate,
    extracted_json: Record<string, unknown>,
    document_type: string = "pedido",
  ) =>
    request<WorkflowEvaluation>("/api/v1/workflow-rules/test", {
      method: "POST",
      body: JSON.stringify({ rule, extracted_json, document_type }),
    }),
};

export const integrationsApi = {
  list: () => request<EmailIntegrationRead[]>("/api/v1/integrations"),
  connectOutlook: () =>
    request<{ authorization_url: string }>("/api/v1/integrations/outlook/connect", {
      method: "POST",
      body: "{}",
    }),
  disconnect: async (id: string): Promise<void> => {
    const res = await fetch(`${BASE_URL}/api/v1/integrations/${id}`, {
      method: "DELETE",
      headers: await authHeaders(),
    });
    if (!res.ok) throw new Error(`API ${res.status}: ${await res.text()}`);
  },
  pollNow: (id: string) =>
    request<{ started: boolean; message: string }>(
      `/api/v1/integrations/outlook/${id}/poll`,
      { method: "POST", body: "{}" },
    ),
};
