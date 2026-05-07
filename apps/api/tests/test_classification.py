"""Tests del servicio classify_document."""

from app.models.document import DocumentType
from app.services.classification import (
    classify_by_filename,
    classify_document,
)

# =============================================================================
# Filename heurística
# =============================================================================


def test_filename_offer_number_pattern() -> None:
    assert classify_by_filename("Offre de Matériel TL260422-113.pdf") == DocumentType.OFERTA
    assert classify_by_filename("TL260506-14_Quimilock.pdf") == DocumentType.OFERTA
    assert classify_by_filename("devis-tl241201-7.pdf") == DocumentType.OFERTA


def test_filename_offer_keywords() -> None:
    assert classify_by_filename("Offre Quimilock 2026.pdf") == DocumentType.OFERTA
    assert classify_by_filename("Devis_Evolis.pdf") == DocumentType.OFERTA
    assert classify_by_filename("Oferta_Madic.pdf") == DocumentType.OFERTA
    assert classify_by_filename("quote-2026-Q1.pdf") == DocumentType.OFERTA


def test_filename_order_keywords() -> None:
    assert classify_by_filename("Commande BuyXSell DL03175054.pdf") == DocumentType.PEDIDO
    assert classify_by_filename("Pedido_12345.pdf") == DocumentType.PEDIDO
    assert classify_by_filename("Purchase Order 1069250.pdf") == DocumentType.PEDIDO
    assert classify_by_filename("PO_2026_001.pdf") == DocumentType.PEDIDO
    assert classify_by_filename("bon-de-commande-evolis.pdf") == DocumentType.PEDIDO


def test_filename_ambiguous_returns_none() -> None:
    """Cuando hay ambas keywords o ninguna, no decide."""
    assert classify_by_filename("documento.pdf") is None
    assert classify_by_filename("test.pdf") is None
    assert classify_by_filename(None) is None
    assert classify_by_filename("") is None


def test_filename_offer_pattern_wins_over_order_keyword() -> None:
    """Si el filename tiene TL...-N, gana sobre 'commande'."""
    assert classify_by_filename("TL260422-113-commande-fake.pdf") == DocumentType.OFERTA


# =============================================================================
# classify_document (filename + JSON)
# =============================================================================


def test_classify_filename_wins_over_json() -> None:
    """Si filename es decisivo, ignora la sugerencia de Claude."""
    result = classify_document(
        filename="Offre TL260422-113.pdf",
        extracted_json={"document_type": "pedido"},  # Claude se equivocó
    )
    assert result == DocumentType.OFERTA


def test_classify_falls_back_to_json() -> None:
    """Si filename ambiguo, usa la sugerencia de Claude."""
    result = classify_document(
        filename="documento.pdf",
        extracted_json={"document_type": "pedido"},
    )
    assert result == DocumentType.PEDIDO


def test_classify_falls_back_to_json_offer_number() -> None:
    """Si Claude no dice tipo pero el JSON tiene numero_oferta TL... → oferta."""
    result = classify_document(
        filename="documento.pdf",
        extracted_json={"pedido": {"numero_oferta": "TL260422-113", "numero_pedido_cliente": None}},
    )
    assert result == DocumentType.OFERTA


def test_classify_returns_desconocido_only_when_no_content() -> None:
    """Sin filename y sin JSON → desconocido. Cualquier otro caso → pedido (default)."""
    assert classify_document(filename=None, extracted_json=None) == DocumentType.DESCONOCIDO


def test_classify_default_pedido_when_filename_ambiguous() -> None:
    """Si hay filename pero no es oferta clara → asumir pedido."""
    assert classify_document(filename="documento.pdf", extracted_json=None) == DocumentType.PEDIDO
    assert classify_document(filename="x.pdf", extracted_json={}) == DocumentType.PEDIDO
    assert (
        classify_document(filename="random_name.pdf", extracted_json={"lineas": []})
        == DocumentType.PEDIDO
    )
