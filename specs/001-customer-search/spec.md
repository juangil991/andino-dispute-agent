# Spec: Buscar un cliente por documento, nombre o últimos dígitos de tarjeta

| Campo | Valor |
|---|---|
| Feature | `001-customer-search` |
| Versión | 0.2.0 |
| Estado | Aprobada |
| Fecha | 2026-10-16 |
| Origen | Issue [#25](https://github.com/juangil991/andino-dispute-agent/issues/25) del backlog (P0) |
| Plan | [plan.md](./plan.md) |
| Tareas | [tasks.md](./tasks.md) |
| Constitución | [docs/constitution.md](../../docs/constitution.md) |

---

## 1. Contexto y problema

Para atender una disputa, el agente necesita primero **localizar** al cliente en el core bancario a partir de lo que este cuenta en el chat: su documento, su nombre o los últimos dígitos de su tarjeta. Hoy el core simulado (`core_banking_mcp`) no expone ninguna herramienta: sin ella, ninguna conversación puede avanzar.

Localizar no es autenticar (Art. 7): la búsqueda ocurre **antes** de verificar la identidad, así que debe devolver solo lo mínimo para reconocer o distinguir al cliente, con la PII enmascarada, y nunca saldos, productos ni movimientos. Es la primera herramienta del catálogo (§3.4) y fija el patrón de contrato, errores y auditoría para las siguientes.

## 2. Objetivos

- Exponer la herramienta MCP `buscar_cliente` en `core_banking_mcp` con el contrato de §7.
- Devolver como máximo 5 coincidencias con datos mínimos y enmascarados; con más de 5, pedir un criterio adicional.
- Rechazar entradas inválidas con un error tipado `INVALID_INPUT`, sin exponer datos.
- Ante una falla inesperada, devolver `INTERNAL` no reintentable (para que el consumidor escale, Art. 10).
- Auditar el 100 % de las invocaciones, válidas o no (Art. 8).

### Fuera de alcance

- Cambios en `dispute_agent`: operación en `BankingToolsPort`, adaptador `McpStdioBankingAdapter`, loop LLM y chat (spec propia).
- La ejecución del escalamiento (`escalar_a_analista`): esta feature solo garantiza que la falla se señala como no reintentable.
- `verificar_identidad` y el resto de herramientas del catálogo.
- Búsqueda difusa o parcial por nombre (prefijos, errores tipográficos, nombres incompletos).

## 3. Historias de usuario

| ID | Como | Quiero | Para |
|---|---|---|---|
| HU-001-01 | agente de disputas | localizar a un cliente por su documento, su nombre completo o los últimos 4 dígitos de su tarjeta | empezar a atenderlo |
| HU-001-02 | agente de disputas | recibir, ante varias coincidencias, los datos mínimos que distinguen a cada cliente | pedir la verificación al cliente correcto |
| HU-001-03 | cliente de Banco Andino | que mis datos se muestren parcialmente ocultos y sin saldos ni movimientos mientras no me haya verificado | proteger mi información |
| HU-001-04 | responsable de auditoría | que cada búsqueda quede registrada con su conversación, momento, criterio y resultado | tener trazabilidad total |

## 4. Reglas de negocio

| ID | Regla | Fuente / justificación |
|---|---|---|
| RN-001-01 | Los criterios de búsqueda son `document`, `full_name` y `card_last4`. Se exige **al menos uno**. Si llegan varios, un cliente coincide solo si cumple **todos** (AND). Un criterio ausente o `null` no se aplica. | Issue #25 |
| RN-001-02 | `document` coincide si, tras recortar espacios en los extremos, es igual al documento registrado **sin distinguir mayúsculas y minúsculas**; el resto de caracteres (guiones incluidos) debe coincidir exactamente (`d-1001` coincide con `D-1001`; `D1001` no). | Clarificación 2026-10-16 |
| RN-001-03 | `full_name` coincide si, tras normalizar ambos lados (quitar acentos/diacríticos, ignorar mayúsculas, recortar extremos y colapsar espacios internos), es **igual al nombre completo registrado**. Un nombre parcial no coincide (`José` no coincide con `José Álvarez`; `José Álvarez` no coincide con `José Álvarez Pérez`). | Issue #25; clarificación 2026-10-16 |
| RN-001-04 | `card_last4` coincide con un cliente si **cualquiera** de sus tarjetas termina en esos 4 dígitos, **sea cual sea el estado de la tarjeta** (activa, bloqueada, cancelada). | Clarificación 2026-10-16 |
| RN-001-05 | Validación de entrada: `document` de 1 a 32 caracteres y `full_name` de 1 a 100, contados tras recortar (vacío o solo espacios es inválido); `card_last4` exactamente 4 dígitos `0-9`, sin espacios; `conversation_id` obligatorio y no vacío. Toda violación ⇒ error `INVALID_INPUT` sin datos de clientes. | Issue #25; clarificación 2026-10-16; `mcp-tools.md` §6 |
| RN-001-06 | Sin coincidencias, la respuesta es exitosa con lista vacía; no es un error. | Issue #25 |
| RN-001-07 | Tope de 5 clientes. Con 1 a 5 coincidencias se devuelven todas con `refinement_required = false`. Con más de 5, la respuesta es exitosa, **sin ningún cliente** y con `refinement_required = true` para que se pida un dato adicional. | Issue #25; clarificación 2026-10-16 |
| RN-001-08 | Cada cliente devuelto contiene **solo** `customer_id`, `full_name`, `masked_document`, `masked_cards` y `cards` (lista de `{card_id, masked_card}` de sus tarjetas, en el mismo orden que `masked_cards`, sin estado ni número; spec 007, RN-007-31). Nunca saldos, productos, movimientos, documento completo ni número completo de tarjeta. | Issue #25; Art. 7; `mcp-tools.md` §8; clarificación 2026-10-16 |
| RN-001-09 | Enmascarado: el documento se muestra como `****` seguido de sus 2 últimos caracteres (`D-1001` → `****01`); si tiene 4 caracteres o menos, solo `****`. Cada tarjeta se muestra como `**** ` seguido de sus 4 últimos dígitos (`**** 4321`). | Issue #25; `mcp-tools.md` §8; clarificación 2026-10-16 |
| RN-001-10 | `buscar_cliente` **no requiere** identidad verificada (excepción de `mcp-tools.md` §5) y **no la confirma**: su respuesta no incluye ningún token ni indicador de verificación y la conversación no queda marcada como verificada. | Art. 7 |
| RN-001-11 | Los clientes devueltos se ordenan por `customer_id` ascendente (resultado determinista). | §5.3.6 (tests deterministas) |
| RN-001-12 | Cada invocación (con resultado, sin resultado, con `refinement_required`, con datos inválidos o con falla) genera un registro de auditoría con `conversation_id` (o vacío si no llegó), fecha y hora del reloj inyectado, herramienta, criterio recibido (documento enmascarado según RN-001-09) y resultado (tipo, cantidad y `customer_id` devueltos, o código de error). | Art. 8; issue #25 |
| RN-001-13 | Ante una falla inesperada (p. ej. el repositorio de clientes no responde), la herramienta devuelve el error `INTERNAL` con `retryable = false`, sin datos de clientes y sin detalles internos (trazas, SQL) en el mensaje. | Art. 10; issue #25; `mcp-tools.md` §7 |

## 5. Tabla de decisión de `DisputePolicy`

No aplica: la búsqueda de clientes no decide sobre disputas.

## 6. Criterios de aceptación

### AC-001-01 — Cliente único por documento

Cubre: HU-001-01, RN-001-01, RN-001-08

- **Given** existe un único cliente con el documento `D-1001`
- **When** se invoca `buscar_cliente` con `document = "D-1001"`
- **Then** la respuesta contiene exactamente 1 cliente, con `refinement_required = false`
- **And** el cliente trae solo `customer_id`, `full_name`, `masked_document`, `masked_cards` y `cards` (sin saldos, productos ni movimientos)

### AC-001-02 — Comparación del documento

Cubre: HU-001-01, RN-001-02

- **Given** existe un único cliente con el documento `D-1001`
- **When** se invoca `buscar_cliente` con `document` = `<valor>`
- **Then** la respuesta contiene `<cantidad>` clientes

| valor | cantidad |
|---|---|
| `D-1001` | 1 |
| `d-1001` | 1 |
| `  D-1001  ` | 1 |
| `D1001` | 0 |

### AC-001-03 — Cliente único por últimos 4 dígitos de tarjeta, en cualquier estado

Cubre: HU-001-01, RN-001-04, RN-001-09

- **Given** existe un único cliente con una tarjeta que termina en `<últimos>` en estado `<estado>`
- **When** se invoca `buscar_cliente` con `card_last4 = "<últimos>"`
- **Then** la respuesta contiene exactamente 1 cliente
- **And** su `masked_cards` incluye `**** <últimos>`

| últimos | estado |
|---|---|
| `4321` | activa |
| `8765` | bloqueada |
| `5555` | cancelada |

### AC-001-04 — Homónimos distinguibles

Cubre: HU-001-02, RN-001-03, RN-001-08, RN-001-11

- **Given** existen 2 clientes llamados `Ana Torres` con documentos distintos
- **When** se invoca `buscar_cliente` con `full_name = "Ana Torres"`
- **Then** la respuesta contiene 2 clientes ordenados por `customer_id` ascendente
- **And** ambos tienen `customer_id` distinto y `masked_document` distinto

### AC-001-05 — El nombre ignora acentos, mayúsculas y espacios, pero debe ser completo

Cubre: HU-001-01, RN-001-03

- **Given** existe un cliente llamado `José Álvarez` y otro llamado `José Álvarez Pérez`
- **When** se invoca `buscar_cliente` con `full_name` = `<nombre>`
- **Then** la respuesta contiene `<cantidad>` clientes

| nombre | cantidad |
|---|---|
| `José Álvarez` | 1 |
| `jose alvarez` | 1 |
| `JOSÉ ÁLVAREZ` | 1 |
| `  José   Álvarez  ` | 1 |
| `José` | 0 |
| `José Álvarez2` | 0 |
| `José Álvarez Pérez` | 1 |

### AC-001-06 — Búsqueda sin resultados

Cubre: HU-001-01, RN-001-06

- **Given** no existe ningún cliente con el documento `D-9999`
- **When** se invoca `buscar_cliente` con `document = "D-9999"`
- **Then** la respuesta es exitosa (no es un error), con `customers = []` y `refinement_required = false`

### AC-001-07 — Tope de 5 clientes

Cubre: HU-001-02, RN-001-07

- **Given** existen `<coincidencias>` clientes que cumplen el criterio de búsqueda
- **When** se invoca `buscar_cliente` con ese criterio
- **Then** la respuesta contiene `<devueltos>` clientes y `refinement_required = <bandera>`

| coincidencias | devueltos | bandera |
|---|---|---|
| 4 | 4 | `false` |
| 5 | 5 | `false` |
| 6 | 0 | `true` |

### AC-001-08 — Varios criterios se combinan con AND

Cubre: HU-001-01, RN-001-01

- **Given** existe un cliente con el documento `D-1001` y otro, con nombre distinto, con el documento `D-1002`
- **When** se invoca `buscar_cliente` con `document = "D-1001"` y `full_name` = nombre del cliente `D-1002`
- **Then** la respuesta es exitosa con `customers = []`
- **And** la misma búsqueda con `document = "D-1001"` y el nombre del cliente `D-1001` devuelve 1 cliente

### AC-001-09 — Entradas inválidas

Cubre: RN-001-01, RN-001-05

- **When** se invoca `buscar_cliente` con `<entrada>`
- **Then** se devuelve el error `INVALID_INPUT` con `retryable = false`
- **And** no se devuelve información de ningún cliente

| entrada |
|---|
| ningún criterio (los tres ausentes o `null`) |
| `document = ""` |
| `document` de 33 caracteres |
| `full_name = "   "` |
| `full_name` de 101 caracteres |
| `card_last4 = "123"` |
| `card_last4 = "12345"` |
| `card_last4 = "12a4"` |
| `conversation_id` ausente o vacío |

### AC-001-10 — Buscar no exige ni confirma la identidad

Cubre: HU-001-01, RN-001-10

- **Given** la identidad de la conversación no ha sido verificada
- **When** se invoca `buscar_cliente` con `document = "D-1001"`
- **Then** la respuesta contiene al cliente (no se rechaza con `IDENTITY_NOT_VERIFIED`)
- **And** la respuesta no incluye ningún token ni indicador de identidad verificada
- **And** la conversación sigue sin estar verificada en el servidor

### AC-001-11 — Datos personales enmascarados

Cubre: HU-001-03, RN-001-08, RN-001-09

- **Given** existe un cliente con el documento `D-1001` y tarjetas `4111111111114321` y `5500000000008765`
- **When** se invoca `buscar_cliente` con `document = "D-1001"`
- **Then** `masked_document = "****01"` y `masked_cards = ["**** 4321", "**** 8765"]`
- **And** en ninguna parte de la respuesta aparece `D-1001` ni un número de tarjeta completo

### AC-001-12 — Enmascarado de documentos cortos

Cubre: HU-001-03, RN-001-09

- **Given** existe un cliente con el documento `AB12`
- **When** se invoca `buscar_cliente` con `document = "AB12"`
- **Then** `masked_document = "****"`

### AC-001-13 — Cada invocación queda auditada

Cubre: HU-001-04, RN-001-12

- **Given** un reloj inyectado fijo
- **When** se invoca `buscar_cliente` produciendo `<caso>`
- **Then** queda exactamente 1 registro de auditoría con `conversation_id`, la fecha y hora del reloj, `tool = "buscar_cliente"`, el criterio recibido con el documento enmascarado y `<resultado registrado>`
- **And** el registro no contiene el documento completo

| caso | resultado registrado |
|---|---|
| un cliente | tipo `found`, cantidad 1 y su `customer_id` |
| varios clientes | tipo `found`, cantidad N y sus `customer_id` |
| ningún cliente | tipo `found`, cantidad 0 |
| más de 5 coincidencias | tipo `refinement_required`, cantidad 0 |
| datos inválidos | código `INVALID_INPUT` |
| falla inesperada | código `INTERNAL` |

### AC-001-14 — Falla inesperada

Cubre: RN-001-13

- **Given** el repositorio de clientes falla de forma inesperada
- **When** se invoca `buscar_cliente` con `document = "D-1001"`
- **Then** se devuelve el error `INTERNAL` con `retryable = false`
- **And** no se devuelve información de clientes
- **And** el mensaje no contiene trazas, SQL ni el texto de la excepción original

## 7. Contratos de herramientas MCP

### `buscar_cliente`

- **Propósito:** localizar clientes de Banco Andino por documento, nombre completo o últimos 4 dígitos de tarjeta.
- **Cuándo usarla / cuándo no:** al inicio de la atención, para saber a qué cliente (o clientes posibles) se refiere la persona. **No autentica**: después hay que usar `verificar_identidad` antes de consultar transacciones o actuar sobre la cuenta. Si devuelve varias coincidencias o `refinement_required = true`, pedir al cliente otro dato y repetir la búsqueda.
- **Precondiciones:** ninguna sobre identidad (excepción del Art. 7). Exige `conversation_id`.
- **Efectos secundarios:** ninguno salvo el registro de auditoría. Idempotente (solo lectura).

**Entrada**

| Campo | Tipo | Obligatorio | Descripción / validación |
|---|---|---|---|
| `conversation_id` | `string` | Sí | Identificador de correlación; no vacío. |
| `document` | `string \| null` | No* | Documento del cliente; 1–32 caracteres tras recortar. Comparación según RN-001-02. |
| `full_name` | `string \| null` | No* | Nombre completo; 1–100 caracteres tras recortar. Comparación según RN-001-03. |
| `card_last4` | `string \| null` | No* | Exactamente 4 dígitos `0-9`. Comparación según RN-001-04. |

\* Al menos uno de `document`, `full_name` o `card_last4` es obligatorio; si llegan varios se combinan con AND (RN-001-01).

**Salida**

| Campo | Tipo | Descripción |
|---|---|---|
| `customers` | `list[CustomerMatch]` | 0 a 5 clientes, ordenados por `customer_id` ascendente. Vacía si no hay coincidencias o si hay más de 5. |
| `refinement_required` | `bool` | `true` solo si hubo más de 5 coincidencias (en ese caso `customers` está vacía). |

`CustomerMatch` (no admite campos adicionales):

| Campo | Tipo | Descripción |
|---|---|---|
| `customer_id` | `string` | Identificador opaco del cliente en el core. |
| `full_name` | `string` | Nombre completo tal como está registrado. |
| `masked_document` | `string` | Documento enmascarado (RN-001-09), p. ej. `****01`. |
| `masked_cards` | `list[string]` | Tarjetas del cliente en cualquier estado, enmascaradas (`**** 4321`). Puede estar vacía. |
| `cards` | `list[{card_id, masked_card}]` | **Nuevo (spec 007, RN-007-31).** Las mismas tarjetas y en el mismo orden que `masked_cards`: `card_id` es el identificador opaco de la tarjeta en el core y `masked_card` su forma enmascarada. No incluye el estado ni el número. Puede estar vacía. |

Sin resultados: `{"customers": [], "refinement_required": false}` (no es un error).
Más de 5 coincidencias: `{"customers": [], "refinement_required": true}`.

**Errores** (formato `{code, message, retryable}`, `mcp-tools.md` §7)

| Código | Tipo | Reintentable | Cuándo ocurre |
|---|---|---|---|
| `INVALID_INPUT` | validación | No | Entrada que viola RN-001-01 o RN-001-05. |
| `INTERNAL` | interno | No | Falla inesperada del core (RN-001-13). El consumidor debe escalar (Art. 10). |

## 8. Casos de escalamiento

Esta feature no ejecuta escalamientos (`escalar_a_analista` está fuera de alcance); solo señala al consumidor cuándo debe escalar.

| Condición | Motivo | Datos del resumen estructurado |
|---|---|---|
| `buscar_cliente` devuelve `INTERNAL` (`retryable = false`) | Falla no recuperable del core (Art. 10) | Lo definirá la spec de `escalar_a_analista`; como mínimo `conversation_id`, criterio buscado (enmascarado) y código de error. |

## 9. Clarificaciones

| Fecha | Pregunta | Respuesta | Secciones afectadas |
|---|---|---|---|
| 2026-10-16 | ¿Qué alcance tiene la feature? (`escalar_a_analista` no existe todavía) | Solo el servidor MCP (`core_banking_mcp`): herramienta, contrato y auditoría. El agente y el escalamiento quedan fuera. | §2, §8, RN-001-13, AC-001-14 |
| 2026-10-16 | ¿Cómo responde la herramienta con más de 5 coincidencias? | Respuesta exitosa con `customers = []` y `refinement_required = true` (no es un error). | RN-001-07, AC-001-07, §7 |
| 2026-10-16 | ¿Qué datos mínimos devuelve cada cliente? | `customer_id`, nombre completo, documento enmascarado (solo los 2 últimos caracteres visibles) y tarjetas enmascaradas `**** NNNN`. | RN-001-08, RN-001-09, AC-001-01, AC-001-11, §7 |
| 2026-10-16 | ¿Qué es un nombre "completo"? | Igual al nombre completo registrado tras normalizar acentos, mayúsculas y espacios; los nombres parciales no coinciden. | RN-001-03, AC-001-05 |
| 2026-10-16 | ¿Cómo se compara el documento? | Exacto tras recortar extremos y sin distinguir mayúsculas; los separadores cuentan. | RN-001-02, AC-001-02 |
| 2026-10-16 | ¿Qué tarjetas cuentan para `card_last4`? | Todas las del cliente, en cualquier estado. | RN-001-04, AC-001-03, §7 |
| 2026-10-16 | ¿Longitudes máximas de documento y nombre? | Documento 1–32 y nombre 1–100 caracteres tras recortar; si se exceden, `INVALID_INPUT`. | RN-001-05, AC-001-09, §7 |

## 10. Preguntas abiertas

Ninguna.

## 11. Historial de cambios

| Versión | Fecha | Cambio | Autor |
|---|---|---|---|
| 0.1.0 | 2026-10-16 | Versión inicial a partir de la issue #25 | Juangiov (con Claude Code) |
| 0.1.0 | 2026-10-16 | Spec aprobada por el usuario | Juangiov |
| 0.2.0 | 2026-10-18 | Se añade `cards` a `CustomerMatch` (RN-001-08 y tabla de §7) (cambio compatible, spec [007](../007-dispute-resolution-agent/spec.md) §7.1, RN-007-31) | Juangiov (con Claude Code) |

---

## Gate de salida

- [x] No quedan preguntas abiertas.
- [x] Cada clarificación está reflejada en las secciones afectadas.
- [x] Todos los criterios de aceptación tienen ID y formato Given/When/Then.
- [x] Cada regla de negocio está cubierta por al menos un criterio de aceptación.
- [x] Contratos MCP y casos de escalamiento completos o marcados "No aplica".
- [x] Estado cambiado a **Aprobada**.
