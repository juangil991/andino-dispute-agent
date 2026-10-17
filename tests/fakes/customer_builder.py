"""Builder de clientes ficticios y deterministas."""

from dataclasses import dataclass, field

from core_banking_mcp.domain.models.customer import Card, Customer


@dataclass
class CustomerBuilder:
    customer_id: str = "C-001"
    full_name: str = "Cliente Ficticio"
    document: str = "DOC-0001"
    cards: tuple[Card, ...] = field(default_factory=tuple)

    def with_id(self, customer_id: str) -> "CustomerBuilder":
        self.customer_id = customer_id
        return self

    def with_name(self, full_name: str) -> "CustomerBuilder":
        self.full_name = full_name
        return self

    def with_document(self, document: str) -> "CustomerBuilder":
        self.document = document
        return self

    def with_cards(self, *cards: Card) -> "CustomerBuilder":
        self.cards = tuple(cards)
        return self

    def build(self) -> Customer:
        return Customer(self.customer_id, self.full_name, self.document, self.cards)
