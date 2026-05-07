"""Tests del servicio matching pedido ↔ oferta + comparación de líneas."""

from typing import Any
from uuid import uuid4

from sqlmodel import Session

from app.models.document import Document, DocumentSource, DocumentStatus, DocumentType
from app.models.document_link import MatchStrategy
from app.services.matching import (
    _extract_offer_numbers,
    _normalize_client_name,
    compare_order_vs_offer,
    find_matching_offer,
)


def _doc(tenant_id, *, dtype: DocumentType, extracted: dict[str, Any]) -> Document:
    return Document(
        id=uuid4(),
        tenant_id=tenant_id,
        source=DocumentSource.UPLOAD,
        status=DocumentStatus.EXTRACTED,
        document_type=dtype,
        pdf_key=f"{tenant_id}/x.pdf",
        original_filename="x.pdf",
        extracted_json=extracted,
    )


# =============================================================================
# Helpers
# =============================================================================


def test_normalize_client_name() -> None:
    assert _normalize_client_name("EVOLIS SAS") == "evolis"
    assert _normalize_client_name("Evolís S.A.S.") == "evolis"
    assert _normalize_client_name("Quimilock SL") == "quimilock"
    assert _normalize_client_name("") == ""
    assert _normalize_client_name(None) == ""


def test_extract_offer_numbers() -> None:
    extracted: dict[str, Any] = {
        "pedido": {
            "numero_oferta": "TL260506-14",
            "observaciones": "ref offer TL260506-14 + alt TL260301-7",
        },
        "source_texts": {"pedido.numero_oferta": "Réf. devis TL260506-14"},
    }
    nums = _extract_offer_numbers(extracted)
    assert "TL260506-14" in nums
    assert "TL260301-7" in nums


# =============================================================================
# Comparación
# =============================================================================


def test_compare_identical() -> None:
    extracted = {
        "lineas": [
            {"referencia": "TF-75", "cantidad": 10, "precio_unitario": 16.9},
            {"referencia": "GF-1", "cantidad": 5, "precio_unitario": 0.85},
        ]
    }
    result = compare_order_vs_offer(extracted, extracted)
    assert result["summary"]["common"] == 2
    assert result["summary"]["price_discrepancies"] == 0
    assert result["summary"]["qty_discrepancies"] == 0
    assert result["summary"]["added_in_order"] == 0
    assert result["summary"]["removed_from_offer"] == 0


def test_compare_price_changed() -> None:
    order = {"lineas": [{"referencia": "TF-75", "cantidad": 10, "precio_unitario": 18.0}]}
    offer = {"lineas": [{"referencia": "TF-75", "cantidad": 10, "precio_unitario": 16.9}]}
    result = compare_order_vs_offer(order, offer)
    assert result["summary"]["price_discrepancies"] == 1
    assert "price_changed" in result["lines_in_both"][0]["issues"]


def test_compare_qty_and_extras() -> None:
    order = {
        "lineas": [
            {"referencia": "TF-75", "cantidad": 12, "precio_unitario": 16.9},  # qty changed
            {"referencia": "NEW-1", "cantidad": 1, "precio_unitario": 5.0},  # extra
        ]
    }
    offer = {
        "lineas": [
            {"referencia": "TF-75", "cantidad": 10, "precio_unitario": 16.9},
            {"referencia": "GF-1", "cantidad": 3, "precio_unitario": 0.85},  # missing
        ]
    }
    result = compare_order_vs_offer(order, offer)
    assert result["summary"]["common"] == 1
    assert result["summary"]["qty_discrepancies"] == 1
    assert result["summary"]["added_in_order"] == 1
    assert result["summary"]["removed_from_offer"] == 1
    assert result["lines_only_in_order"][0]["reference"] == "NEW-1"
    assert result["lines_only_in_offer"][0]["reference"] == "GF-1"


def test_compare_price_within_tolerance() -> None:
    """Diferencia <5% no se considera discrepancia."""
    order = {"lineas": [{"referencia": "TF-75", "cantidad": 1, "precio_unitario": 17.5}]}
    offer = {"lineas": [{"referencia": "TF-75", "cantidad": 1, "precio_unitario": 16.9}]}
    # diff = 3.5%
    result = compare_order_vs_offer(order, offer)
    assert result["summary"]["price_discrepancies"] == 0


# =============================================================================
# Matching
# =============================================================================


def test_match_by_exact_offer_number(session: Session) -> None:
    from app.models.tenant import Tenant

    tenant = Tenant(name="Quimilock", slug="quimilock")
    session.add(tenant)
    session.commit()
    session.refresh(tenant)

    offer = _doc(
        tenant.id,
        dtype=DocumentType.OFERTA,
        extracted={
            "cliente": {"nombre": "Evolis"},
            "pedido": {"numero_oferta": "TL260506-14"},
            "lineas": [{"referencia": "TF-75", "cantidad": 10, "precio_unitario": 16.9}],
        },
    )
    order = _doc(
        tenant.id,
        dtype=DocumentType.PEDIDO,
        extracted={
            "cliente": {"nombre": "EVOLIS SAS"},
            "pedido": {"numero_oferta": "TL260506-14"},
            "lineas": [{"referencia": "TF-75", "cantidad": 10, "precio_unitario": 16.9}],
        },
    )
    session.add(offer)
    session.add(order)
    session.commit()

    match = find_matching_offer(
        session,
        tenant_id=tenant.id,
        order_extracted=order.extracted_json or {},
        order_doc_id=order.id,
    )
    assert match is not None
    matched_offer, strategy, score = match
    assert matched_offer.id == offer.id
    assert strategy == MatchStrategy.EXACT_OFFER_NUMBER
    assert score == 1.0


def test_match_by_client_lines_similarity(session: Session) -> None:
    from app.models.tenant import Tenant

    tenant = Tenant(name="Quimilock", slug="quimilock")
    session.add(tenant)
    session.commit()
    session.refresh(tenant)

    offer = _doc(
        tenant.id,
        dtype=DocumentType.OFERTA,
        extracted={
            "cliente": {"nombre": "Evolis SAS"},
            "lineas": [
                {"referencia": "TF-75", "cantidad": 10, "precio_unitario": 16.9},
                {"referencia": "GF-1", "cantidad": 5, "precio_unitario": 0.85},
                {"referencia": "T-A", "cantidad": 2, "precio_unitario": 0.85},
            ],
        },
    )
    order = _doc(
        tenant.id,
        dtype=DocumentType.PEDIDO,
        extracted={
            "cliente": {"nombre": "EVOLIS"},
            "lineas": [
                {"referencia": "TF-75", "cantidad": 12, "precio_unitario": 16.9},
                {"referencia": "GF-1", "cantidad": 5, "precio_unitario": 0.85},
            ],
        },
    )
    session.add(offer)
    session.add(order)
    session.commit()

    match = find_matching_offer(
        session,
        tenant_id=tenant.id,
        order_extracted=order.extracted_json or {},
        order_doc_id=order.id,
    )
    assert match is not None
    matched_offer, strategy, score = match
    assert matched_offer.id == offer.id
    assert strategy == MatchStrategy.CLIENT_LINES_SIMILARITY
    # 2 refs comunes / 3 totales = 0.66
    assert score > 0.5


def test_match_no_offer_returns_none(session: Session) -> None:
    from app.models.tenant import Tenant

    tenant = Tenant(name="Quimilock", slug="quimilock")
    session.add(tenant)
    session.commit()
    session.refresh(tenant)

    order = _doc(
        tenant.id,
        dtype=DocumentType.PEDIDO,
        extracted={
            "cliente": {"nombre": "Evolis"},
            "lineas": [{"referencia": "TF-75", "cantidad": 1}],
        },
    )
    session.add(order)
    session.commit()

    match = find_matching_offer(
        session,
        tenant_id=tenant.id,
        order_extracted=order.extracted_json or {},
        order_doc_id=order.id,
    )
    assert match is None


def test_match_skips_already_linked_offers(session: Session) -> None:
    """Una oferta ya vinculada a otro pedido NO se vuelve a usar."""
    from app.models.document_link import DocumentLink
    from app.models.tenant import Tenant

    tenant = Tenant(name="Quimilock", slug="quimilock")
    session.add(tenant)
    session.commit()
    session.refresh(tenant)

    offer = _doc(
        tenant.id,
        dtype=DocumentType.OFERTA,
        extracted={
            "cliente": {"nombre": "Evolis"},
            "pedido": {"numero_oferta": "TL260506-14"},
            "lineas": [{"referencia": "TF-75", "cantidad": 10, "precio_unitario": 16.9}],
        },
    )
    other_order = _doc(
        tenant.id,
        dtype=DocumentType.PEDIDO,
        extracted={"cliente": {"nombre": "Evolis"}, "lineas": []},
    )
    session.add_all([offer, other_order])
    session.commit()

    # La oferta ya está vinculada al primer pedido
    session.add(
        DocumentLink(
            tenant_id=tenant.id,
            order_document_id=other_order.id,
            offer_document_id=offer.id,
            match_strategy=MatchStrategy.MANUAL,
            match_score=1.0,
        )
    )
    session.commit()

    new_order = _doc(
        tenant.id,
        dtype=DocumentType.PEDIDO,
        extracted={
            "cliente": {"nombre": "Evolis"},
            "pedido": {"numero_oferta": "TL260506-14"},
            "lineas": [{"referencia": "TF-75", "cantidad": 10, "precio_unitario": 16.9}],
        },
    )
    session.add(new_order)
    session.commit()

    match = find_matching_offer(
        session,
        tenant_id=tenant.id,
        order_extracted=new_order.extracted_json or {},
        order_doc_id=new_order.id,
    )
    assert match is None
