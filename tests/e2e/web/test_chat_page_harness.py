"""Arnés de la página de chat: verifica el guion de /api/chat y el servidor en vivo (spec 008)."""

from playwright.sync_api import Page
from tests.fakes.chat_api_script import ChatApiScript


# Regla: soporte de pruebas de navegador — sin AC propio; el arnés intercepta POST /api/chat.
# Art. 1 (datos ficticios, sin LLM real) · §5.3 (tests deterministas)
def test_chat_page_harness__scripted_chat_api__fulfills_and_records_request(
    page: Page, live_server_url: str
) -> None:
    """Soporte de pruebas: respuesta guionizada y petición registrada."""
    script = ChatApiScript().enqueue(status=200, body={"reply": "hola"})
    script.install(page)
    page.goto(live_server_url + "/docs")

    result = page.evaluate(
        """async () => {
            const r = await fetch('/api/chat', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({message: 'hola'}),
            });
            return {status: r.status, body: await r.json()};
        }"""
    )

    assert result == {"status": 200, "body": {"reply": "hola"}}
    assert len(script.requests) == 1
    assert script.requests[0].method == "POST"
    assert script.requests[0].url == live_server_url + "/api/chat"
    assert script.requests[0].json_body == {"message": "hola"}
