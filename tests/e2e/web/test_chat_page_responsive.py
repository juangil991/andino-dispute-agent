"""La página se usa sin desplazamiento horizontal en escritorio y celular (spec 008, RN-008-19)."""

import pytest
from playwright.sync_api import Browser, Locator, expect
from tests.fakes.chat_api_script import ChatApiScript

_LONG_WORD = "x" * 80
_LONG_REPLY = ("Respuesta larga " * 40)[: 600 - len(_LONG_WORD) - 1] + " " + _LONG_WORD


def _inside_viewport(locator: Locator, width: int, height: int) -> bool:
    box = locator.bounding_box()
    if box is None:
        return False
    return bool(
        box["x"] >= 0
        and box["y"] >= 0
        and box["x"] + box["width"] <= width
        and box["y"] + box["height"] <= height
    )


# Regla: RN-008-19 — sin desplazamiento horizontal y con caja y Enviar visibles en 3 pantallas.
# AC-008-21 · Art. 7 (identificación antes que información)
@pytest.mark.parametrize(
    ("width", "height", "is_mobile"),
    [(1280, 800, False), (360, 740, True), (740, 360, True)],
    ids=["desktop_1280x800", "phone_portrait_360x740", "phone_landscape_740x360"],
)
def test_ac_008_21_chat_page__viewport__no_horizontal_scroll_and_input_visible(
    browser: Browser, live_server_url: str, width: int, height: int, is_mobile: bool
) -> None:
    """AC-008-21: con una respuesta de 600 caracteres, sin scroll horizontal y se puede escribir."""
    assert len(_LONG_REPLY) == 600
    context = browser.new_context(
        viewport={"width": width, "height": height}, is_mobile=is_mobile, has_touch=is_mobile
    )
    try:
        page = context.new_page()
        script = ChatApiScript()
        script.enqueue(
            body={"conversation_id": "conv-1", "reply": _LONG_REPLY, "status": "ACTIVE"}
        ).enqueue(body={"conversation_id": "conv-1", "reply": "Listo", "status": "ACTIVE"})
        script.install(page)
        page.goto(live_server_url + "/")
        box = page.get_by_label("Escribe tu mensaje")
        send = page.get_by_role("button", name="Enviar")

        box.fill("Hola")
        send.click()
        expect(page.locator("[data-author='agent']")).to_have_count(2)
        expect(page.get_by_text(_LONG_WORD)).to_be_visible()

        metrics = page.evaluate(
            "() => ({sw: document.documentElement.scrollWidth, iw: window.innerWidth})"
        )
        assert metrics["sw"] <= metrics["iw"]
        inner = page.evaluate("() => ({w: window.innerWidth, h: window.innerHeight})")
        assert _inside_viewport(box, inner["w"], inner["h"])
        assert _inside_viewport(send, inner["w"], inner["h"])

        box.fill("Gracias")
        send.click()
        expect(page.locator("[data-author='agent']")).to_have_count(3)
        assert [r.json_body["message"] for r in script.requests] == ["Hola", "Gracias"]
        metrics = page.evaluate(
            "() => ({sw: document.documentElement.scrollWidth, iw: window.innerWidth})"
        )
        assert metrics["sw"] <= metrics["iw"]
    finally:
        context.close()
