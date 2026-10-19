"""La respuesta del agente aparece palabra por palabra desde `/api/chat/stream` (spec 009)."""

import re
from typing import Any

import pytest
from playwright.sync_api import Dialog, Page, expect
from tests.fakes.chat_stream_script import ChatStreamScript, StreamBuilder

GREETING = (
    "Hola, soy el asistente de disputas de Banco Andino. Antes de revisar tu cuenta necesito "
    "identificarte. Para empezar, indícame tu número de documento, tu nombre completo o los "
    "últimos 4 dígitos de tu tarjeta."
)

_OBSERVER = """() => {
    window.draftHistory = [];
    const draft = document.getElementById('draft');
    new MutationObserver(() => {
        const t = draft.querySelector('.message-text');
        if (t && t.textContent !== '') window.draftHistory.push(t.textContent);
    }).observe(draft, {childList: true, subtree: true, characterData: true});
}"""


def _fragments(reply: str) -> list[str]:
    """Cada fragmento = espacio en blanco previo + palabra (spec 009 RN-009-06)."""
    tokens = re.findall(r"\s*\S+", reply)
    rest = reply[len("".join(tokens)) :]
    if rest:
        tokens[-1] += rest
    return tokens


def _stream_reply(
    script: ChatStreamScript,
    reply: str,
    status: str = "ACTIVE",
    delay_ms: int = 0,
    outcomes: list[dict[str, Any]] | None = None,
) -> StreamBuilder:
    builder = script.enqueue_stream().event("start", {"conversation_id": "conv-1"})
    for fragment in _fragments(reply):
        builder.event("word", {"text": fragment}, delay_ms)
    return builder.event(
        "end",
        {
            "conversation_id": "conv-1",
            "reply": reply,
            "status": status,
            "outcomes": outcomes or [],
        },
    )


def _send(page: Page, text: str) -> None:
    page.get_by_label("Escribe tu mensaje").fill(text)
    page.get_by_role("button", name="Enviar").click()


def _api_calls(page: Page, base: str) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []
    page.on(
        "request",
        lambda r: calls.append((r.method, r.url.removeprefix(base))) if "/api/" in r.url else None,
    )
    return calls


# Regla: RN-009-13 — la página envía cada mensaje a `POST /api/chat/stream` y a ningún otro.
# Regla: RN-009-15 — cada fragmento se añade apenas llega; al `end` el texto es exactamente `reply`.
# AC-009-15 · Art. 5 (la respuesta se muestra sin esperar al final)
def test_chat_page__reply_streams__appears_word_by_word(
    page: Page, live_server_url: str, chat_stream_script: ChatStreamScript
) -> None:
    """AC-009-15: la burbuja crece palabra a palabra y termina con exactamente `reply`."""
    reply = "Abrimos tu disputa por 85.000 COP."
    _stream_reply(chat_stream_script, reply, delay_ms=500)
    page.goto(live_server_url + "/")
    calls = _api_calls(page, live_server_url)
    page.evaluate(_OBSERVER)

    _send(page, "Hola")
    draft_text = page.locator("#draft .message-agent .message-text")
    expect(draft_text).to_have_text("Abrimos")
    assert page.locator("#draft .message-agent .message-text").text_content() != reply
    expect(page.locator("#conversation [data-author='agent']")).to_have_count(2, timeout=10000)

    last = page.locator("#conversation [data-author='agent'] .message-text").last
    expect(last).to_have_text(reply)
    words = reply.split(" ")
    prefixes = [" ".join(words[: i + 1]) for i in range(len(words))]
    history = page.evaluate("window.draftHistory")
    assert history[0] == "Abrimos"
    assert history[-1] == reply
    assert all(value in prefixes for value in history)
    assert [prefixes.index(v) for v in history] == sorted(prefixes.index(v) for v in history)
    assert len(set(history)) > 2
    assert calls == [("POST", "/api/chat/stream")]
    assert [r.json_body for r in chat_stream_script.requests] == [{"message": "Hola"}]


# Regla: RN-009-14 — hasta la primera palabra se ve el indicador y ninguna palabra de la respuesta.
# AC-009-16 · Art. 5 (indicador de espera hasta la primera palabra)
def test_chat_page__before_first_word__shows_typing_indicator(
    page: Page, live_server_url: str, chat_stream_script: ChatStreamScript
) -> None:
    """AC-009-16: con `start` sin palabras hay indicador y no hay burbuja; luego desaparece."""
    chat_stream_script.enqueue_stream().event("start", {"conversation_id": "conv-1"}).hold().event(
        "word", {"text": "Hola"}
    ).hold("end").event(
        "end", {"conversation_id": "conv-1", "reply": "Hola", "status": "ACTIVE", "outcomes": []}
    )
    page.goto(live_server_url + "/")

    _send(page, "Hola")
    expect(page.get_by_text("El agente está escribiendo…")).to_be_visible()
    page.wait_for_timeout(300)
    expect(page.get_by_text("El agente está escribiendo…")).to_be_visible()
    assert page.locator("#draft .message-agent").count() == 0
    assert page.locator("#conversation [data-author='agent']").count() == 1

    chat_stream_script.release()
    expect(page.locator("#draft .message-agent .message-text")).to_have_text("Hola")
    expect(page.get_by_text("El agente está escribiendo…")).to_be_hidden()
    chat_stream_script.release("end")
    expect(page.locator("#conversation [data-author='agent']")).to_have_count(2)


_LONG_WORD = "x" * 80
_CONTENTS = [
    pytest.param("Tildes, ñandú y emojis 😀", id="tildes-emojis"),
    pytest.param("Línea 1\nLínea 2", id="saltos-de-linea"),
    pytest.param("Mira " + _LONG_WORD, id="palabra-de-80-caracteres"),
    pytest.param("<b>texto</b> con marcas de código", id="marcas-b"),
    pytest.param("<img src=x onerror=alert(1)>", id="marca-img-onerror"),
]


# Regla: RN-009-15 — el texto se muestra siempre como texto plano y exacto.
# Regla: RN-008-09 — nada del texto se interpreta como HTML.
# AC-009-17 · Art. 5 (el contenido del agente no se interpreta)
@pytest.mark.parametrize("content", _CONTENTS)
def test_chat_page__streamed_content__is_plain_text_and_exact(
    page: Page, live_server_url: str, chat_stream_script: ChatStreamScript, content: str
) -> None:
    """AC-009-17: burbuja exacta, sin elementos del texto, sin diálogos ni desborde horizontal."""
    _stream_reply(chat_stream_script, content)
    dialogs: list[Dialog] = []
    page.on("dialog", lambda d: (dialogs.append(d), d.dismiss()))
    page.goto(live_server_url + "/")

    _send(page, "Hola")
    expect(page.locator("#conversation [data-author='agent']")).to_have_count(2)

    bubble = page.locator("#conversation [data-author='agent'] .message-text").last
    assert bubble.text_content() == content
    for tag in ("b", "img", "script"):
        assert page.locator(f"#conversation {tag}, #draft {tag}").count() == 0
    assert page.locator("#draft *").count() == 0
    page.wait_for_timeout(200)
    assert dialogs == []
    no_overflow = page.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )
    assert no_overflow is True


# Regla: RN-009-13 — de los eventos solo se usan `reply`/`status`; `outcomes` nunca se muestra.
# AC-009-18 · Art. 8 (datos sensibles enmascarados)
def test_chat_page__masked_data_in_stream__is_shown_as_received(
    page: Page, live_server_url: str, chat_stream_script: ChatStreamScript
) -> None:
    """AC-009-18: la burbuja es exacta y ningún campo de `outcomes` aparece en la página."""
    reply = "Bloqueamos tu tarjeta **** 4321."
    outcome = {
        "kind": "CARD_BLOCKED",
        "masked_card": "**** 4321",
        "rule": "RN-007-14",
        "reason": "Motivo ficticio de bloqueo",
        "next_steps": "Pasos ficticios a seguir",
        "transaction_id": None,
        "reference": "E-9",
    }
    _stream_reply(chat_stream_script, reply, outcomes=[outcome])
    page.goto(live_server_url + "/")

    _send(page, "Bloquea mi tarjeta")
    expect(page.locator("#conversation [data-author='agent']")).to_have_count(2)

    bubble = page.locator("#conversation [data-author='agent'] .message-text").last
    assert bubble.text_content() == reply
    visible = page.inner_text("body")
    for hidden in ("RN-007-14", "E-9", "conv-1", "CARD_BLOCKED", "Motivo ficticio", "Pasos"):
        assert hidden not in visible


# Regla: RN-009-21 — solo la redacción del agente va palabra por palabra; lo fijo, completo.
# AC-009-24 · Art. 5 (textos fijos al instante)
def test_chat_page__reply_types__only_drafted_reply_streams(
    page: Page, live_server_url: str, chat_stream_script: ChatStreamScript
) -> None:
    """AC-009-24: saludo, mensaje, respuesta fija y aviso de derivación aparecen completos."""
    fixed = "Te derivamos con un analista."
    chat_stream_script.enqueue_stream().event("start", {"conversation_id": "conv-1"}).event(
        "end", {"conversation_id": "conv-1", "reply": fixed, "status": "ESCALATED", "outcomes": []}
    )
    page.goto(live_server_url + "/")
    expect(page.locator("#conversation .message-text")).to_have_text([GREETING])
    page.evaluate(_OBSERVER)

    _send(page, "Hola")
    expect(page.locator("#conversation .message-text")).to_have_text([GREETING, "Hola", fixed])
    expect(
        page.get_by_text("Tu caso fue derivado a un analista. Una persona continuará la atención.")
    ).to_be_visible()
    assert page.evaluate("window.draftHistory") == []
    assert page.locator("#draft .message-agent").count() == 0
    expect(page.get_by_text("El agente está escribiendo…")).to_be_hidden()


# Regla: RN-009-26 — sin identidad verificada la respuesta no contiene datos de la cuenta.
# Regla: RN-009-13 — la única petición es `POST /api/chat/stream`.
# AC-009-30 · Art. 7 (identificación antes que información)
def test_chat_page__no_verified_identity__shows_no_account_data(
    page: Page, live_server_url: str, chat_stream_script: ChatStreamScript
) -> None:
    """AC-009-30: solo saludo, mensaje y respuesta; sin transacciones, tarjetas ni datos."""
    reply = "Para ayudarte necesito tu número de documento."
    message = "No reconozco un cobro"
    _stream_reply(chat_stream_script, reply, delay_ms=20)
    page.goto(live_server_url + "/")
    calls = _api_calls(page, live_server_url)

    _send(page, message)
    expect(page.locator("#conversation .message-text")).to_have_text(
        [GREETING, message, reply], timeout=10000
    )

    remaining = page.inner_text("body")
    for known in (GREETING, message, reply):
        remaining = remaining.replace(known, "")
    for forbidden in ("transacci", "tarjeta", "D-1001", "****", "COP", "$"):
        assert forbidden not in remaining
    assert calls == [("POST", "/api/chat/stream")]
