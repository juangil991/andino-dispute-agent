"""Fallas del servicio, sin conexión, demora de 60 s y reintento (spec 008, RN-008-16/17/18)."""

import contextlib
import json
from typing import Any

import pytest
from playwright.sync_api import BrowserContext, Page, Route, expect
from tests.fakes.chat_api_script import ChatApiScript

_TEXT = "No reconozco un cobro"
_UNAVAILABLE = "No pudimos atenderte en este momento. Intenta de nuevo en unos minutos."
_OFFLINE = "No hay conexión a internet. Revisa tu conexión y vuelve a intentarlo."
_TIMEOUT = "La respuesta está tardando más de lo normal. Puedes volver a intentarlo."
_TYPING = "El agente está escribiendo…"
_FORBIDDEN = ["500", "503", "422", "Error", "Exception", "Traceback", "Internal Server"]

_FAILURES = {
    "http_500_with_body": {"status": 500, "body": "Internal Server Error"},
    "http_503": {"status": 503, "body": {"detail": "unavailable"}},
    "http_422": {"status": 422, "body": {"detail": "invalid"}},
    "http_200_not_json": {"status": 200, "body": "<html>no json</html>"},
    "http_200_without_reply": {"status": 200, "body": {"conversation_id": "conv-1"}},
}


def _reply(text: str) -> dict[str, Any]:
    return {"conversation_id": "conv-1", "reply": text, "status": "ACTIVE"}


def _send(page: Page, text: str) -> None:
    page.get_by_label("Escribe tu mensaje").fill(text)
    page.get_by_role("button", name="Enviar").click()


def _agent_texts(page: Page) -> list[str]:
    return page.locator("[data-author='agent'] .message-text").all_inner_texts()


# Regla: RN-008-16 — una falla del servicio se avisa sin detalles técnicos y se puede reintentar.
# AC-008-16 · Art. 7 (identificación antes que información)
@pytest.mark.parametrize("failure", list(_FAILURES.values()), ids=list(_FAILURES))
def test_ac_008_16_chat_page__service_unavailable__notice_and_retry(
    page: Page, live_server_url: str, failure: dict[str, Any]
) -> None:
    """AC-008-16: aviso fijo, mensaje marcado `No enviado` y `Reintentar` sin duplicar burbuja."""
    script = ChatApiScript()
    script.enqueue(**failure).enqueue(body=_reply("Revisemos tu caso."))
    script.install(page)
    page.goto(live_server_url + "/")

    _send(page, _TEXT)

    expect(page.get_by_text(_UNAVAILABLE)).to_be_visible()
    visible = page.locator("body").inner_text()
    for fragment in _FORBIDDEN:
        assert fragment not in visible
    bubble = page.locator("[data-author='user']")
    expect(bubble).to_have_count(1)
    expect(bubble).to_contain_text(_TEXT)
    expect(bubble).to_contain_text("No enviado")
    retry = page.get_by_role("button", name="Reintentar")
    expect(retry).to_be_visible()

    retry.click()

    expect(page.get_by_text("Revisemos tu caso.")).to_be_visible()
    expect(page.get_by_text(_UNAVAILABLE)).to_have_count(0)
    expect(page.locator("[data-author='user']")).to_have_count(1)
    expect(page.locator("[data-author='user']")).not_to_contain_text("No enviado")
    expect(retry).to_be_hidden()
    assert [r.json_body for r in script.requests] == [{"message": _TEXT}, {"message": _TEXT}]


# Regla: RN-008-16 (a) — sin conexión se avisa sin detalles técnicos y se conserva la conversación
# Regla: RN-008-17 — Reintentar reenvía el mismo texto al mismo `conversation_id`
# Regla: RN-008-18 — con el aviso visible la caja no envía mensajes nuevos
# AC-008-17 · Art. 7 (identificación antes que información)
def test_ac_008_17_chat_page__offline__notice_keeps_messages_and_retries(
    page: Page, context: BrowserContext, live_server_url: str
) -> None:
    """AC-008-17: aviso de sin conexión, mensajes conservados y reintento al volver la red."""
    script = ChatApiScript()
    script.enqueue(body=_reply("Hola, indícame tu documento."))
    script.enqueue(body=_reply("Gracias, ya te identifiqué."))
    script.enqueue(body=_reply("Aquí sigo."))
    script.install(page)
    page.goto(live_server_url + "/")
    _send(page, "Hola")
    expect(page.get_by_text("Hola, indícame tu documento.")).to_be_visible()
    _send(page, "Mi documento es 1234")
    expect(page.get_by_text("Gracias, ya te identifiqué.")).to_be_visible()

    context.set_offline(True)
    _send(page, "¿Sigues ahí?")

    expect(page.get_by_text(_OFFLINE)).to_be_visible()
    expect(page.locator("[data-author='user']")).to_have_count(3)
    expect(page.locator("[data-author='user']").last).to_contain_text("No enviado")
    expect(page.locator("[data-author='user']").first).not_to_contain_text("No enviado")
    expect(page.locator("[data-author='agent']")).to_have_count(3)
    page.evaluate(
        """() => {
          document.getElementById("message").value = "Otro";
          document.getElementById("composer").requestSubmit();
        }"""
    )
    expect(page.locator("[data-author='user']")).to_have_count(3)
    assert len(script.requests) == 2

    context.set_offline(False)
    page.get_by_role("button", name="Reintentar").click()

    expect(page.get_by_text("Aquí sigo.")).to_be_visible()
    assert script.requests[-1].json_body == {"conversation_id": "conv-1", "message": "¿Sigues ahí?"}
    expect(page.locator("[data-author='user']")).to_have_count(3)
    expect(page.get_by_text(_OFFLINE)).to_have_count(0)
    assert _agent_texts(page)[-1] == "Aquí sigo."


def _hang_requests(page: Page) -> list[Route]:
    """Deja colgadas las peticiones a /api/chat/stream sin bloquear el hilo de Playwright."""
    held: list[Route] = []
    page.route("**/api/chat/stream", lambda route, _request: held.append(route))
    return held


def _wait_for_requests(page: Page, held: list[Route], count: int) -> None:
    page.wait_for_function("() => true")
    for _ in range(200):
        if len(held) >= count:
            return
        page.wait_for_timeout(25)
    raise AssertionError("la petición no llegó")


def _fulfill(route: Route, body: dict[str, Any]) -> None:
    with contextlib.suppress(Exception):  # la petición abortada ya no admite respuesta
        end = json.dumps({"outcomes": [], **body}, ensure_ascii=False)
        start = 'event: start\ndata: {"conversation_id": "conv-1"}\n\n'
        route.fulfill(
            status=200,
            content_type="text/event-stream",
            body=start + f"event: end\ndata: {end}\n\n",
        )


# Regla: RN-008-16 (b) — a los 60 s sin respuesta se corta la espera y se descarta la tardía
# Regla: RN-008-17 — Reintentar reenvía el mismo texto sin duplicar la burbuja
# AC-008-18 · Art. 7 (identificación antes que información); bordes: 59 s y 61 s
@pytest.mark.parametrize("seconds", [59, 61], ids=["reply_at_59s", "reply_at_61s"])
def test_ac_008_18_chat_page__slow_reply__timeout_at_60s(
    page: Page, live_server_url: str, seconds: int
) -> None:
    """AC-008-18: con 59 s se muestra la respuesta; con 61 s aparece la demora y se descarta."""
    page.clock.install()
    held = _hang_requests(page)
    page.goto(live_server_url + "/")
    _send(page, _TEXT)
    _wait_for_requests(page, held, 1)
    expect(page.get_by_text(_TYPING)).to_be_visible()

    if seconds == 59:
        page.clock.run_for(59_000)
        _fulfill(held[0], _reply("Respuesta a tiempo."))
        expect(page.get_by_text("Respuesta a tiempo.")).to_be_visible()
        expect(page.get_by_text(_TIMEOUT)).to_have_count(0)
        expect(page.get_by_text(_TYPING)).to_be_hidden()
        return

    page.clock.run_for(60_000)
    expect(page.get_by_text(_TIMEOUT)).to_be_visible()
    expect(page.get_by_text(_TYPING)).to_be_hidden()
    retry = page.get_by_role("button", name="Reintentar")
    expect(retry).to_be_visible()
    page.clock.run_for(1_000)
    _fulfill(held[0], _reply("Respuesta tardía."))
    page.wait_for_timeout(200)
    expect(page.get_by_text("Respuesta tardía.")).to_have_count(0)

    retry.click()
    _wait_for_requests(page, held, 2)
    _fulfill(held[1], _reply("Respuesta al reintento."))

    expect(page.get_by_text("Respuesta al reintento.")).to_have_count(1)
    expect(page.locator("[data-author='user']")).to_have_count(1)
    expect(page.get_by_text(_TIMEOUT)).to_have_count(0)
