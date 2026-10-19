"""Lector de pantalla y movimiento reducido con la respuesta en flujo (spec 009, HU-009-03)."""

from collections.abc import Iterator

import pytest
from playwright.sync_api import Browser, Page, expect
from tests.fakes.chat_stream_script import ChatStreamScript

REPLY = "Abrimos tu disputa."

# Registra, en TODAS las regiones vivas, el texto que se añade o cambia (no los atributos).
_LIVE_OBSERVER = """() => {
    window.liveMutations = [];
    const regions = document.querySelectorAll('[aria-live], [role="log"]');
    window.liveRegionCount = regions.length;
    for (const region of regions) {
        new MutationObserver((records) => {
            for (const r of records) {
                if (r.type === 'characterData') {
                    window.liveMutations.push({kind: 'text', text: r.target.data, agent: false});
                } else if (r.type === 'childList') {
                    for (const n of r.addedNodes) {
                        const el = n.nodeType === 1 ? n : null;
                        window.liveMutations.push({
                            kind: 'added',
                            text: n.textContent,
                            agent: !!el && el.matches('[data-author="agent"]'),
                        });
                    }
                }
            }
        }).observe(region, {childList: true, characterData: true, subtree: true});
    }
}"""


def _stream(script: ChatStreamScript, delay_ms: int) -> None:
    script.enqueue_stream().event("start", {"conversation_id": "conv-1"}).event(
        "word", {"text": "Abrimos"}, delay_ms
    ).event("word", {"text": " tu"}, delay_ms).event("word", {"text": " disputa."}, delay_ms).event(
        "end", {"conversation_id": "conv-1", "reply": REPLY, "status": "ACTIVE", "outcomes": []}
    )


def _send(page: Page, text: str) -> None:
    page.get_by_label("Escribe tu mensaje").fill(text)
    page.get_by_role("button", name="Enviar").click()


@pytest.fixture
def reduced_motion_page(browser: Browser) -> Iterator[Page]:
    context = browser.new_context(reduced_motion="reduce")
    try:
        yield context.new_page()
    finally:
        context.close()


# Regla: RN-009-19 — las palabras intermedias no se anuncian; la respuesta se anuncia una vez.
# AC-009-22 · Art. 5 (accesibilidad de la respuesta en flujo)
def test_chat_page__reply_streams__screen_reader_announces_once(
    page: Page, live_server_url: str, chat_stream_script: ChatStreamScript
) -> None:
    """AC-009-22: sin texto por palabra en regiones vivas; un solo mensaje `Agente` al `end`."""
    _stream(chat_stream_script, delay_ms=400)
    page.goto(live_server_url + "/")
    page.evaluate(_LIVE_OBSERVER)
    assert page.evaluate("() => window.liveRegionCount") >= 1

    _send(page, "Quiero reportar un cobro")
    expect(page.locator("#draft .message-text")).to_have_text("Abrimos tu", timeout=10000)
    during = page.evaluate("() => window.liveMutations")
    assert [m for m in during if any(w in m["text"] for w in ("Abrimos", "disputa"))] == []

    expect(page.locator("#conversation [data-author='agent']")).to_have_count(2, timeout=10000)
    page.wait_for_timeout(500)
    mutations = page.evaluate("() => window.liveMutations")
    with_reply = [m for m in mutations if "Abrimos" in m["text"] or "disputa" in m["text"]]
    assert len(with_reply) == 1
    assert with_reply[0]["kind"] == "added"
    assert with_reply[0]["agent"] is True
    assert with_reply[0]["text"] == "Agente: " + REPLY
    last = page.locator("#conversation [data-author='agent']").last
    assert last.inner_text().startswith("Agente") or last.text_content().startswith("Agente")


# Regla: RN-009-20 — con movimiento reducido no se ven las palabras; la respuesta sale al `end`.
# AC-009-23 · Art. 5 (respeto de la preferencia del dispositivo)
def test_chat_page__reduced_motion__shows_reply_at_end(
    reduced_motion_page: Page, live_server_url: str, chat_stream_script: ChatStreamScript
) -> None:
    """AC-009-23: con `reduce`, indicador visible y ninguna palabra hasta que llega `end`."""
    page = reduced_motion_page
    _stream(chat_stream_script, delay_ms=500)
    page.goto(live_server_url + "/")

    _send(page, "Quiero reportar un cobro")
    typing = page.locator("#typing")
    expect(typing).to_be_visible()
    page.wait_for_timeout(1100)  # ya llegaron al menos dos palabras
    expect(typing).to_be_visible()
    expect(typing).to_have_text("El agente está escribiendo…")
    assert page.locator("#draft .message-text:visible").count() == 0
    assert page.locator("#conversation").inner_text().count("Abrimos") == 0
    assert page.locator("#conversation [data-author='agent']").count() == 1

    expect(page.locator("#conversation [data-author='agent']")).to_have_count(2, timeout=10000)
    expect(page.locator("#conversation [data-author='agent'] .message-text").last).to_have_text(
        REPLY
    )
    expect(typing).to_be_hidden()
