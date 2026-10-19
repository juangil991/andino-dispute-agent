"""Espera por palabra, sin conexión y fallas de la respuesta en streaming (spec 009 §4.5)."""

import pytest
from playwright.sync_api import Page, expect
from tests.fakes.chat_stream_script import ChatStreamScript, StreamBuilder

_TIMEOUT = "La respuesta está tardando más de lo normal. Puedes volver a intentarlo."
_OFFLINE = "No hay conexión a internet. Revisa tu conexión y vuelve a intentarlo."
_UNAVAILABLE = "No pudimos atenderte en este momento. Intenta de nuevo en unos minutos."
_UNAVAILABLE_CONVERSATION = "Esta conversación ya no está disponible."
_NEW_CONVERSATION = "Iniciar una conversación nueva"
_TYPING = "El agente está escribiendo…"
_FORBIDDEN = ["500", "503", "404", "Error", "Exception", "Traceback", "Internal Server"]
_FULL = "Abrimos tu disputa hoy."


def _send(page: Page, text: str) -> None:
    page.get_by_label("Escribe tu mensaje").fill(text)
    page.get_by_role("button", name="Enviar").click()


def _end(builder: StreamBuilder, reply: str) -> StreamBuilder:
    return builder.event(
        "end",
        {"conversation_id": "conv-1", "reply": reply, "status": "ACTIVE", "outcomes": []},
    )


def _start(script: ChatStreamScript) -> StreamBuilder:
    return script.enqueue_stream().event("start", {"conversation_id": "conv-1"})


def _agent_bubble(page: Page, text: str):  # type: ignore[no-untyped-def]
    return page.locator("#conversation [data-author='agent']").filter(has_text=text)


def _first_exchange(page: Page, script: ChatStreamScript) -> None:
    """Un intercambio completo previo: deja la conversación `conv-1` abierta."""
    _end(_start(script).event("word", {"text": "Hola."}), "Hola.")
    _send(page, "Hola")
    expect(_agent_bubble(page, "Hola.")).to_have_count(1)


# Regla: RN-009-22 — 60 s sin palabra nueva cortan la espera; con 59 s se sigue esperando.
# Regla: RN-009-24 — con palabras previas, el parcial queda `Incompleto` y el mensaje de la
#   cliente no se marca `No enviado`.
# AC-009-25 · Art. 10; bordes: 59 s (sigue), 60 s (borde exacto, corta) y 61 s (tardías ignoradas)
@pytest.mark.parametrize("seconds", [59, 60, 61], ids=["wait_59s", "wait_60s", "wait_61s"])
def test_chat_page__waiting_without_new_words__shows_delay_notice(
    page: Page, live_server_url: str, chat_stream_script: ChatStreamScript, seconds: int
) -> None:
    """AC-009-25: con 59 s sigue esperando; con 60 s y 61 s avisa la demora y marca `Incompleto`."""
    builder = _start(chat_stream_script).event("word", {"text": "Abrimos"}).hold()
    for fragment in (" tu", " disputa", " hoy."):
        builder.event("word", {"text": fragment})
    _end(builder, _FULL)
    page.clock.install()
    page.goto(live_server_url + "/")
    _send(page, "Hola")
    expect(page.locator("#draft .message-text")).to_have_text("Abrimos")

    if seconds == 59:
        page.clock.run_for(59_000)
        page.wait_for_timeout(100)
        expect(page.get_by_text(_TIMEOUT)).to_have_count(0)
        chat_stream_script.release()
        expect(_agent_bubble(page, _FULL)).to_have_count(1)
        expect(page.get_by_text(_TIMEOUT)).to_have_count(0)
        return

    page.clock.run_for(60_000)
    expect(page.get_by_text(_TIMEOUT)).to_be_visible()
    expect(page.get_by_text(_TYPING)).to_be_hidden()
    retry = page.get_by_role("button", name="Reintentar")
    expect(retry).to_be_visible()
    partial = _agent_bubble(page, "Abrimos")
    expect(partial).to_have_count(1)
    expect(partial.get_by_text("Incompleto")).to_have_count(1)
    expect(page.locator("[data-author='user']")).not_to_contain_text("No enviado")
    if seconds == 61:
        page.clock.run_for(1_000)
        chat_stream_script.release()
        page.wait_for_timeout(300)
        expect(page.get_by_text("tu disputa")).to_have_count(0)
        expect(_agent_bubble(page, _FULL)).to_have_count(0)
        expect(page.locator("#draft *")).to_have_count(0)


# Regla: RN-009-22 — cada `word` reinicia la espera de 60 s.
# AC-009-26 · Art. 10 (4 palabras con 50 s entre cada una: más de 60 s en total)
def test_chat_page__each_word_arrives__restarts_the_wait(
    page: Page, live_server_url: str, chat_stream_script: ChatStreamScript
) -> None:
    """AC-009-26: 4 palabras con 50 s entre cada una y luego `end`: sin aviso de demora."""
    chat_stream_script.enqueue_stream().event("start", {"conversation_id": "conv-1"}).event(
        "word", {"text": "Abrimos"}
    ).hold("g1").event("word", {"text": " tu"}).hold("g2").event("word", {"text": " disputa"}).hold(
        "g3"
    ).event("word", {"text": " hoy."}).hold("g4").event(
        "end",
        {"conversation_id": "conv-1", "reply": _FULL, "status": "ACTIVE", "outcomes": []},
    )
    page.clock.install()
    page.goto(live_server_url + "/")
    _send(page, "Hola")
    for gate, shown in (
        ("g1", "Abrimos tu"),
        ("g2", "Abrimos tu disputa"),
        ("g3", _FULL),
    ):
        expect(page.locator("#draft .message-text")).not_to_have_text(shown)
        page.clock.run_for(50_000)
        chat_stream_script.release(gate)
        expect(page.locator("#draft .message-text")).to_have_text(shown)
        expect(page.get_by_text(_TIMEOUT)).to_have_count(0)
    page.clock.run_for(50_000)
    expect(page.get_by_text(_TIMEOUT)).to_have_count(0)
    chat_stream_script.release("g4")

    expect(_agent_bubble(page, _FULL)).to_have_count(1)
    expect(page.get_by_text(_TIMEOUT)).to_have_count(0)
    expect(page.get_by_text("Incompleto")).to_have_count(0)


# Regla: RN-009-22 — sin ninguna palabra en 60 s desde el envío se corta la espera.
# Regla: RN-009-24 — sin palabras previas, el mensaje de la cliente se marca `No enviado`.
# AC-009-26 · Art. 10 (caso sin ninguna palabra; borde exacto de 60 s desde el envío)
def test_chat_page__no_new_words_for_60s__shows_delay_notice_and_marks_incomplete(
    page: Page, live_server_url: str, chat_stream_script: ChatStreamScript
) -> None:
    """AC-009-26: sin palabras en 60 s hay aviso de demora y el mensaje queda `No enviado`."""
    _end(_start(chat_stream_script).hold(), _FULL)
    page.clock.install()
    page.goto(live_server_url + "/")
    _send(page, "Hola")
    expect(page.get_by_text(_TYPING)).to_be_visible()

    page.clock.run_for(60_000)

    expect(page.get_by_text(_TIMEOUT)).to_be_visible()
    expect(page.get_by_text(_TYPING)).to_be_hidden()
    expect(page.get_by_role("button", name="Reintentar")).to_be_visible()
    expect(page.locator("[data-author='user']")).to_contain_text("No enviado")


# Regla: RN-009-23 — sin conexión durante la respuesta se deja de esperar y se avisa.
# Regla: RN-009-24 — parcial `Incompleto`, mensaje de la cliente sin `No enviado`; Reintentar
#   reenvía el mismo texto a la misma conversación sin repetir la burbuja de la cliente.
# AC-009-27 · Art. 7 (identificación antes que información)
def test_chat_page__connection_lost_while_streaming__marks_reply_incomplete(
    page: Page, live_server_url: str, chat_stream_script: ChatStreamScript
) -> None:
    """AC-009-27: offline a mitad del flujo deja `Incompleto` el parcial y permite reintentar."""
    page.goto(live_server_url + "/")
    _first_exchange(page, chat_stream_script)
    _start(chat_stream_script).event("word", {"text": "Sí,"}).hold()
    _send(page, "¿Sigues ahí?")
    expect(page.locator("#draft .message-text")).to_have_text("Sí,")

    page.context.set_offline(True)

    expect(page.get_by_text(_OFFLINE)).to_be_visible()
    expect(page.get_by_role("button", name="Reintentar")).to_be_visible()
    expect(page.get_by_text(_TYPING)).to_be_hidden()
    expect(_agent_bubble(page, "Hola.")).to_have_count(1)
    users = page.locator("[data-author='user']")
    expect(users).to_have_count(2)
    expect(users.last).to_contain_text("¿Sigues ahí?")
    expect(users.last).not_to_contain_text("No enviado")
    partial = _agent_bubble(page, "Sí,")
    expect(partial.get_by_text("Incompleto")).to_have_count(1)
    assert len(chat_stream_script.requests) == 2

    page.context.set_offline(False)
    _end(_start(chat_stream_script).event("word", {"text": "Aquí"}), "Aquí sigo.")
    page.get_by_role("button", name="Reintentar").click()

    expect(_agent_bubble(page, "Aquí sigo.")).to_have_count(1)
    assert chat_stream_script.requests[-1].json_body == {
        "conversation_id": "conv-1",
        "message": "¿Sigues ahí?",
    }
    expect(page.locator("[data-author='user']")).to_have_count(2)
    expect(page.get_by_text(_OFFLINE)).to_have_count(0)
    expect(page.get_by_text("Incompleto")).to_have_count(1)
    last_agent = page.locator("#conversation [data-author='agent']").last
    expect(last_agent).to_contain_text("Aquí sigo.")


# Regla: RN-009-23 — flujo cortado o evento inválido ⇒ servicio no disponible y `Reintentar`.
# Regla: RN-009-24 — con palabras previas el parcial queda `Incompleto`.
# AC-009-28 · Art. 7 (identificación antes que información)
@pytest.mark.parametrize(
    "failure",
    ["closed_without_end", "invalid_event"],
    ids=["closed_without_end", "invalid_event"],
)
def test_chat_page__stream_fails_before_finishing__shows_error(
    page: Page, live_server_url: str, chat_stream_script: ChatStreamScript, failure: str
) -> None:
    """AC-009-28: flujo cortado o evento no JSON tras `Abrimos`: aviso fijo e `Incompleto`."""
    builder = _start(chat_stream_script).event("word", {"text": "Abrimos"})
    if failure == "closed_without_end":
        builder.close()
    else:
        builder.raw_event("word", "esto no es json")
    page.goto(live_server_url + "/")

    _send(page, "Hola")

    expect(page.get_by_text(_UNAVAILABLE)).to_be_visible()
    expect(page.get_by_role("button", name="Reintentar")).to_be_visible()
    visible = page.locator("body").inner_text()
    for fragment in _FORBIDDEN:
        assert fragment not in visible
    partial = _agent_bubble(page, "Abrimos")
    expect(partial.get_by_text("Incompleto")).to_have_count(1)
    expect(page.locator("[data-author='user']")).not_to_contain_text("No enviado")
    expect(page.get_by_text(_TYPING)).to_be_hidden()


# Regla: RN-009-23 — una respuesta distinta de 200 y 404 es servicio no disponible.
# Regla: RN-009-24 — sin palabras previas, el mensaje de la cliente se marca `No enviado`.
# AC-009-28 · Art. 7 (caso 503 antes de transmitir)
def test_chat_page__http_503_before_streaming__shows_error(
    page: Page, live_server_url: str, chat_stream_script: ChatStreamScript
) -> None:
    """AC-009-28: `503` antes de transmitir: aviso fijo, `Reintentar` y mensaje `No enviado`."""
    chat_stream_script.enqueue_error(503, {"detail": "unavailable"})
    page.goto(live_server_url + "/")

    _send(page, "Hola")

    expect(page.get_by_text(_UNAVAILABLE)).to_be_visible()
    expect(page.get_by_role("button", name="Reintentar")).to_be_visible()
    expect(page.locator("[data-author='user']")).to_contain_text("No enviado")
    assert "503" not in page.locator("body").inner_text()


# Regla: RN-009-23 — un `404` se trata como en RN-008-15 (cierre, sin `Reintentar`).
# AC-009-28 · Art. 7 (caso 404: actúa como AC-008-20)
def test_chat_page__http_404_before_streaming__closes_conversation(
    page: Page, live_server_url: str, chat_stream_script: ChatStreamScript
) -> None:
    """AC-009-28: `404` cierra la conversación, sin `Reintentar` y sin otra petición."""
    page.goto(live_server_url + "/")
    _first_exchange(page, chat_stream_script)
    chat_stream_script.enqueue_error(404, {"detail": "not found"})

    _send(page, "hola")

    expect(page.get_by_text(_UNAVAILABLE_CONVERSATION)).to_be_visible()
    expect(page.get_by_label("Escribe tu mensaje")).to_be_disabled()
    expect(page.get_by_role("button", name="Enviar")).to_be_disabled()
    expect(page.get_by_role("button", name=_NEW_CONVERSATION)).to_be_visible()
    expect(page.get_by_role("button", name="Reintentar")).to_be_hidden()
    assert "404" not in page.locator("body").inner_text()
    page.wait_for_timeout(300)
    assert len(chat_stream_script.requests) == 2
