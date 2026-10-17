"""Pruebas del caso de uso SearchCustomers: camino de búsqueda (AC-001-01/04/06/07/10)."""

import inspect
from dataclasses import fields

import pytest
from tests.fakes.customer_builder import CustomerBuilder
from tests.fakes.failing_customer_repository import FailingCustomerRepository
from tests.fakes.fake_audit_log import FakeAuditLog
from tests.fakes.fake_customer_repository import FakeCustomerRepository
from tests.fakes.fixed_clock import FixedClock

from core_banking_mcp.application.errors import CoreUnavailableError
from core_banking_mcp.application.ports.audit_log import AuditInput
from core_banking_mcp.application.use_cases.search_customers import (
    SearchCustomers,
    SearchCustomersCommand,
)
from core_banking_mcp.domain.errors import InvalidInputError
from core_banking_mcp.domain.masking import mask_document
from core_banking_mcp.domain.models.customer import Customer
from core_banking_mcp.domain.models.search import MAX_RESULTS, SearchCriteria


class SpyRepository(FakeCustomerRepository):
    def __init__(self, customers: list[Customer]) -> None:
        super().__init__(customers)
        self.limits: list[int] = []

    def find_matching(self, criteria: SearchCriteria, limit: int) -> list[Customer]:
        self.limits.append(limit)
        return super().find_matching(criteria, limit)


def _use_case(repo: FakeCustomerRepository) -> SearchCustomers:
    return SearchCustomers(repo, FakeAuditLog(), FixedClock())


def _cmd(
    document: str | None = None,
    full_name: str | None = None,
    card_last4: str | None = None,
) -> SearchCustomersCommand:
    return SearchCustomersCommand("conv-1", document, full_name, card_last4)


def test_ac_001_01_single_customer_by_document() -> None:
    """AC-001-01: un documento existente devuelve un único cliente."""
    # Regla: RN-001-01 — búsqueda por al menos un criterio
    # AC-001-01 · Art. 3
    customer = CustomerBuilder().with_id("C-001").with_document("DOC-0001").build()
    other = CustomerBuilder().with_id("C-002").with_document("DOC-0002").build()
    result = _use_case(FakeCustomerRepository([customer, other])).execute(_cmd(document="DOC-0001"))
    assert result.customers == (customer,)
    assert result.refinement_required is False


def test_ac_001_04_homonyms_keep_repository_order() -> None:
    """AC-001-04: homónimos se devuelven en el orden del repositorio."""
    # Regla: RN-001-06 — hasta 5 coincidencias se listan
    # AC-001-04 · Art. 3
    c2 = CustomerBuilder().with_id("C-002").with_name("Ana Ficticia").with_document("D2").build()
    c1 = CustomerBuilder().with_id("C-001").with_name("Ana Ficticia").with_document("D1").build()
    result = _use_case(FakeCustomerRepository([c2, c1])).execute(_cmd(full_name="Ana Ficticia"))
    assert [c.customer_id for c in result.customers] == ["C-001", "C-002"]
    assert result.refinement_required is False


def test_ac_001_06_no_matches_returns_empty() -> None:
    """AC-001-06: sin coincidencias, lista vacía sin pedir refinar."""
    # Regla: RN-001-10 — sin coincidencias no es error
    # AC-001-06 · Art. 3
    result = _use_case(FakeCustomerRepository([])).execute(_cmd(document="NOPE"))
    assert result.customers == ()
    assert result.refinement_required is False


def test_ac_001_07_more_than_five_requires_refinement() -> None:
    """AC-001-07: más de 5 coincidencias piden refinar y piden limit=6 al repositorio."""
    # Regla: RN-001-07 — más de 5 coincidencias requiere refinar
    # AC-001-07 · Art. 3
    customers = [
        CustomerBuilder()
        .with_id(f"C-{i:03d}")
        .with_name("Luis Ficticio")
        .with_document(f"D{i}")
        .build()
        for i in range(MAX_RESULTS + 1)
    ]
    repo = SpyRepository(customers)
    result = _use_case(repo).execute(_cmd(full_name="Luis Ficticio"))
    assert repo.limits == [MAX_RESULTS + 1]
    assert result.customers == ()
    assert result.refinement_required is True


def test_ac_001_10_search_does_not_require_nor_confirm_identity() -> None:
    """AC-001-10: el constructor solo recibe repositorio, auditoría y reloj; sin identidad."""
    # Regla: RN-001-11 — la búsqueda no confirma identidad
    # AC-001-10 · Art. 3
    params = list(inspect.signature(SearchCustomers.__init__).parameters)[1:]
    assert params == ["repository", "audit_log", "clock"]
    result = _use_case(FakeCustomerRepository([CustomerBuilder().build()])).execute(
        _cmd(document="DOC-0001")
    )
    names = {f.name for f in fields(result)}
    assert names == {"customers", "refinement_required"}


def _many(n: int) -> list[Customer]:
    return [
        CustomerBuilder()
        .with_id(f"C-{i:03d}")
        .with_name("Luis Ficticio")
        .with_document(f"D{i}")
        .build()
        for i in range(n)
    ]


_ONE = CustomerBuilder().with_id("C-001").with_document("DOC-0001").build()

_AUDIT_CASES = {
    "one": (
        _cmd(document="DOC-0001"),
        FakeCustomerRepository([_ONE]),
        None,
        "found",
        "RN-001-01",
        1,
        ("C-001",),
        None,
        "DOC-0001",
        None,
    ),
    "several": (
        _cmd(full_name="Luis Ficticio"),
        FakeCustomerRepository(_many(3)),
        None,
        "found",
        "RN-001-01",
        3,
        ("C-000", "C-001", "C-002"),
        None,
        None,
        "Luis Ficticio",
    ),
    "none": (
        _cmd(document="NOPE"),
        FakeCustomerRepository([]),
        None,
        "found",
        "RN-001-01",
        0,
        (),
        None,
        "NOPE",
        None,
    ),
    "refinement": (
        _cmd(full_name="Luis Ficticio"),
        FakeCustomerRepository(_many(MAX_RESULTS + 1)),
        None,
        "refinement_required",
        "RN-001-07",
        0,
        (),
        None,
        None,
        "Luis Ficticio",
    ),
    "invalid": (
        _cmd(document="  "),
        FakeCustomerRepository([]),
        InvalidInputError,
        "error",
        "RN-001-05",
        None,
        (),
        "INVALID_INPUT",
        "",
        None,
    ),
    "failure": (
        _cmd(document="DOC-0001"),
        FailingCustomerRepository(),
        CoreUnavailableError,
        "error",
        "RN-001-13",
        None,
        (),
        "INTERNAL",
        "DOC-0001",
        None,
    ),
}


@pytest.mark.parametrize("case", list(_AUDIT_CASES))
def test_ac_001_13_every_invocation_is_audited(case: str) -> None:
    """AC-001-13: toda invocación emite exactamente un AuditEvent enmascarado."""
    # Regla: RN-001-12 — auditoría de cada invocación (reglas 01/07/05/13)
    # AC-001-13 · Art. 8
    cmd, repo, raises, outcome, rule, count, ids, code, doc, name = _AUDIT_CASES[case]
    audit = FakeAuditLog()
    use_case = SearchCustomers(repo, audit, FixedClock())  # type: ignore[arg-type]
    if raises:
        with pytest.raises(raises):
            use_case.execute(cmd)
    else:
        use_case.execute(cmd)
    assert len(audit.events) == 1
    event = audit.events[0]
    assert event.conversation_id == "conv-1"
    assert event.timestamp == FixedClock().now()
    assert event.tool == "buscar_cliente"
    assert event.input == AuditInput(None if doc is None else mask_document(doc), name, None)
    assert (event.outcome, event.rule) == (outcome, rule)
    assert (event.count, event.customer_ids, event.error_code) == (count, ids, code)
    assert event.reason
    if doc and "DOC-0001" in doc:
        assert "DOC-0001" not in repr(event)


@pytest.mark.parametrize("conversation_id", [None, ""])
def test_ac_001_09_missing_conversation_id_is_invalid_input(conversation_id: str | None) -> None:
    """AC-001-09: conversation_id ausente o vacío es InvalidInputError y se audita."""
    # Regla: RN-001-05 — entrada inválida
    # AC-001-09 · Art. 8
    audit = FakeAuditLog()
    use_case = SearchCustomers(FakeCustomerRepository([_ONE]), audit, FixedClock())
    command = SearchCustomersCommand(conversation_id, "DOC-0001", None, None)
    with pytest.raises(InvalidInputError) as exc:
        use_case.execute(command)
    assert exc.value.field == "conversation_id"
    assert len(audit.events) == 1
    assert audit.events[0].conversation_id == conversation_id
    assert audit.events[0].error_code == "INVALID_INPUT"


def test_ac_001_14_repository_failure_raises_core_unavailable() -> None:
    """AC-001-14: una falla del repositorio es CoreUnavailableError sin el texto original."""
    # Regla: RN-001-13 — falla inesperada del core
    # AC-001-14 · Art. 10
    use_case = SearchCustomers(FailingCustomerRepository(), FakeAuditLog(), FixedClock())
    with pytest.raises(CoreUnavailableError) as exc:
        use_case.execute(_cmd(document="DOC-0001"))
    assert "secreto" not in str(exc.value)
    assert "fallo simulado" not in str(exc.value)
