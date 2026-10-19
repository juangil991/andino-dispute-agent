"""Bloqueo de envío, derivación al final e interrupción de la respuesta en streaming (spec 009)."""

from playwright.sync_api import Page, expect
from tests.fakes.chat_stream_script import ChatStreamScript

ESCALATED_NOTICE = "Tu caso fue derivado a un analista. Una persona continuará la atención."
NEW_CONVERSATION = "Iniciar una conversación nueva"
INTERRUPTED_REPLY = (
    "Tuvimos un problema al procesar tu solicitud. Una persona continuará la atención."
)


def _send(page: Page, text: str) -> None:
    page.get_by_label("Escribe tu mensaje").fill(text)
    page.get_by_role("button", name="Enviar").click()


# Regla: RN-009-16 — mientras la respuesta aparece no se envía otro mensaje; al `end` ACTIVE
#   la caja acepta envíos y recibe el foco.
# AC-009-19 · Art. 5 (un solo turno a la vez)
def test_chat_page__reply_streaming__blocks_sending(
    page: Page, live_server_url: str, chat_stream_script: ChatStreamScript
) -> None:
    """AC-009-19: con 2 de 5 palabras no hay petición nueva; al `end` la caja tiene el foco."""
    chat_stream_script.enqueue_stream().event("start", {"conversation_id": "conv-1"}).event(
        "word", {"text": "Abrimos"}
    ).event("word", {"text": " tu"}).hold().event("word", {"text": " disputa"}).event(
        "word", {"text": " por"}
    ).event("word", {"text": " hoy."}).event(
        "end",
        {
            "conversation_id": "conv-1",
            "reply": "Abrimos tu disputa por hoy.",
            "status": "ACTIVE",
            "outcomes": [],
        },
    )
    page.goto(live_server_url + "/")

    _send(page, "Hola")
    expect(page.locator("#draft .message-agent .message-text")).to_have_text("Abrimos tu")
    box = page.get_by_label("Escribe tu mensaje")
    expect(box).to_be_disabled()
    expect(page.get_by_role("button", name="Enviar")).to_be_disabled()
    box.evaluate("(el, v) => { el.value = v; }", "otro")
    box.dispatch_event("keydown", {"key": "Enter"})
    page.get_by_role("button", name="Enviar").dispatch_event("click")
    page.locator("#composer").evaluate("(f) => f.requestSubmit()")
    page.wait_for_timeout(300)
    assert len(chat_stream_script.requests) == 1

    chat_stream_script.release()
    expect(page.locator("#conversation [data-author='agent']")).to_have_count(2)
    expect(box).to_be_enabled()
    expect(box).to_be_focused()
    expect(page.get_by_role("button", name="Enviar")).to_be_enabled()
    assert len(chat_stream_script.requests) == 1


# Regla: RN-009-17 — con `end` ESCALATED el aviso aparece solo tras la última palabra y se cierra.
# AC-009-20 · Art. 10 (ante la duda, escalar; el aviso no se adelanta al texto)
def test_chat_page__escalated_reply_ends__shows_notice_after_last_word(
    page: Page, live_server_url: str, chat_stream_script: ChatStreamScript
) -> None:
    """AC-009-20: sin aviso ni botón durante las palabras; al final, aviso y cierre."""
    reply = "Derivamos tu caso a un analista."
    builder = chat_stream_script.enqueue_stream().event("start", {"conversation_id": "conv-1"})
    for fragment in ("Derivamos", " tu", " caso", " a", " un", " analista."):
        builder.event("word", {"text": fragment}, 500)
    builder.hold("end").event(
        "end",
        {"conversation_id": "conv-1", "reply": reply, "status": "ESCALATED", "outcomes": []},
    )
    page.goto(live_server_url + "/")

    _send(page, "Quiero hablar con alguien")
    expect(page.locator("#draft .message-agent .message-text")).to_have_text(reply, timeout=10000)
    page.wait_for_timeout(300)
    assert page.get_by_text(ESCALATED_NOTICE).count() == 0
    expect(page.get_by_role("button", name=NEW_CONVERSATION)).to_be_hidden()

    chat_stream_script.release("end")
    expect(page.get_by_text(ESCALATED_NOTICE)).to_be_visible()
    expect(page.locator("#conversation [data-author='agent'] .message-text").last).to_have_text(
        reply
    )
    expect(page.get_by_label("Escribe tu mensaje")).to_be_disabled()
    expect(page.get_by_role("button", name="Enviar")).to_be_disabled()
    expect(page.get_by_role("button", name=NEW_CONVERSATION)).to_be_visible()
    notice_below = page.evaluate(
        """() => {
            const n = document.getElementById('notices');
            const last = [...document.querySelectorAll('#conversation .message')].pop();
            return !!(last.compareDocumentPosition(n) & Node.DOCUMENT_POSITION_FOLLOWING);
        }"""
    )
    assert notice_below is True


# Regla: RN-009-18 — `interrupted` conserva el parcial marcado `Incompleto`, muestra `reply`
#   completo al instante, luego el aviso de derivación, y cierra la conversación.
# AC-009-21 · Art. 10 (ante la duda, escalar)
def test_chat_page__reply_interrupted__is_marked_incomplete(
    page: Page, live_server_url: str, chat_stream_script: ChatStreamScript
) -> None:
    """AC-009-21: `Abrimos tu` queda `Incompleto`; debajo `reply` fijo y el aviso; cerrada."""
    chat_stream_script.enqueue_stream().event("start", {"conversation_id": "conv-1"}).event(
        "word", {"text": "Abrimos"}
    ).event("word", {"text": " tu"}).hold().event(
        "interrupted",
        {
            "conversation_id": "conv-1",
            "reply": INTERRUPTED_REPLY,
            "status": "ESCALATED",
            "outcomes": [],
        },
    )
    page.goto(live_server_url + "/")

    _send(page, "Hola")
    expect(page.locator("#draft .message-agent .message-text")).to_have_text("Abrimos tu")
    page.wait_for_timeout(200)
    assert page.get_by_text(ESCALATED_NOTICE).count() == 0

    chat_stream_script.release()
    texts = page.locator("#conversation .message-text")
    expect(texts).to_have_text(
        [
            "Hola, soy el asistente de disputas de Banco Andino. Antes de revisar tu cuenta "
            "necesito identificarte. Para empezar, indícame tu número de documento, tu nombre "
            "completo o los últimos 4 dígitos de tu tarjeta.",
            "Hola",
            "Abrimos tu",
            INTERRUPTED_REPLY,
        ]
    )
    agents = page.locator("#conversation [data-author='agent']")
    partial = agents.nth(1)
    expect(partial.get_by_text("Incompleto")).to_have_count(1)
    expect(agents.nth(2).get_by_text("Incompleto")).to_have_count(0)
    expect(page.get_by_text("Incompleto")).to_have_count(1)
    expect(page.get_by_text("No enviado")).to_have_count(0)
    expect(page.get_by_role("button", name="Reintentar")).to_be_hidden()
    assert page.locator("#draft *").count() == 0
    expect(page.get_by_text(ESCALATED_NOTICE)).to_be_visible()
    expect(page.get_by_label("Escribe tu mensaje")).to_be_disabled()
    expect(page.get_by_role("button", name="Enviar")).to_be_disabled()
    expect(page.get_by_role("button", name=NEW_CONVERSATION)).to_be_visible()


# Regla: RN-009-18 — sin palabras previas no hay burbuja parcial: solo `reply` y el aviso.
# AC-009-21 · Art. 10 (variante sin texto parcial)
def test_chat_page__interrupted_without_words__shows_only_reply_and_notice(
    page: Page, live_server_url: str, chat_stream_script: ChatStreamScript
) -> None:
    """AC-009-21 (sin palabras): sin burbuja parcial ni marca `Incompleto`; conversación cerrada."""
    chat_stream_script.enqueue_stream().event("start", {"conversation_id": "conv-1"}).event(
        "interrupted",
        {
            "conversation_id": "conv-1",
            "reply": INTERRUPTED_REPLY,
            "status": "ESCALATED",
            "outcomes": [],
        },
    )
    page.goto(live_server_url + "/")

    _send(page, "Hola")
    expect(page.locator("#conversation [data-author='agent']")).to_have_count(2)
    expect(page.locator("#conversation .message-text").last).to_have_text(INTERRUPTED_REPLY)
    expect(page.get_by_text("Incompleto")).to_have_count(0)
    expect(page.get_by_text("No enviado")).to_have_count(0)
    expect(page.get_by_role("button", name="Reintentar")).to_be_hidden()
    expect(page.get_by_text(ESCALATED_NOTICE)).to_be_visible()
    expect(page.get_by_label("Escribe tu mensaje")).to_be_disabled()
    expect(page.get_by_role("button", name=NEW_CONVERSATION)).to_be_visible()
