"""Envío de mensajes, orden de la conversación y presentación solo de `reply` (spec 008)."""

from typing import Any

from playwright.sync_api import Page, Request, expect
from tests.fakes.chat_api_script import ChatApiScript


def _reply(text: str, conversation_id: str = "conv-1", **extra: Any) -> dict[str, Any]:
    return {"conversation_id": conversation_id, "reply": text, "status": "ACTIVE", **extra}


def _send(page: Page, text: str) -> None:
    page.get_by_label("Escribe tu mensaje").fill(text)
    page.get_by_role("button", name="Enviar").click()


# Regla: RN-008-08 — la conversación conserva el orden en que se escribieron los mensajes.
# Regla: RN-008-01 — las peticiones al agente van a `POST /api/chat/stream` (RN-009-13).
# AC-008-02 · Art. 7 (identificación antes que información)
def test_ac_008_02_chat_page__two_turns__ordered_and_conversation_id_reused(
    page: Page, live_server_url: str
) -> None:
    """AC-008-02: orden, peticiones sin y con `conversation_id`, solo POST /api/chat/stream."""
    first = "Con gusto te ayudo. ¿Me indicas tu número de documento?"
    second = "Gracias. ¿Cuál es tu fecha de nacimiento?"
    script = ChatApiScript().enqueue(body=_reply(first)).enqueue(body=_reply(second))
    script.install(page)
    page.goto(live_server_url + "/")
    api_calls: list[Request] = []
    page.on("request", lambda r: api_calls.append(r) if "/api/" in r.url else None)

    _send(page, "No reconozco un cobro de mi tarjeta")
    expect(page.locator("[data-author='agent']")).to_have_count(2)
    _send(page, "D-1001")
    messages = page.get_by_role("log").locator("[data-author]")
    expect(messages).to_have_count(5)

    authors = [m.get_attribute("data-author") for m in messages.all()]
    assert authors == ["agent", "user", "agent", "user", "agent"]
    texts = [m.locator(".message-text").inner_text() for m in messages.all()]
    assert texts[1:] == ["No reconozco un cobro de mi tarjeta", first, "D-1001", second]
    assert [r.json_body for r in script.requests] == [
        {"message": "No reconozco un cobro de mi tarjeta"},
        {"conversation_id": "conv-1", "message": "D-1001"},
    ]
    assert [(r.method, r.url.removeprefix(live_server_url)) for r in api_calls] == [
        ("POST", "/api/chat/stream")
    ] * 2


# Regla: RN-008-01 — la página no ofrece acciones que salten al agente.
# AC-008-10 · Art. 7 (identificación antes que información)
def test_ac_008_10_chat_page__after_turn__only_textbox_and_send_controls(
    page: Page, live_server_url: str
) -> None:
    """AC-008-10: tras un turno los únicos controles visibles son la caja y `Enviar`."""
    ChatApiScript().enqueue(
        body=_reply("Verificamos tu identidad. Estas son tus transacciones recientes: ...")
    ).install(page)
    page.goto(live_server_url + "/")
    api_calls: list[Request] = []
    page.on("request", lambda r: api_calls.append(r) if "/api/" in r.url else None)

    _send(page, "Hola")
    expect(page.locator("[data-author='agent']")).to_have_count(2)

    assert [(r.method, r.url.removeprefix(live_server_url)) for r in api_calls] == [
        ("POST", "/api/chat/stream")
    ]
    controls = page.locator("button, a, input, textarea, select, [role='button'], [role='link']")
    visible = [c for c in controls.all() if c.is_visible()]
    names = sorted(
        (c.evaluate("e => e.tagName.toLowerCase()"), c.inner_text() or c.get_attribute("name"))
        for c in visible
    )
    assert names == [("button", "Enviar"), ("textarea", "message")]
    assert page.locator("a[href]").count() == 0
    control_texts = " ".join(
        (c.inner_text() + " " + (c.get_attribute("aria-label") or "")).lower() for c in visible
    )
    for forbidden in ("disputa", "bloque", "analista", "transacci"):
        assert forbidden not in control_texts
    expect(page.get_by_role("button", name="Reintentar")).to_be_hidden()
    expect(page.get_by_role("button", name="Iniciar una conversación nueva")).to_be_hidden()


# Regla: RN-008-10 — se muestra solo `reply`, tal como llega, sin `outcomes` ni otros campos.
# AC-008-11 · Art. 7 (identificación antes que información)
def test_ac_008_11_chat_page__reply_with_outcomes__only_reply_shown(
    page: Page, live_server_url: str
) -> None:
    """AC-008-11: la burbuja muestra el `reply` exacto y ningún campo de `outcomes`."""
    reply = "Bloqueamos tu tarjeta **** 4321."
    ChatApiScript().enqueue(
        body=_reply(
            reply,
            outcomes=[{"masked_card": "**** 4321", "rule": "RN-007-14", "reference": "E-9"}],
        )
    ).install(page)
    page.goto(live_server_url + "/")

    _send(page, "Bloquea mi tarjeta")
    agent = page.locator("[data-author='agent']")
    expect(agent).to_have_count(2)
    expect(agent.last.locator(".message-text")).to_have_text(reply)

    body = page.inner_text("body")
    for hidden in ("RN-007-14", "E-9", "conv-1", "outcomes"):
        assert hidden not in body
