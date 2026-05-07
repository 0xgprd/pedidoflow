import { useEffect, useMemo, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import { ZoomIn, ZoomOut, RotateCcw, Tag, PlusSquare } from "lucide-react";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import workerSrc from "pdfjs-dist/build/pdf.worker.min.mjs?url";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

pdfjs.GlobalWorkerOptions.workerSrc = workerSrc;

export interface Highlight {
  /** Path del campo extraído, ej: "cliente.nombre", "lineas.2.referencia" */
  path: string;
  /** Texto fuente literal del PDF que se quiere resaltar */
  text: string;
}

interface Props {
  data: Uint8Array | null;
  highlights?: Highlight[];
  /** Path del campo activo: highlight más fuerte + scroll */
  activePath?: string | null;
  className?: string;
  /** Callback cuando el usuario selecciona texto y pulsa "Asignar concepto" */
  onAssignConcept?: (selectedText: string) => void;
  /** Callback cuando el usuario selecciona texto y pulsa "Crear campo custom" */
  onCreateCustomField?: (selectedText: string) => void;
}

const MIN_SCALE = 0.5;
const MAX_SCALE = 3;
const STEP = 0.2;

export function PDFViewer({
  data,
  highlights = [],
  activePath = null,
  className,
  onAssignConcept,
  onCreateCustomField,
}: Props) {
  const [numPages, setNumPages] = useState<number>(0);
  const [scale, setScale] = useState<number>(1.4);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectionMenu, setSelectionMenu] = useState<{
    text: string;
    x: number;
    y: number;
  } | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const fileProp = useMemo(() => (data ? { data } : null), [data]);

  // Pre-procesar highlights: lowercase + filter cortos
  const normalizedHighlights = useMemo(
    () =>
      highlights
        .map((h) => ({
          path: h.path,
          text: h.text.toLowerCase().trim(),
        }))
        .filter((h) => h.text.length >= 2),
    [highlights],
  );

  const normalizedActive = useMemo(() => {
    if (!activePath) return null;
    const h = normalizedHighlights.find((h) => h.path === activePath);
    return h?.text ?? null;
  }, [activePath, normalizedHighlights]);

  function textRenderer({ str }: { str: string; itemIndex: number }): string {
    const lower = str.toLowerCase().trim();
    if (lower.length < 2) return escapeHtml(str);

    // Buscar todos los highlights que matcheen este item (substring bidireccional)
    const matches = normalizedHighlights.filter(
      (h) => h.text.includes(lower) || lower.includes(h.text),
    );
    if (matches.length === 0) return escapeHtml(str);

    // Prioridad: si alguno es el activo, usar su color y marcarlo activo
    const activeMatch = matches.find((m) => m.path === activePath);
    const chosen = activeMatch ?? matches[0];
    const isActive = activeMatch !== undefined;

    const color = colorForPath(chosen.path, isActive);
    const ring = isActive ? "box-shadow:0 0 0 2px rgba(0,0,0,0.4);" : "";
    const dataActive = isActive ? ' data-active="true"' : "";

    return `<mark${dataActive} style="background:${color};${ring}color:inherit;border-radius:2px;padding:0 1px;">${escapeHtml(str)}</mark>`;
  }

  // Scroll al match activo cuando cambia
  useEffect(() => {
    if (!activePath || !containerRef.current) return;
    const t = setTimeout(() => {
      const el = containerRef.current?.querySelector<HTMLElement>('[data-active="true"]');
      if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 100);
    return () => clearTimeout(t);
  }, [activePath, scale, numPages]);

  // Detectar selección de texto dentro del PDF para mostrar menú flotante
  useEffect(() => {
    if (!onAssignConcept && !onCreateCustomField) return;
    const container = containerRef.current;
    if (!container) return;

    function handle() {
      const sel = window.getSelection();
      if (!sel || sel.isCollapsed || sel.rangeCount === 0) {
        setSelectionMenu(null);
        return;
      }
      const text = sel.toString().trim();
      if (text.length < 2) {
        setSelectionMenu(null);
        return;
      }
      const range = sel.getRangeAt(0);
      // Solo procesar si la selección está dentro del PDF
      if (!container || !container.contains(range.commonAncestorContainer)) {
        setSelectionMenu(null);
        return;
      }
      const rect = range.getBoundingClientRect();
      const containerRect = container.getBoundingClientRect();
      setSelectionMenu({
        text,
        x: rect.left - containerRect.left + rect.width / 2,
        y: rect.top - containerRect.top - 8,
      });
    }

    document.addEventListener("selectionchange", handle);
    return () => {
      document.removeEventListener("selectionchange", handle);
    };
  }, [onAssignConcept, onCreateCustomField]);

  if (!fileProp) {
    return (
      <div className={cn("rounded-lg border bg-zinc-50 p-8 text-center text-sm text-muted-foreground", className)}>
        Cargando PDF...
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className={cn(
        "rounded-lg border bg-zinc-100 overflow-y-auto overflow-x-auto flex flex-col relative",
        className,
      )}
    >
      {selectionMenu && (
        <div
          className="absolute z-30 -translate-x-1/2 -translate-y-full bg-zinc-900 text-white text-xs rounded shadow-lg flex divide-x divide-zinc-700 whitespace-nowrap"
          style={{ left: selectionMenu.x, top: selectionMenu.y }}
          onMouseDown={(e) => e.preventDefault()}
        >
          {onAssignConcept && (
            <button
              className="px-2.5 py-1.5 hover:bg-zinc-800 flex items-center gap-1.5 first:rounded-l"
              onClick={() => {
                onAssignConcept(selectionMenu.text);
                window.getSelection()?.removeAllRanges();
                setSelectionMenu(null);
              }}
              title="Mapear este texto a un concepto canónico (memoria)"
            >
              <Tag className="h-3 w-3" />
              Asignar concepto
            </button>
          )}
          {onCreateCustomField && (
            <button
              className="px-2.5 py-1.5 hover:bg-zinc-800 flex items-center gap-1.5 last:rounded-r"
              onClick={() => {
                onCreateCustomField(selectionMenu.text);
                window.getSelection()?.removeAllRanges();
                setSelectionMenu(null);
              }}
              title="Añadir como campo nuevo a este documento"
            >
              <PlusSquare className="h-3 w-3" />
              Campo custom
            </button>
          )}
        </div>
      )}
      <div className="sticky top-0 z-10 bg-white/95 backdrop-blur border-b px-3 py-1.5 flex items-center gap-1 text-xs">
        <Button
          size="sm"
          variant="ghost"
          className="h-7 w-7 p-0"
          onClick={() => setScale((s) => Math.max(MIN_SCALE, +(s - STEP).toFixed(2)))}
          disabled={scale <= MIN_SCALE}
          title="Reducir zoom"
        >
          <ZoomOut className="h-3.5 w-3.5" />
        </Button>
        <span className="tabular-nums w-12 text-center text-muted-foreground">
          {Math.round(scale * 100)}%
        </span>
        <Button
          size="sm"
          variant="ghost"
          className="h-7 w-7 p-0"
          onClick={() => setScale((s) => Math.min(MAX_SCALE, +(s + STEP).toFixed(2)))}
          disabled={scale >= MAX_SCALE}
          title="Aumentar zoom"
        >
          <ZoomIn className="h-3.5 w-3.5" />
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="h-7 w-7 p-0"
          onClick={() => setScale(1.4)}
          title="Tamaño original"
        >
          <RotateCcw className="h-3.5 w-3.5" />
        </Button>
        {numPages > 0 && (
          <span className="ml-auto text-muted-foreground">
            {numPages} pág.
          </span>
        )}
      </div>

      <Document
        file={fileProp}
        onLoadSuccess={({ numPages: n }) => {
          setNumPages(n);
          setLoadError(null);
        }}
        onLoadError={(err) => {
          // eslint-disable-next-line no-console
          console.error("PDFViewer load error:", err);
          setLoadError(err instanceof Error ? err.message : String(err));
        }}
        onSourceError={(err) => {
          // eslint-disable-next-line no-console
          console.error("PDFViewer source error:", err);
          setLoadError(err instanceof Error ? err.message : String(err));
        }}
        loading={<div className="p-8 text-center text-sm text-muted-foreground">Cargando PDF...</div>}
        error={
          <div className="p-8 text-center text-sm text-red-700 space-y-1">
            <div className="font-medium">Error cargando PDF</div>
            {loadError && <div className="text-xs font-mono text-red-600">{loadError}</div>}
            <div className="text-xs text-muted-foreground">Mira la consola (F12) para más detalle</div>
          </div>
        }
        className="flex flex-col items-center gap-3 py-3 min-w-fit"
      >
        {Array.from({ length: numPages }, (_, i) => (
          <div key={i} className="bg-white shadow-sm">
            <Page
              pageNumber={i + 1}
              scale={scale}
              customTextRenderer={textRenderer}
              renderAnnotationLayer={false}
            />
          </div>
        ))}
      </Document>
    </div>
  );
}

// =============================================================================
// Paleta de colores por sección
// =============================================================================

const LINE_COLORS = [
  [245, 158, 11], // amber-500
  [249, 115, 22], // orange-500
  [236, 72, 153], // pink-500
  [234, 179, 8], // yellow-500
  [217, 70, 239], // fuchsia-500
];

/** Devuelve un color RGBA según la sección del path. Más opaco si es el activo. */
export function colorForPath(path: string, active: boolean): string {
  const alpha = active ? 0.7 : 0.3;
  if (path.startsWith("cliente.")) return `rgba(16,185,129,${alpha})`; // emerald
  if (path.startsWith("pedido.")) return `rgba(59,130,246,${alpha})`; // sky
  if (path.startsWith("totales.")) return `rgba(139,92,246,${alpha})`; // violet
  const m = path.match(/^lineas\.(\d+)\./);
  if (m) {
    const [r, g, b] = LINE_COLORS[Number(m[1]) % LINE_COLORS.length];
    return `rgba(${r},${g},${b},${alpha})`;
  }
  return `rgba(252,211,77,${alpha})`; // default amber
}

/** Tailwind-ish background class por sección — para badges en el form */
export function bgClassForPath(path: string): string {
  if (path.startsWith("cliente.")) return "bg-emerald-100 ring-emerald-300";
  if (path.startsWith("pedido.")) return "bg-sky-100 ring-sky-300";
  if (path.startsWith("totales.")) return "bg-violet-100 ring-violet-300";
  if (/^lineas\./.test(path)) {
    const m = path.match(/^lineas\.(\d+)\./);
    const idx = m ? Number(m[1]) % 5 : 0;
    return [
      "bg-amber-100 ring-amber-300",
      "bg-orange-100 ring-orange-300",
      "bg-pink-100 ring-pink-300",
      "bg-yellow-100 ring-yellow-300",
      "bg-fuchsia-100 ring-fuchsia-300",
    ][idx];
  }
  return "bg-amber-100 ring-amber-300";
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => {
    switch (c) {
      case "&":
        return "&amp;";
      case "<":
        return "&lt;";
      case ">":
        return "&gt;";
      case '"':
        return "&quot;";
      case "'":
        return "&#39;";
      default:
        return c;
    }
  });
}
