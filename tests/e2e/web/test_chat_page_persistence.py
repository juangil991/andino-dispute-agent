"""La conversación vive solo en memoria: recargar o reabrir empieza una nueva (spec 008)."""

from typing import Any

from playwright.sync_api import Page, expect
from tests.fakes.chat_api_script import ChatApiScript


def _reply(text: str, conversation_id: str = "conv-1") -> dict[str, Any]:
    return {"conversation_id": conversation_id, "reply": text, "status": "ACTIVE"}


def _send(page: Page, text: str) -> None:
    page.get_by_label("Escribe tu mensaje").fill(text)
    page.get_by_role("button", name="Enviar").click()


# Regla: RN-008-12 — al recargar empieza una conversación nueva: solo el saludo y el
# siguiente mensaje se envía sin `conversation_id`.
# AC-008-12 · Art. 7 (identificación antes que información)
def test_ac_008_12_chat_page__reload__starts_new_conversation(
    page: Page, live_server_url: str
) -> None:
    """AC-008-12: tras `reload` solo queda el saludo y la petición siguiente no trae id."""
    script = (
        ChatApiScript()
        .enqueue(body=_reply("Primera respuesta"))
        .enqueue(body=_reply("Respuesta nueva", conversation_id="conv-2"))
    )
    script.install(page)
    page.goto(live_server_url + "/")
    _send(page, "Hola")
    expect(page.locator("[data-author='agent']")).to_have_count(2)

    page.reload()

    expect(page.locator("[data-author]")).to_have_count(1)
    expect(page.locator("[data-author='agent']")).to_have_count(1)
    _send(page, "Otra vez")
    expect(page.locator("[data-author='agent']")).to_have_count(2)
    assert [r.json_body for r in script.requests] == [
        {"message": "Hola"},
        {"message": "Otra vez"},
    ]


# Regla: RN-008-12 — nada se guarda en localStorage, sessionStorage, IndexedDB ni cookies;
# al cerrar y reabrir solo se muestra el saludo.
# AC-008-13 · Art. 7 (identificación antes que información)
def test_ac_008_13_chat_page__reopen__no_browser_storage(page: Page, live_server_url: str) -> None:
    """AC-008-13: sin almacenamiento del navegador antes de cerrar ni al reabrir; solo saludo."""
    script = ChatApiScript().enqueue(body=_reply("Primera respuesta"))
    script.install(page)
    page.goto(live_server_url + "/")
    _send(page, "Hola")
    expect(page.locator("[data-author='agent']")).to_have_count(2)

    def storage_state(p: Page) -> tuple[int, int, list[Any]]:
        return (
            p.evaluate("localStorage.length"),
            p.evaluate("sessionStorage.length"),
            p.evaluate("indexedDB.databases()"),
        )

    assert storage_state(page) == (0, 0, [])
    assert page.context.cookies() == []

    page.close()
    reopened = page.context.new_page()
    reopened.goto(live_server_url + "/")

    expect(reopened.locator("[data-author]")).to_have_count(1)
    expect(reopened.locator("[data-author='agent']")).to_have_count(1)
    assert storage_state(reopened) == (0, 0, [])
    assert reopened.context.cookies() == []
