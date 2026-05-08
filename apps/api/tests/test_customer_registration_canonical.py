"""Tests de los modelos canónicos de alta de cliente y `deduce_tax_category`."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.services.erp import (
    CanonicalAddress,
    CanonicalContact,
    CanonicalCustomerRegistration,
    deduce_tax_category,
)

# =============================================================================
# CanonicalAddress
# =============================================================================


def test_address_minimal_valid() -> None:
    addr = CanonicalAddress(
        line1="Z.I. Des Agriers",
        city="Angouleme",
        postal_code="16000",
        country="France",
    )
    assert addr.country == "France"
    assert addr.line2 is None
    assert addr.state_or_region is None


def test_address_complete() -> None:
    addr = CanonicalAddress(
        line1="Calle Formación 18",
        line2="P.I. Los Olivos",
        city="Getafe",
        postal_code="28906",
        state_or_region="Madrid",
        country="España",
    )
    assert addr.line2 == "P.I. Los Olivos"
    assert addr.state_or_region == "Madrid"


def test_address_is_frozen() -> None:
    addr = CanonicalAddress(line1="x", city="y", postal_code="1", country="ES")
    with pytest.raises(PydanticValidationError):
        addr.city = "OTRO"  # type: ignore[misc]


# =============================================================================
# CanonicalContact
# =============================================================================


def test_contact_minimal() -> None:
    c = CanonicalContact(name="Cédric Chabanne")
    assert c.name == "Cédric Chabanne"
    assert c.role is None


def test_contact_complete() -> None:
    c = CanonicalContact(
        name="Cédric Chabanne",
        role="Acheteur",
        phone="+33 545913737",
        email="cchabanne@angouleme-ts.fr",
    )
    assert c.role == "Acheteur"
    assert c.email == "cchabanne@angouleme-ts.fr"


# =============================================================================
# CanonicalCustomerRegistration — la ficha de Quimilock realista
# =============================================================================


def _quimilock_ficha_ats() -> CanonicalCustomerRegistration:
    """Ficha de alta realista — ATS (Angouleme Traitement de Surface, Francia)."""
    return CanonicalCustomerRegistration(
        source_document_id=uuid4(),
        company_name="ATS",
        fiscal_name="Angouleme Traitement de Surface S.A.S.",
        tax_id="344020303",
        eu_vat="FR76344020383",
        supplier_number_in_customer_system="QML-001",
        fiscal_address=CanonicalAddress(
            line1="Z.I. Des Agriers",
            city="Angouleme",
            postal_code="16000",
            country="France",
        ),
        billing_address=CanonicalAddress(
            line1="Z.I. Des Agriers",
            city="Angouleme",
            postal_code="16000",
            country="France",
        ),
        main_phone="+33 545913737",
        main_email="accueil@angouleme-ts.fr",
        contacts=[
            CanonicalContact(
                name="Cédric Chabanne",
                role="Acheteur",
                phone="+33 545913737",
                email="cchabanne@angouleme-ts.fr",
            ),
            CanonicalContact(name="Delphine Andreo", role="Comptable"),
        ],
        tax_category="eu_intracom",
        payment_terms="Virement bancaire 30 jours",
        bank_account_iban=None,
        preferred_language="fr",
        signed_by_name="Cédric Chabanne",
        signed_by_role="Directeur",
        signature_date=date(2026, 4, 15),
    )


def test_registration_quimilock_ats_full() -> None:
    reg = _quimilock_ficha_ats()
    assert reg.company_name == "ATS"
    assert reg.fiscal_name == "Angouleme Traitement de Surface S.A.S."
    assert reg.eu_vat == "FR76344020383"
    assert reg.supplier_number_in_customer_system == "QML-001"
    assert reg.fiscal_address.country == "France"
    assert reg.billing_address is not None
    assert len(reg.contacts) == 2
    assert reg.tax_category == "eu_intracom"
    assert reg.payment_terms == "Virement bancaire 30 jours"
    assert reg.signed_by_name == "Cédric Chabanne"


def test_registration_minimal_required_fields() -> None:
    """company_name + fiscal_address son los únicos obligatorios."""
    reg = CanonicalCustomerRegistration(
        source_document_id=uuid4(),
        company_name="Cliente Minimal",
        fiscal_address=CanonicalAddress(line1="X", city="Y", postal_code="00000", country="ES"),
    )
    assert reg.tax_category == "unknown"
    assert reg.contacts == []
    assert reg.billing_address is None


def test_registration_rejects_missing_fiscal_address() -> None:
    with pytest.raises(PydanticValidationError):
        CanonicalCustomerRegistration(
            source_document_id=uuid4(),
            company_name="X",
        )  # type: ignore[call-arg]


def test_registration_is_frozen() -> None:
    reg = _quimilock_ficha_ats()
    with pytest.raises(PydanticValidationError):
        reg.company_name = "OTRO"  # type: ignore[misc]


# =============================================================================
# deduce_tax_category — heurísticas para Quimilock (home = ES) y otras empresas
# =============================================================================


def test_deduce_eu_intracom_from_french_vat() -> None:
    """VAT FR + home ES → intracomunitario."""
    assert deduce_tax_category(eu_vat="FR76344020383", tax_id=None, country=None) == "eu_intracom"


def test_deduce_eu_intracom_from_german_vat() -> None:
    assert deduce_tax_category(eu_vat="DE123456789", tax_id=None, country=None) == "eu_intracom"


def test_deduce_domestic_when_vat_matches_home() -> None:
    """VAT español + home ES → doméstico."""
    assert deduce_tax_category(eu_vat="ESB12345678", tax_id=None, country=None) == "domestic"


def test_deduce_domestic_when_vat_matches_other_home() -> None:
    """Si la empresa que da de alta es FR (home="FR"), un VAT FR es doméstico."""
    assert (
        deduce_tax_category(
            eu_vat="FR76344020383", tax_id=None, country=None, home_country_code="FR"
        )
        == "domestic"
    )


def test_deduce_export_from_us_vat() -> None:
    """Sin prefijo UE en VAT → fuera de UE."""
    assert deduce_tax_category(eu_vat="US123456", tax_id=None, country=None) == "export"


def test_deduce_domestic_from_spanish_cif_no_vat() -> None:
    """Sin VAT pero con CIF español (empieza por letra) → doméstico."""
    assert deduce_tax_category(eu_vat=None, tax_id="B12345678", country=None) == "domestic"


def test_deduce_eu_intracom_from_country_only() -> None:
    """Sin VAT ni tax_id, pero país conocido UE distinto del home → intracom."""
    assert deduce_tax_category(eu_vat=None, tax_id=None, country="France") == "eu_intracom"


def test_deduce_export_from_non_eu_country() -> None:
    assert deduce_tax_category(eu_vat=None, tax_id=None, country="USA") == "export"


def test_deduce_unknown_when_no_data() -> None:
    assert deduce_tax_category(eu_vat=None, tax_id=None, country=None) == "unknown"


def test_deduce_unknown_when_country_unrecognized() -> None:
    """País raro no en la tabla → unknown (no asumimos)."""
    assert deduce_tax_category(eu_vat=None, tax_id=None, country="Atlantis") == "unknown"


def test_deduce_handles_lowercase_country() -> None:
    assert deduce_tax_category(eu_vat=None, tax_id=None, country="francia") == "eu_intracom"
