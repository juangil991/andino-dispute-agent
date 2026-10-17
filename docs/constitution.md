# Constitución del Proyecto — Agente de Disputas Banco Andino

| Campo | Valor |
|---|---|
| Versión | 1.0.1 |
| Fecha de ratificación | 2026-10-16 |
| Estado | Vigente |
| Metodología | Spec-Driven Development (SDD) puro, sin frameworks de SDD |

Esta constitución fija los principios **no negociables** del proyecto. Toda spec, plan, tarea y línea de código debe cumplirla. Cuando un artefacto la contradiga, prevalece la constitución.

> **Banco Andino es un banco completamente ficticio.** Ningún dato, cliente, tarjeta o transacción de este proyecto corresponde a personas o entidades reales.

---

## 1. Misión

### 1.1 Resumen

Construir un **agente de inteligencia artificial** que atienda a los clientes de Banco Andino cuando reportan **disputas de transacciones** y **solicitudes de contracargo**. El agente conversa con el cliente a través de un chat web, lo identifica, consulta sus transacciones, decide qué hacer con cada transacción disputada y actúa sobre los sistemas del banco exclusivamente mediante **herramientas expuestas por un servidor MCP** que simula el core bancario.

### 1.2 Objetivos

1. **Maximizar la resolución en primer contacto**: resolver automáticamente, dentro de la misma conversación, toda disputa que las reglas de negocio permitan resolver sin intervención humana.
2. **Escalar correctamente**: identificar y derivar a un analista humano los casos que lo requieren (sospecha de fraude, montos sobre umbral, información insuficiente o contradictoria, reglas no concluyentes). **Cero casos resueltos automáticamente que debían escalarse.**
3. **Trazabilidad total**: el 100 % de las decisiones y de las llamadas a herramientas quedan registradas con su motivo, la regla aplicada y el identificador de la conversación.
4. **Seguridad del cliente**: nunca exponer información de una cuenta sin haber identificado al cliente.
5. **Experiencia clara**: respuestas comprensibles, en español, que informen al cliente qué se hizo, por qué y cuáles son los próximos pasos.

### 1.3 Fuera de alcance

- Integración con bancos, redes de tarjetas o pasarelas de pago reales.
- Movimiento de dinero real o uso de datos personales reales.
- Bandeja de trabajo para analistas humanos (el escalamiento se registra en el core simulado; su gestión queda fuera de esta versión).

### 1.4 Principios no negociables (Artículos)

**Art. 1 — Datos ficticios.** Todo dato del sistema es sintético y se genera mediante semillas reproducibles. Está prohibido introducir PII real.

**Art. 2 — Spec primero y viva (spec-anchored).** No se escribe código de producción sin una spec aprobada. Todo cambio de comportamiento actualiza la spec en el mismo cambio. Ver §4.

**Art. 3 — TDD obligatorio.** Ningún código de producción existe sin un test que primero haya fallado. Ver §5.

**Art. 4 — Arquitectura hexagonal.** El dominio no depende de frameworks, bases de datos, LLM ni MCP. Ver §3.

**Art. 5 — El dominio decide, el LLM conversa.** El LLM interpreta al cliente, recolecta datos y redacta respuestas. La decisión sobre cada disputa (resolver, rechazar o escalar) la toma un **motor de reglas determinista en el dominio** (`DisputePolicy`). El LLM no puede saltarse, sobrescribir ni reinterpretar esa decisión.

**Art. 6 — Toda acción sobre el core pasa por MCP.** El agente solo lee o modifica el estado bancario a través de herramientas del servidor MCP. Prohibido el acceso directo a la base de datos del core desde el agente.

**Art. 7 — Identificación antes que información.** Ninguna herramienta que devuelva o modifique datos de un cliente se invoca antes de que `verificar_identidad` haya tenido éxito en la conversación (`buscar_cliente` solo localiza al cliente, no lo autentica). El servidor MCP también lo valida (defensa en profundidad).

**Art. 8 — Auditoría.** Cada llamada a herramienta, cada decisión del motor de reglas y cada escalamiento se registra con: `conversation_id`, marca de tiempo, entrada, salida, regla aplicada y motivo.

**Art. 9 — Secretos y configuración.** Las credenciales (p. ej. `ANTHROPIC_API_KEY`) viven solo en variables de entorno / `.env`, nunca en el repositorio. Se versiona únicamente `.env.example`.

**Art. 10 — Ante la duda, escalar.** Si las reglas no son concluyentes, una herramienta falla de forma no recuperable o el LLM produce una salida inválida, el resultado por defecto es escalar a un humano, nunca resolver.

---

## 2. Tech-stack

| Capa | Tecnología |
|---|---|
| Lenguaje / runtime | Python 3.12 |
| Gestor de dependencias y entornos | uv (`pyproject.toml` + `uv.lock`) |
| API web | FastAPI + Uvicorn |
| Validación y modelos de E/S | Pydantic v2 |
| Configuración | pydantic-settings (lectura de `.env`) |
| LLM | Claude mediante el SDK oficial `anthropic`; el modelo se configura por variable de entorno |
| Orquestación del agente | Loop de *tool use* propio, sin frameworks de agentes |
| Servidor MCP | SDK oficial `mcp` (FastMCP), transporte **stdio** |
| Cliente MCP | SDK oficial `mcp` (cliente stdio; el agente lanza el servidor como subproceso) |
| Persistencia del core simulado | SQLite + SQLAlchemy 2.x, con datos semilla reproducibles |
| Front | HTML + CSS, con JavaScript vanilla mínimo (solo `fetch` para el chat), servido por FastAPI como estáticos |
| Lint y formato | ruff |
| Tipado | mypy en modo estricto |
| Hooks de calidad | pre-commit (ruff + mypy + pytest rápido) |
| Testing | pytest, pytest-asyncio, pytest-cov, `TestClient` de FastAPI / httpx |
| Observabilidad | Logging estructurado en JSON con `conversation_id` como correlation id |

**Convenciones de idioma:** documentación, specs y mensajes al cliente en **español**; código, identificadores, nombres de archivos y commits en **inglés**.

Agregar una dependencia nueva requiere justificarla en el `plan.md` de la feature que la introduce.

---

## 3. Arquitectura

### 3.1 Visión general

El sistema se compone de **dos aplicaciones hexagonales independientes** que solo se comunican mediante el protocolo MCP:

```
┌──────────────┐  HTTP   ┌──────────────────────────────────────┐  MCP/stdio  ┌──────────────────────────┐
│ Chat web     │ ──────▶ │ dispute_agent                        │ ──────────▶ │ core_banking_mcp         │
│ (HTML + CSS) │ ◀────── │ FastAPI · loop LLM · DisputePolicy   │ ◀────────── │ Herramientas MCP · SQLite│
└──────────────┘         └──────────────────────────────────────┘             └──────────────────────────┘
                                         │
                                         ▼
                                  Anthropic API (Claude)
```

- **`dispute_agent`**: expone el chat (API + estáticos), ejecuta el loop del agente con Claude, aplica el motor de reglas del dominio y registra la auditoría.
- **`core_banking_mcp`**: simula el core bancario (clientes, productos, tarjetas, transacciones, disputas, escalamientos) y lo expone como herramientas MCP.

### 3.2 Capas y reglas de dependencia

Cada aplicación sigue puertos y adaptadores:

| Capa | Contenido | Puede depender de |
|---|---|---|
| `domain` | Entidades, value objects, reglas de negocio, `DisputePolicy`, errores de dominio | Solo la librería estándar |
| `application` | Casos de uso y **puertos** (interfaces `Protocol`) | `domain` |
| `infrastructure/inbound` | Adaptadores de entrada: FastAPI (agente), herramientas MCP (core) | `application`, `domain` |
| `infrastructure/outbound` | Adaptadores de salida: Anthropic, cliente MCP, SQLAlchemy, auditoría | `application`, `domain` |

Reglas:

1. Las dependencias apuntan **hacia adentro**. `domain` nunca importa `application` ni `infrastructure`.
2. Prohibido importar código entre `dispute_agent` y `core_banking_mcp`. El contrato compartido son los **esquemas de las herramientas MCP**, versionados en la spec y verificados con tests de contrato.
3. El cableado (inyección de dependencias) ocurre únicamente en los puntos de arranque (`main.py`, `server.py`).
4. Los modelos de SQLAlchemy y de Pydantic no cruzan hacia el dominio: se mapean en el adaptador.

### 3.3 Puertos principales

**dispute_agent**

| Puerto | Responsabilidad | Adaptador por defecto |
|---|---|---|
| `LLMPort` | Enviar mensajes + definiciones de herramientas y recibir respuesta / *tool calls* | `AnthropicLLMAdapter` |
| `BankingToolsPort` | Invocar herramientas del core bancario | `McpStdioBankingAdapter` |
| `ConversationRepository` | Guardar y recuperar el estado de la conversación | En memoria (v1) |
| `AuditLogPort` | Registrar eventos de auditoría | Logger JSON estructurado |

**core_banking_mcp**

| Puerto | Adaptador por defecto |
|---|---|
| `CustomerRepository` | SQLAlchemy / SQLite |
| `TransactionRepository` | SQLAlchemy / SQLite |
| `DisputeRepository` | SQLAlchemy / SQLite |

### 3.4 Herramientas MCP iniciales (contrato)

| Herramienta | Propósito |
|---|---|
| `buscar_cliente` | Encuentra al cliente por documento, nombre o últimos dígitos de tarjeta. Puede devolver varias coincidencias. |
| `verificar_identidad` | Confirma la identidad del cliente con un dato adicional. |
| `consultar_transacciones` | Lista transacciones de un producto en un rango de fechas. |
| `iniciar_disputa` | Abre una disputa sobre una transacción. |
| `bloquear_tarjeta` | Bloquea una tarjeta por sospecha de fraude. |
| `escalar_a_analista` | Pasa el caso a un analista humano con un resumen estructurado. |

Los nombres de las herramientas MCP están en español por ser parte del contrato acordado; es la única excepción a la convención de identificadores en inglés (§2).

Los esquemas exactos (entradas, salidas, errores) se definen en la spec correspondiente; esta tabla solo fija el catálogo inicial.

### 3.5 Flujo de una conversación

1. El cliente escribe en el chat → `POST /api/chat` → caso de uso `HandleCustomerMessage`.
2. El caso de uso ejecuta el loop: envía el historial y las herramientas a `LLMPort`; mientras el LLM pida herramientas, se invocan vía `BankingToolsPort` y se devuelven los resultados.
3. Cuando hay datos suficientes de una transacción disputada, el caso de uso construye el objeto de dominio y consulta a `DisputePolicy`, que devuelve una `DisputeDecision` (`RESOLVE`, `REJECT` o `ESCALATE`) con la regla aplicada y el motivo.
4. La aplicación ejecuta **solo** las acciones permitidas por esa decisión (p. ej. `iniciar_disputa`, `bloquear_tarjeta` o `escalar_a_analista`).
5. Todo paso se registra en `AuditLogPort`. El LLM redacta la respuesta final al cliente a partir de la decisión.
6. El loop tiene un límite de iteraciones configurable; al superarlo aplica el Art. 10.

### 3.6 Estructura de carpetas

```
.
├── docs/
│   └── constitution.md
├── specs/
│   ├── _templates/
│   │   ├── spec.md
│   │   ├── plan.md
│   │   └── tasks.md
│   └── NNN-feature-name/
│       ├── spec.md
│       ├── plan.md
│       └── tasks.md
├── src/
│   ├── dispute_agent/
│   │   ├── domain/
│   │   │   ├── models/              # Dispute, Transaction, Customer, DisputeDecision...
│   │   │   ├── policies/            # DisputePolicy y reglas
│   │   │   └── errors.py
│   │   ├── application/
│   │   │   ├── ports/               # LLMPort, BankingToolsPort, ConversationRepository, AuditLogPort
│   │   │   └── use_cases/           # HandleCustomerMessage, EvaluateDispute...
│   │   ├── infrastructure/
│   │   │   ├── inbound/
│   │   │   │   └── web/
│   │   │   │       ├── api/         # routers FastAPI y esquemas Pydantic
│   │   │   │       └── static/      # index.html, styles.css, chat.js
│   │   │   └── outbound/
│   │   │       ├── llm/             # AnthropicLLMAdapter
│   │   │       ├── mcp/             # McpStdioBankingAdapter
│   │   │       ├── persistence/     # ConversationRepository en memoria
│   │   │       └── audit/           # logger JSON
│   │   ├── config.py
│   │   └── main.py                  # composición y arranque FastAPI
│   └── core_banking_mcp/
│       ├── domain/
│       ├── application/
│       │   ├── ports/
│       │   └── use_cases/
│       ├── infrastructure/
│       │   ├── inbound/
│       │   │   └── mcp/             # definición de herramientas FastMCP
│       │   └── outbound/
│       │       └── persistence/
│       │           ├── models/      # modelos SQLAlchemy
│       │           └── seeds/       # datos ficticios reproducibles
│       ├── config.py
│       └── server.py                # composición y arranque del servidor MCP (stdio)
├── tests/
│   ├── unit/
│   │   ├── dispute_agent/
│   │   └── core_banking_mcp/
│   ├── integration/
│   ├── contract/                    # esquemas de herramientas MCP
│   ├── e2e/
│   └── fakes/                       # FakeLLM, FakeBankingTools, builders
├── pyproject.toml
├── uv.lock
├── .env.example
└── .gitignore
```

### 3.7 Escalabilidad y evolución

Los puertos garantizan que se puedan sustituir piezas sin tocar el dominio:

- MCP stdio → MCP HTTP streamable (servidor desplegado aparte).
- SQLite → PostgreSQL (cambiando el adaptador y la URL de conexión).
- `ConversationRepository` en memoria → Redis / base de datos.
- Claude → otro proveedor (nuevo adaptador de `LLMPort`).

Cualquiera de estos cambios requiere una spec propia, pero no debe modificar `domain` ni `application`.

---

## 4. Relación entre spec y código

### 4.1 Modelo: **spec-anchored**

La spec se escribe **antes** del código y **permanece viva** durante toda la vida de la funcionalidad. Spec y código evolucionan juntos: la spec es la fuente de verdad del **comportamiento**; el código es la fuente de verdad de la **implementación**.

### 4.2 Flujo SDD (sin frameworks)

Cada funcionalidad vive en `specs/NNN-feature-name/` y recorre cuatro fases, usando las plantillas de `specs/_templates/`:

| Fase | Artefacto | Contenido | Gate de salida |
|---|---|---|---|
| 1. Specify | `spec.md` | **Qué y por qué**: contexto, historias de usuario, reglas de negocio, criterios de aceptación (Given/When/Then), contratos de herramientas MCP, casos de escalamiento, preguntas abiertas | Sin preguntas abiertas; spec aprobada |
| 2. Plan | `plan.md` | **Cómo**: componentes por capa, puertos y adaptadores afectados, modelo de datos, dependencias nuevas justificadas, riesgos, verificación de cumplimiento de la constitución | Plan aprobado |
| 3. Tasks | `tasks.md` | Lista ordenada de tareas pequeñas; cada una referencia los criterios de aceptación que cubre y empieza por su test | Tareas trazables a la spec |
| 4. Implement | Código + tests | Ejecución de las tareas con TDD (§5) | Definition of Done cumplida |

### 4.3 Reglas

1. **Sin spec aprobada no hay código de producción.**
2. **Trazabilidad**: cada criterio de aceptación tiene un ID único con formato `AC-NNN-XX` (p. ej. `AC-003-02`). Los tests que lo verifican lo referencian en su nombre o docstring.
3. **Cambio de comportamiento ⇒ cambio de spec en el mismo commit/PR.** Primero se actualiza la spec, luego el test, luego el código.
4. **Una divergencia entre spec y código es un defecto**, se detecte donde se detecte, y se corrige alineando ambos.
5. Las refactorizaciones que no cambian comportamiento no requieren cambiar la spec, pero sí deben mantener los tests verdes.
6. Las reglas del motor de decisión (`DisputePolicy`) se documentan en la spec como tabla de decisión; cada fila corresponde a, al menos, un test.

---

## 5. Política de tests

### 5.1 TDD obligatorio

Todo el código de producción se desarrolla con el ciclo **Red → Green → Refactor**:

1. **Red**: escribir un test que exprese un criterio de aceptación o una regla y verificar que **falla** por el motivo correcto.
2. **Green**: escribir el código mínimo para que pase.
3. **Refactor**: mejorar el diseño manteniendo todos los tests en verde.

El ciclo debe ser evidenciable en el historial (p. ej. commits `test:` → `feat:` → `refactor:`, o un commit por ciclo que incluya test y código).

### 5.2 Niveles de test

| Nivel | Carpeta | Alcance | Dependencias externas |
|---|---|---|---|
| Unitario | `tests/unit/` | Dominio y casos de uso, con fakes de los puertos | Ninguna (sin I/O, sin red) |
| Integración | `tests/integration/` | Adaptadores: SQLAlchemy con SQLite en memoria, routers FastAPI con `TestClient`, herramientas MCP contra repositorios reales | Solo locales |
| Contrato | `tests/contract/` | Esquemas de entrada/salida de cada herramienta MCP, verificados en ambos lados (servidor y cliente) | Ninguna |
| End-to-end | `tests/e2e/` | Chat → agente → servidor MCP real por stdio → SQLite, con **LLM falso determinista** | Subproceso MCP local |

### 5.3 Reglas específicas

1. **El LLM nunca se llama en la suite por defecto.** Se usa un `FakeLLM` guionizado que devuelve respuestas y *tool calls* predefinidas.
2. Las pruebas opcionales con Claude real se marcan con `@pytest.mark.llm`, se excluyen por defecto y nunca bloquean la integración.
3. **`DisputePolicy` se prueba con tests parametrizados (table-driven)**: una fila por regla de la tabla de decisión de la spec, incluidos los casos límite (umbral exacto, fuera de plazo, datos faltantes).
4. Todo caso que deba escalar según la spec tiene un test que lo verifica (Art. 10).
5. Se testea la violación de invariantes: llamada a herramientas sin identificación previa (Art. 7), decisiones no ejecutables, límite de iteraciones del loop.
6. Los tests son deterministas: sin dependencia de reloj real (se inyecta un `Clock`), sin aleatoriedad sin semilla, sin orden de ejecución implícito.
7. Los datos de prueba se construyen con *builders* / *fixtures* en `tests/fakes/`, nunca copiando datos de semillas a mano.

### 5.4 Cobertura

| Ámbito | Mínimo |
|---|---|
| `domain` + `application` (ambas apps) | **≥ 90 %** líneas y ramas |
| Global | **≥ 80 %** |

La verificación (`pytest --cov`) falla si no se alcanzan los umbrales. La cobertura es un piso, no un objetivo: un test sin aserciones significativas no cuenta como cumplimiento.

### 5.5 Definition of Done

Una tarea está terminada solo si:

- [ ] Existe la spec aprobada y los criterios de aceptación cubiertos están trazados a tests.
- [ ] Los tests se escribieron antes del código y todos pasan.
- [ ] Se cumplen los umbrales de cobertura.
- [ ] `ruff check`, `ruff format --check` y `mypy --strict` pasan sin errores.
- [ ] La spec refleja el comportamiento implementado.
- [ ] No se introdujeron secretos ni datos reales.

---

## 6. Gobernanza

### 6.1 Precedencia

`constitution.md` > `spec.md` > `plan.md` > `tasks.md` > código.

### 6.2 Enmiendas

- Toda modificación de esta constitución se hace mediante un cambio dedicado que explique el motivo y su impacto en specs existentes.
- Se versiona con **semver**: MAJOR para eliminar o redefinir un artículo, MINOR para añadir un artículo o sección, PATCH para aclaraciones de redacción.
- Las specs afectadas por una enmienda MAJOR deben revisarse antes de continuar su implementación.

### 6.3 Checklist de cumplimiento para revisión

- [ ] ¿El cambio tiene spec aprobada y trazable? (Art. 2)
- [ ] ¿El código nació de un test en rojo? (Art. 3)
- [ ] ¿El dominio sigue libre de dependencias de infraestructura? (Art. 4)
- [ ] ¿Las decisiones de disputa las toma `DisputePolicy` y no el LLM? (Art. 5)
- [ ] ¿Todo acceso al core pasa por herramientas MCP? (Art. 6)
- [ ] ¿Se valida la identificación antes de exponer datos? (Art. 7)
- [ ] ¿Las acciones y decisiones quedan auditadas? (Art. 8)
- [ ] ¿No hay secretos en el repositorio? (Art. 9)
- [ ] ¿Los casos dudosos escalan por defecto? (Art. 10)

### 6.4 Historial de enmiendas

| Versión | Fecha | Cambio | Motivo | Impacto |
|---|---|---|---|---|
| 1.0.0 | 2026-10-16 | Ratificación | — | — |
| 1.0.1 | 2026-10-16 | §3.2 y §3.6: `infrastructure/in` → `infrastructure/inbound` e `infrastructure/out` → `infrastructure/outbound`. | `in` es palabra reservada de Python: `core_banking_mcp.infrastructure.in` no se puede importar con `import`/`from`. `out` se renombra por simetría. | No cambia ningún principio (PATCH). Se actualizan las rutas en `.claude/rules/`, las plantillas, la skill `tasks-feature` y el plan y las tareas de `001-customer-search`. |
