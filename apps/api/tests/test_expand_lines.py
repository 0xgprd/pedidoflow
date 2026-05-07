"""Tests de _maybe_expand_lines_from_offer."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlmodel import Session

from app.models.document import Document, DocumentSource, DocumentStatus, DocumentType
from app.workers.tasks import _maybe_expand_lines_from_offer


def _make_doc(
    session: Session,
    *,
    tenant_id: UUID,
    doc_type: DocumentType,
    lineas: list[dict[str, Any]],
    subtotal_ht: float | None = None,
) -> Document:
    extracted: dict[str, Any] = {
        "cliente": {"nombre": "ACME"},
        "pedido": {"numero_pedido_cliente": "PO-1"},
        "lineas": lineas,
        "totales": {"subtotal_ht": subtotal_ht} if subtotal_ht is not None else {},
        "confianza_global": "alta",
        "source_texts": {},
    }
    doc = Document(
        tenant_id=tenant_id,
        source=DocumentSource.UPLOAD,
        status=DocumentStatus.EXTRACTED,
        document_type=doc_type,
        pdf_key=f"{tenant_id}/{uuid4()}.pdf",
        original_filename="test.pdf",
        extracted_json=extracted,
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)
    return doc


def test_expand_when_one_line_resumen_matches_offer_total(session: Session) -> None:
    """Pedido con 1 línea cuyo total cuadra con suma de oferta → expande."""
    tid = uuid4()
    # Crear tenant artificial (no via API, para evitar overhead)
    from app.models.tenant import Tenant

    session.add(Tenant(id=tid, name="Q", slug=f"q-{tid.hex[:6]}"))
    session.commit()

    offer_lines = [
        {
            "referencia": "T-A",
            "descripcion": "Junta A",
            "cantidad": 100,
            "precio_unitario": 0.38,
            "importe_linea": 38.0,
        },
        {
            "referencia": "T-B",
            "descripcion": "Junta B",
            "cantidad": 50,
            "precio_unitario": 0.43,
            "importe_linea": 21.5,
        },
        {
            "referencia": "TR-400",
            "descripcion": "Raíl",
            "cantidad": 10,
            "precio_unitario": 13.5,
            "importe_linea": 135.0,
        },
    ]
    offer_total = 38.0 + 21.5 + 135.0  # = 194.5

    offer = _make_doc(session, tenant_id=tid, doc_type=DocumentType.OFERTA, lineas=offer_lines)
    order = _make_doc(
        session,
        tenant_id=tid,
        doc_type=DocumentType.PEDIDO,
        lineas=[
            {
                "referencia": None,
                "descripcion": "Según oferta TLxxxx",
                "cantidad": 1,
                "precio_unitario": offer_total,
                "importe_linea": offer_total,
            }
        ],
        subtotal_ht=offer_total,
    )

    result = _maybe_expand_lines_from_offer(order.id, offer.id, session=session)

    assert result is not None
    assert result["expanded_to"] == 3
    assert result["order_total"] == offer_total
    assert result["offer_total"] == offer_total

    # Verificar que el pedido en DB tiene 3 líneas reales ahora
    session.refresh(order)
    new_lines = order.extracted_json["lineas"]
    assert len(new_lines) == 3
    assert {ln["referencia"] for ln in new_lines} == {"T-A", "T-B", "TR-400"}
    assert "lines_expanded_from_offer" in order.extracted_json
    assert order.extracted_json["lines_expanded_from_offer"]["original_line_count"] == 1


def test_no_expand_when_pedido_has_multiple_lines(session: Session) -> None:
    """Si el pedido ya tiene N>1 líneas, no expande (no es caso resumen)."""
    tid = uuid4()
    from app.models.tenant import Tenant

    session.add(Tenant(id=tid, name="Q", slug=f"q-{tid.hex[:6]}"))
    session.commit()

    offer_lines = [
        {
            "referencia": "T-A",
            "cantidad": 10,
            "precio_unitario": 1.0,
            "importe_linea": 10.0,
            "descripcion": "A",
        },
        {
            "referencia": "T-B",
            "cantidad": 10,
            "precio_unitario": 2.0,
            "importe_linea": 20.0,
            "descripcion": "B",
        },
    ]
    offer = _make_doc(session, tenant_id=tid, doc_type=DocumentType.OFERTA, lineas=offer_lines)

    order_lines = [
        {
            "referencia": "X",
            "cantidad": 1,
            "precio_unitario": 15.0,
            "importe_linea": 15.0,
            "descripcion": "X",
        },
        {
            "referencia": "Y",
            "cantidad": 1,
            "precio_unitario": 15.0,
            "importe_linea": 15.0,
            "descripcion": "Y",
        },
    ]
    order = _make_doc(
        session, tenant_id=tid, doc_type=DocumentType.PEDIDO, lineas=order_lines, subtotal_ht=30.0
    )

    result = _maybe_expand_lines_from_offer(order.id, offer.id, session=session)
    assert result is None
    session.refresh(order)
    assert len(order.extracted_json["lineas"]) == 2  # sin cambio


def test_no_expand_when_totals_dont_match(session: Session) -> None:
    """Diferencia >1% entre order.subtotal y oferta_sum → no expande."""
    tid = uuid4()
    from app.models.tenant import Tenant

    session.add(Tenant(id=tid, name="Q", slug=f"q-{tid.hex[:6]}"))
    session.commit()

    offer_lines = [
        {
            "referencia": "T-A",
            "cantidad": 100,
            "precio_unitario": 0.38,
            "importe_linea": 38.0,
            "descripcion": "A",
        },
        {
            "referencia": "T-B",
            "cantidad": 50,
            "precio_unitario": 0.43,
            "importe_linea": 21.5,
            "descripcion": "B",
        },
    ]
    offer = _make_doc(session, tenant_id=tid, doc_type=DocumentType.OFERTA, lineas=offer_lines)

    # Pedido total = 100 (vs oferta 59.5 → diff > 1%)
    order = _make_doc(
        session,
        tenant_id=tid,
        doc_type=DocumentType.PEDIDO,
        lineas=[
            {
                "referencia": None,
                "descripcion": "según oferta",
                "cantidad": 1,
                "precio_unitario": 100.0,
                "importe_linea": 100.0,
            }
        ],
        subtotal_ht=100.0,
    )

    result = _maybe_expand_lines_from_offer(order.id, offer.id, session=session)
    assert result is None


def test_expand_within_1pct_tolerance(session: Session) -> None:
    """Diferencia 0.5% ≤ 1% → SÍ expande (tolerancia)."""
    tid = uuid4()
    from app.models.tenant import Tenant

    session.add(Tenant(id=tid, name="Q", slug=f"q-{tid.hex[:6]}"))
    session.commit()

    offer_lines = [
        {
            "referencia": "A",
            "cantidad": 1,
            "precio_unitario": 100.0,
            "importe_linea": 100.0,
            "descripcion": "A",
        },
        {
            "referencia": "B",
            "cantidad": 1,
            "precio_unitario": 100.0,
            "importe_linea": 100.0,
            "descripcion": "B",
        },
    ]
    offer = _make_doc(session, tenant_id=tid, doc_type=DocumentType.OFERTA, lineas=offer_lines)
    # Order total = 199.50 vs oferta = 200 → diff = 0.25%
    order = _make_doc(
        session,
        tenant_id=tid,
        doc_type=DocumentType.PEDIDO,
        lineas=[
            {
                "referencia": None,
                "descripcion": "x",
                "cantidad": 1,
                "precio_unitario": 199.5,
                "importe_linea": 199.5,
            }
        ],
        subtotal_ht=199.5,
    )

    result = _maybe_expand_lines_from_offer(order.id, offer.id, session=session)
    assert result is not None
    assert result["expanded_to"] == 2


def test_no_expand_when_offer_has_only_one_line(session: Session) -> None:
    """Si oferta tiene 1 línea también, no aporta nada expandir."""
    tid = uuid4()
    from app.models.tenant import Tenant

    session.add(Tenant(id=tid, name="Q", slug=f"q-{tid.hex[:6]}"))
    session.commit()

    offer = _make_doc(
        session,
        tenant_id=tid,
        doc_type=DocumentType.OFERTA,
        lineas=[
            {
                "referencia": "X",
                "cantidad": 1,
                "precio_unitario": 50.0,
                "importe_linea": 50.0,
                "descripcion": "X",
            }
        ],
    )
    order = _make_doc(
        session,
        tenant_id=tid,
        doc_type=DocumentType.PEDIDO,
        lineas=[
            {
                "referencia": None,
                "descripcion": "x",
                "cantidad": 1,
                "precio_unitario": 50.0,
                "importe_linea": 50.0,
            }
        ],
        subtotal_ht=50.0,
    )

    result = _maybe_expand_lines_from_offer(order.id, offer.id, session=session)
    assert result is None
