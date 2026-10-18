# Tareas: Conversar con el agente de disputas desde una página de chat

| Campo | Valor |
|---|---|
| Feature | `008-chat-web-page` |
| Spec | [spec.md](./spec.md) — versión 0.1.0 |
| Plan | [plan.md](./plan.md) — versión 0.1.0 |
| Fecha | 2026-10-18 |

**Estados:** `[ ]` pendiente · `[~]` en curso · `[x]` terminada

Convenciones comunes a todas las tareas:

- Las pruebas de navegador son funciones **síncronas** con la API síncrona de Playwright (plan §7).
- Usan el fixture `chat_page` (página cargada en `GET /` del servidor en vivo) y el ayudante `ChatApiScript` de T-008-01.
- Llevan el comentario de trazabilidad `# Regla: RN-008-XX — …` / `# AC-008-XX · Art. N` (`mcp-testing.md` §4).
- No usan `sleep`: el tiempo se controla con `page.clock` y las esperas con `expect`.
- Todos los textos fijos salen del objeto `TEXTS` de `chat.js` y son los de spec §7.2.

---

## Tareas

### [x] T-008-01 — Dependencias de navegador y arnés de pruebas e2e de la página

- **Cubre:** habilita T-008-03 a T-008-13 (todas las pruebas de navegador de AC-008-01 a AC-008-24)
- **App / capa:** `dispute_agent` / soporte de tests
- **Depende de:** —
- **Archivos:** `pyproject.toml`, `uv.lock`, `CLAUDE.md`, `tests/fakes/chat_api_script.py`, `tests/e2e/web/conftest.py`, `tests/e2e/web/test_chat_page_harness.py`
- **Test primero:** `tests/e2e/web/test_chat_page_harness.py::test_chat_page_harness__scripted_chat_api__fulfills_and_records_request`
- **Red:** el test falla al importar `playwright` / `tests.fakes.chat_api_script` y por la falta del fixture `live_server_url`: ninguno existe aún.
- **Green:**
  - **Dependencias:** añadir `pytest-playwright>=0.5,<1` y `playwright>=1.48,<2` al grupo `dev` y registrar el marcador `browser` (no excluido por defecto) en `pyproject.toml`; `uv sync`.
  - **`tests/e2e/web/conftest.py`:**
    - Fixture de sesión `live_server_url`: `create_app(AgentSettings(_env_file=None), banking=FakeBankingTools(), llm=FakeLLM(...), clock=FixedAgentClock(...))` con Uvicorn en un hilo, en un puerto libre de `127.0.0.1`, esperando a que arranque.
    - Si Chromium no está instalado, falla con un mensaje que indique `uv run playwright install chromium`, sin `skip`.
    - Marca `browser` para todo el directorio.
  - **`ChatApiScript`:**
    - Encola respuestas `(status, body, delay_ms | hold, abort)`.
    - Registra cada petición (método, URL, JSON del cuerpo).
    - Se instala con `install(page)` mediante `page.route("**/api/chat", ...)`.
    - Permite liberar una respuesta retenida (`release()`).
  - **Test:** carga `live_server_url + "/docs"`, ejecuta `fetch('/api/chat', {method:'POST', ...})` con `page.evaluate` y comprueba la respuesta guionizada y la petición registrada.
  - **`CLAUDE.md`:** añadir en "Comandos" `uv run playwright install chromium` (una vez) y `uv run pytest -m browser`.
- **Refactor:** —

### [x] T-008-02 — El agente sirve la página y sus estáticos

- **Cubre:** AC-008-25
- **App / capa:** `dispute_agent` / `infrastructure/inbound`
- **Depende de:** —
- **Archivos:** `src/dispute_agent/infrastructure/inbound/web/page_router.py`, `src/dispute_agent/infrastructure/inbound/web/static/index.html`, `src/dispute_agent/infrastructure/inbound/web/static/styles.css`, `src/dispute_agent/infrastructure/inbound/web/static/chat.js`, `src/dispute_agent/main.py`, `tests/integration/dispute_agent/web/test_chat_page_serving.py`
- **Test primero:** `tests/integration/dispute_agent/web/test_chat_page_serving.py::test_ac_008_25_chat_page__get_root_and_static__served_by_agent_app`
- **Red:** con `TestClient(create_app(...))` (fakes como en `test_chat_api.py`), `GET /` responde `404` y `GET /static/chat.js` y `GET /static/styles.css` también, porque no hay router ni montaje.
- **Green:**
  - **`page_router.py`:**
    - `build_page_router()`: `GET /` → `FileResponse(index.html, media_type="text/html")`.
    - `static_files()`: `StaticFiles(directory=<static>)`, con la ruta resuelta mediante `Path(__file__)`.
  - **`main.py`:** `create_app` incluye el router y monta `/static`.
  - **Estáticos mínimos:**
    - `index.html`: `<!doctype html>`, `lang="es"` y referencias a `/static/styles.css` y `/static/chat.js`.
    - `styles.css` y `chat.js`: vacíos funcionales.
  - **Test:** comprueba `200`, `text/html`, que el HTML referencia `chat.js` y que `POST /api/chat` sigue respondiendo (AC-007-31 sin cambios).
- **Refactor:** —

### [x] T-008-03 — Saludo inicial y página sin datos de la cuenta

- **Cubre:** AC-008-01, AC-008-09
- **App / capa:** `dispute_agent` / `infrastructure/inbound`
- **Depende de:** T-008-01, T-008-02
- **Archivos:** `src/dispute_agent/infrastructure/inbound/web/static/index.html`, `src/dispute_agent/infrastructure/inbound/web/static/chat.js`, `src/dispute_agent/infrastructure/inbound/web/static/styles.css`, `tests/e2e/web/test_chat_page_greeting.py`
- **Test primero:** `tests/e2e/web/test_chat_page_greeting.py::test_ac_008_01_chat_page__loaded__agent_greets_and_input_enabled` (y `test_ac_008_09_chat_page__not_identified__no_account_data_nor_api_calls`)
- **Red:**
  - No hay mensajes en la página ni caja de texto con la etiqueta `Escribe tu mensaje`.
  - Las aserciones sobre el saludo de §7.2 y sobre el texto visible fallan.
- **Green:**
  - **`index.html`:**
    - Título y encabezado `Banco Andino — Asistente de disputas`.
    - Contenedor de conversación `role="log"` con `aria-live="polite"`.
    - `<label>` `Escribe tu mensaje` + `<textarea maxlength="2000">` y botón `Enviar`.
    - Zona de avisos dentro de la región viva.
    - Botones `Reintentar` e `Iniciar una conversación nueva` ocultos.
  - **`chat.js`:**
    - Objeto `TEXTS` con todos los textos de §7.2.
    - Estado en memoria (`conversationId`, `pending`, `failedText`, `closed`).
    - `appendMessage(author, text)` con `createElement` + `textContent` y prefijo accesible visualmente oculto (`Tú: ` / `Agente: `).
    - Al cargar, solo pinta el saludo.
  - **`styles.css`:** diseño base y clase `.visually-hidden`.
  - **AC-008-09:** registrar las peticiones con `page.on("request")` y comprobar que son solo `GET /` y `/static/*`, y que el texto visible es solo el de §7.2.
- **Refactor:** extraer la creación de burbujas a una función única reutilizable.

### [x] T-008-04 — Enviar mensajes, mostrar solo `reply` y no ofrecer acciones

- **Cubre:** AC-008-02, AC-008-10, AC-008-11
- **App / capa:** `dispute_agent` / `infrastructure/inbound`
- **Depende de:** T-008-03
- **Archivos:** `src/dispute_agent/infrastructure/inbound/web/static/chat.js`, `src/dispute_agent/infrastructure/inbound/web/static/index.html`, `tests/e2e/web/test_chat_page_messaging.py`
- **Test primero:** `tests/e2e/web/test_chat_page_messaging.py::test_ac_008_02_chat_page__two_turns__ordered_and_conversation_id_reused` (y `test_ac_008_10_chat_page__after_turn__only_textbox_and_send_controls`, `test_ac_008_11_chat_page__reply_with_outcomes__only_reply_shown`)
- **Red:** pulsar `Enviar` no hace ninguna petición ni añade burbujas.
- **Green:**
  - **`send()`:**
    - Pinta el mensaje de la cliente.
    - Hace `fetch('POST /api/chat')` con `{message}` y añade `conversation_id` solo si existe.
    - Valida que la respuesta `200` sea JSON con `reply: string` y `status ∈ {ACTIVE, ESCALATED}`.
    - Guarda `conversation_id` y pinta solo `reply`.
  - **Envío:** formulario o botón `Enviar`.
  - **Sin acciones:** ningún otro control ni enlace de acción en `index.html`.
- **Refactor:** separar `postMessage()` (red + validación) de la presentación.

### [x] T-008-05 — Todo el texto de la conversación se muestra como texto plano

- **Cubre:** AC-008-07, AC-008-08
- **App / capa:** `dispute_agent` / `infrastructure/inbound`
- **Depende de:** T-008-04
- **Archivos:** `src/dispute_agent/infrastructure/inbound/web/static/chat.js`, `src/dispute_agent/infrastructure/inbound/web/static/styles.css`, `tests/e2e/web/test_chat_page_text_rendering.py`, `tests/integration/dispute_agent/web/test_chat_js_html_guard.py`
- **Test primero:** `tests/e2e/web/test_chat_page_text_rendering.py::test_ac_008_07_chat_page__customer_markup__shown_as_text` (parametrizado, 3 textos) y `test_ac_008_08_chat_page__agent_markup__shown_as_text` (parametrizado, 3 textos). Además, `tests/integration/dispute_agent/web/test_chat_js_html_guard.py::test_ac_008_07_chat_js__no_html_injection_apis`.
- **Red:**
  - La fila `Línea 1\nLínea 2` falla: `inner_text()` de la burbuja no conserva el salto de línea sin `white-space: pre-wrap`.
  - Las aserciones de «ningún `b`/`script`/`img`/`a` en el log» y «ningún evento `dialog`» quedan como protección.
  - La guarda estática se escribe antes de tocar `chat.js`.
- **Green:**
  - `.message { white-space: pre-wrap; overflow-wrap: anywhere; }`.
  - Revisar que todo el pintado use `textContent`.
  - La guarda comprueba que `chat.js` no contiene `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write` ni `eval(`.
- **Refactor:** —

### [x] T-008-06 — Mensajes vacíos, recorte, límite de 2000 caracteres y Shift+Enter

- **Cubre:** AC-008-03, AC-008-04
- **App / capa:** `dispute_agent` / `infrastructure/inbound`
- **Depende de:** T-008-04
- **Archivos:** `src/dispute_agent/infrastructure/inbound/web/static/chat.js`, `src/dispute_agent/infrastructure/inbound/web/static/index.html`, `tests/e2e/web/test_chat_page_input.py`
- **Test primero:** `tests/e2e/web/test_chat_page_input.py::test_ac_008_03_chat_page__blank_message__not_sent` (parametrizado: vacío, espacios, saltos × Enter/`Enviar`) y `test_ac_008_04_chat_page__trim_and_length_limit` (parametrizado, 5 filas)
- **Red:**
  - Un mensaje con solo espacios se envía y pinta una burbuja.
  - `"  hola  "` viaja sin recortar.
  - No existe el contador `Quedan N caracteres`.
  - Enter no envía (o Shift+Enter envía).
- **Green:**
  - Recortar con `trim()` y no enviar si queda vacío.
  - Manejar `keydown`: Enter sin Shift envía con `preventDefault`; Shift+Enter deja el salto de línea.
  - Contador visible cuando quedan ≤ 200 caracteres.
  - `maxlength="2000"` en la caja.
- **Refactor:** —

### [x] T-008-07 — Indicador de respuesta y un solo envío en curso

- **Cubre:** AC-008-05, AC-008-06
- **App / capa:** `dispute_agent` / `infrastructure/inbound`
- **Depende de:** T-008-06
- **Archivos:** `src/dispute_agent/infrastructure/inbound/web/static/chat.js`, `src/dispute_agent/infrastructure/inbound/web/static/index.html`, `tests/e2e/web/test_chat_page_pending.py`
- **Test primero:** `tests/e2e/web/test_chat_page_pending.py::test_ac_008_05_chat_page__awaiting_reply__indicator_and_input_locked` y `test_ac_008_06_chat_page__double_submit__single_request` (parametrizado: doble clic, Enter×2, Enter+clic)
- **Red:**
  - Con una respuesta retenida (`hold`), no aparece `El agente está escribiendo…`.
  - Un segundo Enter genera otra petición y otra burbuja.
- **Green:**
  - Bandera `pending`, comprobada **antes** de cualquier efecto en `send()`.
  - Mostrar el indicador y deshabilitar la caja y `Enviar` durante la espera.
  - Restaurar ambos al terminar.
- **Refactor:** centralizar el cambio de estado de la UI en una función `render()`/`setState()`.

### [x] T-008-08 — Cierre por derivación o por conversación inexistente, y conversación nueva

- **Cubre:** AC-008-14, AC-008-15, AC-008-19, AC-008-20
- **App / capa:** `dispute_agent` / `infrastructure/inbound`
- **Depende de:** T-008-07
- **Archivos:** `src/dispute_agent/infrastructure/inbound/web/static/chat.js`, `src/dispute_agent/infrastructure/inbound/web/static/index.html`, `tests/e2e/web/test_chat_page_closing.py`
- **Test primero:** `tests/e2e/web/test_chat_page_closing.py::test_ac_008_14_chat_page__escalated__conversation_closed` (y `test_ac_008_15_chat_page__new_conversation__resets_state` parametrizado `ESCALATED`/`404`, `test_ac_008_19_chat_page__agent_failure_reply__shown_and_closed`, `test_ac_008_20_chat_page__404__unavailable_notice_without_retry`)
- **Red:**
  - Con `status = "ESCALATED"` la caja sigue habilitada y no aparece el aviso de derivación.
  - Con `404` no aparece el aviso de conversación no disponible.
  - No existe el botón `Iniciar una conversación nueva`.
- **Green:**
  - **`ESCALATED`:** `closed = true`, aviso de derivación tras el `reply`, caja y `Enviar` deshabilitados, botón visible.
  - **`404`:** aviso de conversación no disponible y el mismo cierre, sin `Reintentar`.
  - **Botón `Iniciar una conversación nueva`:**
    - Vacía el log y olvida `conversationId`.
    - Pinta el saludo.
    - Habilita la caja y le da el foco.
- **Refactor:** —

### [x] T-008-09 — Fallas del servicio, falta de conexión, demora de 60 s y reintento

- **Cubre:** AC-008-16, AC-008-17, AC-008-18
- **App / capa:** `dispute_agent` / `infrastructure/inbound`
- **Depende de:** T-008-08
- **Archivos:** `src/dispute_agent/infrastructure/inbound/web/static/chat.js`, `src/dispute_agent/infrastructure/inbound/web/static/index.html`, `src/dispute_agent/infrastructure/inbound/web/static/styles.css`, `tests/e2e/web/test_chat_page_failures.py`
- **Test primero:** `tests/e2e/web/test_chat_page_failures.py::test_ac_008_16_chat_page__service_unavailable__notice_and_retry` (parametrizado: 500 con cuerpo, 503, 422, 200 no JSON, 200 sin `reply`), `test_ac_008_17_chat_page__offline__notice_keeps_messages_and_retries` y `test_ac_008_18_chat_page__slow_reply__timeout_at_60s` (parametrizado: 59 s / 61 s; con `page.clock.install()` y respuesta `hold`)
- **Red:** ante un `500`, la página no muestra el aviso de servicio no disponible ni `Reintentar`; sin conexión no avisa; a los 60 s no corta la espera.
- **Green:**
  - **Clasificación del fallo:**
    - `TypeError` de `fetch` o `navigator.onLine === false` → aviso de sin conexión.
    - Aborto por `setTimeout(60000)` + `AbortController` → aviso de demora.
    - Código distinto de `200`/`404`, o un `200` no válido → aviso de servicio no disponible.
  - **Mensaje fallido:** sigue visible, marcado `No enviado`, y se guarda en `failedText`.
  - **Botón `Reintentar`:**
    - Reenvía el mismo texto al mismo `conversationId` sin pintar otra burbuja.
    - Si tiene éxito, quita la marca y el aviso.
  - Con `failedText` pendiente, la caja no envía mensajes nuevos.
  - **Respuestas tardías:** cada intento lleva un identificador y las respuestas de intentos abortados se descartan.
  - Ningún aviso incluye el código, el cuerpo ni el error.
- **Refactor:** tabla única de clasificación de fallo → texto de §7.2.
- **Nota de ejecución:** el subagente escribió `chat.js` antes que el test, así que el Red de esta tarea no se evidenció (Art. 3). Los tests pasan y el comportamiento está cubierto; queda como desviación de proceso.

### [x] T-008-10 — La conversación no se conserva en el navegador

- **Cubre:** AC-008-12, AC-008-13
- **App / capa:** `dispute_agent` / `infrastructure/inbound`
- **Depende de:** T-008-04
- **Archivos:** `tests/e2e/web/test_chat_page_persistence.py`, `tests/integration/dispute_agent/web/test_chat_js_storage_guard.py`
- **Test primero:** `tests/e2e/web/test_chat_page_persistence.py::test_ac_008_12_chat_page__reload__starts_new_conversation` y `test_ac_008_13_chat_page__reopen__no_browser_storage`. Además, `tests/integration/dispute_agent/web/test_chat_js_storage_guard.py::test_ac_008_13_chat_js__no_browser_storage_apis`.
- **Red:** pruebas de caracterización de RN-008-12. Se verifican en rojo forzando temporalmente un fallo: guardar `conversation_id` en `sessionStorage` en una copia local, o invertir la aserción, y se documenta en el informe. Ningún cambio de producción es necesario si `chat.js` ya cumple; si alguna prueba falla de verdad, la corrección mínima va en `chat.js`, que se añade a Archivos.
- **Green:** las pruebas pasan contra el `chat.js` de T-008-04. La guarda estática comprueba la ausencia de `localStorage`, `sessionStorage`, `indexedDB` y `document.cookie` en `chat.js`.
- **Refactor:** —

### [x] T-008-11 — Diseño sin desplazamiento horizontal en escritorio y celular

- **Cubre:** AC-008-21
- **App / capa:** `dispute_agent` / `infrastructure/inbound`
- **Depende de:** T-008-05
- **Archivos:** `src/dispute_agent/infrastructure/inbound/web/static/styles.css`, `src/dispute_agent/infrastructure/inbound/web/static/index.html`, `tests/e2e/web/test_chat_page_responsive.py`
- **Test primero:** `tests/e2e/web/test_chat_page_responsive.py::test_ac_008_21_chat_page__viewport__no_horizontal_scroll_and_input_visible` (parametrizado: 1280×800, 360×740, 740×360)
- **Red:** sin `<meta name="viewport">` ni diseño fluido, en 360×740 `scrollWidth > innerWidth` o la caja de texto queda fuera del viewport.
- **Green:**
  - `<meta name="viewport" content="width=device-width, initial-scale=1">`.
  - Columna fluida (`max-width` + `width: 100%`), `box-sizing: border-box` y log desplazable en vertical.
  - Formulario fijo al pie y visible en 740×360.
- **Refactor:** —

### [x] T-008-12 — Uso solo con teclado y anuncio por lector de pantalla

- **Cubre:** AC-008-22, AC-008-23
- **App / capa:** `dispute_agent` / `infrastructure/inbound`
- **Depende de:** T-008-08
- **Archivos:** `src/dispute_agent/infrastructure/inbound/web/static/chat.js`, `src/dispute_agent/infrastructure/inbound/web/static/index.html`, `src/dispute_agent/infrastructure/inbound/web/static/styles.css`, `tests/e2e/web/test_chat_page_accessibility.py`
- **Test primero:** `tests/e2e/web/test_chat_page_accessibility.py::test_ac_008_22_chat_page__keyboard_only` (parametrizado, 5 filas) y `test_ac_008_23_chat_page__screen_reader__live_region_and_authors`
- **Red:** tras recibir la respuesta, el foco no vuelve a la caja de texto. Tras el cierre, Tab no llega a `Iniciar una conversación nueva`, o Enter sobre él no reinicia.
- **Green:**
  - Devolver el foco a la caja tras cada respuesta del agente.
  - Orden de tabulación natural; botón nativo `<button>` para la conversación nueva.
  - Foco visible en CSS.
  - Avisos dentro de la región `aria-live="polite"`.
  - Prefijos accesibles `Tú` / `Agente` en cada burbuja.
- **Refactor:** —

### [x] T-008-13 — Todos los textos fijos en español en cada estado

- **Cubre:** AC-008-24
- **App / capa:** `dispute_agent` / `infrastructure/inbound`
- **Depende de:** T-008-09, T-008-11, T-008-12
- **Archivos:** `tests/e2e/web/test_chat_page_language.py`
- **Test primero:** `tests/e2e/web/test_chat_page_language.py::test_ac_008_24_chat_page__every_state__fixed_texts_in_spanish` (parametrizado por estado: inicio, esperando, cerrada por derivación, aviso de servicio no disponible, sin conexión, demora, conversación no disponible, contador)
- **Red:**
  - Escribir primero la prueba con el conjunto de textos de §7.2.
  - Debe fallar si algún texto fijo visible o accesible, fuera de las burbujas de conversación, no pertenece a ese conjunto (p. ej. `aria-label` en inglés o un `title` por defecto).
  - Si pasa a la primera, se documenta como prueba de caracterización y se verifica su rojo forzando un texto ajeno en una copia local.
- **Green:** si falla, corregir en los estáticos el texto ajeno a §7.2; la corrección mínima se añade a Archivos.
- **Refactor:** —

### [x] T-008-14 — Verificación final

- **Cubre:** Definition of Done (constitución §5.5) para AC-008-01 a AC-008-25
- **App / capa:** — / verificación
- **Depende de:** T-008-01, T-008-02, T-008-03, T-008-04, T-008-05, T-008-06, T-008-07, T-008-08, T-008-09, T-008-10, T-008-11, T-008-12, T-008-13
- **Archivos:** — (sin cambios; solo ejecución)
- **Test primero:** `uv run pytest --cov` (suite completa, incluidas las pruebas `browser`)
- **Red:** —
- **Green:** pasan `uv run pytest --cov` (cobertura global ≥ 80 % y `domain` + `application` ≥ 90 %), `uv run ruff check .`, `uv run ruff format --check .` y `uv run mypy --strict src`.
- **Refactor:** —

### [x] T-008-15 — Corregir hallazgos H-01 a H-06 de la auditoría de AC (fase 1)

- **Cubre:** AC-008-03, AC-008-10, AC-008-16, AC-008-17, AC-008-18, AC-008-22 (fidelidad de citas y aserciones; sin cambios de comportamiento)
- **App / capa:** `dispute_agent` / tests
- **Depende de:** T-008-14
- **Archivos:** `tests/e2e/web/test_chat_page_failures.py`, `tests/e2e/web/test_chat_page_input.py`, `tests/e2e/web/test_chat_page_messaging.py`, `tests/e2e/web/test_chat_page_harness.py`, `tests/e2e/web/test_chat_page_accessibility.py`, `tests/integration/dispute_agent/web/test_chat_js_html_guard.py`, `tests/integration/dispute_agent/web/test_chat_js_storage_guard.py`
- **Test primero:** `tests/e2e/web/test_chat_page_messaging.py::test_ac_008_10_chat_page__after_turn__only_textbox_and_send_controls` (H-04: la aserción de peticiones se añade antes de cualquier otro cambio)
- **Red:** H-04: la aserción nueva «todas las peticiones a `/api/` fueron `POST /api/chat`» debe poder fallar si la página llamara a otro endpoint; se verifica el rojo forzando una petición ajena en una copia local y restaurando.
- **Green:**
  - **H-01:** en `test_chat_page_failures.py` (~línea 140), citar `Regla: RN-008-16 (b) — a los 60 s sin respuesta se corta la espera y se descarta la respuesta tardía` y `Regla: RN-008-17 — Reintentar reenvía el mismo texto sin duplicar la burbuja`.
  - **H-02:** en `test_chat_page_failures.py` (~línea 75), citar tres líneas: `RN-008-16 (a)` aviso sin conexión, `RN-008-17` reintento al mismo `conversation_id`, `RN-008-18` la caja no envía mientras el aviso está visible, cada una con su enunciado fiel.
  - **H-03:** en `test_chat_page_input.py` (~líneas 98-99), citar `AC-008-22` (no `AC-008-03`) en el test de Enter y Shift+Enter.
  - **H-04:** en `test_chat_page_messaging.py` (~líneas 52-75), registrar con `page.on("request")` las peticiones a `/api/` y afirmar que solo son `("POST", "/api/chat")`. Comprobar además que ningún control ni enlace menciona disputa, bloqueo, analista ni transacción.
  - **H-05:** en `test_chat_page_harness.py`, quitar la cita a `AC-008-01` y dejar solo el artículo que corresponda al arnés, sin pretender cobertura de un AC.
  - **H-06:** renombrar con tres segmentos `test_<tool>__<condición>__<resultado>` los tests `test_ac_008_22_chat_page__keyboard_only`, `test_ac_008_04_chat_page__trim_and_length_limit`, `test_ac_008_07_chat_js__no_html_injection_apis` y `test_ac_008_13_chat_js__no_browser_storage_apis`.
  - Sin cambios en `src/`.
- **Refactor:** —

## Matriz de trazabilidad

| AC | Tareas | Tests |
|---|---|---|
| AC-008-01 | T-008-03 | `test_ac_008_01_chat_page__loaded__agent_greets_and_input_enabled` |
| AC-008-02 | T-008-04 | `test_ac_008_02_chat_page__two_turns__ordered_and_conversation_id_reused` |
| AC-008-03 | T-008-06 | `test_ac_008_03_chat_page__blank_message__not_sent` |
| AC-008-04 | T-008-06 | `test_ac_008_04_chat_page__trim_and_length_limit__enforced` |
| AC-008-05 | T-008-07 | `test_ac_008_05_chat_page__awaiting_reply__indicator_and_input_locked` |
| AC-008-06 | T-008-07 | `test_ac_008_06_chat_page__double_submit__single_request` |
| AC-008-07 | T-008-05 | `test_ac_008_07_chat_page__customer_markup__shown_as_text`, `test_ac_008_07_chat_js__no_html_injection_apis__none_used` |
| AC-008-08 | T-008-05 | `test_ac_008_08_chat_page__agent_markup__shown_as_text` |
| AC-008-09 | T-008-03 | `test_ac_008_09_chat_page__not_identified__no_account_data_nor_api_calls` |
| AC-008-10 | T-008-04 | `test_ac_008_10_chat_page__after_turn__only_textbox_and_send_controls` |
| AC-008-11 | T-008-04 | `test_ac_008_11_chat_page__reply_with_outcomes__only_reply_shown` |
| AC-008-12 | T-008-10 | `test_ac_008_12_chat_page__reload__starts_new_conversation` |
| AC-008-13 | T-008-10 | `test_ac_008_13_chat_page__reopen__no_browser_storage`, `test_ac_008_13_chat_js__no_browser_storage_apis__none_used` |
| AC-008-14 | T-008-08 | `test_ac_008_14_chat_page__escalated__conversation_closed` |
| AC-008-15 | T-008-08 | `test_ac_008_15_chat_page__new_conversation__resets_state` |
| AC-008-16 | T-008-09 | `test_ac_008_16_chat_page__service_unavailable__notice_and_retry` |
| AC-008-17 | T-008-09 | `test_ac_008_17_chat_page__offline__notice_keeps_messages_and_retries` |
| AC-008-18 | T-008-09 | `test_ac_008_18_chat_page__slow_reply__timeout_at_60s` |
| AC-008-19 | T-008-08 | `test_ac_008_19_chat_page__agent_failure_reply__shown_and_closed` |
| AC-008-20 | T-008-08 | `test_ac_008_20_chat_page__404__unavailable_notice_without_retry` |
| AC-008-21 | T-008-11 | `test_ac_008_21_chat_page__viewport__no_horizontal_scroll_and_input_visible` |
| AC-008-22 | T-008-12 | `test_ac_008_22_chat_page__keyboard_only__all_actions_work`, `test_ac_008_22_chat_page__enter_sends_and_shift_enter_inserts_line_break` |
| AC-008-23 | T-008-12 | `test_ac_008_23_chat_page__screen_reader__live_region_and_authors` |
| AC-008-24 | T-008-13 | `test_ac_008_24_chat_page__every_state__fixed_texts_in_spanish` |
| AC-008-25 | T-008-02 | `test_ac_008_25_chat_page__get_root_and_static__served_by_agent_app` |

---

## Cierre de la feature

Definition of Done según constitución §5.5:

- [x] Todos los AC trazados a tests en verde.
- [x] Umbrales de cobertura cumplidos.
- [x] Lint, formato y tipado sin errores.
- [x] Spec actualizada al comportamiento implementado.
- [x] Sin secretos ni datos reales.
