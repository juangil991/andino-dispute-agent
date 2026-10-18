"""Todo el texto de la conversación se muestra como texto plano (spec 008, RN-008-09)."""

import pytest
from playwright.sync_api import Dialog, Page, expect
from tests.fakes.chat_api_script import ChatApiScript

_FORBIDDEN = "b, script, img, a, iframe, style"


def _record_dialog(dialogs: list[str], dialog: Dialog) -> None:
    dialogs.append(dialog.message)
    dialog.dismiss()


def _send(page: Page, text: str) -> None:
    page.get_by_label("Escribe tu mensaje").fill(text)
    page.get_by_role("button", name="Enviar").click()


# Regla: RN-008-09 — el texto de la cliente es texto plano; conserva Unicode y no se ejecuta.
# AC-008-07 · Art. 7 (identificación antes que información)
@pytest.mark.parametrize(
    "text",
    ["<b>hola</b>", "<script>alert(1)</script>", "ñandú, áéíóú y 😀"],
    ids=["bold_tag", "script_tag", "unicode"],
)
def test_ac_008_07_chat_page__customer_markup__shown_as_text(
    page: Page, live_server_url: str, text: str
) -> None:
    """AC-008-07: la burbuja de la cliente muestra exactamente el texto, sin elementos nuevos."""
    ChatApiScript().enqueue(
        body={"conversation_id": "conv-1", "reply": "Recibido", "status": "ACTIVE"}
    ).install(page)
    dialogs: list[str] = []
    page.on("dialog", lambda d: _record_dialog(dialogs, d))
    page.goto(live_server_url + "/")

    _send(page, text)
    expect(page.locator("[data-author='agent']")).to_have_count(2)

    user = page.locator("[data-author='user']")
    expect(user).to_have_count(1)
    assert user.locator(".message-text").inner_text() == text
    assert page.get_by_role("log").locator(_FORBIDDEN).count() == 0
    assert dialogs == []


# Regla: RN-008-09 — el texto del agente es texto plano y conserva sus saltos de línea.
# AC-008-08 · Art. 7 (identificación antes que información)
@pytest.mark.parametrize(
    "text",
    [
        "<img src=x onerror=alert(1)>",
        '<a href="javascript:alert(1)">ver</a>',
        "Línea 1\nLínea 2",
    ],
    ids=["img_onerror", "javascript_link", "line_break"],
)
def test_ac_008_08_chat_page__agent_markup__shown_as_text(
    page: Page, live_server_url: str, text: str
) -> None:
    """AC-008-08: la burbuja del agente muestra exactamente el texto, con sus saltos de línea."""
    ChatApiScript().enqueue(
        body={"conversation_id": "conv-1", "reply": text, "status": "ACTIVE"}
    ).install(page)
    dialogs: list[str] = []
    page.on("dialog", lambda d: _record_dialog(dialogs, d))
    page.goto(live_server_url + "/")

    _send(page, "Hola")
    agent = page.locator("[data-author='agent']")
    expect(agent).to_have_count(2)

    assert agent.last.locator(".message-text").inner_text() == text
    assert page.get_by_role("log").locator(_FORBIDDEN).count() == 0
    assert dialogs == []
