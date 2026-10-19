# Plan: Conversar con el agente de disputas desde una página de chat

| Campo | Valor |
|---|---|
| Feature | `008-chat-web-page` |
| Versión | 0.1.0 |
| Estado | Aprobado |
| Fecha | 2026-10-18 |
| Spec | [spec.md](./spec.md) — versión 0.1.0 aprobada |
| Tareas | [tasks.md](./tasks.md) |

---

## 1. Resumen técnico

La página es un adaptador de entrada más de `dispute_agent`. Tres archivos estáticos (`index.html`, `styles.css`, `chat.js`) viven en `infrastructure/inbound/web/static/`, como fija la constitución (§3.6). Un router nuevo sirve `GET /` (el `index.html`) y un montaje de `StaticFiles` sirve `/static/*`. El cableado se hace en `main.py`. `POST /api/chat`, el caso de uso, el dominio y el servidor MCP **no cambian**.

`chat.js` es JavaScript vanilla, sin dependencias ni paso de compilación:

- Guarda el estado en memoria (`conversationId`, cola de mensajes, `pending`, `closed`) y nunca toca `localStorage`, `sessionStorage`, IndexedDB ni cookies (RN-008-12).
- Pinta cada mensaje con `document.createElement` + `textContent`, nunca con `innerHTML` (RN-008-09).
- Hace un único `fetch` en curso, protegido por la bandera `pending` (RN-008-07).
- Corta la espera a los 60 s con un `AbortController` disparado por `setTimeout`, no con `AbortSignal.timeout`, para que el reloj falso de Playwright lo controle (RN-008-16 b).
- Valida que la respuesta `200` sea JSON con `reply: string` y `status ∈ {ACTIVE, ESCALATED}` (RN-008-16 c).
- Clasifica cada fallo en una de cuatro ramas: sin conexión, demora, servicio no disponible o `404`.
- Toma todos los textos fijos de §7.2 de un único objeto `TEXTS` al inicio del archivo.

Accesibilidad:

- La conversación es un contenedor `role="log"` con `aria-live="polite"`.
- Cada burbuja empieza con un `span` visualmente oculto (`Tú: ` / `Agente: `).
- La caja de texto es un `<textarea maxlength="2000">` con `<label>`.
- Los avisos se muestran dentro de la región viva.
- `white-space: pre-wrap` y `overflow-wrap: anywhere` evitan el desplazamiento horizontal.

Pruebas:

- **Navegador:** pruebas e2e con Playwright (Chromium) en la suite por defecto (clarificación de la spec). Un fixture levanta la app real (`create_app` con `FakeLLM` y `FakeBankingTools`) con Uvicorn en un hilo y un puerto libre. La página se carga desde esa app.
- **Guion de `POST /api/chat`:** las respuestas se fijan con `page.route`: código, cuerpo, demora o corte de red. Así cada AC es determinista y no depende del LLM ni del MCP.
- **Tiempo:** el tiempo límite se prueba con `page.clock`, sin esperar 60 s reales.
- **Sin conexión:** se simula con `context.set_offline(True)`.
- **Servidor:** un test de integración con `TestClient` cubre que la app sirve la página y sus recursos.
- **Guardas estáticas:** unos tests baratos sobre `chat.js` verifican que no aparecen `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `eval`, `localStorage`, `sessionStorage`, `indexedDB` ni `document.cookie`.

## 2. Componentes por capa

| App | Capa | Componente | Nuevo / Modificado | Cambio |
|---|---|---|---|---|
| `dispute_agent` | `infrastructure/inbound` | `web/static/index.html` | Nuevo | Estructura semántica de la página: `lang="es"`, título y encabezado de §7.2, `role="log"` + `aria-live="polite"`, `<label>` + `<textarea maxlength="2000">`, botón `Enviar`, zona de avisos, botones `Reintentar` e `Iniciar una conversación nueva` ocultos al inicio. Carga `/static/styles.css` y `/static/chat.js`. |
| `dispute_agent` | `infrastructure/inbound` | `web/static/styles.css` | Nuevo | Diseño fluido de una columna, sin anchos fijos mayores que la pantalla. Burbujas con `white-space: pre-wrap` y `overflow-wrap: anywhere`. Clase `.visually-hidden`. Foco visible. Estilo de mensaje `No enviado`. |
| `dispute_agent` | `infrastructure/inbound` | `web/static/chat.js` | Nuevo | Toda la lógica de la página: saludo, envío, recorte, contador, guarda de doble envío, indicador, pintado como texto, cierre, conversación nueva, avisos, reintento y foco. Sin dependencias ni almacenamiento del navegador. |
| `dispute_agent` | `infrastructure/inbound` | `web/page_router.py` | Nuevo | `build_page_router() -> APIRouter` con `GET /` → `FileResponse(index.html, media_type="text/html")`, y `static_files() -> StaticFiles` sobre el directorio `static/`. La ruta del directorio se resuelve con `Path(__file__)`. |
| `dispute_agent` | — (arranque) | `main.py` | Modificado | `create_app` incluye `build_page_router()` y monta `static_files()` en `/static`. Sin otros cambios. |
| — | — | `pyproject.toml` / `uv.lock` | Modificado | Dependencias de desarrollo nuevas (§5). Marcador `browser` registrado (no excluido por defecto) para poder ejecutar solo estas pruebas con `-m browser`. |

No hay cambios en `domain`, `application` ni `infrastructure/outbound`, ni en `core_banking_mcp`.

## 3. Puertos y adaptadores

| Puerto | Nuevo / Modificado | Adaptador(es) | Notas |
|---|---|---|---|
| — | — | Página de chat (`page_router.py` + estáticos) | Adaptador de entrada nuevo. No usa puertos de la aplicación: solo sirve archivos. La página habla con el adaptador HTTP existente (`chat_router.py`) por `POST /api/chat`. No se crean ni modifican puertos (§3.3). |

## 4. Modelo de datos

### Dominio

No aplica: la feature no toca el dominio.

### Persistencia (`core_banking_mcp`)

No aplica.

### Semillas

No aplica: las pruebas de navegador usan respuestas guionizadas de `POST /api/chat`. Los textos de ejemplo de los AC (p. ej. `**** 4321`, `D-1001`) son ficticios y se definen en los tests y en `tests/fakes/` (Art. 1).

**Estado de la página (en memoria, `chat.js`):**

| Campo | Tipo | Invariantes |
|---|---|---|
| `conversationId` | `string \| null` | `null` al cargar y tras una conversación nueva. Solo se fija con una respuesta `200` válida. |
| `pending` | `boolean` | Como máximo un `fetch` en curso. Mientras es `true`, la página ignora cualquier envío. |
| `failedText` | `string \| null` | Mensaje pendiente de reintento. Mientras no es `null`, los envíos nuevos están bloqueados (RN-008-18). |
| `closed` | `boolean` | `true` tras `ESCALATED` o `404`. Con `closed`, la caja de texto y `Enviar` quedan deshabilitados. |

## 5. Dependencias nuevas

| Paquete | Versión | Justificación | Alternativa descartada |
|---|---|---|---|
| `pytest-playwright` (grupo `dev`) | `>=0.5,<1` | Integra Playwright con pytest (fixtures `page`, `context`, `browser`). Es necesario para verificar en un navegador real el escapado, el foco, el doble envío, la falta de conexión, el tiempo límite y los tamaños de pantalla, como decidió la clarificación de la spec. | Solo `TestClient` + aserciones sobre el HTML/JS: no verifica el comportamiento real (descartado en la clarificación). Selenium: requiere un driver aparte y no tiene red interceptable ni reloj falso integrados. |
| `playwright` (grupo `dev`, transitivo de la anterior, fijado) | `>=1.48,<2` | Aporta `page.route` (respuestas guionizadas), `page.clock` (tiempo límite de 60 s sin esperar; desde 1.45) y `context.set_offline`. Requiere instalar Chromium una vez: `uv run playwright install chromium`. | jsdom/Node: queda fuera del stack (§2) y no reproduce el diseño ni el foco reales. |

Ninguna dependencia nueva de producción.

**Recursos estáticos de diseño (sin cambio de comportamiento).** `static/fonts/` aloja tres archivos `woff2` autoalojados, con licencia SIL OFL 1.1 (fuente: paquetes `@fontsource-variable`): `newsreader-latin-wght-normal.woff2` y `newsreader-latin-wght-italic.woff2` (voz del agente y título) e `public-sans-latin-wght-normal.woff2` (interfaz). Se sirven con el montaje existente de `StaticFiles`; no hay CDN ni petición a terceros, y cada `@font-face` usa `font-display: swap` con fuentes del sistema como respaldo. No cambian el DOM, los textos ni `chat.js`.

## 6. Estrategia de pruebas

**Ubicación:**

- Pruebas de navegador: `tests/e2e/web/`. Su fixture está en `tests/e2e/web/conftest.py`: app real en Uvicorn en un hilo, puerto libre, `FakeLLM` y `FakeBankingTools`, sin subproceso MCP.
- Guion de `POST /api/chat`: un ayudante en `tests/fakes/chat_api_script.py` (`ChatApiScript`) encola respuestas `(status, body, delay, abort)`, registra cada petición (método, URL, cuerpo JSON) y se instala con `page.route("**/api/chat", ...)`.
- Pruebas de servidor y guardas estáticas: `tests/integration/dispute_agent/web/`.
- Nombres: `test_chat_page__<condición>__<resultado>`, con comentario de trazabilidad `Regla: RN-008-XX` / `AC-008-XX · Art. N` (`mcp-testing.md` §3–4).

**Sin navegador instalado:** el fixture de sesión falla con un mensaje claro (`uv run playwright install chromium`). No omite las pruebas, porque una omisión dejaría AC sin verificar en silencio.

| AC | Unit | Integración | Contrato | E2E |
|---|---|---|---|---|
| AC-008-01 | — | — | — | Al cargar: un solo mensaje del `Agente` con el saludo de §7.2; `ChatApiScript` sin peticiones; caja habilitada y vacía. |
| AC-008-02 | — | — | — | Dos turnos guionizados: orden y autor de las 5 burbujas; la 1.ª petición sin `conversation_id`; la 2.ª con `conv-1`; todas las peticiones de la página a la API son `POST /api/chat`. |
| AC-008-03 | — | — | — | Parametrizado (3 filas × Enter/`Enviar`): sin peticiones y sin burbujas nuevas. |
| AC-008-04 | — | — | — | Parametrizado (5 filas): recorte en la petición y en la burbuja; contador oculto con 1799 caracteres y `Quedan 200 caracteres` con 1800; pegado de 2001 → 2000 y `Quedan 0 caracteres`; petición de 2000 caracteres completa. |
| AC-008-05 | — | — | — | Respuesta con demora: indicador visible; otro Enter o clic sin petición nueva; al llegar la respuesta, indicador oculto y caja habilitada. |
| AC-008-06 | — | — | — | Parametrizado (3 filas: doble clic, Enter×2, Enter+clic): una sola petición y una sola burbuja. |
| AC-008-07 | — | Guarda estática: `chat.js` no usa `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write` ni `eval`. | — | Parametrizado (3 textos): `textContent` exacto; ningún `b`/`script` en el log; ningún evento `dialog`. |
| AC-008-08 | — | (misma guarda estática) | — | Parametrizado (3 textos del agente): `textContent` exacto con saltos de línea; ningún `img`/`a` en el log; ningún `dialog`. |
| AC-008-09 | — | — | — | Al cargar: las peticiones registradas por `page.on("request")` son solo `GET /` y `/static/*`; el texto visible es solo el de §7.2. |
| AC-008-10 | — | — | — | Tras un turno: los únicos controles habilitados son la caja y `Enviar`; ningún control ni enlace menciona disputa, bloque*, analista ni transacci*; todas las peticiones a la API son `POST /api/chat`. |
| AC-008-11 | — | — | — | Respuesta con `outcomes` (`RN-007-14`, `E-9`, `**** 4321`): la burbuja muestra exactamente el `reply`; el texto de la página no contiene `RN-007-14`, `E-9` ni `conv-1`. |
| AC-008-12 | — | — | — | Conversación, `page.reload()`: solo el saludo; la siguiente petición va sin `conversation_id`. |
| AC-008-13 | — | Guarda estática: `chat.js` no usa `localStorage`, `sessionStorage`, `indexedDB` ni `document.cookie`. | — | Antes de cerrar y tras reabrir otra página en el mismo `context`: `localStorage.length == 0`, `sessionStorage.length == 0`, `indexedDB.databases()` vacío, `context.cookies()` vacío; solo el saludo. |
| AC-008-14 | — | — | — | `status = "ESCALATED"`: `reply` + aviso de derivación; caja y `Enviar` deshabilitados; botón `Iniciar una conversación nueva` visible. |
| AC-008-15 | — | — | — | Parametrizado (`ESCALATED`, `404`): al pulsar el botón, solo el saludo, caja habilitada y con foco; siguiente petición sin `conversation_id`. |
| AC-008-16 | — | — | — | Parametrizado (5 filas: 500 con cuerpo, 503, 422, 200 no JSON, 200 sin `reply`): aviso de servicio no disponible; el texto no contiene el código, `Error`, `Exception`, `Traceback` ni el cuerpo; mensaje marcado `No enviado`; `Reintentar` repite el mismo cuerpo y la respuesta aparece; una sola burbuja del mensaje. |
| AC-008-17 | — | — | — | `context.set_offline(True)` y envío: aviso de sin conexión; mensajes conservados; Enter con otro texto no hace petición; `set_offline(False)` + `Reintentar` → `{"conversation_id": "conv-1", "message": "¿Sigues ahí?"}` y respuesta debajo. |
| AC-008-18 | — | — | — | `page.clock.install()` + respuesta retenida en `page.route`. Fila 59 s: `clock.run_for(59_000)`, se libera la respuesta → se muestra, sin aviso. Fila 61 s: `run_for(60_000)` → aviso de demora, `Reintentar`, sin indicador; se libera tarde → no se muestra. `Reintentar` → una sola respuesta. |
| AC-008-19 | — | — | — | `ESCALATED` con el texto de `LLM_FAILURE`: burbuja exacta; sin `LLM_FAILURE` en la página; cierre como en AC-008-14. |
| AC-008-20 | — | — | — | `404`: aviso de conversación no disponible sin `404`; caja deshabilitada; botón de conversación nueva; sin `Reintentar`; sin más peticiones. |
| AC-008-21 | — | — | — | Parametrizado (1280×800, 360×740, 740×360): respuesta de 600 caracteres con una palabra de 80; `document.documentElement.scrollWidth <= window.innerWidth`; caja y `Enviar` en el viewport; se envía un mensaje. |
| AC-008-22 | — | — | — | Parametrizado (5 filas): Tab desde el inicio → foco en la caja; Enter envía; Shift+Enter → cuerpo `hola\nmundo` en una sola petición; foco en la caja tras la respuesta; tras `ESCALATED`, Tab llega a `Iniciar una conversación nueva` y Enter reinicia. |
| AC-008-23 | — | — | — | El contenedor del log tiene `aria-live="polite"` y contiene los mensajes y avisos; el nombre accesible de cada burbuja empieza por `Tú`/`Agente`; `get_by_label("Escribe tu mensaje")` localiza la caja. |
| AC-008-24 | — | — | — | `lang="es"`; en cada estado (inicio, esperando, cerrada, cada aviso), cada texto fijo visible o accesible fuera de las burbujas de conversación pertenece al conjunto de §7.2 (con `Quedan N caracteres` como patrón). |
| AC-008-25 | — | `TestClient(create_app(...))`: `GET /` → `200`, `text/html`, contiene `chat.js`; `GET /static/chat.js` y `GET /static/styles.css` → `200`; los tests de AC-007-31 siguen en verde. | — | — |

No hay filas `DP-` ni casos de escalamiento en la spec (§5 y §8 "No aplica"). Tampoco hay invariantes nuevos de Art. 7 ni de límite del loop: los cubre la spec 007 y no cambian.

**Cobertura:** el único código Python nuevo es `page_router.py`, cubierto por los tests de integración de AC-008-25. `domain` y `application` no cambian, así que se mantienen ≥ 90 %. La cobertura de `pytest-cov` no mide JavaScript; el comportamiento de `chat.js` lo verifican AC por AC las pruebas e2e.

## 7. Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Chromium no instalado en el equipo o en CI: las pruebas de navegador fallan. | Alto | El fixture de sesión falla con un mensaje que indica `uv run playwright install chromium`. El comando se documenta en el `README.md`/`CLAUDE.md` en la tarea de cierre. Con el marcador `browser`, estas pruebas se pueden ejecutar o diagnosticar aparte. |
| Pruebas de navegador inestables por esperas reales o por carreras. | Alto | Las respuestas se guionizan con `page.route`; el tiempo se controla con `page.clock`; los `expect` de Playwright esperan con reintento; no hay `sleep`. Cada test usa una página nueva (`function` scope) y solo comparte el servidor (`session` scope). |
| El API síncrona de Playwright choca con el bucle de `pytest-asyncio` (`asyncio_mode = "auto"`). | Medio | Las pruebas de navegador son funciones síncronas (no `async def`). Uvicorn corre en un hilo con su propio bucle. Si hay conflicto, se aísla con un `conftest.py` propio en `tests/e2e/web/`. |
| `AbortSignal.timeout` o `fetch` no obedecen al reloj falso, y AC-008-18 no es determinista. | Medio | El tiempo límite usa `setTimeout` + `AbortController`, que `page.clock` controla. La respuesta tardía se retiene en el manejador de la ruta hasta que el test la libera. |
| Una respuesta tardía (tras el aviso de demora) se pinta igualmente. | Medio | Cada envío lleva un identificador de intento; `chat.js` descarta respuestas de intentos abortados o anteriores. Lo verifica la fila de 61 s de AC-008-18. |
| Un desarrollador futuro introduce `innerHTML` o almacenamiento del navegador. | Medio | Guardas estáticas en la suite (AC-008-07/08/13) además de las pruebas de comportamiento. |
| Los estáticos no se empaquetan en el wheel. | Bajo | Hatch incluye los archivos no Python dentro de `src/dispute_agent`. El test de AC-008-25 los resuelve con `Path(__file__)`, igual que en producción. |
| El hook `check_mcp_boundaries.py` interpreta como violación los archivos nuevos en `inbound/web`. | Bajo | `page_router.py` solo importa FastAPI/Starlette y `pathlib`; no importa `core_banking_mcp` ni el dominio. |

## 8. Cumplimiento de la constitución

| Artículo | Estado | Justificación |
|---|---|---|
| Art. 1 — Datos ficticios | Cumple | No se añaden semillas. Los textos de prueba (`**** 4321`, `D-1001`, `conv-1`) son sintéticos y viven en tests y fakes. |
| Art. 2 — Spec-anchored | Cumple | Spec 008 v0.1.0 aprobada; cada AC-008-XX tiene prueba asignada (§6) y los tests lo citan. |
| Art. 3 — TDD | Cumple | Cada tarea empieza por su prueba e2e o de integración en rojo (página o ruta inexistente) antes de crear el estático o el router. |
| Art. 4 — Arquitectura hexagonal | Cumple | Todo lo nuevo está en `infrastructure/inbound/web`; el cableado se hace en `main.py`; `domain` y `application` no cambian. |
| Art. 5 — El dominio decide | Cumple | La página no decide ni ofrece acciones (RN-008-01; AC-008-10): solo envía texto y muestra `reply`. |
| Art. 6 — Acciones vía MCP | Cumple | La página solo llama a `POST /api/chat`; el agente sigue siendo el único que habla con el core, por MCP (AC-008-02, AC-008-09, AC-008-10). |
| Art. 7 — Identificación antes que información | Cumple | La página no consulta ni muestra datos por su cuenta (AC-008-09), no deshace enmascarados (AC-008-11), muestra todo como texto (AC-008-07/08) y no guarda nada en el navegador (AC-008-12/13). La verificación sigue en el agente (spec 007). |
| Art. 8 — Auditoría | N.A. | La página no ejecuta decisiones ni llamadas a herramientas: la auditoría la hace el agente en cada `POST /api/chat` (spec 007, RN-007-28). Servir estáticos no es un evento auditable según el Art. 8. |
| Art. 9 — Secretos | Cumple | La página no maneja credenciales; `ANTHROPIC_API_KEY` sigue solo en el servidor (`.env`). Nada sensible en los estáticos. |
| Art. 10 — Ante la duda, escalar | N.A. | La página no decide disputas. Ante fallas no actúa por su cuenta: informa y permite reintentar (RN-008-16/17). La derivación la sigue decidiendo el agente. |

---

## Gate de salida

- [x] Todos los AC de la spec tienen estrategia de prueba asignada.
- [x] Ningún artículo de la constitución queda incumplido sin justificación.
- [x] Dependencias nuevas justificadas o "Ninguna".
- [x] Estado cambiado a **Aprobado**.
