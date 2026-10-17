"""Value object de criterios de búsqueda de clientes (RN-001-01, RN-001-05)."""

from collections.abc import Sequence
from dataclasses import dataclass

from core_banking_mcp.domain.errors import InvalidInputError
from core_banking_mcp.domain.models.customer import Customer
from core_banking_mcp.domain.normalization import normalize_document, normalize_name

_MAX_DOCUMENT = 32
_MAX_FULL_NAME = 100
_CARD_DIGITS = frozenset("0123456789")


@dataclass(frozen=True)
class SearchCriteria:
    """Criterios validados y normalizados; los ausentes son None."""

    document: str | None
    full_name: str | None
    card_last4: str | None

    @classmethod
    def create(
        cls,
        document: str | None,
        full_name: str | None,
        card_last4: str | None,
    ) -> "SearchCriteria":
        """Valida RN-001-01/05 y normaliza; lanza InvalidInputError."""
        if document is None and full_name is None and card_last4 is None:
            raise InvalidInputError("criteria", "at least one criterion is required")

        norm_document = None
        if document is not None:
            if not 1 <= len(document.strip()) <= _MAX_DOCUMENT:
                raise InvalidInputError("document", "length must be 1 to 32")
            norm_document = normalize_document(document)

        norm_name = None
        if full_name is not None:
            if not 1 <= len(full_name.strip()) <= _MAX_FULL_NAME:
                raise InvalidInputError("full_name", "length must be 1 to 100")
            norm_name = normalize_name(full_name)

        if card_last4 is not None and (len(card_last4) != 4 or not set(card_last4) <= _CARD_DIGITS):
            raise InvalidInputError("card_last4", "must be exactly 4 digits")

        return cls(norm_document, norm_name, card_last4)


MAX_RESULTS = 5


@dataclass(frozen=True)
class CustomerSearchResult:
    """Resultado acotado (RN-001-06/07): más de 5 coincidencias piden refinar."""

    customers: tuple[Customer, ...]
    refinement_required: bool

    def __post_init__(self) -> None:
        if len(self.customers) > MAX_RESULTS:
            raise ValueError("customers exceeds MAX_RESULTS")
        if self.refinement_required and self.customers:
            raise ValueError("refinement_required implies empty customers")

    @classmethod
    def from_matches(cls, matches: Sequence[Customer]) -> "CustomerSearchResult":
        """Aplica RN-001-07: con más de 5 coincidencias devuelve vacío y refinar."""
        if len(matches) > MAX_RESULTS:
            return cls((), True)
        return cls(tuple(matches), False)
