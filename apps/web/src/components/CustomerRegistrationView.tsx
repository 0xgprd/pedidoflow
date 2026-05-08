/**
 * Vista de alta de cliente — formulario editable que el usuario revisa antes
 * de dar de alta el cliente en el ERP. Sustituye al editor de pedido cuando
 * `doc.document_type === "ficha_cliente"`.
 *
 * El extracted_json viene con la estructura de CustomerRegistrationPayload
 * (lo guardó el worker tras la extracción IA). El usuario puede editar
 * cualquier campo antes de pulsar "Dar de alta en el ERP".
 */
import { useEffect, useState } from "react";
import {
  Building2,
  Mail,
  MapPin,
  Phone,
  Receipt,
  Save,
  Send,
  User,
  Users,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { api, ApiError } from "@/lib/api";
import type {
  CustomerAddress,
  CustomerContactPerson,
  CustomerRegistrationPayload,
  CustomerTaxCategory,
  DocumentRead,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const EMPTY_ADDRESS: CustomerAddress = {
  line1: "",
  line2: null,
  city: "",
  postal_code: "",
  state_or_region: null,
  country: "",
};

function emptyDraft(): CustomerRegistrationPayload {
  return {
    company_name: "",
    fiscal_name: null,
    tax_id: null,
    eu_vat: null,
    supplier_number_in_customer_system: null,
    fiscal_address: { ...EMPTY_ADDRESS },
    billing_address: null,
    shipping_address: null,
    main_phone: null,
    secondary_phone: null,
    fax: null,
    main_email: null,
    contacts: [],
    tax_category: "unknown",
    payment_terms: null,
    bank_account_iban: null,
    preferred_language: null,
    signed_by_name: null,
    signed_by_role: null,
    signature_date: null,
  };
}

function fromExtractedJson(json: unknown): CustomerRegistrationPayload {
  // Hidratamos defaults para que ningún campo sea undefined (TS estricto).
  const base = emptyDraft();
  if (!json || typeof json !== "object") return base;
  const e = json as Partial<CustomerRegistrationPayload>;
  return {
    ...base,
    ...e,
    fiscal_address:
      e.fiscal_address && typeof e.fiscal_address === "object"
        ? { ...EMPTY_ADDRESS, ...e.fiscal_address }
        : { ...EMPTY_ADDRESS },
    billing_address:
      e.billing_address && typeof e.billing_address === "object"
        ? { ...EMPTY_ADDRESS, ...e.billing_address }
        : null,
    shipping_address:
      e.shipping_address && typeof e.shipping_address === "object"
        ? { ...EMPTY_ADDRESS, ...e.shipping_address }
        : null,
    contacts: Array.isArray(e.contacts) ? e.contacts : [],
    tax_category: (e.tax_category as CustomerTaxCategory) ?? "unknown",
  };
}

const TAX_CATEGORY_OPTIONS: { value: CustomerTaxCategory; label: string; help: string }[] = [
  { value: "domestic", label: "Doméstico", help: "Mismo país que tu empresa — IVA normal" },
  {
    value: "eu_intracom",
    label: "Intracomunitario UE",
    help: "Cliente UE con VAT válido — IVA 0% (inversión sujeto pasivo)",
  },
  { value: "export", label: "Exportación", help: "Cliente fuera de UE — IVA 0% por exportación" },
  { value: "unknown", label: "Sin determinar", help: "El ERP decidirá según reglas del cliente" },
];

interface Props {
  doc: DocumentRead;
  onUpdated: (doc: DocumentRead) => void;
}

export function CustomerRegistrationView({ doc, onUpdated }: Props) {
  const [draft, setDraft] = useState<CustomerRegistrationPayload>(() =>
    fromExtractedJson(doc.extracted_json),
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Si llega un doc actualizado (e.g. tras refresh) re-hidratamos
  useEffect(() => {
    setDraft(fromExtractedJson(doc.extracted_json));
  }, [doc.extracted_json]);

  const alreadyRegistered = !!doc.erp_id;

  async function handleSubmit() {
    if (!draft.company_name.trim()) {
      setError("La razón social es obligatoria.");
      return;
    }
    if (!draft.fiscal_address.line1.trim() || !draft.fiscal_address.country.trim()) {
      setError(
        "La dirección fiscal necesita al menos calle y país. Revisa los campos.",
      );
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      // Normaliza addresses opcionales: si están totalmente vacías, las mandamos null
      const payload: CustomerRegistrationPayload = {
        ...draft,
        billing_address: addressOrNull(draft.billing_address),
        shipping_address: addressOrNull(draft.shipping_address),
      };
      const updated = await api.registerCustomer(doc.id, payload);
      onUpdated(updated);
    } catch (e) {
      if (e instanceof ApiError) {
        setError(e.message);
      } else {
        setError(e instanceof Error ? e.message : String(e));
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-5">
      {alreadyRegistered ? (
        <div className="rounded-lg border border-emerald-300 bg-emerald-50 p-4 flex items-start gap-3">
          <Send className="h-5 w-5 text-emerald-700 mt-0.5 shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="text-sm font-semibold text-emerald-900">
              Cliente dado de alta en el ERP
            </div>
            <p className="mt-1 text-sm text-emerald-900/90">
              Este cliente está registrado como{" "}
              <span className="font-mono font-medium">{doc.erp_id}</span>. Si quieres
              modificar sus datos, edítalos directamente en el ERP — no aquí.
            </p>
            {doc.erp_url && (
              <a
                href={doc.erp_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 mt-2 text-sm text-emerald-900 hover:underline"
              >
                Ver en el ERP →
              </a>
            )}
          </div>
        </div>
      ) : (
        <div className="rounded-lg border border-indigo-300 bg-indigo-50 p-4 flex items-start gap-3">
          <User className="h-5 w-5 text-indigo-700 mt-0.5 shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="text-sm font-semibold text-indigo-900">
              Ficha de alta de cliente
            </div>
            <p className="mt-1 text-sm text-indigo-900/90">
              Revisa los datos extraídos por la IA. Cuando estés conforme, pulsa{" "}
              <strong>"Dar de alta en el ERP"</strong> para crear el cliente con
              direcciones, contactos y categoría fiscal — todo de una vez.
            </p>
          </div>
        </div>
      )}

      {error && (
        <div className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900">
          {error}
        </div>
      )}

      {/* Identidad */}
      <Section title="Identidad" icon={Building2}>
        <FieldGrid>
          <Field
            label="Razón social *"
            value={draft.company_name}
            onChange={(v) => setDraft({ ...draft, company_name: v ?? "" })}
            disabled={alreadyRegistered}
            wide
          />
          <Field
            label="Razón social fiscal (si distinta)"
            value={draft.fiscal_name}
            onChange={(v) => setDraft({ ...draft, fiscal_name: v })}
            disabled={alreadyRegistered}
            wide
          />
          <Field
            label="VAT intracomunitario"
            value={draft.eu_vat}
            onChange={(v) => setDraft({ ...draft, eu_vat: v })}
            placeholder="FRxxxxxxxxxxx"
            disabled={alreadyRegistered}
          />
          <Field
            label="CIF / NIF local"
            value={draft.tax_id}
            onChange={(v) => setDraft({ ...draft, tax_id: v })}
            disabled={alreadyRegistered}
          />
          <Field
            label="Nº de proveedor en su sistema"
            help="Cómo nos identifican ellos a NOSOTROS en su ERP"
            value={draft.supplier_number_in_customer_system}
            onChange={(v) => setDraft({ ...draft, supplier_number_in_customer_system: v })}
            disabled={alreadyRegistered}
            wide
          />
        </FieldGrid>
      </Section>

      {/* Dirección fiscal */}
      <Section title="Dirección fiscal *" icon={MapPin}>
        <AddressFields
          value={draft.fiscal_address}
          onChange={(v) => setDraft({ ...draft, fiscal_address: v })}
          disabled={alreadyRegistered}
        />
      </Section>

      {/* Dirección de facturación (opcional) */}
      <Section
        title="Dirección de facturación"
        icon={Receipt}
        action={
          !alreadyRegistered &&
          (draft.billing_address ? (
            <button
              onClick={() => setDraft({ ...draft, billing_address: null })}
              className="text-xs text-zinc-600 hover:text-red-700"
            >
              Eliminar (usar la fiscal)
            </button>
          ) : (
            <button
              onClick={() => setDraft({ ...draft, billing_address: { ...EMPTY_ADDRESS } })}
              className="text-xs text-blue-600 hover:underline"
            >
              + Añadir (si distinta de la fiscal)
            </button>
          ))
        }
      >
        {draft.billing_address ? (
          <AddressFields
            value={draft.billing_address}
            onChange={(v) => setDraft({ ...draft, billing_address: v })}
            disabled={alreadyRegistered}
          />
        ) : (
          <p className="text-sm text-muted-foreground italic">
            Misma que la dirección fiscal.
          </p>
        )}
      </Section>

      {/* Contacto a nivel empresa */}
      <Section title="Contacto general" icon={Phone}>
        <FieldGrid>
          <Field
            label="Email general"
            value={draft.main_email}
            onChange={(v) => setDraft({ ...draft, main_email: v })}
            disabled={alreadyRegistered}
            type="email"
          />
          <Field
            label="Teléfono principal"
            value={draft.main_phone}
            onChange={(v) => setDraft({ ...draft, main_phone: v })}
            disabled={alreadyRegistered}
          />
          <Field
            label="Teléfono secundario"
            value={draft.secondary_phone}
            onChange={(v) => setDraft({ ...draft, secondary_phone: v })}
            disabled={alreadyRegistered}
          />
          <Field
            label="Fax"
            value={draft.fax}
            onChange={(v) => setDraft({ ...draft, fax: v })}
            disabled={alreadyRegistered}
          />
        </FieldGrid>
      </Section>

      {/* Personas de contacto */}
      <Section
        title={`Personas de contacto (${draft.contacts.length})`}
        icon={Users}
        action={
          !alreadyRegistered && (
            <button
              onClick={() =>
                setDraft({
                  ...draft,
                  contacts: [...draft.contacts, { name: "", role: null, phone: null, email: null }],
                })
              }
              className="text-xs text-blue-600 hover:underline"
            >
              + Añadir contacto
            </button>
          )
        }
      >
        {draft.contacts.length === 0 ? (
          <p className="text-sm text-muted-foreground italic">Sin contactos personales.</p>
        ) : (
          <div className="space-y-3">
            {draft.contacts.map((c, idx) => (
              <ContactRow
                key={idx}
                value={c}
                onChange={(v) =>
                  setDraft({
                    ...draft,
                    contacts: draft.contacts.map((x, i) => (i === idx ? v : x)),
                  })
                }
                onDelete={() =>
                  setDraft({
                    ...draft,
                    contacts: draft.contacts.filter((_, i) => i !== idx),
                  })
                }
                disabled={alreadyRegistered}
              />
            ))}
          </div>
        )}
      </Section>

      {/* Datos comerciales y fiscales */}
      <Section title="Datos comerciales" icon={Mail}>
        <FieldGrid>
          <div className="md:col-span-2 space-y-1">
            <label className="text-xs text-muted-foreground uppercase tracking-wide">
              Categoría fiscal
            </label>
            <select
              value={draft.tax_category}
              onChange={(e) =>
                setDraft({ ...draft, tax_category: e.target.value as CustomerTaxCategory })
              }
              disabled={alreadyRegistered}
              className="w-full text-sm border rounded px-2 py-1 bg-white disabled:bg-zinc-50"
            >
              {TAX_CATEGORY_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
            <p className="text-xs text-muted-foreground italic">
              {
                TAX_CATEGORY_OPTIONS.find((o) => o.value === draft.tax_category)
                  ?.help
              }
            </p>
          </div>
          <Field
            label="Condiciones de pago"
            value={draft.payment_terms}
            onChange={(v) => setDraft({ ...draft, payment_terms: v })}
            disabled={alreadyRegistered}
            wide
            placeholder="Transferencia 30 días"
          />
          <Field
            label="IBAN"
            value={draft.bank_account_iban}
            onChange={(v) => setDraft({ ...draft, bank_account_iban: v })}
            disabled={alreadyRegistered}
            wide
          />
          <Field
            label="Idioma preferido"
            value={draft.preferred_language}
            onChange={(v) => setDraft({ ...draft, preferred_language: v })}
            disabled={alreadyRegistered}
            placeholder="es / fr / en / de / it"
          />
        </FieldGrid>
      </Section>

      {/* Auditoría: firma de la ficha */}
      <Section title="Firma de la ficha" icon={User}>
        <FieldGrid>
          <Field
            label="Nombre del firmante"
            value={draft.signed_by_name}
            onChange={(v) => setDraft({ ...draft, signed_by_name: v })}
            disabled={alreadyRegistered}
          />
          <Field
            label="Función"
            value={draft.signed_by_role}
            onChange={(v) => setDraft({ ...draft, signed_by_role: v })}
            disabled={alreadyRegistered}
          />
          <Field
            label="Fecha de firma"
            value={draft.signature_date}
            onChange={(v) => setDraft({ ...draft, signature_date: v })}
            disabled={alreadyRegistered}
            placeholder="YYYY-MM-DD"
            type="date"
          />
        </FieldGrid>
      </Section>

      {/* CTA */}
      {!alreadyRegistered && (
        <div className="sticky bottom-0 -mx-8 px-8 py-3 bg-white/95 backdrop-blur border-t flex items-center justify-end gap-2">
          <Button
            size="lg"
            onClick={handleSubmit}
            disabled={submitting}
            className="bg-indigo-600 hover:bg-indigo-700 text-white"
          >
            {submitting ? (
              <>
                <Save className="h-4 w-4 mr-2 animate-pulse" />
                Dando de alta...
              </>
            ) : (
              <>
                <Send className="h-4 w-4 mr-2" />
                Dar de alta en el ERP
              </>
            )}
          </Button>
        </div>
      )}
    </div>
  );
}

// =============================================================================
// Sub-componentes
// =============================================================================

function addressOrNull(addr: CustomerAddress | null | undefined): CustomerAddress | null {
  if (!addr) return null;
  // Si todos los campos relevantes están vacíos, lo tratamos como null
  const hasAny =
    addr.line1?.trim() ||
    addr.line2?.trim() ||
    addr.city?.trim() ||
    addr.postal_code?.trim() ||
    addr.country?.trim();
  return hasAny ? addr : null;
}

function Section({
  title,
  icon: Icon,
  children,
  action,
}: {
  title: string;
  icon: typeof Building2;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-l-4 border-l-indigo-400 bg-card overflow-hidden">
      <div className="px-4 py-2.5 border-b bg-muted/30 flex items-center gap-2">
        <Icon className="h-4 w-4 text-indigo-600" />
        <h2 className="text-sm font-semibold tracking-tight">{title}</h2>
        <div className="ml-auto">{action}</div>
      </div>
      <div className="p-4">{children}</div>
    </div>
  );
}

function FieldGrid({ children }: { children: React.ReactNode }) {
  return <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-3">{children}</div>;
}

function Field({
  label,
  value,
  onChange,
  disabled,
  placeholder,
  help,
  wide,
  type,
}: {
  label: string;
  value: string | null | undefined;
  onChange: (v: string | null) => void;
  disabled?: boolean;
  placeholder?: string;
  help?: string;
  wide?: boolean;
  type?: string;
}) {
  return (
    <div className={cn("space-y-1", wide && "md:col-span-2")}>
      <label className="text-xs text-muted-foreground uppercase tracking-wide">{label}</label>
      <input
        type={type ?? "text"}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value === "" ? null : e.target.value)}
        disabled={disabled}
        placeholder={placeholder}
        className="w-full text-sm border rounded px-2 py-1 bg-white disabled:bg-zinc-50 disabled:text-zinc-600"
      />
      {help && <p className="text-xs text-muted-foreground italic">{help}</p>}
    </div>
  );
}

function AddressFields({
  value,
  onChange,
  disabled,
}: {
  value: CustomerAddress;
  onChange: (v: CustomerAddress) => void;
  disabled?: boolean;
}) {
  return (
    <FieldGrid>
      <Field
        label="Calle / dirección *"
        value={value.line1}
        onChange={(v) => onChange({ ...value, line1: v ?? "" })}
        disabled={disabled}
        wide
      />
      <Field
        label="2ª línea"
        value={value.line2}
        onChange={(v) => onChange({ ...value, line2: v })}
        disabled={disabled}
        wide
        placeholder="Edificio, polígono, piso..."
      />
      <Field
        label="Ciudad *"
        value={value.city}
        onChange={(v) => onChange({ ...value, city: v ?? "" })}
        disabled={disabled}
      />
      <Field
        label="Código postal *"
        value={value.postal_code}
        onChange={(v) => onChange({ ...value, postal_code: v ?? "" })}
        disabled={disabled}
      />
      <Field
        label="Provincia / Departamento"
        value={value.state_or_region}
        onChange={(v) => onChange({ ...value, state_or_region: v })}
        disabled={disabled}
      />
      <Field
        label="País *"
        value={value.country}
        onChange={(v) => onChange({ ...value, country: v ?? "" })}
        disabled={disabled}
        placeholder="España, France, Deutschland..."
      />
    </FieldGrid>
  );
}

function ContactRow({
  value,
  onChange,
  onDelete,
  disabled,
}: {
  value: CustomerContactPerson;
  onChange: (v: CustomerContactPerson) => void;
  onDelete: () => void;
  disabled?: boolean;
}) {
  return (
    <div className="rounded border border-zinc-200 bg-zinc-50/50 p-3 grid grid-cols-1 md:grid-cols-4 gap-3 items-end">
      <Field
        label="Nombre"
        value={value.name}
        onChange={(v) => onChange({ ...value, name: v ?? "" })}
        disabled={disabled}
      />
      <Field
        label="Función"
        value={value.role}
        onChange={(v) => onChange({ ...value, role: v })}
        disabled={disabled}
      />
      <Field
        label="Teléfono"
        value={value.phone}
        onChange={(v) => onChange({ ...value, phone: v })}
        disabled={disabled}
      />
      <div className="flex gap-2 items-end">
        <div className="flex-1">
          <Field
            label="Email"
            value={value.email}
            onChange={(v) => onChange({ ...value, email: v })}
            disabled={disabled}
            type="email"
          />
        </div>
        {!disabled && (
          <button
            onClick={onDelete}
            className="text-xs text-red-600 hover:bg-red-50 rounded px-2 py-1 mb-0.5"
            title="Eliminar contacto"
          >
            ×
          </button>
        )}
      </div>
    </div>
  );
}
