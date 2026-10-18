"""Mensajes vacíos, recorte, límite de 2000 caracteres y Shift+Enter (spec 008)."""

from typing import Any

import pytest
from playwright.sync_api import Page, Request, expect
from tests.fakes.chat_api_script import ChatApiScript


def _reply(text: str = "Entendido.") -> dict[str, Any]:
    return {"conversation_id": "conv-1", "reply": text, "status": "ACTIVE"}


def _type_lines(page: Page, lines: list[str]) -> None:
    box = page.get_by_label("Escribe tu mensaje")
    box.click()
    for index, line in enumerate(lines):
        if index:
            box.press("Shift+Enter")
        if line:
            box.type(line)


# Regla: RN-008-04 — un texto vacío tras recortar no se envía y la conversación no cambia.
# AC-008-03 · Art. 7 (identificación antes que información)
@pytest.mark.parametrize("how", ["enter", "button"])
@pytest.mark.parametrize(
    "lines",
    [[], ["   "], ["", "", ""]],
    ids=["empty", "only_spaces", "only_line_breaks"],
)
def test_ac_008_03_chat_page__blank_message__not_sent(
    page: Page, live_server_url: str, lines: list[str], how: str
) -> None:
    """AC-008-03: vacío, espacios o saltos no producen petición ni burbujas nuevas."""
    script = ChatApiScript().enqueue(body=_reply())
    script.install(page)
    page.goto(live_server_url + "/")
    api_calls: list[Request] = []
    page.on("request", lambda r: api_calls.append(r) if "/api/" in r.url else None)
    bubbles = page.locator("[data-author]")
    expect(bubbles).to_have_count(1)

    _type_lines(page, lines)
    if how == "enter":
        page.get_by_label("Escribe tu mensaje").press("Enter")
    else:
        page.get_by_role("button", name="Enviar").click()
    page.wait_for_timeout(300)

    assert api_calls == []
    assert script.requests == []
    expect(bubbles).to_have_count(1)


# Regla: RN-008-04 y RN-008-05 — se envía el texto recortado; tope de 2000 y contador a ≤ 200.
# AC-008-04 · Art. 7 (identificación antes que información)
@pytest.mark.parametrize(
    "case",
    ["trim", "no_counter_1799", "counter_1800", "paste_2001", "send_2000"],
)
def test_ac_008_04_chat_page__trim_and_length_limit__enforced(
    page: Page, live_server_url: str, case: str
) -> None:
    """AC-008-04: recorte, contador desde 1800, tope de 2000 al pegar y envío de 2000 completos."""
    script = ChatApiScript().enqueue(body=_reply())
    script.install(page)
    page.goto(live_server_url + "/")
    box = page.get_by_label("Escribe tu mensaje")
    counter = page.locator("#counter")

    if case == "trim":
        box.fill("  hola  ")
        page.get_by_role("button", name="Enviar").click()
        expect(page.locator("[data-author='agent']")).to_have_count(2)
        assert [r.json_body for r in script.requests] == [{"message": "hola"}]
        expect(page.locator("[data-author='user'] .message-text")).to_have_text("hola")
    elif case == "no_counter_1799":
        box.fill("a" * 1799)
        expect(counter).to_be_hidden()
    elif case == "counter_1800":
        box.fill("a" * 1800)
        expect(counter).to_be_visible()
        expect(counter).to_have_text("Quedan 200 caracteres")
    elif case == "paste_2001":
        box.focus()
        page.keyboard.insert_text("b" * 2001)
        assert page.evaluate("document.getElementById('message').value.length") == 2000
        expect(counter).to_have_text("Quedan 0 caracteres")
    else:
        text = "c" * 2000
        box.fill(text)
        page.get_by_role("button", name="Enviar").click()
        expect(page.locator("[data-author='agent']")).to_have_count(2)
        assert [r.json_body for r in script.requests] == [{"message": text}]


# Regla: RN-008-06 — Enter envía; Shift+Enter inserta un salto de línea.
# AC-008-22 · Art. 4 (interfaz como adaptador de entrada)
def test_ac_008_22_chat_page__enter_sends_and_shift_enter_inserts_line_break(
    page: Page, live_server_url: str
) -> None:
    """AC-008-22: Shift+Enter deja el salto de línea y Enter envía el mensaje."""
    script = ChatApiScript().enqueue(body=_reply())
    script.install(page)
    page.goto(live_server_url + "/")

    _type_lines(page, ["uno", "dos"])
    assert page.evaluate("document.getElementById('message').value") == "uno\ndos"
    assert script.requests == []
    page.get_by_label("Escribe tu mensaje").press("Enter")

    expect(page.locator("[data-author='agent']")).to_have_count(2)
    assert [r.json_body for r in script.requests] == [{"message": "uno\ndos"}]
