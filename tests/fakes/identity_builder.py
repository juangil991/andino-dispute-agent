"""Builder de identidades ficticias y deterministas."""

from dataclasses import dataclass, field
from datetime import date

from core_banking_mcp.domain.models.identity import IdentityRecord


@dataclass
class IdentityBuilder:
    birth_date: date = field(default_factory=lambda: date(1985, 3, 14))
    document_issue_date: date = field(default_factory=lambda: date(2005, 4, 2))

    def with_birth_date(self, birth_date: date) -> "IdentityBuilder":
        self.birth_date = birth_date
        return self

    def with_issue_date(self, issue_date: date) -> "IdentityBuilder":
        self.document_issue_date = issue_date
        return self

    def build(self) -> IdentityRecord:
        return IdentityRecord(self.birth_date, self.document_issue_date)
