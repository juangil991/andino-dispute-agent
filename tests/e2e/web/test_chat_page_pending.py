"""Indicador de respuesta y un solo envío en curso (spec 008, RN-008-07).

``ChatApiScript`` retiene la respuesta bloqueando el hilo de Playwright, así que mientras dura la
retención el test no puede ejecutar otras acciones. Por eso las interacciones durante la espera
se hacen dentro de la página (síncronas, sin sleeps) y la respuesta se libera con un
``threading.Timer`` ya armado; el resultado se lee después de la liberación.
"""

import json
import threading
from typing import Any

import pytest
from playwright.sync_api import Page, expect
from tests.fakes.chat_api_script import ChatApiScript

_TYPING = "El agente está escribiendo…"
_TEXT = "No reconozco un cobro"
_RELEASE_AFTER_SECONDS = 1.0

# Estado de la UI durante la espera, medido dentro de la página.
_SNAPSHOT_JS = (
    """() => {
  const typing = document.getElementById("typing");
  return {
    typingVisible: !!typing && !typing.hidden && typing.textContent === """
    + json.dumps(_TYPING)
    + """,
    boxDisabled: document.getElementById("message").disabled,
    sendDisabled: document.getElementById("send").disabled,
  };
}"""
)

# Gestos de doble envío, disparados en la misma tarea del navegador que el primer envío.
_GESTURES = {
    "double_click": """() => {
      const send = document.getElementById("send");
      send.click(); send.click();
    }""",
    "enter_twice": """() => {
      const box = document.getElementById("message");
      const press = () => box.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
      press(); press();
    }""",
    "enter_then_click": """() => {
      const box = document.getElementById("message");
      box.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
      document.getElementById("send").click();
    }""",
}


def _reply(text: str) -> dict[str, Any]:
    return {"conversation_id": "conv-1", "reply": text, "status": "ACTIVE"}


def _release_later(script: ChatApiScript) -> threading.Timer:
    timer = threading.Timer(_RELEASE_AFTER_SECONDS, script.release)
    timer.start()
    return timer


# Regla: RN-008-07 — mientras espera, se indica y la caja y `Enviar` no aceptan otro envío.
# AC-008-05 · Art. 7 (identificación antes que información)
def test_ac_008_05_chat_page__awaiting_reply__indicator_and_input_locked(
    page: Page, live_server_url: str
) -> None:
    """AC-008-05: indicador visible y controles bloqueados hasta que llega la respuesta."""
    script = ChatApiScript().enqueue(body=_reply("Listo."), hold=True)
    script.install(page)
    page.goto(live_server_url + "/")
    box = page.get_by_label("Escribe tu mensaje")
    send = page.get_by_role("button", name="Enviar")
    expect(page.get_by_text(_TYPING)).to_be_hidden()
    box.fill(_TEXT)

    # Un temporizador dentro de la página mide el estado mientras la respuesta sigue retenida
    # e intenta un segundo envío (requestSubmit ignora el estado `disabled` de los botones).
    page.evaluate(
        """(snapshotSource) => {
          const snapshot = eval(snapshotSource);
          window.__waiting = new Promise((resolve) => setTimeout(() => {
            const box = document.getElementById("message");
            const during = snapshot();
            box.value = "Otro texto";
            document.getElementById("composer").requestSubmit();
            resolve({ during, userBubbles: document.querySelectorAll(
              "[data-author='user']").length });
          }, 200));
        }""",
        _SNAPSHOT_JS,
    )
    timer = _release_later(script)
    send.click()
    waiting = page.evaluate("window.__waiting")
    timer.join()

    assert waiting["during"] == {"typingVisible": True, "boxDisabled": True, "sendDisabled": True}
    assert waiting["userBubbles"] == 1
    assert len(script.requests) == 1
    expect(page.locator("[data-author='agent']")).to_have_count(2)
    expect(page.get_by_text(_TYPING)).to_be_hidden()
    expect(box).to_be_enabled()
    expect(send).to_be_enabled()
    box.fill("Otro mensaje")
    expect(box).to_have_value("Otro mensaje")


# Regla: RN-008-07 — doble clic, Enter repetido o ambos producen una sola petición y burbuja.
# AC-008-06 · Art. 7 (identificación antes que información)
@pytest.mark.parametrize("gesture", list(_GESTURES), ids=list(_GESTURES))
def test_ac_008_06_chat_page__double_submit__single_request(
    page: Page, live_server_url: str, gesture: str
) -> None:
    """AC-008-06: un doble envío genera una sola petición y una sola burbuja de la cliente."""
    script = ChatApiScript().enqueue(body=_reply("Listo."), hold=True)
    script.install(page)
    page.goto(live_server_url + "/")
    page.get_by_label("Escribe tu mensaje").fill(_TEXT)

    timer = _release_later(script)
    page.evaluate(_GESTURES[gesture])
    # Segundo intento con el texto repuesto: solo la bandera `pending` puede detenerlo.
    page.evaluate(
        """(text) => {
          document.getElementById("message").value = text;
          document.getElementById("composer").requestSubmit();
        }""",
        _TEXT,
    )
    expect(page.locator("[data-author='agent']")).to_have_count(2)
    timer.join()

    assert [r.json_body for r in script.requests] == [{"message": _TEXT}]
    expect(page.locator("[data-author='user']")).to_have_count(1)
