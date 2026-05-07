import { useEffect, useMemo, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import { ZoomIn, ZoomOut, RotateCcw, Tag, PlusSquare, X, Check } from "lucide-react";
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

interface SelectedItem {
  text: string;
  /** Coordenadas relativas al containerRef (incluyen scroll) */
  rect: { x: number; y: number; width: number; height: number };
  id: string;
}

interface Props {
  data: Uint8Array | null;
  highlights?: Highlight[];
  /** Path del campo activo: highlight más fuerte + scroll */
  activePath?: string | null;
  className?: string;
  /** Callback al pulsar "Asignar a concepto" tras seleccionar texto */
  onAssignConcept?: (selectedText: string) => void;
  /** Callback al pulsar "Campo custom" tras seleccionar texto */
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
  // Selección por clicks acumulativos sobre palabras del text layer
  const [selectedItems, setSelectedItems] = useState<SelectedItem[]>([]);
  const [menuOpen, setMenuOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const enableClickSelect = !!(onAssignConcept || onCreateCustomField);

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

  // Memoizar textRenderer para evitar re-render del text layer (que destruye
  // la selección del usuario en curso).
  const textRenderer = useMemo(() => {
    return ({ str }: { str: string; itemIndex: number }): string => {
      const lower = str.toLowerCase().trim();
      if (lower.length < 2) return escapeHtml(str);

      const matches = normalizedHighlights.filter(
        (h) => h.text.includes(lower) || lower.includes(h.text),
      );
      if (matches.length === 0) return escapeHtml(str);

      const activeMatch = matches.find((m) => m.path === activePath);
      const chosen = activeMatch ?? matches[0];
      const isActive = activeMatch !== undefined;

      const color = colorForPath(chosen.path, isActive);
      const ring = isActive ? "box-shadow:0 0 0 2px rgba(0,0,0,0.4);" : "";
      const dataActive = isActive ? ' data-active="true"' : "";

      return `<mark${dataActive} style="background:${color};${ring}color:inherit;border-radius:2px;padding:0 1px;">${escapeHtml(str)}</mark>`;
    };
  }, [normalizedHighlights, activePath]);

  // Scroll al match activo cuando cambia
  useEffect(() => {
    if (!activePath || !containerRef.current) return;
    const t = setTimeout(() => {
      const el = containerRef.current?.querySelector<HTMLElement>('[data-active="true"]');
      if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 100);
    return () => clearTimeout(t);
  }, [activePath, scale, numPages]);

  // Modelo de selección por clicks acumulativos:
  // - 1 click sobre palabra → la añade/quita a la selección (toggle, cajita amarilla)
  // - dbl-click sobre palabra → reemplaza con solo esa + abre menú directamente
  //
  // pdf.js mete varias palabras en un mismo <span>. Para identificar SOLO la
  // palabra clicada usamos `caretRangeFromPoint` (Chrome/Safari) o
  // `caretPositionFromPoint` (Firefox), que mapean (x,y) → posición exacta en
  // el text node. Después extraemos la palabra que envuelve esa posición.
  useEffect(() => {
    if (!enableClickSelect) return;
    const container = containerRef.current;
    if (!container) return;

    function isInsideTextLayer(node: Node | null): boolean {
      if (!node) return false;
      const el = node.nodeType === Node.TEXT_NODE ? node.parentElement : (node as HTMLElement);
      return !!el?.closest?.(".react-pdf__Page__textContent");
    }

    function caretAtPoint(x: number, y: number): { node: Node; offset: number } | null {
      // Chrome / Safari / Edge
      const docAny = document as Document & {
        caretRangeFromPoint?: (x: number, y: number) => Range | null;
        caretPositionFromPoint?: (x: number, y: number) => { offsetNode: Node; offset: number } | null;
      };
      if (typeof docAny.caretRangeFromPoint === "function") {
        const r = docAny.caretRangeFromPoint(x, y);
        if (r) return { node: r.startContainer, offset: r.startOffset };
      }
      // Firefox
      if (typeof docAny.caretPositionFromPoint === "function") {
        const p = docAny.caretPositionFromPoint(x, y);
        if (p) return { node: p.offsetNode, offset: p.offset };
      }
      return null;
    }

    /**
     * Devuelve la palabra (texto + bounding rect) bajo el punto (x,y), o null.
     * "Palabra" = secuencia de caracteres no-espacio.
     */
    function getWordAt(x: number, y: number): { text: string; range: Range } | null {
      const caret = caretAtPoint(x, y);
      if (!caret) return null;
      if (!isInsideTextLayer(caret.node)) return null;
      const node = caret.node;
      if (node.nodeType !== Node.TEXT_NODE) return null;

      const text = node.textContent ?? "";
      const offset = caret.offset;

      // Buscar word boundaries: non-whitespace alrededor del offset
      let start = offset;
      let end = offset;
      while (start > 0 && /\S/.test(text[start - 1])) start--;
      while (end < text.length && /\S/.test(text[end])) end++;
      if (start === end) return null;  // no había palabra (espacio)

      const word = text.slice(start, end);
      const range = document.createRange();
      range.setStart(node, start);
      range.setEnd(node, end);
      return { text: word, range };
    }

    function rectFromRange(range: Range): SelectedItem["rect"] | null {
      const c = containerRef.current;
      if (!c) return null;
      const r = range.getBoundingClientRect();
      const cr = c.getBoundingClientRect();
      return {
        x: r.left - cr.left + c.scrollLeft,
        y: r.top - cr.top + c.scrollTop,
        width: r.width,
        height: r.height,
      };
    }

    function idForWord(word: string, rect: SelectedItem["rect"]): string {
      return `${word}@${Math.round(rect.x)},${Math.round(rect.y)}`;
    }

    function handleClick(e: MouseEvent) {
      // Ignorar clicks sobre el menú/cajitas/botones flotantes
      const t = e.target as HTMLElement;
      if (t.closest("[data-pdf-selection-menu]")) return;

      const word = getWordAt(e.clientX, e.clientY);
      if (!word) return;
      e.preventDefault();
      e.stopPropagation();

      const rect = rectFromRange(word.range);
      if (!rect) return;
      const id = idForWord(word.text, rect);

      setMenuOpen(false);
      setSelectedItems((prev) => {
        const idx = prev.findIndex((s) => s.id === id);
        if (idx >= 0) return prev.filter((_, i) => i !== idx);  // toggle off
        return [...prev, { text: word.text, rect, id }];
      });
    }

    function handleDblClick(e: MouseEvent) {
      const t = e.target as HTMLElement;
      if (t.closest("[data-pdf-selection-menu]")) return;

      const word = getWordAt(e.clientX, e.clientY);
      if (!word) return;
      e.preventDefault();
      e.stopPropagation();

      const rect = rectFromRange(word.range);
      if (!rect) return;
      const id = idForWord(word.text, rect);
      setSelectedItems([{ text: word.text, rect, id }]);
      setMenuOpen(true);
    }

    container.addEventListener("click", handleClick);
    container.addEventListener("dblclick", handleDblClick);
    return () => {
      container.removeEventListener("click", handleClick);
      container.removeEventListener("dblclick", handleDblClick);
    };
  }, [enableClickSelect, scale, numPages]);

  function clearSelection() {
    setSelectedItems([]);
    setMenuOpen(false);
  }

  const selectedText = selectedItems.map((s) => s.text).join(" ");

  function actAndClear(action: (text: string) => void) {
    if (!selectedText.trim()) return;
    action(selectedText);
    clearSelection();
  }

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
        enableClickSelect && "pf-clickable",
        className,
      )}
    >
      <style>{CLICK_SELECT_CSS}</style>

      {/* Cajitas amarillas sobre las palabras clicadas */}
      {selectedItems.map((item) => (
        <div
          key={item.id}
          className="absolute pointer-events-none rounded-sm bg-yellow-300/55 ring-2 ring-yellow-500 z-20"
          style={{
            left: item.rect.x - 1,
            top: item.rect.y - 1,
            width: item.rect.width + 2,
            height: item.rect.height + 2,
          }}
        />
      ))}

      {/* Botón flotante "Mapear (N)" o menú desplegable */}
      {selectedItems.length > 0 && !menuOpen && (
        <button
          data-pdf-selection-menu
          onClick={() => setMenuOpen(true)}
          className="fixed lg:absolute z-30 right-6 top-20 lg:top-16 bg-emerald-600 hover:bg-emerald-700 text-white text-sm rounded-lg shadow-xl px-3 py-2 flex items-center gap-2 font-medium"
        >
          <Check className="h-4 w-4" />
          Mapear ({selectedItems.length} {selectedItems.length === 1 ? "palabra" : "palabras"})
        </button>
      )}

      {selectedItems.length > 0 && menuOpen && (
        <div
          data-pdf-selection-menu
          className="fixed lg:absolute z-30 right-6 top-20 lg:top-16 bg-white text-zinc-900 rounded-lg shadow-xl border w-72 p-2 space-y-1"
        >
          <div className="px-2 py-1.5 border-b mb-1 flex items-start justify-between gap-2">
            <div className="text-xs font-medium leading-tight break-words flex-1 min-w-0">
              "{selectedText}"
            </div>
            <button
              onClick={clearSelection}
              className="text-muted-foreground hover:text-foreground p-0.5 rounded shrink-0"
              title="Cancelar"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
          {onAssignConcept && (
            <MenuRow
              icon={Tag}
              label="Asignar a concepto"
              hint="Reconocible en futuros documentos (memoria del cliente o global)"
              onClick={() => actAndClear(onAssignConcept)}
            />
          )}
          {onCreateCustomField && (
            <MenuRow
              icon={PlusSquare}
              label="Campo custom"
              hint="Añade un campo nuevo solo a este documento"
              onClick={() => actAndClear(onCreateCustomField)}
            />
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
        {enableClickSelect && (
          <span className="ml-auto text-muted-foreground italic hidden lg:inline">
            Click = seleccionar · Doble-click = mapear directo
          </span>
        )}
        {numPages > 0 && (
          <span className={cn("text-muted-foreground", !enableClickSelect && "ml-auto")}>
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

const CLICK_SELECT_CSS = `
  /* Modo click-to-select: cursor pointer y bloquea selección nativa.
     No usamos hover :hover en el span porque pdf.js mete varias palabras en
     un mismo span — se iluminaría todo el grupo. La palabra exacta se
     identifica por (x,y) con caretRangeFromPoint y se marca con la cajita
     amarilla del state. */
  .pf-clickable .react-pdf__Page__textContent {
    user-select: none;
    -webkit-user-select: none;
    cursor: pointer;
  }
`;

function MenuRow({
  icon: Icon,
  label,
  hint,
  onClick,
}: {
  icon: typeof Tag;
  label: string;
  hint: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="w-full text-left px-2 py-1.5 rounded hover:bg-muted flex items-start gap-2"
    >
      <Icon className="h-3.5 w-3.5 mt-0.5 shrink-0 text-muted-foreground" />
      <div className="min-w-0">
        <div className="text-sm font-medium">{label}</div>
        <div className="text-xs text-muted-foreground">{hint}</div>
      </div>
    </button>
  );
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
