import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ArrowLeft,
  RefreshCw,
  Save,
  Check,
  X,
  Plus,
  Trash2,
  Undo2,
  Tag,
  AlertTriangle,
  ShieldCheck,
  CircleHelp,
  Link2,
  Link2Off,
  Sparkles,
  ShieldX,
  Workflow as WorkflowIcon,
  Send,
  ExternalLink,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { PDFViewer, bgClassForPath, type Highlight } from "@/components/PDFViewer";
import { AssignToConceptModal } from "@/components/AssignToConceptModal";
import { AddCustomFieldModal } from "@/components/AddCustomFieldModal";
import { CustomerRegistrationView } from "@/components/CustomerRegistrationView";
import { api, ApiError } from "@/lib/api";
import type {
  ComparisonResult,
  Confianza,
  CustomField,
  DocumentLinkRead,
  DocumentRead,
  DocumentStatus,
  DocumentType,
  ExtractedLinea,
  ExtractionData,
  MatchStrategy,
  SchemaField,
  ValidationLevel,
  ValidationResult,
  WorkflowEvaluation,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const STATUS_BADGE: Record<DocumentStatus, string> = {
  pending: "bg-slate-200 text-slate-800",
  processing: "bg-blue-200 text-blue-900 animate-pulse",
  extracted: "bg-slate-100 text-slate-700",
  failed: "bg-red-200 text-red-900",
  approved: "bg-green-300 text-green-900",
  rejected: "bg-zinc-300 text-zinc-800",
};

const CONFIANZA_BADGE: Record<Confianza, string> = {
  alta: "bg-emerald-100 text-emerald-800 border-emerald-300",
  media: "bg-amber-100 text-amber-800 border-amber-300",
  baja: "bg-red-100 text-red-800 border-red-300",
};

const ACTIVE_STATUSES = new Set<DocumentStatus>(["pending", "processing"]);
const EDITABLE_STATUSES = new Set<DocumentStatus>(["extracted", "approved", "rejected"]);

export function DocumentDetail() {
  const { id } = useParams<{ id: string }>();
  const [doc, setDoc] = useState<DocumentRead | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [pdfData, setPdfData] = useState<Uint8Array | null>(null);
  const [activeFieldPath, setActiveFieldPath] = useState<string | null>(null);

  // Estado local de edición (sobrescribe extracted_json mientras hay cambios sin guardar)
  const [draft, setDraft] = useState<ExtractionData | null>(null);
  const [saving, setSaving] = useState(false);

  // Modal "asignar a concepto" (per-tenant o global Concept)
  const [conceptModal, setConceptModal] = useState<{ sourceText: string } | null>(null);

  // Modal "campo custom" (añade entrada a extracted_json.custom_fields)
  const [customFieldModal, setCustomFieldModal] = useState<{ text: string } | null>(null);

  // Si este doc es OFERTA, cargar pedidos que la tienen vinculada
  const [linkedOrders, setLinkedOrders] = useState<DocumentLinkRead[]>([]);

  // DocumentLink (oferta vinculada — solo si el doc es pedido)
  const [link, setLink] = useState<DocumentLinkRead | null>(null);
  const [linkBusy, setLinkBusy] = useState(false);

  // Schema fields (fijos + custom del tenant). Se usa para renderizar campos
  // custom dentro de cada grupo del panel derecho.
  const [schemaFields, setSchemaFields] = useState<SchemaField[]>([]);

  useEffect(() => {
    api
      .listSchemaFields()
      .then(setSchemaFields)
      .catch(() => setSchemaFields([]));
  }, []);

  // Custom fields agrupados por grupo (Cliente / Pedido / Totales)
  const customFieldsByGroup = useMemo(() => {
    const m = new Map<string, SchemaField[]>();
    for (const f of schemaFields) {
      if (!f.is_custom) continue;
      const arr = m.get(f.group) ?? [];
      arr.push(f);
      m.set(f.group, arr);
    }
    return m;
  }, [schemaFields]);

  const refresh = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    try {
      const fresh = await api.getDocument(id);
      setDoc(fresh);
      setDraft(fresh.extracted_json ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (!doc || !ACTIVE_STATUSES.has(doc.status)) return;
    const timer = setInterval(refresh, 2500);
    return () => clearInterval(timer);
  }, [doc, refresh]);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    api
      .getDocumentPdfBytes(id)
      .then((bytes) => {
        if (!cancelled) setPdfData(bytes);
      })
      .catch(() => {
        if (!cancelled) setPdfData(null);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  // Cargar el link (oferta vinculada) cuando el doc es un pedido
  useEffect(() => {
    if (!id || !doc || doc.document_type !== "pedido") {
      setLink(null);
      return;
    }
    let cancelled = false;
    api
      .getDocumentLink(id)
      .then((l) => {
        if (!cancelled) setLink(l);
      })
      .catch(() => {
        if (!cancelled) setLink(null);
      });
    return () => {
      cancelled = true;
    };
  }, [id, doc]);

  // Si es oferta, cargar lista de pedidos que apuntan a ella
  useEffect(() => {
    if (!id || !doc || doc.document_type !== "oferta") {
      setLinkedOrders([]);
      return;
    }
    let cancelled = false;
    api
      .listLinkedOrders(id)
      .then((arr) => {
        if (!cancelled) setLinkedOrders(arr);
      })
      .catch(() => {
        if (!cancelled) setLinkedOrders([]);
      });
    return () => {
      cancelled = true;
    };
  }, [id, doc]);

  const handleAutoLink = async () => {
    if (!id) return;
    setLinkBusy(true);
    try {
      const updated = await api.autoLinkOffer(id);
      setLink(updated);
      if (!updated) alert("No se ha encontrado oferta para vincular automáticamente.");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLinkBusy(false);
    }
  };

  const handleUnlink = async () => {
    if (!id || !confirm("¿Desvincular esta oferta del pedido?")) return;
    setLinkBusy(true);
    try {
      await api.unlinkOffer(id);
      setLink(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLinkBusy(false);
    }
  };

  const dirty = useMemo(() => {
    if (!doc?.extracted_json || !draft) return false;
    return JSON.stringify(doc.extracted_json) !== JSON.stringify(draft);
  }, [doc, draft]);

  const highlights: Highlight[] = useMemo(() => {
    const map = doc?.extracted_json?.source_texts;
    if (!map) return [];
    return Object.entries(map)
      .filter((entry): entry is [string, string] => typeof entry[1] === "string" && entry[1].length > 0)
      .map(([path, text]) => ({ path, text }));
  }, [doc]);

  // ---- Acciones ----

  const handleSave = async () => {
    if (!id || !draft) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await api.patchExtracted(id, draft);
      setDoc(updated);
      setDraft(updated.extracted_json ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const handleDiscardDraft = () => {
    setDraft(doc?.extracted_json ?? null);
  };

  const handleApprove = async () => {
    if (!id || !doc) return;
    if (dirty && !confirm("Tienes cambios sin guardar. ¿Aprobar de todas formas?")) return;
    setSaving(true);
    try {
      const updated = await api.patchStatus(id, "approved");
      setDoc(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const handleReject = async () => {
    if (!id || !doc) return;
    const reason = prompt("Motivo del rechazo (opcional):") ?? undefined;
    setSaving(true);
    try {
      const updated = await api.patchStatus(id, "rejected", reason);
      setDoc(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const handleReopen = async () => {
    if (!id || !doc) return;
    if (doc.erp_id) {
      alert(
        `Este pedido ya se empujó al ERP como ${doc.erp_id}. ` +
          "No se puede volver a pendiente sin antes cancelar el documento en el ERP.",
      );
      return;
    }
    if (
      !confirm(
        "¿Volver este pedido a pendiente de revisión? Esto deshace la aprobación y permite editarlo de nuevo.",
      )
    ) {
      return;
    }
    setSaving(true);
    try {
      const updated = await api.patchStatus(id, "extracted");
      setDoc(updated);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  // Si el último intento de push falló por cliente no dado de alta, guardamos
  // los datos del cliente para mostrar el panel "Dar de alta cliente".
  const [customerNotRegistered, setCustomerNotRegistered] = useState<{
    customer_name: string;
    message: string;
  } | null>(null);

  const handlePushToErp = async () => {
    if (!id || !doc) return;
    if (
      doc.erp_id &&
      !confirm(
        `Este pedido ya se empujó al ERP como ${doc.erp_id}. ` +
          "Empujarlo de nuevo creará un Sales Order DUPLICADO. " +
          "Si quieres re-pushear, primero cancela el SO antiguo en el ERP.\n\n" +
          "¿Continuar de todas formas?",
      )
    ) {
      return;
    }
    setSaving(true);
    setError(null);
    setCustomerNotRegistered(null);
    try {
      const updated = await api.pushToErp(id);
      setDoc(updated);
    } catch (e) {
      // Caso especial: cliente no dado de alta → panel específico, no error rojo
      if (e instanceof ApiError && e.code === "customer_not_registered") {
        const detail = e.detail as { customer_name: string; message: string };
        setCustomerNotRegistered({
          customer_name: detail.customer_name,
          message: detail.message,
        });
        // Refrescamos doc para que el panel inferior muestre erp_push_error
        try {
          const fresh = await api.getDocument(id);
          setDoc(fresh);
        } catch {
          /* ignore */
        }
      } else {
        setError(e instanceof Error ? e.message : String(e));
      }
    } finally {
      setSaving(false);
    }
  };

  // ---- Render ----

  if (error && !doc) {
    return (
      <div className="space-y-4">
        <Link to="/inbox" className="text-sm text-blue-600 hover:underline inline-flex items-center gap-1">
          <ArrowLeft className="h-3 w-3" /> Volver
        </Link>
        <div className="rounded-md border border-red-300 bg-red-50 p-4 text-sm text-red-900">
          {error}
        </div>
      </div>
    );
  }

  if (!doc) {
    return (
      <div className="space-y-5">
        <div className="h-4 w-32 bg-muted/40 rounded animate-pulse" />
        <div className="h-8 w-96 bg-muted/40 rounded animate-pulse" />
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          <div className="h-[80vh] bg-muted/30 rounded-lg animate-pulse" />
          <div className="space-y-3">
            <div className="h-32 bg-muted/30 rounded-lg animate-pulse" />
            <div className="h-48 bg-muted/30 rounded-lg animate-pulse" />
            <div className="h-64 bg-muted/30 rounded-lg animate-pulse" />
          </div>
        </div>
      </div>
    );
  }

  const canEdit = EDITABLE_STATUSES.has(doc.status);

  return (
    <div className="space-y-5">
      <Link to="/inbox" className="text-sm text-blue-600 hover:underline inline-flex items-center gap-1">
        <ArrowLeft className="h-3 w-3" /> Volver a la bandeja
      </Link>

      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-3">
            <DocumentTypeSelector
              value={doc.document_type}
              onChange={async (next) => {
                if (!id) return;
                try {
                  const updated = await api.patchDocumentType(id, next);
                  setDoc(updated);
                  // Si pasó a pedido, recargar el link
                  if (next === "pedido") {
                    const l = await api.getDocumentLink(id);
                    setLink(l);
                  } else {
                    setLink(null);
                  }
                } catch (e) {
                  setError(e instanceof Error ? e.message : String(e));
                }
              }}
            />
            {doc.original_filename ?? doc.id.slice(0, 8)}
          </h1>
          <div className="mt-2 flex items-center gap-3 text-sm text-muted-foreground">
            <span
              className={cn(
                "inline-block rounded-full px-2 py-0.5 text-xs font-medium",
                STATUS_BADGE[doc.status],
              )}
            >
              {doc.status}
            </span>
            <span>·</span>
            <span>fuente: {doc.source}</span>
            <span>·</span>
            <span>creado {new Date(doc.created_at).toLocaleString("es-ES")}</span>
          </div>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={refresh} disabled={loading}>
            <RefreshCw className={cn("h-4 w-4 mr-2", loading && "animate-spin")} />
            Refrescar
          </Button>
        </div>
      </div>

      {error && (
        <div className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900">
          {error}
        </div>
      )}

      {doc.extraction_error && (
        <div className="rounded-md border border-red-300 bg-red-50 p-4">
          <div className="text-sm font-medium text-red-900 mb-1">Error de extracción</div>
          <pre className="text-xs text-red-800 whitespace-pre-wrap">{doc.extraction_error}</pre>
        </div>
      )}

      {/* Acciones (sticky bar arriba) — sólo para pedidos/ofertas. Las fichas
          de alta usan su propia CTA dentro de CustomerRegistrationView. */}
      {canEdit && draft && doc.document_type !== "ficha_cliente" && (
        <div className="sticky top-0 z-20 -mx-8 px-8 py-2 bg-white/90 backdrop-blur border-b flex items-center gap-2">
          {dirty ? (
            <>
              <span className="text-sm text-amber-700 font-medium">● Cambios sin guardar</span>
              <Button size="sm" onClick={handleSave} disabled={saving}>
                <Save className="h-4 w-4 mr-2" /> {saving ? "Guardando..." : "Guardar cambios"}
              </Button>
              <Button size="sm" variant="ghost" onClick={handleDiscardDraft} disabled={saving}>
                <Undo2 className="h-4 w-4 mr-2" /> Descartar
              </Button>
            </>
          ) : (
            <span className="text-sm text-muted-foreground">Click sobre cualquier campo para editarlo.</span>
          )}
          {/* Las ofertas son catálogo pasivo (auto-aprobadas), no requieren
              decisión humana. Sólo pedidos muestran los botones aprobar/rechazar. */}
          {doc.document_type === "pedido" && (
            <div className="ml-auto flex gap-2">
              {doc.status === "approved" ? (
                /* Pedido ya aprobado — empujar al ERP, o volver atrás si se aprobó por error. */
                <>
                  {!doc.erp_id && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={handleReopen}
                      disabled={saving}
                      title="Deshacer la aprobación y volver a pendiente"
                    >
                      <Undo2 className="h-4 w-4 mr-1" /> Volver a pendiente
                    </Button>
                  )}
                  <Button
                    size="sm"
                    className="bg-violet-600 hover:bg-violet-700 text-white"
                    onClick={handlePushToErp}
                    disabled={saving}
                    title={
                      doc.erp_id
                        ? `Ya empujado como ${doc.erp_id}. Re-pushear creará un duplicado.`
                        : "Crear pedido en el ERP"
                    }
                  >
                    <Send className="h-4 w-4 mr-1" />
                    {saving
                      ? "Empujando..."
                      : doc.erp_id
                        ? "Re-empujar al ERP"
                        : "Empujar al ERP"}
                  </Button>
                </>
              ) : (
                <>
                  <Button
                    size="sm"
                    variant="outline"
                    className="border-red-300 text-red-700 hover:bg-red-50"
                    onClick={handleReject}
                    disabled={saving}
                  >
                    <X className="h-4 w-4 mr-1" /> Rechazar
                  </Button>
                  <Button
                    size="sm"
                    className={cn(
                      "text-white",
                      draft.workflow?.blocked
                        ? "bg-zinc-400 hover:bg-zinc-400 cursor-not-allowed"
                        : "bg-emerald-600 hover:bg-emerald-700",
                    )}
                    onClick={handleApprove}
                    disabled={saving || !!draft.workflow?.blocked}
                    title={
                      draft.workflow?.blocked
                        ? "Aprobación bloqueada por regla(s) workflow"
                        : "Aprobar pedido"
                    }
                  >
                    {draft.workflow?.blocked ? (
                      <ShieldX className="h-4 w-4 mr-1" />
                    ) : (
                      <Check className="h-4 w-4 mr-1" />
                    )}
                    {draft.workflow?.blocked ? "Bloqueado" : "Aprobar"}
                  </Button>
                </>
              )}
            </div>
          )}
          {doc.document_type === "oferta" && (
            <div className="ml-auto text-xs text-muted-foreground italic">
              Las ofertas se almacenan automáticamente — sin acción requerida.
            </div>
          )}
        </div>
      )}

      {/* Cliente no dado de alta — caso especial con call-to-action específico */}
      {customerNotRegistered && (
        <CustomerNotRegisteredPanel
          customerName={customerNotRegistered.customer_name}
          message={customerNotRegistered.message}
          onDismiss={() => setCustomerNotRegistered(null)}
        />
      )}

      {/* Estado del push al ERP (solo pedidos: si se empujó OK o si falló). */}
      {doc.document_type === "pedido" && (doc.erp_id || doc.erp_push_error) && (
        <ErpPushStatusPanel doc={doc} />
      )}

      {/* Layout 50/50 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <PDFViewer
          data={pdfData}
          highlights={highlights}
          activePath={activeFieldPath}
          onAssignConcept={(text) => setConceptModal({ sourceText: text })}
          onCreateCustomField={(text) => setCustomFieldModal({ text })}
          className="h-[80vh] sticky top-20"
        />

        <div className="space-y-5">
          {doc.document_type === "ficha_cliente" ? (
            // Vista específica de alta de cliente — formulario editable
            // con CTA "Dar de alta en el ERP".
            <CustomerRegistrationView doc={doc} onUpdated={setDoc} />
          ) : (
            <>
              {doc.document_type === "pedido" && doc.status === "extracted" && (
                <OfferLinkPanel
                  link={link}
                  busy={linkBusy}
                  onAutoLink={handleAutoLink}
                  onUnlink={handleUnlink}
                />
              )}
              {doc.document_type === "oferta" && linkedOrders.length > 0 && (
                <LinkedOrdersPanel orders={linkedOrders} />
              )}
              {draft ? (
                <ExtractionView
                  data={draft}
                  onChange={setDraft}
                  activeFieldPath={activeFieldPath}
                  onFieldFocus={setActiveFieldPath}
                  editable={canEdit}
                  onAssignConcept={(sourceText) => setConceptModal({ sourceText })}
                  originalData={doc.extracted_json ?? null}
                  customFieldsByGroup={customFieldsByGroup}
                />
              ) : (
                <div className="rounded-lg border bg-card p-8 text-center text-sm text-muted-foreground">
                  {ACTIVE_STATUSES.has(doc.status)
                    ? "Procesando con OCR + IA... (auto-refresh activo)"
                    : "Sin datos extraídos."}
                </div>
              )}
            </>
          )}
        </div>
      </div>

      <details className="rounded-lg border bg-card">
        <summary className="px-4 py-2 text-xs font-medium text-muted-foreground cursor-pointer select-none">
          Detalles técnicos
        </summary>
        <div className="px-4 pb-3 text-xs font-mono text-muted-foreground space-y-1">
          <div>id: {doc.id}</div>
          <div>tenant: {doc.tenant_id}</div>
          <div>storage: {doc.pdf_key}</div>
          {doc.processed_at && <div>procesado: {new Date(doc.processed_at).toLocaleString("es-ES")}</div>}
        </div>
      </details>

      <AssignToConceptModal
        open={conceptModal !== null}
        sourceText={conceptModal?.sourceText ?? ""}
        onClose={() => setConceptModal(null)}
      />

      <AddCustomFieldModal
        open={customFieldModal !== null}
        initialValue={customFieldModal?.text ?? ""}
        onClose={() => setCustomFieldModal(null)}
        onConfirm={(field) => {
          if (!draft) return;
          setDraft({
            ...draft,
            custom_fields: [...(draft.custom_fields ?? []), field],
          });
        }}
      />
    </div>
  );
}

// =============================================================================
// Vista estructurada de la extracción (editable)
// =============================================================================

interface ExtractionViewProps {
  data: ExtractionData;
  onChange: (next: ExtractionData) => void;
  activeFieldPath: string | null;
  onFieldFocus: (path: string | null) => void;
  editable: boolean;
  onAssignConcept?: (sourceText: string, hintFieldPath: string) => void;
  /** Versión original de extracted_json (sin draft) — usada para sugerir
   *  el `source_text` cuando se quiere mapear desde el form. */
  originalData?: ExtractionData | null;
  /** Campos custom (TenantField) agrupados por grupo — render dinámico. */
  customFieldsByGroup?: Map<string, SchemaField[]>;
}

function ExtractionView({
  data,
  onChange,
  activeFieldPath,
  onFieldFocus,
  editable,
  onAssignConcept,
  originalData,
  customFieldsByGroup,
}: ExtractionViewProps) {
  const moneda = data.pedido.moneda ?? "EUR";

  function patchCliente<K extends keyof typeof data.cliente>(key: K, value: string | null) {
    onChange({ ...data, cliente: { ...data.cliente, [key]: value || null } });
  }
  function patchPedido<K extends keyof typeof data.pedido>(key: K, value: string | null) {
    onChange({ ...data, pedido: { ...data.pedido, [key]: value || null } });
  }
  function patchCustom(key: string, value: string | null) {
    const next = { ...(data.custom ?? {}), [key]: value || null };
    onChange({ ...data, custom: next });
  }
  function patchLinea(idx: number, patch: Partial<ExtractedLinea>) {
    const lineas = data.lineas.map((l, i) => (i === idx ? { ...l, ...patch } : l));
    onChange({ ...data, lineas });
  }
  function addLinea() {
    onChange({
      ...data,
      lineas: [
        ...data.lineas,
        {
          referencia: null,
          descripcion: "",
          cantidad: 1,
          unidad: null,
          precio_unitario: null,
          importe_linea: null,
        },
      ],
    });
  }
  function deleteLinea(idx: number) {
    onChange({ ...data, lineas: data.lineas.filter((_, i) => i !== idx) });
  }

  // Resolver el valor original (literal del PDF) del campo activo, para poder
  // sugerirlo como source_text cuando el usuario quiere asignar un Concept.
  const activeOriginalValue = useMemo(() => {
    if (!activeFieldPath || !originalData) return null;
    return getByPath(originalData, activeFieldPath);
  }, [activeFieldPath, originalData]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <ConfianzaBadge confianza={data.confianza_global} />
        <span className="text-xs text-muted-foreground">
          Click en un campo para resaltarlo en el PDF{editable && " · click otra vez para editarlo"}
        </span>
      </div>

      {activeFieldPath && activeOriginalValue && onAssignConcept && (
        <div className="rounded-md border border-zinc-200 bg-zinc-50 px-3 py-2 flex items-center justify-between gap-3">
          <div className="text-xs text-muted-foreground truncate">
            Campo activo:{" "}
            <span className="font-mono text-foreground">{activeFieldPath}</span>
            {" — "}
            <span className="font-medium">"{activeOriginalValue}"</span>
          </div>
          <Button
            size="sm"
            variant="outline"
            onClick={() => onAssignConcept(activeOriginalValue, activeFieldPath)}
          >
            <Tag className="h-3 w-3 mr-1.5" />
            Asignar concepto
          </Button>
        </div>
      )}

      {data.notas_extraccion && (
        <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          <span className="font-medium">Notas: </span>
          {data.notas_extraccion}
        </div>
      )}

      {data.workflow && <WorkflowPanel result={data.workflow} />}
      {data.validation && <ValidationPanel result={data.validation} />}

      <Section title="Cliente" sectionTone="emerald">
        <FieldGrid>
          <EditField path="cliente.nombre" label="Nombre" value={data.cliente.nombre} onChange={(v) => patchCliente("nombre", v)} active={activeFieldPath} onFocus={onFieldFocus} editable={editable} wide />
          <EditField path="cliente.cif_nif" label="CIF / NIF" value={data.cliente.cif_nif} onChange={(v) => patchCliente("cif_nif", v)} active={activeFieldPath} onFocus={onFieldFocus} editable={editable} />
          <EditField path="cliente.numero_iva" label="Nº IVA intracomunitario" value={data.cliente.numero_iva} onChange={(v) => patchCliente("numero_iva", v)} active={activeFieldPath} onFocus={onFieldFocus} editable={editable} />
          <EditField path="cliente.contacto_email" label="Email" value={data.cliente.contacto_email} onChange={(v) => patchCliente("contacto_email", v)} active={activeFieldPath} onFocus={onFieldFocus} editable={editable} wide />
          <EditField path="cliente.direccion_entrega" label="Dirección de entrega" value={data.cliente.direccion_entrega} onChange={(v) => patchCliente("direccion_entrega", v)} active={activeFieldPath} onFocus={onFieldFocus} editable={editable} wide />
          <EditField path="cliente.direccion_facturacion" label="Dirección de facturación" value={data.cliente.direccion_facturacion} onChange={(v) => patchCliente("direccion_facturacion", v)} active={activeFieldPath} onFocus={onFieldFocus} editable={editable} wide />
          {(customFieldsByGroup?.get("Cliente") ?? []).map((cf) => (
            <EditField
              key={cf.path}
              path={cf.path}
              label={cf.label}
              value={data.custom?.[cf.path.replace("custom.", "")] ?? null}
              onChange={(v) => patchCustom(cf.path.replace("custom.", ""), v)}
              active={activeFieldPath}
              onFocus={onFieldFocus}
              editable={editable}
              wide
            />
          ))}
        </FieldGrid>
      </Section>

      <Section title="Pedido" sectionTone="sky">
        <FieldGrid>
          <EditField path="pedido.numero_pedido_cliente" label="Nº pedido cliente" value={data.pedido.numero_pedido_cliente} onChange={(v) => patchPedido("numero_pedido_cliente", v)} active={activeFieldPath} onFocus={onFieldFocus} editable={editable} />
          <EditField path="pedido.numero_oferta" label="Nº oferta" value={data.pedido.numero_oferta} onChange={(v) => patchPedido("numero_oferta", v)} active={activeFieldPath} onFocus={onFieldFocus} editable={editable} />
          <EditField path="pedido.fecha_pedido" label="Fecha pedido" value={data.pedido.fecha_pedido} onChange={(v) => patchPedido("fecha_pedido", v)} active={activeFieldPath} onFocus={onFieldFocus} editable={editable} />
          <EditField path="pedido.fecha_entrega_solicitada" label="Fecha entrega" value={data.pedido.fecha_entrega_solicitada} onChange={(v) => patchPedido("fecha_entrega_solicitada", v)} active={activeFieldPath} onFocus={onFieldFocus} editable={editable} />
          <EditField path="pedido.moneda" label="Moneda" value={data.pedido.moneda} onChange={(v) => patchPedido("moneda", v)} active={activeFieldPath} onFocus={onFieldFocus} editable={editable} />
          <EditField path="pedido.observaciones" label="Observaciones" value={data.pedido.observaciones} onChange={(v) => patchPedido("observaciones", v)} active={activeFieldPath} onFocus={onFieldFocus} editable={editable} wide multiline />
          {(customFieldsByGroup?.get("Pedido") ?? []).map((cf) => (
            <EditField
              key={cf.path}
              path={cf.path}
              label={cf.label}
              value={data.custom?.[cf.path.replace("custom.", "")] ?? null}
              onChange={(v) => patchCustom(cf.path.replace("custom.", ""), v)}
              active={activeFieldPath}
              onFocus={onFieldFocus}
              editable={editable}
              wide
            />
          ))}
        </FieldGrid>
      </Section>

      <Section title={`Líneas (${data.lineas.length})`} empty={data.lineas.length === 0 ? "Sin líneas detectadas" : null}>
        {data.lineas.length > 0 && (
          <div className="overflow-x-auto -mx-4">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 text-left">
                <tr>
                  <th className="px-3 py-2 font-medium w-8"></th>
                  <th className="px-3 py-2 font-medium">Ref</th>
                  <th className="px-3 py-2 font-medium">Descripción</th>
                  <th className="px-3 py-2 font-medium text-right">Cant</th>
                  <th className="px-3 py-2 font-medium">Ud</th>
                  <th className="px-3 py-2 font-medium text-right">€/ud</th>
                  <th className="px-3 py-2 font-medium text-right">Importe</th>
                  {editable && <th className="px-2 py-2 w-8"></th>}
                </tr>
              </thead>
              <tbody>
                {data.lineas.map((linea, i) => (
                  <LineaRow
                    key={i}
                    idx={i}
                    linea={linea}
                    moneda={moneda}
                    activePath={activeFieldPath}
                    onFocus={onFieldFocus}
                    onChange={(patch) => patchLinea(i, patch)}
                    onDelete={() => deleteLinea(i)}
                    editable={editable}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
        {editable && (
          <Button size="sm" variant="outline" className="mt-3" onClick={addLinea}>
            <Plus className="h-3 w-3 mr-1" /> Añadir línea
          </Button>
        )}
      </Section>

      <Section title="Totales" sectionTone="violet">
        <div className="space-y-1 text-sm max-w-xs ml-auto">
          <TotalRow label="Subtotal HT" value={data.totales.subtotal_ht} moneda={moneda} />
          <TotalRow
            label="Transporte"
            value={data.totales.transporte}
            moneda={moneda}
            mutedIfNull="(no mencionado)"
          />
          <TotalRow label="IVA" value={data.totales.iva} moneda={moneda} />
          <TotalRow label="Total TTC" value={data.totales.total_ttc} moneda={moneda} bold />
        </div>
        {(customFieldsByGroup?.get("Totales") ?? []).length > 0 && (
          <div className="mt-3 pt-3 border-t">
            <FieldGrid>
              {(customFieldsByGroup?.get("Totales") ?? []).map((cf) => (
                <EditField
                  key={cf.path}
                  path={cf.path}
                  label={cf.label}
                  value={data.custom?.[cf.path.replace("custom.", "")] ?? null}
                  onChange={(v) => patchCustom(cf.path.replace("custom.", ""), v)}
                  active={activeFieldPath}
                  onFocus={onFieldFocus}
                  editable={editable}
                />
              ))}
            </FieldGrid>
          </div>
        )}
      </Section>

      {(data.custom_fields?.length ?? 0) > 0 && (
        <Section title={`Campos custom (${data.custom_fields!.length})`}>
          <div className="space-y-2">
            {data.custom_fields!.map((cf, i) => (
              <CustomFieldRow
                key={i}
                field={cf}
                editable={editable}
                onChange={(patch) => {
                  const next = (data.custom_fields ?? []).map((c, j) => (j === i ? { ...c, ...patch } : c));
                  onChange({ ...data, custom_fields: next });
                }}
                onDelete={() => {
                  const next = (data.custom_fields ?? []).filter((_, j) => j !== i);
                  onChange({ ...data, custom_fields: next });
                }}
              />
            ))}
          </div>
          {editable && (
            <p className="mt-3 text-xs text-muted-foreground italic">
              Para añadir más, selecciona texto en el PDF y pulsa "Campo custom".
            </p>
          )}
        </Section>
      )}
    </div>
  );
}

function LineaRow({
  idx,
  linea,
  moneda,
  activePath,
  onFocus,
  onChange,
  onDelete,
  editable,
}: {
  idx: number;
  linea: ExtractedLinea;
  moneda: string;
  activePath: string | null;
  onFocus: (path: string | null) => void;
  onChange: (patch: Partial<ExtractedLinea>) => void;
  onDelete: () => void;
  editable: boolean;
}) {
  const dotPath = `lineas.${idx}.referencia`;
  return (
    <tr className="border-t hover:bg-muted/20">
      <td className="px-3 py-2">
        <span className={cn("inline-block w-2 h-6 rounded-sm", bgClassForPath(dotPath))} />
      </td>
      <td className="px-1 py-1">
        <CellEdit
          path={`lineas.${idx}.referencia`}
          value={linea.referencia}
          onChange={(v) => onChange({ referencia: v })}
          active={activePath}
          onFocus={onFocus}
          editable={editable}
          mono
        />
      </td>
      <td className="px-1 py-1">
        <CellEdit
          path={`lineas.${idx}.descripcion`}
          value={linea.descripcion}
          onChange={(v) => onChange({ descripcion: v ?? "" })}
          active={activePath}
          onFocus={onFocus}
          editable={editable}
        />
      </td>
      <td className="px-1 py-1 text-right">
        <CellEdit
          path={`lineas.${idx}.cantidad`}
          value={String(linea.cantidad)}
          onChange={(v) => onChange({ cantidad: Number(v) || 0 })}
          active={activePath}
          onFocus={onFocus}
          editable={editable}
          align="right"
          numeric
        />
      </td>
      <td className="px-1 py-1">
        <CellEdit
          path={`lineas.${idx}.unidad`}
          value={linea.unidad}
          onChange={(v) => onChange({ unidad: v })}
          active={activePath}
          onFocus={onFocus}
          editable={editable}
        />
      </td>
      <td className="px-1 py-1 text-right">
        <CellEdit
          path={`lineas.${idx}.precio_unitario`}
          value={linea.precio_unitario != null ? String(linea.precio_unitario) : null}
          onChange={(v) => onChange({ precio_unitario: v == null || v === "" ? null : Number(v) })}
          active={activePath}
          onFocus={onFocus}
          editable={editable}
          align="right"
          numeric
        />
      </td>
      <td className="px-1 py-1 text-right">
        <CellEdit
          path={`lineas.${idx}.importe_linea`}
          value={linea.importe_linea != null ? String(linea.importe_linea) : null}
          onChange={(v) => onChange({ importe_linea: v == null || v === "" ? null : Number(v) })}
          active={activePath}
          onFocus={onFocus}
          editable={editable}
          align="right"
          numeric
          suffix={moneda === "EUR" ? "€" : moneda === "USD" ? "$" : moneda}
        />
      </td>
      {editable && (
        <td className="px-1 py-1">
          <Button
            size="sm"
            variant="ghost"
            className="h-6 w-6 p-0 text-red-600 hover:text-red-800 hover:bg-red-50"
            onClick={onDelete}
            title="Borrar línea"
          >
            <Trash2 className="h-3 w-3" />
          </Button>
        </td>
      )}
    </tr>
  );
}

// =============================================================================
// Componentes de presentación / edición
// =============================================================================

const SECTION_TONES: Record<string, string> = {
  emerald: "border-l-emerald-400",
  sky: "border-l-sky-400",
  violet: "border-l-violet-400",
};

function Section({
  title,
  children,
  empty,
  sectionTone,
}: {
  title: string;
  children: React.ReactNode;
  empty?: string | null;
  sectionTone?: string;
}) {
  const toneClass = sectionTone ? SECTION_TONES[sectionTone] : "border-l-amber-400";
  return (
    <div className={cn("rounded-lg border border-l-4 bg-card overflow-hidden", toneClass)}>
      <div className="px-4 py-2.5 border-b bg-muted/30">
        <h2 className="text-sm font-semibold tracking-tight">{title}</h2>
      </div>
      <div className="p-4">
        {empty ? <p className="text-sm text-muted-foreground italic">{empty}</p> : children}
      </div>
    </div>
  );
}

function FieldGrid({ children }: { children: React.ReactNode }) {
  return <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-3">{children}</div>;
}

/** Campo del formulario: click 1 → resalta en PDF, click 2 → editar inline. */
function EditField({
  path,
  label,
  value,
  onChange,
  active,
  onFocus,
  editable,
  wide,
  multiline,
}: {
  path: string;
  label: string;
  value: string | null;
  onChange: (next: string | null) => void;
  active: string | null;
  onFocus: (path: string | null) => void;
  editable: boolean;
  wide?: boolean;
  multiline?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [tmp, setTmp] = useState<string>(value ?? "");
  const isActive = active === path;
  const isEmpty = value === null || value === undefined || value === "";

  useEffect(() => {
    setTmp(value ?? "");
  }, [value]);

  const commit = () => {
    setEditing(false);
    onChange(tmp.trim() === "" ? null : tmp);
  };
  const cancel = () => {
    setTmp(value ?? "");
    setEditing(false);
  };

  const onClick = () => {
    if (!isActive) {
      onFocus(path);
      return;
    }
    if (editable) setEditing(true);
  };

  return (
    <div
      className={cn(
        wide && "md:col-span-2",
        "rounded -mx-1 px-1.5 py-1 transition-colors",
        !editing && "cursor-pointer",
        isActive && !editing && cn("ring-1", bgClassForPath(path)),
        !isActive && !editing && !isEmpty && "hover:bg-muted/40",
      )}
      onClick={editing ? undefined : onClick}
    >
      <div className="text-xs text-muted-foreground uppercase tracking-wide mb-0.5">{label}</div>
      {editing ? (
        multiline ? (
          <textarea
            autoFocus
            value={tmp}
            onChange={(e) => setTmp(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => {
              if (e.key === "Escape") cancel();
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) commit();
            }}
            rows={3}
            className="w-full text-sm border rounded px-2 py-1 bg-white"
          />
        ) : (
          <input
            autoFocus
            type="text"
            value={tmp}
            onChange={(e) => setTmp(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => {
              if (e.key === "Escape") cancel();
              if (e.key === "Enter") commit();
            }}
            className="w-full text-sm border rounded px-2 py-1 bg-white"
          />
        )
      ) : (
        <div className="text-sm">
          {isEmpty ? (
            <span className="text-muted-foreground italic">{editable ? "(click para añadir)" : "—"}</span>
          ) : (
            value
          )}
        </div>
      )}
    </div>
  );
}

/** Versión compacta para celdas de tabla (líneas). */
function CellEdit({
  path,
  value,
  onChange,
  active,
  onFocus,
  editable,
  align,
  numeric,
  mono,
  suffix,
}: {
  path: string;
  value: string | null;
  onChange: (next: string | null) => void;
  active: string | null;
  onFocus: (path: string | null) => void;
  editable: boolean;
  align?: "right";
  numeric?: boolean;
  mono?: boolean;
  suffix?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [tmp, setTmp] = useState<string>(value ?? "");
  const isActive = active === path;
  const isEmpty = value === null || value === undefined || value === "";

  useEffect(() => {
    setTmp(value ?? "");
  }, [value]);

  const commit = () => {
    setEditing(false);
    onChange(tmp.trim() === "" ? null : tmp);
  };
  const cancel = () => {
    setTmp(value ?? "");
    setEditing(false);
  };

  const onClick = () => {
    if (!isActive) {
      onFocus(path);
      return;
    }
    if (editable) setEditing(true);
  };

  if (editing) {
    return (
      <input
        autoFocus
        type={numeric ? "number" : "text"}
        step="any"
        value={tmp}
        onChange={(e) => setTmp(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Escape") cancel();
          if (e.key === "Enter") commit();
        }}
        className={cn(
          "w-full text-sm border rounded px-1 py-0.5 bg-white",
          align === "right" && "text-right",
          mono && "font-mono text-xs",
        )}
      />
    );
  }

  return (
    <div
      className={cn(
        "rounded px-1.5 py-1 transition-colors",
        editable && "cursor-pointer",
        isActive && cn("ring-1", bgClassForPath(path)),
        !isActive && editable && !isEmpty && "hover:bg-muted/30",
        align === "right" && "text-right tabular-nums",
        mono && "font-mono text-xs",
      )}
      onClick={onClick}
    >
      {isEmpty ? (
        <span className="text-muted-foreground italic">—</span>
      ) : numeric && suffix ? (
        `${formatMoneyValue(Number(value))} ${suffix}`
      ) : (
        value
      )}
    </div>
  );
}

function CustomFieldRow({
  field,
  editable,
  onChange,
  onDelete,
}: {
  field: CustomField;
  editable: boolean;
  onChange: (patch: Partial<CustomField>) => void;
  onDelete: () => void;
}) {
  return (
    <div className="rounded border bg-amber-50/40 p-3 flex items-start gap-2">
      <div className="flex-1 min-w-0 space-y-1">
        <div className="flex gap-2 items-baseline">
          <input
            value={field.name}
            onChange={(e) => onChange({ name: e.target.value })}
            disabled={!editable}
            placeholder="Nombre del campo"
            className="text-xs font-medium uppercase tracking-wide text-muted-foreground bg-transparent border-b border-dashed border-amber-300 focus:outline-none focus:border-amber-600 flex-1 min-w-0"
          />
        </div>
        <input
          value={field.value ?? ""}
          onChange={(e) => onChange({ value: e.target.value })}
          disabled={!editable}
          placeholder="Valor"
          className="text-sm w-full bg-transparent border-b border-dashed border-amber-200 focus:outline-none focus:border-amber-600"
        />
        {field.source_text && field.source_text !== field.value && (
          <div className="text-xs font-mono text-muted-foreground italic truncate">
            origen PDF: "{field.source_text}"
          </div>
        )}
      </div>
      {editable && (
        <button
          onClick={onDelete}
          className="text-red-600 hover:bg-red-50 p-1 rounded"
          title="Borrar campo"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  );
}

function TotalRow({
  label,
  value,
  moneda,
  bold,
  mutedIfNull,
}: {
  label: string;
  value: number | null;
  moneda: string;
  bold?: boolean;
  /** Texto a mostrar si value === null (en lugar del em-dash). */
  mutedIfNull?: string;
}) {
  return (
    <div
      className={cn(
        "flex justify-between items-baseline py-1",
        bold && "border-t pt-2 mt-1 font-semibold text-base",
      )}
    >
      <span className={cn(!bold && "text-muted-foreground")}>{label}</span>
      <span className="tabular-nums">
        {value === null && mutedIfNull ? (
          <span className="text-muted-foreground italic text-xs">{mutedIfNull}</span>
        ) : (
          formatMoney(value, moneda)
        )}
      </span>
    </div>
  );
}

function ConfianzaBadge({ confianza }: { confianza: Confianza }) {
  const labels: Record<Confianza, string> = {
    alta: "Confianza alta",
    media: "Confianza media",
    baja: "Confianza baja",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-3 py-1 text-xs font-medium",
        CONFIANZA_BADGE[confianza],
      )}
    >
      {labels[confianza]}
    </span>
  );
}

// =============================================================================
// Panel "Cliente no dado de alta" — se muestra cuando el push falla por
// CustomerNotRegisteredError. Lleva al user a la acción correcta (dar de alta)
// en vez de tratarlo como error técnico.
// =============================================================================

function CustomerNotRegisteredPanel({
  customerName,
  message,
  onDismiss,
}: {
  customerName: string;
  message: string;
  onDismiss: () => void;
}) {
  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50 p-4">
      <div className="flex items-start gap-3">
        <AlertTriangle className="h-5 w-5 text-amber-700 mt-0.5 shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-amber-900">
            Cliente no dado de alta: {customerName}
          </div>
          <p className="mt-1 text-sm text-amber-900/90">{message}</p>
          <div className="mt-3 flex items-center gap-2">
            <Link
              to="/clientes/alta"
              className="inline-flex items-center gap-1.5 rounded-md bg-amber-600 hover:bg-amber-700 text-white text-sm px-3 py-1.5 font-medium"
            >
              <Plus className="h-4 w-4" />
              Dar de alta cliente
            </Link>
            <button
              onClick={onDismiss}
              className="text-sm text-amber-900/70 hover:text-amber-900 px-2 py-1.5"
            >
              Cerrar
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// Panel estado del push al ERP — solo si se ha intentado empujar
// =============================================================================

function ErpPushStatusPanel({ doc }: { doc: DocumentRead }) {
  // Caso 1: push exitoso — id presente, error null
  if (doc.erp_id && !doc.erp_push_error) {
    const dateLabel = doc.erp_pushed_at
      ? new Date(doc.erp_pushed_at).toLocaleString("es-ES")
      : null;
    return (
      <div className="rounded-lg border border-emerald-300 bg-emerald-50 p-4">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="text-sm font-medium text-emerald-900 flex items-center gap-1.5">
              <Send className="h-4 w-4" />
              Empujado al ERP
              {doc.erp_adapter && (
                <span className="text-xs font-normal text-emerald-800/70">
                  · {doc.erp_adapter}
                </span>
              )}
            </div>
            <div className="mt-1 text-xs text-emerald-900/80 font-mono break-all">
              {doc.erp_id}
            </div>
            {dateLabel && (
              <div className="mt-0.5 text-xs text-emerald-800/70">{dateLabel}</div>
            )}
          </div>
          {doc.erp_url && (
            <a
              href={doc.erp_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 text-sm text-emerald-900 hover:underline shrink-0"
            >
              Ver en el ERP
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          )}
        </div>
      </div>
    );
  }

  // Caso 2: último intento falló
  if (doc.erp_push_error) {
    return (
      <div className="rounded-lg border border-red-300 bg-red-50 p-4">
        <div className="text-sm font-medium text-red-900 flex items-center gap-1.5 mb-1">
          <AlertTriangle className="h-4 w-4" />
          Error empujando al ERP
        </div>
        <pre className="text-xs text-red-800 whitespace-pre-wrap font-mono break-all">
          {doc.erp_push_error}
        </pre>
        <p className="mt-2 text-xs text-red-900/80">
          Revisa el detalle, corrige y vuelve a pulsar "Empujar al ERP".
        </p>
      </div>
    );
  }

  return null;
}

// =============================================================================
// Panel "Pedidos vinculados" — solo si el doc es OFERTA
// =============================================================================

function LinkedOrdersPanel({ orders }: { orders: DocumentLinkRead[] }) {
  return (
    <div className="rounded-lg border border-sky-300 bg-sky-50 p-4">
      <div className="text-sm font-medium text-sky-900 flex items-center gap-1.5 mb-2">
        <Link2 className="h-4 w-4" />
        Pedidos vinculados a esta oferta ({orders.length})
      </div>
      <ul className="space-y-1.5">
        {orders.map((o) => (
          <li key={o.id} className="text-sm flex items-center gap-2">
            <Link
              to={`/inbox/${o.order_document_id}`}
              className="text-blue-600 hover:underline font-medium"
            >
              ← Volver al pedido
            </Link>
            <span className="text-xs text-muted-foreground">
              {STRATEGY_LABEL[o.match_strategy]}
              {o.match_score < 1 && ` · ${Math.round(o.match_score * 100)}% similaridad`}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// =============================================================================
// Selector manual de tipo (header)
// =============================================================================

function DocumentTypeSelector({
  value,
  onChange,
}: {
  value: DocumentType;
  onChange: (next: DocumentType) => void;
}) {
  const [open, setOpen] = useState(false);
  const TYPES: Array<{ key: DocumentType; label: string; cls: string }> = [
    { key: "pedido", label: "Pedido", cls: "bg-sky-100 text-sky-900 border-sky-300 hover:bg-sky-200" },
    { key: "oferta", label: "Oferta", cls: "bg-violet-100 text-violet-900 border-violet-300 hover:bg-violet-200" },
    {
      key: "ficha_cliente",
      label: "Ficha cliente",
      cls: "bg-indigo-100 text-indigo-900 border-indigo-300 hover:bg-indigo-200",
    },
    {
      key: "albaran",
      label: "Albarán",
      cls: "bg-emerald-100 text-emerald-900 border-emerald-300 hover:bg-emerald-200",
    },
    {
      key: "factura",
      label: "Factura",
      cls: "bg-amber-100 text-amber-900 border-amber-300 hover:bg-amber-200",
    },
    { key: "desconocido", label: "?", cls: "bg-zinc-100 text-zinc-700 border-zinc-300 hover:bg-zinc-200" },
  ];
  const current = TYPES.find((t) => t.key === value)!;

  return (
    <div className="relative inline-block">
      <button
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "inline-flex items-center rounded border px-2 py-0.5 text-xs font-medium uppercase tracking-wide cursor-pointer",
          current.cls,
        )}
        title="Click para cambiar el tipo"
      >
        {current.label}
        <span className="ml-1 opacity-60">▾</span>
      </button>
      {open && (
        <>
          {/* Backdrop sobre TODO incluido el sticky bar (que va a z-20) */}
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          {/* Menú por encima del backdrop y del sticky bar */}
          <div className="absolute top-full left-0 mt-1 z-40 rounded border bg-white shadow-lg py-1 min-w-32">
            {TYPES.map((t) => (
              <button
                key={t.key}
                onClick={() => {
                  setOpen(false);
                  if (t.key !== value) onChange(t.key);
                }}
                className={cn(
                  "w-full text-left px-3 py-1.5 text-sm hover:bg-muted/50 flex items-center gap-2 normal-case",
                  t.key === value && "font-semibold",
                )}
              >
                <span className={cn("inline-block w-2 h-2 rounded-full", t.cls.split(" ")[0])} />
                {t.label}
                {t.key === value && <span className="ml-auto text-xs text-muted-foreground">actual</span>}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

// =============================================================================
// Panel "Oferta vinculada" — solo si el doc es PEDIDO
// =============================================================================

const STRATEGY_LABEL: Record<MatchStrategy, string> = {
  exact_offer_number: "Por número de oferta exacto",
  client_lines_similarity: "Por similaridad de líneas (cliente + refs)",
  manual: "Vinculación manual",
};

function OfferLinkPanel({
  link,
  busy,
  onAutoLink,
  onUnlink,
}: {
  link: DocumentLinkRead | null;
  busy: boolean;
  onAutoLink: () => void;
  onUnlink: () => void;
}) {
  if (link === null) {
    return (
      <div className="rounded-lg border border-amber-300 bg-amber-50/60 p-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="text-sm font-medium text-amber-900 flex items-center gap-1.5">
              <Link2Off className="h-4 w-4" /> Sin oferta vinculada
            </div>
            <p className="text-xs text-amber-800 mt-1">
              No se ha encontrado oferta automáticamente. Comprueba que la oferta esté en el sistema
              (Bandeja → Ofertas) y reintenta el matching.
            </p>
          </div>
          <Button size="sm" variant="outline" onClick={onAutoLink} disabled={busy}>
            <Sparkles className="h-3 w-3 mr-1.5" />
            {busy ? "Buscando..." : "Buscar oferta"}
          </Button>
        </div>
      </div>
    );
  }

  const cmp = link.comparison_result;
  const issuesCount = (cmp?.summary.price_discrepancies ?? 0) + (cmp?.summary.qty_discrepancies ?? 0);
  const hasExtras = (cmp?.summary.added_in_order ?? 0) > 0 || (cmp?.summary.removed_from_offer ?? 0) > 0;
  const allClean = issuesCount === 0 && !hasExtras;
  const headerStyle = allClean
    ? "border-emerald-300 bg-emerald-50 text-emerald-900"
    : "border-amber-300 bg-amber-50 text-amber-900";

  return (
    <div className={cn("rounded-lg border", headerStyle)}>
      <div className="px-4 py-2.5 border-b border-current/20 flex items-center gap-2">
        <Link2 className="h-4 w-4" />
        <span className="font-medium">
          Oferta vinculada
        </span>
        <Link
          to={`/inbox/${link.offer_document_id}`}
          className="text-xs underline hover:no-underline"
        >
          ver oferta →
        </Link>
        <span className="ml-auto flex items-center gap-2 text-xs">
          <span className="text-muted-foreground">
            {STRATEGY_LABEL[link.match_strategy]}
            {link.match_score < 1 && ` (similaridad ${Math.round(link.match_score * 100)}%)`}
          </span>
          <button
            onClick={onUnlink}
            disabled={busy}
            className="text-red-700 hover:bg-red-100 rounded p-1"
            title="Desvincular"
          >
            <Link2Off className="h-3.5 w-3.5" />
          </button>
        </span>
      </div>

      {cmp && <ComparisonTable cmp={cmp} />}
    </div>
  );
}

function ComparisonTable({ cmp }: { cmp: ComparisonResult }) {
  const { summary, lines_in_both, lines_only_in_order, lines_only_in_offer } = cmp;

  return (
    <div className="px-4 py-3">
      <div className="flex flex-wrap items-center gap-2 text-xs mb-3">
        <Pill color="emerald" label={`${summary.common} comunes`} />
        {summary.price_discrepancies > 0 && (
          <Pill color="amber" label={`${summary.price_discrepancies} precios distintos`} />
        )}
        {summary.qty_discrepancies > 0 && (
          <Pill color="amber" label={`${summary.qty_discrepancies} cantidades distintas`} />
        )}
        {summary.added_in_order > 0 && (
          <Pill color="sky" label={`${summary.added_in_order} añadidas en pedido`} />
        )}
        {summary.removed_from_offer > 0 && (
          <Pill color="zinc" label={`${summary.removed_from_offer} ausentes`} />
        )}
      </div>

      {lines_in_both.some((l) => l.issues.length > 0) && (
        <details open className="mb-2">
          <summary className="text-xs cursor-pointer text-muted-foreground hover:text-foreground">
            Líneas con discrepancias ({lines_in_both.filter((l) => l.issues.length > 0).length})
          </summary>
          <table className="w-full text-xs mt-2">
            <thead className="text-left text-muted-foreground">
              <tr>
                <th className="px-2 py-1">Ref</th>
                <th className="px-2 py-1 text-right">Cant. oferta</th>
                <th className="px-2 py-1 text-right">Cant. pedido</th>
                <th className="px-2 py-1 text-right">€/ud oferta</th>
                <th className="px-2 py-1 text-right">€/ud pedido</th>
                <th className="px-2 py-1">Issues</th>
              </tr>
            </thead>
            <tbody>
              {lines_in_both
                .filter((l) => l.issues.length > 0)
                .map((l, i) => (
                  <tr key={i} className="border-t border-current/10">
                    <td className="px-2 py-1 font-mono">{l.reference}</td>
                    <td className="px-2 py-1 text-right tabular-nums">{l.in_offer.cantidad ?? "—"}</td>
                    <td className={cn("px-2 py-1 text-right tabular-nums", l.issues.includes("qty_changed") && "font-bold")}>
                      {l.in_order.cantidad ?? "—"}
                    </td>
                    <td className="px-2 py-1 text-right tabular-nums">
                      {l.in_offer.precio_unitario != null ? l.in_offer.precio_unitario.toFixed(2) : "—"}
                    </td>
                    <td className={cn("px-2 py-1 text-right tabular-nums", l.issues.includes("price_changed") && "font-bold")}>
                      {l.in_order.precio_unitario != null ? l.in_order.precio_unitario.toFixed(2) : "—"}
                    </td>
                    <td className="px-2 py-1 text-amber-800">{l.issues.join(", ")}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </details>
      )}

      {lines_only_in_order.length > 0 && (
        <details className="mb-2">
          <summary className="text-xs cursor-pointer text-muted-foreground hover:text-foreground">
            Añadidas en pedido (no estaban en oferta) — {lines_only_in_order.length}
          </summary>
          <ul className="text-xs mt-2 space-y-0.5">
            {lines_only_in_order.map((l, i) => (
              <li key={i} className="font-mono">
                + {l.reference} ({l.cantidad ?? "—"}) {l.precio_unitario ? `@ ${l.precio_unitario.toFixed(2)}` : ""}
              </li>
            ))}
          </ul>
        </details>
      )}

      {lines_only_in_offer.length > 0 && (
        <details>
          <summary className="text-xs cursor-pointer text-muted-foreground hover:text-foreground">
            En oferta pero no pedidas — {lines_only_in_offer.length}
          </summary>
          <ul className="text-xs mt-2 space-y-0.5">
            {lines_only_in_offer.map((l, i) => (
              <li key={i} className="font-mono">
                − {l.reference} ({l.cantidad ?? "—"})
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function Pill({ color, label }: { color: "emerald" | "amber" | "sky" | "zinc"; label: string }) {
  const colors = {
    emerald: "bg-emerald-200 text-emerald-900",
    amber: "bg-amber-200 text-amber-900",
    sky: "bg-sky-200 text-sky-900",
    zinc: "bg-zinc-200 text-zinc-800",
  };
  return <span className={cn("rounded-full px-2 py-0.5", colors[color])}>{label}</span>;
}

// =============================================================================
// Panel "Reglas workflow" — bloqueos / avisos / notas dinámicos del tenant
// =============================================================================

function WorkflowPanel({ result }: { result: WorkflowEvaluation }) {
  if (
    !result.blocked &&
    result.warnings.length === 0 &&
    result.notes.length === 0 &&
    result.status_overrides.length === 0
  ) {
    return null;  // no aplicó ninguna regla → no mostrar panel
  }

  const headerStyle = result.blocked
    ? "border-red-300 bg-red-50 text-red-900"
    : result.warnings.length > 0
      ? "border-amber-300 bg-amber-50 text-amber-900"
      : "border-zinc-300 bg-zinc-50 text-zinc-800";

  return (
    <div className={cn("rounded-lg border", headerStyle)}>
      <div className="px-4 py-2.5 border-b border-current/20 flex items-center gap-2">
        <WorkflowIcon className="h-4 w-4" />
        <span className="font-medium">Reglas de workflow</span>
        <span className="ml-auto text-xs">
          {result.rules_matched.length} de {result.rules_evaluated} aplicaron
        </span>
      </div>
      <div className="divide-y divide-current/10">
        {result.blocking_rules.map((r, i) => (
          <div key={`b-${i}`} className="px-4 py-2 flex items-start gap-2">
            <ShieldX className="h-4 w-4 mt-0.5 shrink-0 text-red-700" />
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-red-900">{r.name}</div>
              <div className="text-sm">{r.message}</div>
            </div>
            <span className="text-xs bg-red-200 text-red-900 rounded px-1.5 py-0.5 shrink-0">BLOQUEA</span>
          </div>
        ))}
        {result.warnings.map((r, i) => (
          <div key={`w-${i}`} className="px-4 py-2 flex items-start gap-2">
            <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0 text-amber-700" />
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium text-amber-900">{r.name}</div>
              <div className="text-sm">{r.message}</div>
            </div>
            <span className="text-xs bg-amber-200 text-amber-900 rounded px-1.5 py-0.5 shrink-0">AVISO</span>
          </div>
        ))}
        {result.notes.map((r, i) => (
          <div key={`n-${i}`} className="px-4 py-2 flex items-start gap-2">
            <CircleHelp className="h-4 w-4 mt-0.5 shrink-0 text-zinc-700" />
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium">{r.name}</div>
              <div className="text-sm">{r.message}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// =============================================================================
// Panel de validación contra catálogo
// =============================================================================

const LEVEL_STYLE: Record<ValidationLevel, { bg: string; text: string; icon: typeof AlertTriangle }> = {
  blocking: { bg: "bg-red-100 border-red-300", text: "text-red-900", icon: AlertTriangle },
  warning: { bg: "bg-amber-100 border-amber-300", text: "text-amber-900", icon: AlertTriangle },
  unknown: { bg: "bg-zinc-100 border-zinc-300", text: "text-zinc-800", icon: CircleHelp },
  ok: { bg: "bg-emerald-100 border-emerald-300", text: "text-emerald-900", icon: ShieldCheck },
};

function ValidationPanel({ result }: { result: ValidationResult }) {
  const { summary, lines } = result;
  const issues = lines.filter((l) => l.level !== "ok");

  if (summary.total_lines === 0) return null;

  const allOk = summary.blocking === 0 && summary.warnings === 0 && summary.unknown === 0;
  if (allOk) {
    return (
      <div className="rounded-md border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-900 flex items-center gap-2">
        <ShieldCheck className="h-4 w-4" />
        Validación OK: <strong>{summary.ok}</strong> líneas dentro del catálogo y por encima del precio mínimo.
      </div>
    );
  }

  const headerStyle =
    summary.blocking > 0
      ? "border-red-300 bg-red-50 text-red-900"
      : summary.warnings > 0
        ? "border-amber-300 bg-amber-50 text-amber-900"
        : "border-zinc-300 bg-zinc-50 text-zinc-800";

  return (
    <div className={cn("rounded-lg border", headerStyle)}>
      <div className="px-4 py-2.5 border-b border-current/20 flex items-center gap-2 font-medium">
        <AlertTriangle className="h-4 w-4" />
        Validación contra catálogo
        <div className="ml-auto flex items-center gap-2 text-xs font-normal">
          {summary.blocking > 0 && (
            <span className="bg-red-200/60 rounded-full px-2 py-0.5">
              {summary.blocking} bloqueante{summary.blocking !== 1 && "s"}
            </span>
          )}
          {summary.warnings > 0 && (
            <span className="bg-amber-200/60 rounded-full px-2 py-0.5">
              {summary.warnings} aviso{summary.warnings !== 1 && "s"}
            </span>
          )}
          {summary.unknown > 0 && (
            <span className="bg-zinc-200/60 rounded-full px-2 py-0.5">
              {summary.unknown} sin catálogo
            </span>
          )}
          {summary.ok > 0 && (
            <span className="bg-emerald-200/60 rounded-full px-2 py-0.5 text-emerald-900">
              {summary.ok} OK
            </span>
          )}
        </div>
      </div>
      <div className="divide-y divide-current/10 text-sm">
        {issues.map((line, i) => {
          const style = LEVEL_STYLE[line.level];
          const Icon = style.icon;
          return (
            <div key={i} className="px-4 py-2 flex items-start gap-2">
              <Icon className={cn("h-4 w-4 mt-0.5 shrink-0", style.text)} />
              <div className="flex-1 min-w-0">
                <div className="flex items-baseline gap-2">
                  {line.reference && (
                    <span className="font-mono text-xs">{line.reference}</span>
                  )}
                  <span className="text-xs text-muted-foreground">
                    línea {line.line_index + 1}
                  </span>
                </div>
                <div className="text-sm">{line.message}</div>
              </div>
              {line.actual_price !== null && line.min_price !== null && (
                <div className="text-xs text-right tabular-nums shrink-0">
                  <div>actual {line.actual_price}</div>
                  <div className="text-muted-foreground">mín. {line.min_price}</div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function formatMoney(value: number | null | undefined, moneda: string): React.ReactNode {
  if (value === null || value === undefined) {
    return <span className="text-muted-foreground italic">—</span>;
  }
  const symbol = moneda === "EUR" ? "€" : moneda === "USD" ? "$" : moneda;
  return `${formatMoneyValue(value)} ${symbol}`;
}

function formatMoneyValue(value: number): string {
  return value.toLocaleString("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** Resolución de path tipo "lineas.0.descripcion" sobre un objeto. */
function getByPath(obj: unknown, path: string): string | null {
  const parts = path.split(".");
  let cur: unknown = obj;
  for (const p of parts) {
    if (cur === null || cur === undefined) return null;
    if (Array.isArray(cur)) {
      const idx = Number(p);
      if (Number.isNaN(idx)) return null;
      cur = cur[idx];
    } else if (typeof cur === "object") {
      cur = (cur as Record<string, unknown>)[p];
    } else {
      return null;
    }
  }
  if (typeof cur === "string") return cur;
  if (typeof cur === "number") return String(cur);
  return null;
}
