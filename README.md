# Agente de Disputas — Banco Andino

Agente de IA que atiende **disputas y contracargos de tarjeta por chat web**. Banco Andino es **ficticio**: todos los datos son sintéticos y salen de semillas reproducibles.

Objetivos: resolver en primer contacto, escalar correctamente (cero casos auto-resueltos que debían escalarse), trazabilidad total, seguridad del cliente y respuestas claras en español.
Fuera de alcance: bancos o pasarelas reales, dinero real y bandeja de analistas.

La fuente de verdad del proyecto es [`docs/constitution.md`](docs/constitution.md). Metodología: **Spec-Driven Development (SDD)** con TDD.

## Contenido

1. [Specs implementadas](#specs-implementadas)
2. [Stack](#stack)
3. [Arquitectura](#arquitectura)
4. [Herramientas MCP](#herramientas-mcp)
5. [Configuración](#configuración)
6. [Comandos](#comandos)
7. [Datos de prueba para pruebas manuales](#datos-de-prueba-para-pruebas-manuales)
8. [Estado y notas](#estado-y-notas)

## Specs implementadas

| Spec | Meta |
|---|---|
| 001-customer-search | Buscar cliente por documento, nombre o últimos 4 de tarjeta (`buscar_cliente`) |
| 002-identity-verification | Verificar identidad con fecha de nacimiento y de expedición del documento (`verificar_identidad`) |
| 003-card-transactions | Consultar transacciones de una tarjeta por rango de fechas (`consultar_transacciones`) |
| 004-open-dispute | Abrir una disputa sobre una transacción (`iniciar_disputa`) |
| 005-card-block | Bloquear una tarjeta por sospecha de fraude (`bloquear_tarjeta`) |
| 006-analyst-escalation | Derivar un caso a un analista con resumen estructurado (`escalar_a_analista`) |
| 007-dispute-resolution-agent | Agente que resuelve en primer contacto y escala cuando corresponde (`POST /api/chat`, `DisputePolicy`) |

## Stack

Python 3.12 · uv · FastAPI + Uvicorn · Pydantic v2 / pydantic-settings · SDK `anthropic` (loop de tool use propio) · MCP con FastMCP (transporte **stdio**) · SQLite + SQLAlchemy 2 · ruff · mypy `--strict` · pytest (+asyncio, cov) · httpx.

## Arquitectura

Dos aplicaciones hexagonales independientes que **solo se comunican por MCP**:

```
Chat web ──HTTP──▶ dispute_agent (FastAPI)
                    ├─ loop LLM ──▶ API de Anthropic
                    ├─ DisputePolicy (decide RESOLVE / REJECT / ESCALATE)
                    └─ MCP stdio ──▶ core_banking_mcp (tools) ──▶ SQLite
```

- **Capas:** `domain` (solo stdlib) ← `application` (casos de uso y puertos `Protocol`) ← `infrastructure/inbound` e `infrastructure/outbound`. El cableado ocurre solo en `main.py` y `server.py`.
- **El dominio decide, el LLM conversa:** `DisputePolicy` determina la acción; solo se ejecutan las acciones permitidas. Si el loop supera `LLM_MAX_ITERATIONS`, se escala.
- **Identificación antes que información** y **ante la duda, escalar**.
- Prohibido importar código entre `core_banking_mcp` y `dispute_agent`; el contrato compartido son los esquemas MCP (tests de contrato).
- Auditoría de cada acción; logging JSON con `conversation_id`. El PAN completo nunca aparece en respuestas.

Estructura:

```
src/core_banking_mcp/   domain/ application/ infrastructure/{inbound/mcp,outbound/...} server.py
src/dispute_agent/      domain/ application/ infrastructure/{inbound/web/api,outbound/...} main.py
tests/                  unit/ integration/ contract/ e2e/ fakes/
specs/NNN-feature/      spec.md → plan.md → tasks.md
docs/                   constitution.md, mcp-inspector.md
.claude/                rules/, hooks/, skills/, agents/
```

Flujo SDD: Specify → Plan → Tasks → Implement, con aprobación en cada fase; los criterios de aceptación llevan ID `AC-NNN-XX` y los tests los citan. Los hooks `check_mcp_boundaries.py` (fronteras de capas) y `ac_coverage_gate.py` (trazabilidad antes del PR) lo hacen cumplir. Precedencia: constitución > rules > spec > plan > tasks > código.

## Herramientas MCP

Todas exigen `conversation_id`; las de acción exigen `idempotency_key` (1-64 caracteres). Error: `{code, message, retryable}` con `isError=true`. Códigos: `INVALID_INPUT`, `IDENTITY_NOT_VERIFIED`, `NOT_FOUND`, `TRANSACTION_NOT_DISPUTABLE`, `DISPUTE_ALREADY_OPEN`, `CARD_NOT_BLOCKABLE`, `INTERNAL`.

| Tool | Entradas clave | Salida |
|---|---|---|
| `buscar_cliente` | `document`, `full_name`, `card_last4` (≥1 criterio, AND) | Hasta 5 clientes con datos enmascarados; si hay más, `refinement_required=true` |
| `verificar_identidad` | `customer_id`, `birth_date`, `document_issue_date` | `verified`, `attempts_remaining`, `escalation_required` (3 intentos por conversación) |
| `consultar_transacciones` | `card_last4`, `date_from`, `date_to` (máx. 89 días, no futuro) | Hasta 50 transacciones, recientes primero |
| `iniciar_disputa` | `transaction_id`, `reason` (`UNRECOGNIZED_CHARGE`, `DUPLICATE_CHARGE`, `INCORRECT_AMOUNT`, `NOT_RECEIVED`, `OTHER`) | `dispute_id`, estado `OPEN` |
| `bloquear_tarjeta` | `card_id`, `reason` (`FRAUD_SUSPECTED`, `LOST_OR_STOLEN`) | Estado `BLOCKED`, `already_blocked` |
| `escalar_a_analista` | `reason` (`FRAUD_SUSPECTED`, `AMOUNT_OVER_THRESHOLD`, `INSUFFICIENT_OR_CONTRADICTORY_INFO`, `INCONCLUSIVE_RULES`, `UNRECOVERABLE_SYSTEM_FAILURE`, `IDENTITY_VERIFICATION_FAILED`, `OTHER`), opcionales `transaction_id`, `card_id`, `prior_actions`, `dispute_id`, `note` | `escalation_id`, estado `PENDING`, resumen estructurado |

## Configuración

Copia `.env.example` a `.env`:

| Variable | Valor por defecto | Descripción |
|---|---|---|
| `ANTHROPIC_API_KEY` | (vacía) | Obligatoria para el agente (falla en la primera llamada al LLM si falta) |
| `ANTHROPIC_MODEL` | `claude-sonnet-5-5` | Modelo |
| `LLM_MAX_ITERATIONS` | `8` | Límite del loop de tool use |
| `USD_COP_RATE` | `4000` | Tasa para convertir USD a COP |
| `MCP_CALL_TIMEOUT_SECONDS` | `10` | Timeout por llamada MCP |
| `CORE_DATABASE_URL` | `sqlite:///./data/core_banking.db` (default del código) | Base del core |
| `CORE_SEED_ON_START` | `True` | Siembra si la base está vacía |

`.mcp.json` declara el servidor `core_banking_mcp` (stdio) y el MCP de GitHub, que requiere `GITHUB_PERSONAL_ACCESS_TOKEN`.

## Comandos

Entorno: Windows 11 con PowerShell.

```powershell
uv sync                                                   # instalar dependencias

uv run python -m core_banking_mcp.server                  # servidor MCP por stdio
uv run mcp dev src/core_banking_mcp/server.py             # MCP Inspector (requiere Node/npx; ver docs/mcp-inspector.md)
uv run python -m dispute_agent.main                       # agente en http://127.0.0.1:8000

uv run pytest                                             # suite completa (excluye tests con LLM real)
uv run pytest tests/unit/<ruta>/test_x.py::test_name      # un solo test
uv run pytest -m llm                                      # pruebas con Claude real (opcionales)
uv run pytest --cov                                       # cobertura (mínimo 80 %)
uv run ruff check . ; uv run ruff format --check .
uv run mypy --strict src
```

Al arrancar, el servidor MCP crea el esquema y siembra los datos si la base está vacía. No hay migraciones: si cambia el esquema, borra `data/core_banking.db`.

### Probar el agente por HTTP

```powershell
$body = @{ message = "Hola, desconozco un cargo en mi tarjeta" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/chat -ContentType "application/json" -Body $body
```

Request: `{ "conversation_id": "opcional", "message": "1-2000 caracteres" }`.
Response: `{ conversation_id, reply, status: "ACTIVE" | "ESCALATED", outcomes: [{ kind, transaction_id, masked_card, rule, reason, next_steps, reference }] }`.
Reenvía el `conversation_id` devuelto para continuar la conversación (uno inexistente responde 404). Fallas del LLM o del core responden 200 como derivación.

## Datos de prueba para pruebas manuales

"Hoy" en las pruebas es **2026-10-18** (zona Bogotá, UTC-5).

### Verificación de identidad

No hay PIN ni preguntas de seguridad: se verifica con **fecha de nacimiento** y **fecha de expedición del documento** (AAAA-MM-DD). Hay **3 intentos por conversación**; el tercer fallo bloquea la conversación y escala.

### Clientes

| customer_id | Nombre | Documento | Nacimiento | Expedición | Tarjetas (últimos 4 → estado) |
|---|---|---|---|---|---|
| C-0001 | Laura Méndez | D-1001 | 1990-03-15 | 2008-04-20 | 4321 ACTIVE (`CARD-0001`), 8765 BLOCKED (`CARD-0002`) |
| C-0002 | Pedro Ríos | D-1002 | 1985-07-02 | 2003-08-10 | 1234 ACTIVE (`CARD-0003`) |
| C-0003 | Ana Torres | D-2001 | 1992-11-30 | 2010-12-01 | ninguna |
| C-0004 | Ana Torres | D-2002 | 1988-01-09 | 2006-02-14 | ninguna |
| C-0005 | José Álvarez | D-3001 | 1979-05-21 | 1997-06-30 | ninguna |
| C-0006 | José Álvarez Pérez | D-3002 | 1995-09-12 | 2013-10-05 | ninguna |
| C-0007 | Marta Gil | AB12 | 2000-02-29 | 2018-03-12 | 5555 CANCELLED (`CARD-0004`) |

### Transacciones

Estado `CONFIRMED` salvo indicación. Horas de Bogotá.

| ID | Tarjeta | Fecha y hora | Comercio | Monto | País | Estado | Escenario |
|---|---|---|---|---|---|---|---|
| TX-000001 | 4321 | 2026-09-05 09:15 | Supermercado La Cosecha | 185000.00 COP | CO | CONFIRMED | Resoluble (DP-007-05): disputa abierta automática |
| TX-000002 | 4321 | 2026-09-12 20:40 | StreamFlix Andina | 15.99 USD | US | CONFIRMED | Ya tiene disputa OPEN → `DISPUTE_ALREADY_OPEN` |
| TX-000003 | 4321 | 2026-09-20 14:32 | Aerolínea Cóndor del Sur | 1250000.00 COP | CO | PENDING | No disputable (DP-007-01, REJECT) |
| TX-000004 | 4321 | 2026-09-25 11:05 | Farmacia Vida Plena | 42000.00 COP | CO | REVERSED | No disputable (DP-007-01) |
| TX-000005 | 4321 | 2026-10-02 18:20 | Café Montaña Azul | 12500.00 COP | CO | CONFIRMED | Resoluble, monto bajo |
| TX-000006 | 8765 | 2026-09-18 22:10 | Tienda Online Mercurio | 320000.00 COP | CO | CONFIRMED | Tarjeta BLOCKED; disputa semilla CLOSED |
| TX-000007 | 1234 | 2026-09-08 07:45 | Gasolinera El Páramo | 98000.00 COP | CO | CONFIRMED | Resoluble (Pedro Ríos) |
| TX-000008 | 1234 | 2026-09-22 13:00 | Librería Letras Andinas | 64000.00 COP | CO | CONFIRMED | Disputa semilla REJECTED |
| TX-000009 | 5555 | 2026-08-30 16:30 | Restaurante Fogón Criollo | 75000.00 COP | CO | CONFIRMED | Tarjeta CANCELLED (Marta Gil) |
| TX-000010 | 4321 | 2026-06-01 10:00 | Hotel Pacífico Sur | 300000.00 COP | US | CONFIRMED | Exterior >90 días (DP-007-04) → escala `INCONCLUSIVE_RULES` |
| TX-000011 | 4321 | 2026-10-05 16:45 | Electro Hogar Andes | 800000.00 COP | CO | CONFIRMED | Sobre umbral 500.000 (DP-007-03) → escala `AMOUNT_OVER_THRESHOLD` |

### Disputas semilla

| Clave | Transacción | Motivo | Estado |
|---|---|---|---|
| SEED-1 | TX-000002 | UNRECOGNIZED_CHARGE | OPEN |
| SEED-2 | TX-000006 | NOT_RECEIVED | CLOSED |
| SEED-3 | TX-000008 | INCORRECT_AMOUNT | REJECTED |

Solo una disputa `OPEN` impide abrir otra (únicamente TX-000002).

### Qué probar

| Escenario | Cliente / dato | Resultado esperado |
|---|---|---|
| Resolución feliz | Laura Méndez (D-1001), disputar TX-000001 o TX-000005 | Disputa abierta automáticamente |
| Resolución feliz (otro cliente) | Pedro Ríos (D-1002), TX-000007 | Disputa abierta |
| Monto sobre umbral | Laura, TX-000011 | Escala (`AMOUNT_OVER_THRESHOLD`) |
| Exterior antiguo | Laura, TX-000010 (consultar p. ej. 2026-05-25 a 2026-06-10) | Escala (`INCONCLUSIVE_RULES`) |
| Disputa ya abierta | Laura, TX-000002 | `DISPUTE_ALREADY_OPEN` |
| No disputable | Laura, TX-000003 (PENDING) o TX-000004 (REVERSED) | Rechazo |
| Fraude declarado | Laura, tarjeta 4321 | Bloqueo + disputa + escalamiento (TX-000001/5/7) o bloqueo + escalamiento sin disputa (TX-000003/4/10/11) |
| Tarjeta ya bloqueada | Laura, tarjeta 8765 | `already_blocked` |
| Tarjeta cancelada | Marta Gil, tarjeta 5555 | `CARD_NOT_BLOCKABLE` |
| Homónimos | Buscar "Ana Torres" | 2 coincidencias; pedir documento o tarjeta |
| Nombre exacto | "José Álvarez" → solo C-0005; "José Álvarez Pérez" → solo C-0006 | Sin acentos ni mayúsculas relevantes; no acepta nombres parciales |
| Cliente sin tarjetas | C-0003 a C-0006 | Caso sin productos |
| Identidad fallida | Fechas incorrectas 3 veces | Conversación bloqueada y escalada (`IDENTITY_VERIFICATION_FAILED`) |
| Sin coincidencia | Buscar un cliente inexistente 2 veces | Escala (`INSUFFICIENT_OR_CONTRADICTORY_INFO`) |
| Solicitud de persona | Pedir hablar con un humano | Escalamiento |

Ejemplo de conversación: *"Hola, no reconozco un cargo de StreamFlix"* → el agente pide documento (`D-1001`) → pide fecha de nacimiento (`1990-03-15`) y de expedición (`2008-04-20`) → consulta transacciones de la tarjeta 4321 → (con TX-000001/5) abre la disputa y entrega la referencia.

Para pruebas por MCP Inspector (sin agente) usa `docs/mcp-inspector.md`.

## Estado y notas

- No hay front estático todavía: la interfaz disponible es `POST /api/chat`.
- La spec 007 y `src/dispute_agent` pueden tener cambios sin commitear en la rama de trabajo.
- La guía del Inspector solo cubre `buscar_cliente` y `verificar_identidad`.
- La verificación de identidad y su contador viven en memoria del proceso del servidor MCP; se reinician al reconectar.
- Convenciones: documentación, specs y mensajes al cliente en español; código, identificadores y commits en inglés (los nombres de las tools MCP en español son la excepción).
