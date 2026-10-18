"""Cierre de la conversación por derivación o por conversación inexistente (spec 008)."""

from typing import Any

import pytest
from playwright.sync_api import Page, expect
from tests.fakes.chat_api_script import ChatApiScript

_ESCALATED_NOTICE = "Tu caso fue derivado a un analista. Una persona continuará la atención."
_UNAVAILABLE_NOTICE = "Esta conversación ya no está disponible."
_NEW_CONVERSATION = "Iniciar una conversación nueva"
_GREETING_START = "Hola, soy el asistente de disputas de Banco Andino."
_FAILURE_REPLY = "Tuvimos un problema al procesar tu solicitud. Una persona continuará la atención."


def _body(reply: str, status: str = "ACTIVE") -> dict[str, Any]:
    return {"conversation_id": "conv-1", "reply": reply, "status": status}


def _send(page: Page, text: str) -> None:
    page.get_by_label("Escribe tu mensaje").fill(text)
    page.get_by_role("button", name="Enviar").click()


def _assert_closed(page: Page) -> None:
    expect(page.get_by_label("Escribe tu mensaje")).to_be_disabled()
    expect(page.get_by_role("button", name="Enviar")).to_be_disabled()
    expect(page.get_by_role("button", name=_NEW_CONVERSATION)).to_be_visible()


# Regla: RN-008-13 — una derivación cierra la conversación y ofrece una nueva.
# AC-008-14 · Art. 10 (ante la duda, escalar)
def test_ac_008_14_chat_page__escalated__conversation_closed(
    page: Page, live_server_url: str
) -> None:
    """AC-008-14: ESCALATED muestra el reply, el aviso fijo y bloquea la caja."""
    script = ChatApiScript().enqueue(body=_body("Derivamos tu caso a un analista.", "ESCALATED"))
    script.install(page)
    page.goto(live_server_url + "/")
    _send(page, "hola")

    expect(page.get_by_text("Derivamos tu caso a un analista.")).to_be_visible()
    expect(page.get_by_text(_ESCALATED_NOTICE)).to_be_visible()
    _assert_closed(page)
    order = page.evaluate(
        """() => {
          const reply = [...document.querySelectorAll("[data-author='agent']")].pop();
          const notice = document.getElementById("notices");
          return !!(reply.compareDocumentPosition(notice) & Node.DOCUMENT_POSITION_FOLLOWING);
        }"""
    )
    assert order is True


# Regla: RN-008-14 — la conversación nueva olvida la anterior y no envía conversation_id.
# AC-008-15 · Art. 7 (identificación antes que información)
@pytest.mark.parametrize("cause", ["ESCALATED", "404"], ids=["escalated", "not_found"])
def test_ac_008_15_chat_page__new_conversation__resets_state(
    page: Page, live_server_url: str, cause: str
) -> None:
    """AC-008-15: el botón deja solo el saludo, habilita la caja y olvida conversation_id."""
    script = ChatApiScript()
    if cause == "ESCALATED":
        script.enqueue(body=_body("Derivamos tu caso.", "ESCALATED"))
    else:
        script.enqueue(body=_body("Hola."))
        script.enqueue(status=404, body={"detail": "not found"})
    script.enqueue(body=_body("Nueva."))
    script.install(page)
    page.goto(live_server_url + "/")
    _send(page, "primero")
    if cause == "404":
        expect(page.get_by_text("Hola.", exact=True)).to_be_visible()
        _send(page, "segundo")
    _assert_closed(page)

    page.get_by_role("button", name=_NEW_CONVERSATION).click()

    messages = page.locator("[data-author]")
    expect(messages).to_have_count(1)
    expect(messages.first).to_contain_text(_GREETING_START)
    box = page.get_by_label("Escribe tu mensaje")
    expect(box).to_be_enabled()
    expect(box).to_be_focused()
    expect(page.get_by_text(_ESCALATED_NOTICE)).to_have_count(0)
    expect(page.get_by_text(_UNAVAILABLE_NOTICE)).to_have_count(0)
    expect(page.get_by_role("button", name=_NEW_CONVERSATION)).to_be_hidden()
    _send(page, "hola")
    expect(page.get_by_text("Nueva.", exact=True)).to_be_visible()
    assert script.requests[-1].json_body == {"message": "hola"}


# Regla: RN-008-13 — la respuesta de falla del agente llega como ESCALATED y se cierra igual.
# AC-008-19 · Art. 10 (ante la duda, escalar)
def test_ac_008_19_chat_page__agent_failure_reply__shown_and_closed(
    page: Page, live_server_url: str
) -> None:
    """AC-008-19: el reply de falla se muestra tal cual, sin códigos, y se cierra."""
    script = ChatApiScript().enqueue(body=_body(_FAILURE_REPLY, "ESCALATED"))
    script.install(page)
    page.goto(live_server_url + "/")
    _send(page, "hola")

    expect(page.locator("[data-author='agent']").last.locator(".message-text")).to_have_text(
        _FAILURE_REPLY
    )
    expect(page.get_by_text(_ESCALATED_NOTICE)).to_be_visible()
    _assert_closed(page)
    content = page.locator("body").inner_text()
    assert "LLM_FAILURE" not in content
    assert "Traceback" not in content


# Regla: RN-008-15 — una conversación inexistente (404) se cierra sin reintento.
# AC-008-20 · Art. 7 (identificación antes que información)
def test_ac_008_20_chat_page__404__unavailable_notice_without_retry(
    page: Page, live_server_url: str
) -> None:
    """AC-008-20: 404 muestra el aviso fijo, sin código ni Reintentar, y no repite la petición."""
    script = ChatApiScript()
    script.enqueue(body=_body("Hola."))
    script.enqueue(status=404, body={"detail": "not found"})
    script.install(page)
    page.goto(live_server_url + "/")
    _send(page, "primero")
    expect(page.get_by_text("Hola.", exact=True)).to_be_visible()
    _send(page, "hola")

    expect(page.get_by_text(_UNAVAILABLE_NOTICE)).to_be_visible()
    _assert_closed(page)
    expect(page.get_by_role("button", name="Reintentar")).to_be_hidden()
    assert "404" not in page.locator("body").inner_text()
    assert len(script.requests) == 2
