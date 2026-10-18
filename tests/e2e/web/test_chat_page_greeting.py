"""Saludo inicial de la página de chat y ausencia de datos de la cuenta (spec 008)."""

from playwright.sync_api import Page, Request, expect
from tests.fakes.chat_api_script import ChatApiScript

TITLE = "Banco Andino — Asistente de disputas"
GREETING = (
    "Hola, soy el asistente de disputas de Banco Andino. Antes de revisar tu cuenta necesito "
    "identificarte. Para empezar, indícame tu número de documento, tu nombre completo o los "
    "últimos 4 dígitos de tu tarjeta."
)
LABEL = "Escribe tu mensaje"


# Regla: RN-008-03 — al cargar se muestra el saludo fijo sin llamar al agente.
# Regla: RN-008-11 — la página no muestra datos de la cuenta por su cuenta.
# AC-008-01 · Art. 7 (identificación antes que información)
def test_ac_008_01_chat_page__loaded__agent_greets_and_input_enabled(
    page: Page, live_server_url: str
) -> None:
    """AC-008-01: el único mensaje es el saludo del Agente y la caja está habilitada y vacía."""
    script = ChatApiScript()
    script.install(page)

    page.goto(live_server_url + "/")

    log = page.get_by_role("log")
    messages = log.locator("[data-author]")
    expect(messages).to_have_count(1)
    expect(messages.first).to_have_attribute("data-author", "agent")
    expect(messages.first).to_have_text("Agente: " + GREETING)
    expect(page).to_have_title(TITLE)
    expect(page.get_by_role("heading", level=1)).to_have_text(TITLE)

    textbox = page.get_by_label(LABEL)
    expect(textbox).to_be_enabled()
    expect(textbox).to_have_value("")
    textbox.fill("hola")
    expect(textbox).to_have_value("hola")
    assert script.requests == []


# Regla: RN-008-01 — la página solo pide `GET /` y sus estáticos al abrir.
# Regla: RN-008-11 — el texto visible es solo el de §7.2.
# AC-008-09 · Art. 7 (identificación antes que información)
def test_ac_008_09_chat_page__not_identified__no_account_data_nor_api_calls(
    page: Page, live_server_url: str
) -> None:
    """AC-008-09: solo peticiones a `/` y `/static/*`, y texto visible únicamente de §7.2."""
    requested: list[Request] = []
    page.on("request", lambda request: requested.append(request))

    page.goto(live_server_url + "/")
    expect(page.get_by_role("log").locator("[data-author]")).to_have_count(1)

    paths = [(r.method, r.url.removeprefix(live_server_url)) for r in requested]
    assert paths
    for method, path in paths:
        assert method == "GET"
        assert path == "/" or path.startswith("/static/"), path

    visible = [line.strip() for line in page.inner_text("body").splitlines() if line.strip()]
    allowed = {TITLE, "Agente: " + GREETING, "Agente:", GREETING, LABEL, "Enviar"}
    assert set(visible) <= allowed, set(visible) - allowed
    assert TITLE in visible
    assert GREETING in "".join(visible)
    assert LABEL in visible
    assert "Enviar" in visible
    expect(page.get_by_role("button", name="Reintentar")).to_be_hidden()
    expect(page.get_by_role("button", name="Iniciar una conversación nueva")).to_be_hidden()
