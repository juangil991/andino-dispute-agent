"""Tests de normalización de nombre y documento (T-001-02)."""

import pytest

from core_banking_mcp.domain.normalization import normalize_document, normalize_name


@pytest.mark.parametrize(
    ("value", "target", "matches"),
    [
        ("José Álvarez", "José Álvarez", True),
        ("jose alvarez", "José Álvarez", True),
        ("JOSÉ ÁLVAREZ", "José Álvarez", True),
        ("  José   Álvarez  ", "José Álvarez", True),
        ("José", "José Álvarez", False),
        ("José Álvarez", "José Álvarez Pérez", False),
        ("José Álvarez Pérez", "José Álvarez Pérez", True),
        ("Muñoz", "Munoz", True),
    ],
)
def test_ac_001_05_name_normalization_ignores_accents_case_and_spaces(
    value: str, target: str, matches: bool
) -> None:
    """AC-001-05: el nombre ignora acentos, mayúsculas y espacios, pero debe ser completo."""
    assert (normalize_name(value) == normalize_name(target)) is matches


@pytest.mark.parametrize(
    ("value", "matches"),
    [
        ("D-1001", True),
        ("d-1001", True),
        ("  D-1001  ", True),
        ("D1001", False),
    ],
)
def test_ac_001_02_document_normalization_trims_and_ignores_case(value: str, matches: bool) -> None:
    """AC-001-02: el documento se compara recortado y sin distinguir mayúsculas."""
    assert (normalize_document(value) == normalize_document("D-1001")) is matches
