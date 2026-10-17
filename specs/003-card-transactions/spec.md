# Spec: Consultar las transacciones de una tarjeta del cliente en un rango de fechas

| Campo | Valor |
|---|---|
| Feature | `003-card-transactions` |
| Versión | 0.1.0 |
| Estado | Aprobada |
| Fecha | 2026-10-17 |
| Origen | Issue [#28](https://github.com/juangil991/andino-dispute-agent/issues/28) del backlog (P0) |
| Plan | [plan.md](./plan.md) |
| Tareas | [tasks.md](./tasks.md) |
| Constitución | [docs/constitution.md](../../docs/constitution.md) |

---

## 1. Contexto y problema

Con `buscar_cliente` (spec 001) el agente localiza al cliente y con `verificar_identidad` (spec 002) confirma que quien conversa es ese cliente. Para atender una disputa falta el paso siguiente: mostrarle al cliente los movimientos de una de sus tarjetas en un periodo concreto, para que señale el cargo que no reconoce. Hoy el core simulado no guarda transacciones ni ofrece ninguna forma de consultarlas.

Esta feature añade la herramienta `consultar_transacciones`. Es la primera herramienta que expone datos de cuenta, así que valida en el servidor que la conversación esté verificada (Art. 7, defensa en profundidad) usando el estado que dejó `verificar_identidad`. Responde igual ante una tarjeta ajena que ante una inexistente, limita el rango y la cantidad de resultados (`mcp-tools.md` §10), enmascara los datos de la tarjeta y audita cada invocación (Art. 8).

## 2. Objetivos

- Exponer la herramienta MCP `consultar_transacciones` en `core_banking_mcp` con el contrato de §7.
- Incorporar al core simulado las transacciones de tarjeta, con datos semilla ficticios y reproducibles (Art. 1).
- Rechazar con `IDENTITY_NOT_VERIFIED` toda consulta de una conversación no verificada en el servidor (Art. 7).
- Devolver como máximo 50 transacciones de un rango de hasta 90 días; con más de 50, pedir que se acote el rango.
- Responder `NOT_FOUND` de forma idéntica ante una tarjeta ajena o inexistente, sin revelar datos de otros clientes.
- Rechazar entradas inválidas con `INVALID_INPUT` y, ante una falla inesperada, devolver `INTERNAL` no reintentable (Art. 10).
- Auditar el 100 % de las invocaciones sin registrar números completos de tarjeta (Art. 8).

### Fuera de alcance

- Cambios en `dispute_agent`: operación en `BankingToolsPort`, adaptador MCP, loop LLM y chat (spec propia).
- La ejecución del escalamiento (`escalar_a_analista`): esta feature solo señala cuándo derivar.
- Paginación de resultados: con más de 50 transacciones se pide acotar el rango.
- Consultas por cuenta, por comercio, por monto o de productos que no sean tarjetas.
- Límite de antigüedad para la fecha inicial: los plazos de disputa se aplicarán en `DisputePolicy`.
- Las reversiones como movimientos aparte: se ven solo en el estado de la transacción original.
- Cambios en `buscar_cliente` y `verificar_identidad`.

## 3. Historias de usuario

| ID | Como | Quiero | Para |
|---|---|---|---|
| HU-003-01 | agente de disputas | consultar las transacciones de una tarjeta del cliente verificado en un rango de fechas | que el cliente señale el cargo que no reconoce |
| HU-003-02 | cliente de Banco Andino | que nadie vea mis movimientos sin haberse verificado como yo, ni pueda averiguar si una tarjeta existe | proteger mi información |
| HU-003-03 | agente de disputas | distinguir a qué tarjeta pertenece cada transacción aunque dos tarjetas terminen en los mismos dígitos | abrir la disputa sobre la transacción correcta |
| HU-003-04 | agente de disputas | saber cuándo debo acotar el rango o derivar el caso a un analista | no quedarme sin respuesta ante consultas muy amplias o fallas |
| HU-003-05 | responsable de auditoría | que cada consulta quede registrada con su conversación, momento, tarjeta enmascarada, rango y resultado | tener trazabilidad total sin exponer números de tarjeta |

## 4. Reglas de negocio

| ID | Regla | Fuente / justificación |
|---|---|---|
| RN-003-01 | La solicitud indica la tarjeta por sus últimos 4 dígitos (`card_last4`) y el rango con `date_from` y `date_to` en formato ISO `AAAA-MM-DD`, ambos incluidos. | Issue #28 |
| RN-003-02 | La herramienta exige que la conversación esté verificada en el servidor (estado de RN-002-13). Una conversación sin verificación exitosa, desconocida o bloqueada por intentos agotados se rechaza con `IDENTITY_NOT_VERIFIED`. La verificación no se traslada: estar verificada en otra conversación no cuenta. | Art. 7; issue #28; `mcp-tools.md` §5 |
| RN-003-03 | Se consultan **todas** las tarjetas del cliente verificado en la conversación que terminan en `card_last4`, **sea cual sea su estado** (activa, bloqueada, cancelada); sus transacciones se devuelven juntas en una sola lista. | Issue #28 |
| RN-003-04 | Si el cliente verificado no tiene ninguna tarjeta terminada en `card_last4` (porque la tarjeta es de otro cliente o porque no existe), se devuelve `NOT_FOUND` con un mensaje fijo, **idéntico** en ambos casos, sin datos de ningún cliente. | Issue #28; clarificación 2026-10-17 |
| RN-003-05 | Cada transacción tiene un instante `occurred_at` (fecha y hora con zona). Entra en el rango si su **fecha local en `America/Bogota`** está entre `date_from` y `date_to`, ambos incluidos. | Issue #28; clarificación 2026-10-17 |
| RN-003-06 | Validación de entrada: `conversation_id` obligatorio y no vacío tras recortar; `card_last4` obligatorio, exactamente 4 dígitos `0-9`, sin espacios; `date_from` y `date_to` obligatorias, en formato `AAAA-MM-DD` y existentes en el calendario; `date_from` no posterior a `date_to`; `date_to` no posterior a hoy; el rango no supera **90 días contando ambos extremos** (`date_to − date_from + 1 ≤ 90`). No hay límite hacia el pasado para `date_from`. Toda violación ⇒ `INVALID_INPUT`, sin transacciones. | Issue #28; clarificación 2026-10-17; `mcp-tools.md` §10 |
| RN-003-07 | "Hoy" es la fecha del reloj inyectado en la zona horaria `America/Bogota` (UTC−05:00), igual que RN-002-08. | RN-002-08; §5.3.6 |
| RN-003-08 | Las comprobaciones se evalúan en este orden y se devuelve el primer error: (1) validación de entrada → `INVALID_INPUT`; (2) identidad verificada → `IDENTITY_NOT_VERIFIED`; (3) tarjeta del cliente verificado → `NOT_FOUND`. | Clarificación 2026-10-17 |
| RN-003-09 | Se devuelven transacciones en cualquier estado: confirmada (`CONFIRMED`), pendiente (`PENDING`) o reversada (`REVERSED`). El monto es siempre el original y positivo; la reversión se ve solo en el estado. | Issue #28; clarificación 2026-10-17 |
| RN-003-10 | Tope de 50 transacciones. Sin transacciones en el rango, la respuesta es exitosa con lista vacía y `refinement_required = false`. Con 1 a 50 se devuelven todas con `refinement_required = false`. Con más de 50, la respuesta es exitosa, **sin ninguna transacción** y con `refinement_required = true` para que se acote el rango. | Issue #28; `mcp-tools.md` §10 |
| RN-003-11 | Las transacciones se ordenan de la más reciente a la más antigua por `occurred_at`; si dos tienen el mismo instante, por `transaction_id` ascendente (resultado determinista). | Issue #28; clarificación 2026-10-17; §5.3.6 |
| RN-003-12 | Cada transacción devuelta contiene **solo**: `transaction_id`, `occurred_at`, `merchant`, `amount` (texto decimal positivo con exactamente 2 decimales, p. ej. `"125000.00"`), `currency` (código ISO 4217, p. ej. `COP`, `USD`), `status`, `card_id` (identificador opaco de la tarjeta en el core, no derivado de su número) y `masked_card` (`**** ` seguido de los 4 últimos dígitos, RN-001-09). | Issue #28; clarificación 2026-10-17 |
| RN-003-13 | La respuesta nunca contiene el número completo de ninguna tarjeta, el documento del cliente ni su nombre, ni datos de otros clientes. | Issue #28; Art. 7; `mcp-tools.md` §8 |
| RN-003-14 | La herramienta es de solo lectura: no modifica transacciones, tarjetas ni el estado de verificación de la conversación (cliente verificado e intentos fallidos). | Art. 7; issue #28 |
| RN-003-15 | Cada invocación genera exactamente un registro de auditoría con `conversation_id` (o vacío si no llegó), fecha y hora del reloj inyectado, `tool = "consultar_transacciones"`, tarjeta enmascarada (`**** NNNN`; vacía si `card_last4` no es válido, para no registrar lo que se haya escrito en ese campo), rango consultado (`date_from` y `date_to` recibidos) y resultado: `found` con la cantidad y los `transaction_id` devueltos (cantidad 0 si no hubo), `refinement_required`, o el código de error (`INVALID_INPUT`, `IDENTITY_NOT_VERIFIED`, `NOT_FOUND`, `INTERNAL`). El registro **nunca** contiene el número completo de una tarjeta. | Art. 8; issue #28 |
| RN-003-16 | Ante una falla inesperada (p. ej. el repositorio de transacciones no responde), la herramienta devuelve `INTERNAL` con `retryable = false`, sin transacciones ni detalles internos (trazas, SQL, texto de la excepción). | Art. 10; issue #28; `mcp-tools.md` §7 |

## 5. Tabla de decisión de `DisputePolicy`

No aplica: la consulta de transacciones no decide sobre disputas.

## 6. Criterios de aceptación

En todos los criterios, salvo que se indique otra cosa: el reloj inyectado marca `2026-10-17T15:00:00Z` (hoy es 17 de octubre de 2026 en Bogotá); existe la cliente `C-0001` "Laura Méndez" con una tarjeta activa terminada en `4321`; la conversación está verificada para `C-0001`; y la consulta se hace con `card_last4 = "4321"`, `date_from = "2026-09-01"` y `date_to = "2026-09-30"`. Los instantes de las transacciones se expresan en hora de Bogotá (`−05:00`). Los datos de prueba se construyen con builders (§5.3.7), no con las semillas.

### AC-003-01 — Listar las transacciones de la tarjeta en el rango

Cubre: HU-003-01, RN-003-01, RN-003-05, RN-003-11, RN-003-12

- **Given** la tarjeta `4321` tiene 3 transacciones el 5, el 12 y el 20 de septiembre de 2026, y 1 transacción el 2 de octubre de 2026
- **When** se invoca `consultar_transacciones`
- **Then** la respuesta contiene exactamente las 3 transacciones de septiembre, en el orden 20, 12 y 5 de septiembre, con `refinement_required = false`
- **And** cada transacción trae `transaction_id`, `occurred_at`, `merchant`, `amount`, `currency`, `status`, `card_id` y `masked_card = "**** 4321"`
- **And** la transacción del 2 de octubre no aparece

### AC-003-02 — Los días extremos del rango se incluyen, según la fecha de Bogotá

Cubre: HU-003-01, RN-003-01, RN-003-05

- **Given** la tarjeta `4321` tiene una sola transacción con `occurred_at = <instante>`
- **When** se invoca `consultar_transacciones`
- **Then** `<resultado>`

| instante | resultado |
|---|---|
| `2026-09-01T00:00:00-05:00` | la transacción aparece |
| `2026-09-30T23:59:59-05:00` | la transacción aparece |
| `2026-08-31T23:59:59-05:00` | la transacción no aparece |
| `2026-10-01T00:00:00-05:00` | la transacción no aparece |
| `2026-10-01T03:30:00Z` (30 de septiembre, 22:30 en Bogotá) | la transacción aparece |
| `2026-09-01T04:30:00Z` (31 de agosto, 23:30 en Bogotá) | la transacción no aparece |

### AC-003-03 — Se muestran transacciones en cualquier estado

Cubre: HU-003-01, RN-003-09

- **Given** la tarjeta `4321` tiene una transacción de `125000.00 COP` el 10 de septiembre de 2026 en estado `<estado>`
- **When** se invoca `consultar_transacciones`
- **Then** la transacción aparece con `status = <estado>` y `amount = "125000.00"`

| estado |
|---|
| `CONFIRMED` |
| `PENDING` |
| `REVERSED` |

### AC-003-04 — Se pueden consultar tarjetas en cualquier estado

Cubre: HU-003-01, RN-003-03

- **Given** la tarjeta `4321` está en estado `<estado de la tarjeta>` y tiene 2 transacciones en septiembre de 2026
- **When** se invoca `consultar_transacciones`
- **Then** la respuesta contiene las 2 transacciones

| estado de la tarjeta |
|---|
| activa |
| bloqueada |
| cancelada |

### AC-003-05 — Dos tarjetas del cliente terminan en los mismos dígitos

Cubre: HU-003-03, RN-003-03, RN-003-12

- **Given** `C-0001` tiene otra tarjeta también terminada en `4321`
- **And** cada una de sus dos tarjetas terminadas en `4321` tiene 1 transacción en septiembre de 2026
- **When** se invoca `consultar_transacciones`
- **Then** la respuesta contiene las 2 transacciones, ambas con `masked_card = "**** 4321"`
- **And** cada transacción trae el `card_id` de su tarjeta, y los dos `card_id` son distintos

### AC-003-06 — Sin transacciones en el rango

Cubre: HU-003-01, RN-003-10

- **Given** la tarjeta `4321` no tiene transacciones en septiembre de 2026
- **When** se invoca `consultar_transacciones`
- **Then** la respuesta es exitosa (no es un error), con `transactions = []` y `refinement_required = false`

### AC-003-07 — Rango máximo de 90 días contando ambos extremos

Cubre: RN-003-06

- **When** se invoca `consultar_transacciones` con `date_from = <desde>` y `date_to = <hasta>`
- **Then** `<resultado>`

| desde | hasta | resultado |
|---|---|---|
| `2026-09-10` | `2026-09-10` | respuesta exitosa (1 día) |
| `2026-06-01` | `2026-08-28` | respuesta exitosa (89 días) |
| `2026-06-01` | `2026-08-29` | respuesta exitosa (90 días) |
| `2026-06-01` | `2026-08-30` | `INVALID_INPUT` con `retryable = false` (91 días) |
| `2019-01-01` | `2019-01-31` | respuesta exitosa (sin límite hacia el pasado) |

### AC-003-08 — Tope de 50 transacciones por consulta

Cubre: HU-003-04, RN-003-10

- **Given** la tarjeta `4321` tiene `<cantidad>` transacciones en septiembre de 2026
- **When** se invoca `consultar_transacciones`
- **Then** la respuesta contiene `<devueltas>` transacciones y `refinement_required = <bandera>`

| cantidad | devueltas | bandera |
|---|---|---|
| 49 | 49 | `false` |
| 50 | 50 | `false` |
| 51 | 0 | `true` |

### AC-003-09 — Datos de consulta inválidos

Cubre: RN-003-06

- **When** se invoca `consultar_transacciones` con `<dato>` (el resto de campos válidos)
- **Then** se devuelve el error `INVALID_INPUT` con `retryable = false`
- **And** no se devuelve ninguna transacción

| dato |
|---|
| `date_from = ""` |
| `date_to = ""` |
| `date_from` ausente o `null` |
| `date_to` ausente o `null` |
| `date_to = "2026-09-31"` (inexistente) |
| `date_from = "01/09/2026"` (formato distinto de `AAAA-MM-DD`) |
| `date_from = "2026-09-30"`, `date_to = "2026-09-01"` (inicial posterior a la final) |
| `date_from = "2026-10-01"`, `date_to = "2026-10-18"` (final posterior a hoy) |
| `card_last4` ausente o `null` |
| `card_last4 = "432"` (3 dígitos) |
| `card_last4 = "54321"` (5 dígitos) |
| `card_last4 = "43a1"` (con letras) |
| `conversation_id` ausente, vacío o solo espacios |

### AC-003-10 — "Hoy" se calcula en Bogotá

Cubre: RN-003-06, RN-003-07

- **Given** el reloj inyectado marca `<instante>` (UTC)
- **When** se invoca `consultar_transacciones` con `date_from = "2026-10-01"` y `date_to = <hasta>`
- **Then** el resultado es `<resultado>`

| instante | hasta | resultado |
|---|---|---|
| `2026-10-17T15:00:00Z` | `2026-10-17` (hoy en Bogotá) | respuesta exitosa |
| `2026-10-18T03:00:00Z` | `2026-10-18` (aún 17 en Bogotá) | `INVALID_INPUT` |
| `2026-10-18T05:00:00Z` | `2026-10-18` (ya 18 en Bogotá) | respuesta exitosa |

### AC-003-11 — No se muestra información sin la identidad verificada

Cubre: HU-003-02, RN-003-02, RN-003-14

- **Given** `<situación>`
- **When** se invoca `consultar_transacciones` en esa conversación
- **Then** se devuelve el error `IDENTITY_NOT_VERIFIED` con `retryable = false`
- **And** no se devuelve ninguna transacción
- **And** el estado de verificación de la conversación (cliente verificado e intentos fallidos) no cambia

| situación |
|---|
| la conversación nunca ha invocado `verificar_identidad` |
| la conversación acumula 1 intento fallido de verificación y ningún éxito |
| la conversación agotó sus intentos de verificación (bloqueada) |
| la conversación `A` está verificada para `C-0001` y la consulta se hace en la conversación `B`, no verificada |

### AC-003-12 — Orden de las comprobaciones

Cubre: RN-003-08

- **Given** `<situación>`
- **When** se invoca `consultar_transacciones` con `<entrada>`
- **Then** se devuelve el error `<código>`

| situación | entrada | código |
|---|---|---|
| la conversación no está verificada | `card_last4 = "43a1"` | `INVALID_INPUT` |
| la conversación no está verificada | `card_last4 = "0000"` (no existe) | `IDENTITY_NOT_VERIFIED` |
| la conversación está verificada para `C-0001` | `card_last4 = "0000"`, `date_to = "2026-10-18"` | `INVALID_INPUT` |

### AC-003-13 — Una tarjeta ajena o inexistente recibe la misma respuesta

Cubre: HU-003-02, RN-003-04, RN-003-13

- **Given** existe el cliente `C-0002` "Pedro Ríos" con una tarjeta terminada en `8765` que tiene transacciones en septiembre de 2026
- **And** ningún cliente tiene una tarjeta terminada en `0000`
- **When** se invoca `consultar_transacciones` con `card_last4 = "8765"` y, en otra invocación, con `card_last4 = "0000"`
- **Then** ambas devuelven el error `NOT_FOUND` con `retryable = false`
- **And** las dos respuestas son idénticas campo a campo (mismo código, mensaje y `retryable`)
- **And** no se devuelve ninguna transacción ni dato de `C-0002`

### AC-003-14 — La respuesta protege los datos de la tarjeta y del cliente

Cubre: HU-003-02, RN-003-12, RN-003-13

- **Given** la tarjeta `4321` tiene el número `4111111111114321`, el documento de `C-0001` es `D-1001` y la tarjeta tiene transacciones en septiembre de 2026
- **When** se invoca `consultar_transacciones`
- **Then** la respuesta contiene exactamente los campos `transactions` y `refinement_required`, y cada transacción exactamente los campos de RN-003-12
- **And** `masked_card = "**** 4321"` y `card_id` no contiene `4111111111114321`
- **And** en ninguna parte de la respuesta aparecen `4111111111114321`, `D-1001` ni `Laura Méndez`

### AC-003-15 — Orden estable ante transacciones simultáneas

Cubre: RN-003-11

- **Given** la tarjeta `4321` tiene 2 transacciones con el mismo `occurred_at = 2026-09-15T10:00:00-05:00` y otra el `2026-09-16T08:00:00-05:00`
- **When** se invoca `consultar_transacciones`
- **Then** primero aparece la del 16 de septiembre y después las dos del 15, ordenadas por `transaction_id` ascendente

### AC-003-16 — Formato del monto y de la moneda

Cubre: RN-003-09, RN-003-12

- **Given** la tarjeta `4321` tiene una transacción en septiembre de 2026 por `<monto registrado>` en `<moneda>`
- **When** se invoca `consultar_transacciones`
- **Then** la transacción trae `amount = <monto>` y `currency = <moneda>`

| monto registrado | moneda | monto |
|---|---|---|
| 125000 | `COP` | `"125000.00"` |
| 49.9 | `USD` | `"49.90"` |
| 0.05 | `USD` | `"0.05"` |

### AC-003-17 — Cada consulta queda registrada sin el número de la tarjeta

Cubre: HU-003-05, RN-003-15

- **Given** un reloj inyectado fijo
- **When** se invoca `consultar_transacciones` produciendo `<caso>`
- **Then** queda exactamente 1 registro de auditoría con `conversation_id`, la fecha y hora del reloj, `tool = "consultar_transacciones"`, la tarjeta enmascarada, el rango recibido y `<resultado registrado>`
- **And** el registro no contiene ningún número completo de tarjeta

| caso | resultado registrado |
|---|---|
| transacciones encontradas | tipo `found`, la cantidad y los `transaction_id` devueltos |
| ninguna transacción | tipo `found`, cantidad 0 |
| más de 50 transacciones | tipo `refinement_required` |
| datos inválidos | código `INVALID_INPUT` |
| `card_last4 = "4111111111114321"` (número completo en el campo) | código `INVALID_INPUT` y tarjeta enmascarada vacía |
| sin verificación | código `IDENTITY_NOT_VERIFIED` |
| tarjeta no encontrada | código `NOT_FOUND` |
| falla inesperada | código `INTERNAL` |

### AC-003-18 — Falla inesperada

Cubre: HU-003-04, RN-003-16

- **Given** el repositorio de transacciones falla de forma inesperada
- **When** se invoca `consultar_transacciones`
- **Then** se devuelve el error `INTERNAL` con `retryable = false`
- **And** no se devuelve ninguna transacción
- **And** el mensaje no contiene trazas, SQL ni el texto de la excepción original

## 7. Contratos de herramientas MCP

### `consultar_transacciones`

- **Propósito:** listar las transacciones de una tarjeta del cliente verificado en un rango de fechas, para que el cliente identifique el cargo que disputa.
- **Cuándo usarla / cuándo no:** solo **después** de que `verificar_identidad` haya respondido `verified = true` en la conversación. Pedir al cliente los últimos 4 dígitos de la tarjeta y el periodo (hasta 90 días). No sirve para localizar clientes ni para verificar identidad. Si responde `refinement_required = true`, pedir un rango más corto; si responde `NOT_FOUND`, pedir al cliente que revise los dígitos de la tarjeta; si responde `INTERNAL`, no reintentar y derivar a un analista.
- **Precondiciones:** identidad verificada en el servidor para la conversación (Art. 7, RN-003-02). Exige `conversation_id`.
- **Efectos secundarios:** ninguno salvo el registro de auditoría. Idempotente (solo lectura, RN-003-14).

**Entrada**

| Campo | Tipo | Obligatorio | Descripción / validación |
|---|---|---|---|
| `conversation_id` | `string` | Sí | Identificador de correlación; no vacío tras recortar. |
| `card_last4` | `string` | Sí | Últimos 4 dígitos de la tarjeta; exactamente 4 dígitos `0-9`. |
| `date_from` | `string` | Sí | Fecha inicial `AAAA-MM-DD`, incluida; existente en el calendario y no posterior a `date_to`. |
| `date_to` | `string` | Sí | Fecha final `AAAA-MM-DD`, incluida; existente, no posterior a hoy (Bogotá) y a lo sumo 89 días después de `date_from` (RN-003-06). |

**Salida** (no admite campos adicionales)

| Campo | Tipo | Descripción |
|---|---|---|
| `transactions` | `list[TransactionItem]` | 0 a 50 transacciones, de la más reciente a la más antigua (RN-003-11). Vacía si no hay transacciones en el rango o si hay más de 50. |
| `refinement_required` | `bool` | `true` solo si hubo más de 50 transacciones en el rango (en ese caso `transactions` está vacía). |

`TransactionItem` (no admite campos adicionales):

| Campo | Tipo | Descripción |
|---|---|---|
| `transaction_id` | `string` | Identificador opaco de la transacción en el core. |
| `occurred_at` | `string` | Fecha y hora de la transacción en ISO 8601 con zona (p. ej. `2026-09-20T14:32:00-05:00`). |
| `merchant` | `string` | Nombre del comercio. |
| `amount` | `string` | Monto original, positivo, con exactamente 2 decimales (p. ej. `"125000.00"`). |
| `currency` | `string` | Código ISO 4217 de 3 letras (p. ej. `COP`, `USD`). |
| `status` | `string` | `CONFIRMED`, `PENDING` o `REVERSED`. |
| `card_id` | `string` | Identificador opaco de la tarjeta en el core, no derivado de su número; distingue tarjetas con los mismos últimos dígitos. |
| `masked_card` | `string` | Tarjeta enmascarada: `**** ` seguido de sus 4 últimos dígitos. |

Ejemplos:

- Con resultados: `{"transactions": [{"transaction_id": "...", "occurred_at": "2026-09-20T14:32:00-05:00", "merchant": "...", "amount": "125000.00", "currency": "COP", "status": "CONFIRMED", "card_id": "...", "masked_card": "**** 4321"}], "refinement_required": false}`
- Sin resultados: `{"transactions": [], "refinement_required": false}` (no es un error).
- Más de 50: `{"transactions": [], "refinement_required": true}`.

**Errores** (formato `{code, message, retryable}`, `mcp-tools.md` §7; se evalúan en el orden de RN-003-08)

| Código | Tipo | Reintentable | Cuándo ocurre |
|---|---|---|---|
| `INVALID_INPUT` | validación | No | Entrada que viola RN-003-06. |
| `IDENTITY_NOT_VERIFIED` | permisos | No | La conversación no está verificada en el servidor (RN-003-02). |
| `NOT_FOUND` | negocio | No | El cliente verificado no tiene ninguna tarjeta terminada en `card_last4`; mensaje fijo, idéntico para tarjeta ajena o inexistente (RN-003-04). |
| `INTERNAL` | interno | No | Falla inesperada del core (RN-003-16). El consumidor debe escalar (Art. 10). |

## 8. Casos de escalamiento

Esta feature no ejecuta escalamientos (`escalar_a_analista` está fuera de alcance); solo señala al consumidor cuándo debe derivar.

| Condición | Motivo | Datos del resumen estructurado |
|---|---|---|
| `consultar_transacciones` devuelve `INTERNAL` (`retryable = false`) | Falla no recuperable del core (Art. 10, RN-003-16) | Lo definirá la spec de `escalar_a_analista`; como mínimo `conversation_id`, tarjeta enmascarada, rango consultado y código de error. Nunca el número completo de la tarjeta. |

## 9. Clarificaciones

| Fecha | Pregunta | Respuesta | Secciones afectadas |
|---|---|---|---|
| 2026-10-17 | Si dos tarjetas del cliente terminan en los mismos dígitos, ¿cómo indica cada transacción a qué tarjeta pertenece? | Con un `card_id` opaco del core (no derivado del número) además de `masked_card`. | RN-003-12, AC-003-05, AC-003-14, §7 |
| 2026-10-17 | ¿Cómo se representan el monto y la moneda? | `amount` como texto decimal positivo con 2 decimales y `currency` con código ISO 4217. | RN-003-12, AC-003-16, §7 |
| 2026-10-17 | ¿Qué fecha tiene una transacción y cómo se aplica el rango? | `occurred_at` es fecha y hora con zona; entra en el rango según su fecha local en `America/Bogota`; orden descendente por `occurred_at` y, ante empate, por `transaction_id`. | RN-003-05, RN-003-11, AC-003-02, AC-003-15, §7 |
| 2026-10-17 | ¿Cómo se responde ante una tarjeta ajena o inexistente? | Error `NOT_FOUND`, `retryable = false`, con el mismo mensaje en ambos casos. | RN-003-04, AC-003-13, §7 |
| 2026-10-17 | ¿Qué alcance tiene la feature? | Solo el servidor MCP: herramienta, contrato, transacciones y semillas, validación de identidad y auditoría. El agente y el escalamiento quedan fuera. | §2, §8 |
| 2026-10-17 | Si hay datos inválidos y además la conversación no está verificada, ¿qué error gana? | Validación → identidad → tarjeta. | RN-003-08, AC-003-12, §7 |
| 2026-10-17 | ¿Hay un límite hacia el pasado para la fecha inicial? | No; solo el máximo de 90 días y que la fecha final no sea posterior a hoy. | RN-003-06, AC-003-07, §2 |
| 2026-10-17 | ¿Cómo se muestra el monto de una transacción reversada? | Con el monto original positivo; la reversión se ve solo en `status = REVERSED`. | RN-003-09, AC-003-03, §2 |

## 10. Preguntas abiertas

Ninguna.

## 11. Historial de cambios

| Versión | Fecha | Cambio | Autor |
|---|---|---|---|
| 0.1.0 | 2026-10-17 | Versión inicial a partir de la issue #28 | Juangiov (con Claude Code) |
| 0.1.0 | 2026-10-17 | Spec aprobada por el usuario | Juangiov |

---

## Gate de salida

- [x] No quedan preguntas abiertas.
- [x] Cada clarificación está reflejada en las secciones afectadas.
- [x] Todos los criterios de aceptación tienen ID y formato Given/When/Then.
- [x] Cada regla de negocio está cubierta por al menos un criterio de aceptación.
- [x] Contratos MCP y casos de escalamiento completos o marcados "No aplica".
- [x] Estado cambiado a **Aprobada**.
