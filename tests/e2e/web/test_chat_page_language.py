"""Idioma y textos fijos de la página en cada estado (spec 008, RN-008-22)."""

import re
from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import BrowserContext, Page, Route, expect
from tests.fakes.chat_api_script import ChatApiScript

# Copia literal de la tabla de spec §7.2 (no se lee de chat.js).
_ALLOWED_TEXTS = {
    "Banco Andino — Asistente de disputas",
    "Hola, soy el asistente de disputas de Banco Andino. Antes de revisar tu cuenta necesito "
    "identificarte. Para empezar, indícame tu número de documento, tu nombre completo o los "
    "últimos 4 dígitos de tu tarjeta.",
    "Escribe tu mensaje",
    "Enviar",
    "El agente está escribiendo…",
    "Tú",
    "Agente",
    "No enviado",
    "Tu caso fue derivado a un analista. Una persona continuará la atención.",
    "Esta conversación ya no está disponible.",
    "Iniciar una conversación nueva",
    "No hay conexión a internet. Revisa tu conexión y vuelve a intentarlo.",
    "La respuesta está tardando más de lo normal. Puedes volver a intentarlo.",
    "No pudimos atenderte en este momento. Intenta de nuevo en unos minutos.",
    "Reintentar",
}
_COUNTER = re.compile(r"Quedan \d+ caracteres")

# Recorre el DOM completo: texto fijo (fuera del cuerpo de las burbujas) y atributos accesibles.
_COLLECT_JS = """() => {
  const found = [];
  const add = (t) => { const s = (t || "").replace(/\\s+/g, " ").trim(); if (s) found.push(s); };
  add(document.title);
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode;
    const parent = node.parentElement;
    if (parent.closest("script, style")) continue;
    if (parent.closest(".message-text")) continue;
    add(node.textContent);
  }
  for (const el of document.querySelectorAll("*")) {
    for (const attr of ["aria-label", "title", "placeholder", "alt"]) {
      if (el.hasAttribute(attr)) add(el.getAttribute(attr));
    }
    for (const id of (el.getAttribute("aria-describedby") || "").split(/\\s+/)) {
      const target = id && document.getElementById(id);
      if (target) add(target.textContent);
    }
  }
  return found;
}"""


def _send(page: Page, text: str) -> None:
    page.get_by_label("Escribe tu mensaje").fill(text)
    page.get_by_role("button", name="Enviar").click()


def _is_allowed(text: str) -> bool:
    return text in _ALLOWED_TEXTS or _COUNTER.fullmatch(text) is not None


def _assert_spanish_fixed_texts(page: Page) -> None:
    assert page.locator("html").get_attribute("lang") == "es"
    foreign = [t for t in page.evaluate(_COLLECT_JS) if not _is_allowed(t)]
    # Los prefijos ocultos se leen como "Tú: " / "Agente: " dentro de la burbuja.
    foreign = [t for t in foreign if t.rstrip(": ") not in {"Tú", "Agente"}]
    assert foreign == []


def _hang(page: Page) -> list[Route]:
    held: list[Route] = []
    page.route("**/api/chat/stream", lambda route, _request: held.append(route))
    return held


def _wait_held(page: Page, held: list[Route]) -> None:
    for _ in range(200):
        if held:
            return
        page.wait_for_timeout(25)
    raise AssertionError("la petición no llegó")


def _scripted(page: Page, **response: Any) -> None:
    ChatApiScript().enqueue(**response).install(page)


def _state_initial(page: Page, context: BrowserContext, url: str) -> None:
    page.goto(url)


def _state_waiting(page: Page, context: BrowserContext, url: str) -> None:
    held = _hang(page)
    page.goto(url)
    _send(page, "Hola")
    _wait_held(page, held)
    expect(page.get_by_text("El agente está escribiendo…")).to_be_visible()
    _assert_spanish_fixed_texts(page)
    held[0].abort()


def _state_escalated(page: Page, context: BrowserContext, url: str) -> None:
    body = {"conversation_id": "c-1", "reply": "Te derivo.", "status": "ESCALATED"}
    _scripted(page, body=body)
    page.goto(url)
    _send(page, "Hola")
    expect(page.get_by_text("Tu caso fue derivado a un analista.", exact=False)).to_be_visible()


def _state_unavailable(page: Page, context: BrowserContext, url: str) -> None:
    _scripted(page, status=503, body={"detail": "x"})
    page.goto(url)
    _send(page, "Hola")
    expect(page.get_by_text("No pudimos atenderte", exact=False)).to_be_visible()


def _state_offline(page: Page, context: BrowserContext, url: str) -> None:
    page.goto(url)
    context.set_offline(True)
    _send(page, "Hola")
    expect(page.get_by_text("No hay conexión a internet.", exact=False)).to_be_visible()
    context.set_offline(False)


def _state_slow(page: Page, context: BrowserContext, url: str) -> None:
    page.clock.install()
    held = _hang(page)
    page.goto(url)
    _send(page, "Hola")
    _wait_held(page, held)
    page.clock.run_for(60_000)
    expect(page.get_by_text("La respuesta está tardando", exact=False)).to_be_visible()


def _state_not_found(page: Page, context: BrowserContext, url: str) -> None:
    ok = {"conversation_id": "c-1", "reply": "Hola, dime.", "status": "ACTIVE"}
    script = ChatApiScript()
    script.enqueue(body=ok).enqueue(status=404, body={"detail": "nf"}).install(page)
    page.goto(url)
    _send(page, "Hola")
    expect(page.get_by_text("Hola, dime.")).to_be_visible()
    _send(page, "Sigo aquí")
    expect(page.get_by_text("Esta conversación ya no está disponible.")).to_be_visible()


def _state_counter(page: Page, context: BrowserContext, url: str) -> None:
    page.goto(url)
    page.get_by_label("Escribe tu mensaje").fill("a" * 1800)
    expect(page.get_by_text("Quedan 200 caracteres")).to_be_visible()


_STATES: dict[str, Callable[[Page, BrowserContext, str], None]] = {
    "initial": _state_initial,
    "waiting": _state_waiting,
    "closed_by_escalation": _state_escalated,
    "service_unavailable": _state_unavailable,
    "offline": _state_offline,
    "slow_reply": _state_slow,
    "conversation_unavailable": _state_not_found,
    "counter": _state_counter,
}


# Regla: RN-008-22 — idioma español y textos fijos solo los de §7.2 en cada estado.
# AC-008-24 · Constitución §2 (idioma de la interfaz)
@pytest.mark.parametrize("state", list(_STATES), ids=list(_STATES))
def test_ac_008_24_chat_page__every_state__fixed_texts_in_spanish(
    page: Page, context: BrowserContext, live_server_url: str, state: str
) -> None:
    """AC-008-24: `lang="es"` y todo texto fijo visible o accesible pertenece a spec §7.2."""
    _STATES[state](page, context, live_server_url + "/")

    _assert_spanish_fixed_texts(page)
