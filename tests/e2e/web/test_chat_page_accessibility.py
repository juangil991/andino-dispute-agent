"""Uso solo con teclado y anuncio por lector de pantalla de la página de chat (spec 008)."""

from typing import Any

import pytest
from playwright.sync_api import Page, expect
from tests.fakes.chat_api_script import ChatApiScript

_NEW_CONVERSATION = "Iniciar una conversación nueva"
_GREETING_START = "Hola, soy el asistente de disputas de Banco Andino."


def _body(reply: str, status: str = "ACTIVE") -> dict[str, Any]:
    return {"conversation_id": "conv-1", "reply": reply, "status": status}


def _open(page: Page, live_server_url: str, script: ChatApiScript) -> None:
    script.install(page)
    page.goto(live_server_url + "/")


def _tab_to_box(page: Page) -> None:
    page.keyboard.press("Tab")
    expect(page.get_by_label("Escribe tu mensaje")).to_be_focused()


def _case_reaches_box(page: Page, script: ChatApiScript) -> None:
    _tab_to_box(page)
    page.keyboard.type("hola")
    expect(page.get_by_label("Escribe tu mensaje")).to_have_value("hola")


def _case_enter_sends(page: Page, script: ChatApiScript) -> None:
    _tab_to_box(page)
    page.keyboard.type("hola")
    page.keyboard.press("Enter")
    expect(page.get_by_text("Respuesta.", exact=True)).to_be_visible()
    assert len(script.requests) == 1
    assert script.requests[0].json_body == {"message": "hola"}


def _case_shift_enter_newline(page: Page, script: ChatApiScript) -> None:
    _tab_to_box(page)
    page.keyboard.type("hola")
    page.keyboard.press("Shift+Enter")
    page.keyboard.type("mundo")
    page.keyboard.press("Enter")
    expect(page.get_by_text("Respuesta.", exact=True)).to_be_visible()
    assert len(script.requests) == 1
    assert script.requests[0].json_body == {"message": "hola\nmundo"}


def _case_focus_returns(page: Page, script: ChatApiScript) -> None:
    _tab_to_box(page)
    page.keyboard.type("hola")
    page.keyboard.press("Enter")
    expect(page.get_by_text("Respuesta.", exact=True)).to_be_visible()
    box = page.get_by_label("Escribe tu mensaje")
    expect(box).to_be_enabled()
    expect(box).to_be_focused()


def _case_new_conversation(page: Page, script: ChatApiScript) -> None:
    _tab_to_box(page)
    page.keyboard.type("hola")
    page.keyboard.press("Enter")
    button = page.get_by_role("button", name=_NEW_CONVERSATION)
    expect(button).to_be_visible()
    page.keyboard.press("Tab")
    expect(button).to_be_focused()
    page.keyboard.press("Enter")
    messages = page.locator("[data-author]")
    expect(messages).to_have_count(1)
    expect(messages.first).to_contain_text(_GREETING_START)
    expect(page.get_by_label("Escribe tu mensaje")).to_be_focused()


# Regla: RN-008-06 / RN-008-20 — toda la página se usa solo con teclado y el foco vuelve a la caja.
# AC-008-22 · Art. 4 (interfaz como adaptador de entrada)
@pytest.mark.parametrize(
    "case",
    [
        _case_reaches_box,
        _case_enter_sends,
        _case_shift_enter_newline,
        _case_focus_returns,
        _case_new_conversation,
    ],
    ids=[
        "tab_reaches_box",
        "enter_sends",
        "shift_enter_newline",
        "focus_returns_after_reply",
        "new_conversation_by_keyboard",
    ],
)
def test_ac_008_22_chat_page__keyboard_only__all_actions_work(
    page: Page, live_server_url: str, case: Any
) -> None:
    """AC-008-22: la página completa se maneja con teclado, incluido el foco tras cada respuesta."""
    escalated = case is _case_new_conversation
    script = ChatApiScript().enqueue(
        body=_body("Respuesta.", "ESCALATED" if escalated else "ACTIVE")
    )
    _open(page, live_server_url, script)
    case(page, script)


# Regla: RN-008-21 — el log es una región viva y cada mensaje anuncia su autor.
# AC-008-23 · Art. 4 (interfaz como adaptador de entrada)
def test_ac_008_23_chat_page__screen_reader__live_region_and_authors(
    page: Page, live_server_url: str
) -> None:
    """AC-008-23: región aria-live polite, prefijos Tú/Agente y caja con label."""
    script = ChatApiScript().enqueue(body=_body("Derivamos tu caso.", "ESCALATED"))
    _open(page, live_server_url, script)
    page.get_by_label("Escribe tu mensaje").fill("hola")
    page.get_by_role("button", name="Enviar").click()
    expect(page.get_by_text("Derivamos tu caso.")).to_be_visible()

    log = page.locator("[aria-live='polite']")
    expect(log).to_have_count(1)
    expect(log.locator("[data-author]")).to_have_count(3)
    expect(log.locator("#notices .notice")).to_have_count(1)
    users = page.locator("[data-author='user']")
    expect(users).to_have_count(1)
    assert users.first.text_content().startswith("Tú")  # type: ignore[union-attr]
    agents = page.locator("[data-author='agent']")
    assert agents.count() == 2
    for index in range(agents.count()):
        assert agents.nth(index).text_content().startswith("Agente")  # type: ignore[union-attr]
    assert page.get_by_label("Escribe tu mensaje").count() == 1
