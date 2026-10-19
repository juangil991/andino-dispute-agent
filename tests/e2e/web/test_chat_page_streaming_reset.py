"""Sin texto residual al recargar o empezar de nuevo; eventos tardíos ignorados (spec 009 §4.5)."""

import pytest
from playwright.sync_api import Page, expect
from tests.fakes.chat_stream_script import ChatStreamScript, StreamBuilder

_NEW_CONVERSATION = "Iniciar una conversación nueva"
_GREETING_START = "Hola, soy el asistente de disputas de Banco Andino."
_INTERRUPTED_REPLY = "No pudimos completar tu respuesta. Un analista continuará la atención."
_LATE_WORDS = (" residuo1", " residuo2", " residuo3")


def _send(page: Page, text: str) -> None:
    page.get_by_label("Escribe tu mensaje").fill(text)
    page.get_by_role("button", name="Enviar").click()


def _start(script: ChatStreamScript) -> StreamBuilder:
    return script.enqueue_stream().event("start", {"conversation_id": "conv-1"})


def _assert_only_greeting(page: Page) -> None:
    expect(page.locator("#conversation [data-author]")).to_have_count(1)
    expect(page.locator("#conversation [data-author='agent']")).to_contain_text(_GREETING_START)
    expect(page.locator("#draft *")).to_have_count(0)
    for word in ("Abrimos", "residuo", "analista", "Incompleto"):
        expect(page.locator("body")).not_to_contain_text(word)


def _assert_next_message_is_new_conversation(page: Page, script: ChatStreamScript) -> None:
    _start(script).event("word", {"text": "Hola."}).event(
        "end",
        {"conversation_id": "conv-2", "reply": "Hola.", "status": "ACTIVE", "outcomes": []},
    )
    _send(page, "hola")
    expect(
        page.locator("#conversation [data-author='agent']").filter(has_text="Hola.")
    ).to_have_count(1)
    assert script.requests[-1].json_body == {"message": "hola"}


# Regla: RN-009-25 — recargar o pulsar `Iniciar una conversación nueva` abandona el flujo en
#   curso; solo queda el saludo y el siguiente mensaje inicia una conversación nueva.
# AC-009-29 · Art. 7 (no se arrastra la identidad de la conversación anterior)
@pytest.mark.parametrize(
    "action",
    ["reload", "interrupted_then_new_conversation"],
    ids=["reload", "interrupted_then_new_conversation"],
)
def test_chat_page__reload_or_new_conversation_mid_stream__leaves_no_residual_words(
    page: Page, live_server_url: str, chat_stream_script: ChatStreamScript, action: str
) -> None:
    """AC-009-29: tras recargar o empezar de nuevo, solo el saludo y sin `conversation_id`."""
    builder = _start(chat_stream_script).event("word", {"text": "Abrimos"})
    if action == "reload":
        builder.event("word", {"text": " tu"}).hold()
        for fragment in _LATE_WORDS:
            builder.event("word", {"text": fragment})
    else:
        # Sin "outcomes" a propósito: spec §7.1 (v0.1.1) — la página no lo usa ni lo valida
        # (RN-009-13, RN-009-23).
        builder.event("word", {"text": " tu"}).event(
            "interrupted",
            {"conversation_id": "conv-1", "reply": _INTERRUPTED_REPLY, "status": "ESCALATED"},
        ).hold()
        for fragment in _LATE_WORDS:
            builder.event("word", {"text": fragment})
    page.goto(live_server_url + "/")
    _send(page, "Hola")

    if action == "reload":
        expect(page.locator("#draft .message-text")).to_have_text("Abrimos tu")
        page.reload()
    else:
        expect(page.get_by_text(_INTERRUPTED_REPLY)).to_be_visible()
        page.get_by_role("button", name=_NEW_CONVERSATION).click()
    chat_stream_script.release()
    page.wait_for_timeout(2000)

    _assert_only_greeting(page)
    _assert_next_message_is_new_conversation(page, chat_stream_script)


# Regla: RN-009-25 — una vez que la respuesta termina con `end`, los eventos posteriores del flujo
#   se ignoran.
# AC-009-29 · Art. 7 (el texto mostrado es exactamente `reply`)
def test_chat_page__words_arrive_after_end__are_ignored(
    page: Page, live_server_url: str, chat_stream_script: ChatStreamScript
) -> None:
    """AC-009-29: las palabras que llegan después de `end` no cambian la burbuja."""
    reply = "Abrimos tu disputa."
    builder = (
        _start(chat_stream_script)
        .event("word", {"text": "Abrimos"})
        .event(
            "end",
            {"conversation_id": "conv-1", "reply": reply, "status": "ACTIVE", "outcomes": []},
        )
    )
    for fragment in _LATE_WORDS:
        builder.event("word", {"text": fragment}, delay_ms=50)
    page.goto(live_server_url + "/")
    _send(page, "Hola")
    bubble = page.locator("#conversation [data-author='agent']").filter(has_text="Abrimos")
    expect(bubble).to_have_count(1)
    page.wait_for_timeout(1000)

    expect(bubble.locator(".message-text")).to_have_text(reply)
    expect(page.locator("body")).not_to_contain_text("residuo")
    expect(page.locator("#draft *")).to_have_count(0)
