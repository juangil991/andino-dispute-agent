"""Arnés de la página de chat: verifica el guion de /api/chat y el servidor en vivo (spec 008)."""

import json

from playwright.sync_api import Page
from tests.fakes.chat_api_script import ChatApiScript
from tests.fakes.chat_stream_script import ChatStreamScript


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


# Regla: soporte de pruebas — ChatStreamScript emite los eventos de forma progresiva (con pausa).
# Soporte de tests · Art. 3
def test_chat_stream_script__scripted_events__arrive_progressively(
    page: Page, live_server_url: str, chat_stream_script: ChatStreamScript
) -> None:
    """`start` se lee antes de que se libere el primer `word`."""
    chat_stream_script.enqueue_stream().event("start", {"conversation_id": "c-1"}).hold().event(
        "word", {"text": "Hola"}
    ).event(
        "end",
        {"conversation_id": "c-1", "reply": "Hola", "status": "active", "outcomes": []},
    )
    page.goto(live_server_url + "/docs")
    page.evaluate(
        """() => {
            window.chunks = [];
            window.done = false;
            fetch('/api/chat/stream', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({message: 'hola'}),
            }).then(async (r) => {
                const reader = r.body.getReader();
                const decoder = new TextDecoder();
                for (;;) {
                    const {done, value} = await reader.read();
                    if (done) break;
                    window.chunks.push(decoder.decode(value));
                }
                window.done = true;
            });
        }"""
    )

    page.wait_for_function("window.chunks.length >= 1")
    before = page.evaluate("window.chunks.join('')")
    assert "event: start" in before
    assert "event: word" not in before
    assert page.evaluate("window.done") is False

    chat_stream_script.release()
    page.wait_for_function("window.done === true")
    after = page.evaluate("window.chunks.join('')")
    assert "event: word" in after
    assert after.rstrip().endswith('"outcomes": []}')
    assert chat_stream_script.requests[0].json_body == {"message": "hola"}


# Regla: soporte de pruebas — ChatApiScript traduce el JSON guionizado a SSE (spec 009 §7.1).
# Soporte de tests · Art. 3
def test_chat_api_script__json_reply__is_translated_to_sse_on_stream_route(
    page: Page, live_server_url: str
) -> None:
    """Start, un word por palabra (concatenado == reply) y end."""
    reply = "Hola, ¿en qué te ayudo?"
    script = ChatApiScript().enqueue(
        status=200,
        body={"conversation_id": "c-1", "reply": reply, "status": "active", "outcomes": []},
    )
    script.enqueue(status=503, body={"detail": "no"})
    script.install(page)
    page.goto(live_server_url + "/docs")

    result = page.evaluate(
        """async () => {
            const call = async () => {
                const r = await fetch('/api/chat/stream', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({message: 'hola'}),
                });
                const type = r.headers.get('content-type');
                return {status: r.status, type, text: await r.text()};
            };
            return [await call(), await call()];
        }"""
    )

    ok, error = result
    assert ok["status"] == 200
    assert ok["type"].startswith("text/event-stream")
    blocks = [b for b in ok["text"].split("\n\n") if b]
    names = [b.split("\n")[0] for b in blocks]
    assert names[0] == "event: start"
    assert names[-1] == "event: end"
    assert set(names[1:-1]) == {"event: word"}
    words = [json.loads(b.split("\n")[1][len("data: ") :])["text"] for b in blocks[1:-1]]
    assert "".join(words) == reply
    assert len(words) == len(reply.split())
    assert error["status"] == 503
    assert [r.url for r in script.requests] == [live_server_url + "/api/chat/stream"] * 2
