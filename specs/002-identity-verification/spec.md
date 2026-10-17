# Spec: Verificar la identidad del cliente con su fecha de nacimiento y la de expedición de su documento

| Campo | Valor |
|---|---|
| Feature | `002-identity-verification` |
| Versión | 0.1.0 |
| Estado | Aprobada |
| Fecha | 2026-10-17 |
| Origen | Issue [#27](https://github.com/juangil991/andino-dispute-agent/issues/27) del backlog (P0) |
| Plan | [plan.md](./plan.md) |
| Tareas | [tasks.md](./tasks.md) |
| Constitución | [docs/constitution.md](../../docs/constitution.md) |

---

## 1. Contexto y problema

Con `buscar_cliente` (spec 001) el agente ya puede **localizar** al cliente, pero localizar no es autenticar (Art. 7). Antes de mostrar o modificar información de una cuenta, el banco debe confirmar que quien conversa es el cliente localizado. Hoy el core simulado no ofrece ninguna forma de hacerlo, así que ninguna herramienta que exponga datos de cuenta (`consultar_transacciones`, `iniciar_disputa`, …) puede construirse respetando el Art. 7.

Esta feature añade la herramienta `verificar_identidad`: el cliente demuestra su identidad con dos datos que solo él debería conocer —su fecha de nacimiento y la fecha de expedición de su documento—. El servidor recuerda qué cliente quedó verificado en cada conversación (defensa en profundidad, Art. 7) para que las herramientas futuras lo validen, limita los intentos fallidos para frenar la adivinación y señala cuándo derivar el caso a un analista (Art. 10).

## 2. Objetivos

- Exponer la herramienta MCP `verificar_identidad` en `core_banking_mcp` con el contrato de §7.
- Verificar al cliente solo si **ambas** fechas coinciden, sin revelar cuál dato falló ni si el cliente existe.
- Mantener en el servidor el estado de verificación por conversación (cliente verificado e intentos fallidos), consultable por las herramientas que se construyan después.
- Bloquear la verificación tras 3 intentos fallidos en la conversación e indicar que debe derivarse a un analista.
- Rechazar entradas inválidas con `INVALID_INPUT` sin consumir intentos; ante una falla inesperada, devolver `INTERNAL` no reintentable (Art. 10).
- Auditar el 100 % de las invocaciones sin registrar las fechas (Art. 8).

### Fuera de alcance

- Cambios en `dispute_agent`: operación en `BankingToolsPort`, adaptador MCP, loop LLM y chat (spec propia).
- La ejecución del escalamiento (`escalar_a_analista`): esta feature solo indica cuándo derivar.
- Las herramientas que consumirán el estado de verificación (`consultar_transacciones`, `iniciar_disputa`, `bloquear_tarjeta`): cada una validará la verificación en su propia spec.
- Persistencia de la verificación entre reinicios del servidor, expiración por inactividad y cierre explícito de la conversación.
- Desbloqueo de una conversación bloqueada (requiere otra conversación o intervención humana).
- Cambios en `buscar_cliente`.

## 3. Historias de usuario

| ID | Como | Quiero | Para |
|---|---|---|---|
| HU-002-01 | agente de disputas | verificar al cliente localizado con su fecha de nacimiento y la de expedición de su documento | poder consultar y actuar sobre su cuenta |
| HU-002-02 | cliente de Banco Andino | que nadie pueda verificarse como yo adivinando datos ni averiguando cuál dato falló | proteger mi cuenta |
| HU-002-03 | agente de disputas | saber cuándo se agotaron los intentos o el sistema falló | derivar el caso a un analista |
| HU-002-04 | herramienta del core que expone datos de cliente | consultar en el servidor si la conversación está verificada y para qué cliente | cumplir el Art. 7 por defensa en profundidad |
| HU-002-05 | responsable de auditoría | que cada intento quede registrado con su conversación, momento, cliente y resultado, sin las fechas en claro | tener trazabilidad total sin exponer datos personales |

## 4. Reglas de negocio

| ID | Regla | Fuente / justificación |
|---|---|---|
| RN-002-01 | La solicitud identifica al cliente por el `customer_id` devuelto por `buscar_cliente` y aporta `birth_date` y `document_issue_date` en formato ISO `AAAA-MM-DD`. Todo cliente del core tiene registradas ambas fechas. | Issue #27; clarificación 2026-10-17 |
| RN-002-02 | La verificación es exitosa solo si el cliente existe y **ambas** fechas son iguales a las registradas. Basta una fecha distinta (incluidas las fechas intercambiadas) para que no lo sea. | Issue #27 |
| RN-002-03 | Una verificación no exitosa responde `verified = false` sin indicar cuál dato fue incorrecto. Un `customer_id` bien formado que no existe recibe una respuesta **idéntica** a la de unas fechas incorrectas y cuenta como intento fallido. | Issue #27; clarificación 2026-10-17 |
| RN-002-04 | Los intentos fallidos se cuentan **por conversación** (no por cliente). Máximo 3: con 1 o 2 fallos acumulados se admite un nuevo intento; el 3.º fallo **bloquea** la verificación de esa conversación. `attempts_remaining` = 3 − fallos acumulados (mínimo 0). | Issue #27 |
| RN-002-05 | Mientras la conversación no esté bloqueada, unas fechas correctas verifican aunque haya fallos previos (p. ej. tras 2 fallos). Una conversación bloqueada responde `verified = false`, `attempts_remaining = 0` y `escalation_required = true` a toda solicitud válida, aunque las fechas sean correctas, y no se desbloquea. | Issue #27 |
| RN-002-06 | `escalation_required = true` solo cuando la conversación está bloqueada (desde el 3.er fallo en adelante). En el resto de respuestas exitosas es `false`. | Issue #27; Art. 10 |
| RN-002-07 | Validación de entrada: `conversation_id` obligatorio y no vacío tras recortar; `customer_id` obligatorio, de 1 a 32 caracteres tras recortar; `birth_date` y `document_issue_date` obligatorias, en formato `AAAA-MM-DD`, que existan en el calendario, no posteriores a la fecha de hoy y con `document_issue_date` no anterior a `birth_date` (pueden ser iguales). Toda violación ⇒ `INVALID_INPUT`, que **no** cuenta como intento fallido, no cambia el estado de la conversación y no revela datos del cliente. | Issue #27; clarificación 2026-10-17; `mcp-tools.md` §6–7 |
| RN-002-08 | "Hoy" es la fecha del reloj inyectado en la zona horaria `America/Bogota` (UTC−05:00). | Clarificación 2026-10-17; §5.3.6 |
| RN-002-09 | Una verificación exitosa deja la conversación verificada para ese cliente mientras viva el proceso del servidor MCP (sin expiración ni persistencia entre reinicios). | Clarificación 2026-10-17 |
| RN-002-10 | Una conversación se verifica para **un solo** cliente. Si ya está verificada para un cliente y llega una solicitud para **otro** `customer_id` (exista o no, con fechas correctas o no), la respuesta es `verified = false`, sin contar intento, sin `escalation_required` y sin cambiar el cliente verificado. | Issue #27; clarificación 2026-10-17 |
| RN-002-11 | Si la conversación ya está verificada para el **mismo** `customer_id`, la respuesta es `verified = true` sin comparar las fechas ni contar intentos (idempotente). | Clarificación 2026-10-17 |
| RN-002-12 | La verificación pertenece a su `conversation_id`: no se traslada a otra conversación, y cada conversación tiene su propio contador de intentos. | Issue #27; Art. 7 |
| RN-002-13 | El servidor ofrece a las demás herramientas una consulta del estado de verificación de una conversación (cliente verificado o ninguno); una conversación sin verificación exitosa —o desconocida— se considera no verificada. | Art. 7; `mcp-tools.md` §5 |
| RN-002-14 | La respuesta contiene **solo** `verified`, `attempts_remaining` y `escalation_required`. Nunca las fechas registradas, saldos, productos, movimientos, documento completo, números de tarjeta ni el nombre del cliente. | Issue #27; Art. 7; `mcp-tools.md` §8 |
| RN-002-15 | Cada invocación genera exactamente un registro de auditoría con `conversation_id` (o vacío si no llegó), fecha y hora del reloj inyectado, `tool = "verificar_identidad"`, `customer_id` recibido y resultado: `verified`, `already_verified`, `failed` con el número de intento, `locked` (3.er fallo y solicitudes posteriores en una conversación bloqueada), `other_customer`, o el código de error. El registro **nunca** contiene las fechas recibidas ni las registradas, ni en claro ni derivadas. | Art. 8; issue #27 |
| RN-002-16 | Ante una falla inesperada (p. ej. el repositorio de clientes no responde), la herramienta devuelve `INTERNAL` con `retryable = false`, sin datos del cliente ni detalles internos (trazas, SQL); no cuenta como intento fallido y no cambia el estado de la conversación. | Art. 10; issue #27; `mcp-tools.md` §7 |

## 5. Tabla de decisión de `DisputePolicy`

No aplica: la verificación de identidad no decide sobre disputas.

## 6. Criterios de aceptación

En todos los criterios, salvo que se indique otra cosa: existe la cliente `C-0001` "Laura Méndez" con nacimiento `1990-03-15` y expedición `2008-04-20`; existe el cliente `C-0002` "Pedro Ríos" con nacimiento `1985-07-02` y expedición `2003-08-10`; la conversación todavía no tiene cliente verificado ni intentos fallidos; y el reloj inyectado marca `2026-10-17T15:00:00Z`.

### AC-002-01 — Ambas fechas correctas verifican al cliente

Cubre: HU-002-01, RN-002-01, RN-002-02, RN-002-09

- **When** se invoca `verificar_identidad` con `customer_id = "C-0001"`, `birth_date = "1990-03-15"` y `document_issue_date = "2008-04-20"`
- **Then** la respuesta es `verified = true`, `attempts_remaining = 3`, `escalation_required = false`
- **And** el estado de verificación de la conversación indica el cliente `C-0001`

### AC-002-02 — Basta una fecha incorrecta para no verificar

Cubre: HU-002-02, RN-002-02, RN-002-03

- **When** se invoca `verificar_identidad` con `customer_id = "C-0001"`, `birth_date = <nacimiento>` y `document_issue_date = <expedición>`
- **Then** la respuesta es `verified = false`, `attempts_remaining = 2`, `escalation_required = false`
- **And** la respuesta no indica cuál dato fue incorrecto
- **And** la conversación sigue sin cliente verificado

| nacimiento | expedición |
|---|---|
| `1990-03-16` | `2008-04-20` |
| `1990-03-15` | `2008-04-21` |
| `1990-03-16` | `2008-04-21` |

La fila de la issue con las fechas intercambiadas (`2008-04-20` / `1990-03-15`) tiene la expedición anterior al nacimiento y se trata en AC-002-03.

### AC-002-03 — Fechas intercambiadas

Cubre: HU-002-02, RN-002-02, RN-002-07

- **When** se invoca `verificar_identidad` con `customer_id = "C-0001"`, `birth_date = "2008-04-20"` y `document_issue_date = "1990-03-15"` (las fechas registradas, intercambiadas)
- **Then** se devuelve el error `INVALID_INPUT` con `retryable = false` (la expedición es anterior al nacimiento)
- **And** la conversación sigue sin cliente verificado y sin intentos fallidos

### AC-002-04 — Un cliente inexistente responde igual que unas fechas incorrectas

Cubre: HU-002-02, RN-002-03, RN-002-04

- **Given** no existe ningún cliente con `customer_id = "C-9999"`
- **When** se invoca `verificar_identidad` con `customer_id = "C-9999"`, `birth_date = "1990-03-15"` y `document_issue_date = "2008-04-20"`
- **Then** la respuesta es idéntica (campo a campo) a la de AC-002-02: `verified = false`, `attempts_remaining = 2`, `escalation_required = false`
- **And** la conversación acumula 1 intento fallido

### AC-002-05 — Límite de intentos fallidos

Cubre: HU-002-02, HU-002-03, RN-002-04, RN-002-06

- **Given** la conversación acumula `<fallos previos>` intentos fallidos
- **When** se invoca `verificar_identidad` para `C-0001` con `birth_date = "1990-03-16"` y `document_issue_date = "2008-04-20"`
- **Then** la respuesta es `verified = false`, `attempts_remaining = <restantes>`, `escalation_required = <derivar>`

| fallos previos | restantes | derivar |
|---|---|---|
| 0 | 2 | `false` |
| 1 | 1 | `false` |
| 2 | 0 | `true` |

### AC-002-06 — Fechas correctas antes de agotar los intentos

Cubre: HU-002-01, RN-002-05

- **Given** la conversación acumula 2 intentos fallidos
- **When** se invoca `verificar_identidad` para `C-0001` con `birth_date = "1990-03-15"` y `document_issue_date = "2008-04-20"`
- **Then** la respuesta es `verified = true`, `attempts_remaining = 1`, `escalation_required = false`
- **And** el estado de verificación de la conversación indica el cliente `C-0001`

### AC-002-07 — Tras agotar los intentos ni las fechas correctas verifican

Cubre: HU-002-02, HU-002-03, RN-002-05, RN-002-06

- **Given** la conversación acumula 3 intentos fallidos (bloqueada)
- **When** se invoca `verificar_identidad` para `C-0001` con `birth_date = "1990-03-15"` y `document_issue_date = "2008-04-20"`
- **Then** la respuesta es `verified = false`, `attempts_remaining = 0`, `escalation_required = true`
- **And** la conversación sigue sin cliente verificado

### AC-002-08 — Datos de verificación inválidos

Cubre: RN-002-07, RN-002-08

- **When** se invoca `verificar_identidad` para `C-0001` con `<dato>` (el resto de campos válidos)
- **Then** se devuelve el error `INVALID_INPUT` con `retryable = false`
- **And** la conversación sigue sin cliente verificado y sin intentos fallidos

| dato |
|---|
| `birth_date = ""` |
| `document_issue_date = ""` |
| `birth_date` ausente o `null` |
| `document_issue_date` ausente o `null` |
| `birth_date = "1990-02-31"` (inexistente) |
| `document_issue_date = "2008-02-31"` (inexistente) |
| `birth_date = "15/03/1990"` (formato distinto de `AAAA-MM-DD`) |
| `birth_date = "2026-10-18"` (posterior a hoy) |
| `document_issue_date = "2026-10-18"` (posterior a hoy) |
| `birth_date = "1990-03-15"`, `document_issue_date = "1990-03-14"` (expedición anterior al nacimiento) |
| `customer_id` ausente, vacío o solo espacios |
| `customer_id` de 33 caracteres |
| `conversation_id` ausente, vacío o solo espacios |

### AC-002-09 — Límites de las fechas válidas

Cubre: RN-002-07, RN-002-08

- **Given** el reloj inyectado marca `<instante>` (UTC)
- **When** se invoca `verificar_identidad` con `customer_id = "C-9999"`, `birth_date = "1990-03-15"` y `document_issue_date = <expedición>`
- **Then** el resultado es `<resultado>`

| instante | expedición | resultado |
|---|---|---|
| `2026-10-17T15:00:00Z` | `2026-10-17` (hoy en Bogotá) | `verified = false` (datos válidos) |
| `2026-10-18T03:00:00Z` | `2026-10-18` (aún 17 en Bogotá) | `INVALID_INPUT` |
| `2026-10-18T05:00:00Z` | `2026-10-18` (ya 18 en Bogotá) | `verified = false` (datos válidos) |
| `2026-10-17T15:00:00Z` | `1990-03-15` (igual al nacimiento) | `verified = false` (datos válidos) |

### AC-002-10 — Los datos inválidos no consumen intentos

Cubre: RN-002-04, RN-002-07

- **Given** la conversación acumula 2 intentos fallidos
- **When** se invoca `verificar_identidad` para `C-0001` con `birth_date = "1990-02-31"`
- **Then** se devuelve `INVALID_INPUT`
- **And** una invocación posterior para `C-0001` con las fechas correctas devuelve `verified = true`

### AC-002-11 — Solo un cliente verificado por conversación

Cubre: HU-002-01, RN-002-10

- **Given** la conversación ya está verificada para `C-0001`
- **When** se invoca `verificar_identidad` para `<cliente>` con `<fechas>`
- **Then** la respuesta es `verified = false`, `attempts_remaining = 3`, `escalation_required = false`
- **And** el estado de verificación de la conversación sigue indicando `C-0001`

| cliente | fechas |
|---|---|
| `C-0002` | `1985-07-02` / `2003-08-10` (correctas de Pedro) |
| `C-0002` | `1985-07-03` / `2003-08-10` (incorrectas) |
| `C-9999` | `1990-03-15` / `2008-04-20` (inexistente) |

### AC-002-12 — Re-verificar al mismo cliente es idempotente

Cubre: RN-002-11

- **Given** la conversación ya está verificada para `C-0001`
- **When** se invoca `verificar_identidad` para `C-0001` con `<fechas>`
- **Then** la respuesta es `verified = true`, `attempts_remaining = 3`, `escalation_required = false`
- **And** la conversación sigue verificada para `C-0001` sin intentos fallidos

| fechas |
|---|
| `1990-03-15` / `2008-04-20` (correctas) |
| `1990-03-16` / `2008-04-20` (incorrectas) |

### AC-002-13 — La verificación no se traslada a otra conversación

Cubre: HU-002-04, RN-002-12, RN-002-13

- **Given** la conversación `A` está verificada para `C-0001` y la conversación `B` no ha invocado ninguna herramienta
- **When** se consulta el estado de verificación de `B`
- **Then** `B` no está verificada
- **And** una invocación en `B` para `C-0001` con `birth_date = "1990-03-16"` devuelve `verified = false` y `attempts_remaining = 2` (la verificación de `A` no aplica y el contador de `B` es propio)
- **And** el estado de `A` sigue indicando `C-0001`

### AC-002-14 — La respuesta no expone datos personales

Cubre: HU-002-02, RN-002-14

- **When** se invoca `verificar_identidad` para `C-0001` con `<fechas>`
- **Then** la respuesta contiene exactamente los campos `verified`, `attempts_remaining` y `escalation_required`
- **And** en ninguna parte de la respuesta aparecen `1990-03-15`, `2008-04-20`, `Laura Méndez`, `D-1001` ni un número de tarjeta

| fechas |
|---|
| `1990-03-15` / `2008-04-20` (correctas) |
| `1990-03-16` / `2008-04-20` (incorrectas) |

### AC-002-15 — Cada invocación queda auditada sin las fechas

Cubre: HU-002-05, RN-002-15

- **Given** un reloj inyectado fijo
- **When** se invoca `verificar_identidad` produciendo `<caso>`
- **Then** queda exactamente 1 registro de auditoría con `conversation_id`, la fecha y hora del reloj, `tool = "verificar_identidad"`, el `customer_id` recibido y `<resultado registrado>`
- **And** el registro no contiene ninguna de las fechas recibidas ni registradas

| caso | resultado registrado |
|---|---|
| ambas fechas correctas | `verified` |
| conversación ya verificada para el mismo cliente | `already_verified` |
| alguna fecha incorrecta (1.er fallo) | `failed`, intento 1 |
| el 3.er fallo | `locked` |
| solicitud en una conversación ya bloqueada | `locked` |
| conversación verificada para otro cliente | `other_customer` |
| datos inválidos | código `INVALID_INPUT` |
| falla inesperada | código `INTERNAL` |

### AC-002-16 — Falla inesperada

Cubre: HU-002-03, RN-002-16

- **Given** el repositorio de clientes falla de forma inesperada
- **When** se invoca `verificar_identidad` para `C-0001` con `birth_date = "1990-03-15"` y `document_issue_date = "2008-04-20"`
- **Then** se devuelve el error `INTERNAL` con `retryable = false`
- **And** el mensaje no contiene trazas, SQL ni el texto de la excepción original
- **And** la conversación sigue sin cliente verificado y sin intentos fallidos

## 7. Contratos de herramientas MCP

### `verificar_identidad`

- **Propósito:** confirmar que quien conversa es el cliente localizado, comparando su fecha de nacimiento y la fecha de expedición de su documento con las registradas.
- **Cuándo usarla / cuándo no:** después de `buscar_cliente`, con el `customer_id` del cliente elegido y **antes** de cualquier herramienta que muestre o modifique datos de su cuenta. No sirve para localizar clientes. Si responde `verified = false` con `attempts_remaining > 0`, pedir de nuevo las fechas sin decir cuál falló; si responde `escalation_required = true`, no reintentar y derivar a un analista.
- **Precondiciones:** ninguna sobre identidad (excepción del Art. 7, `mcp-tools.md` §5). Exige `conversation_id`.
- **Efectos secundarios:** registra en memoria del servidor el cliente verificado o el intento fallido de la conversación, y un registro de auditoría. No es idempotente salvo cuando la conversación ya está verificada para el mismo cliente (RN-002-11).

**Entrada**

| Campo | Tipo | Obligatorio | Descripción / validación |
|---|---|---|---|
| `conversation_id` | `string` | Sí | Identificador de correlación; no vacío tras recortar. |
| `customer_id` | `string` | Sí | `customer_id` devuelto por `buscar_cliente`; 1–32 caracteres tras recortar. |
| `birth_date` | `string` | Sí | Fecha de nacimiento `AAAA-MM-DD`; existente en el calendario y no posterior a hoy (RN-002-07/08). |
| `document_issue_date` | `string` | Sí | Fecha de expedición del documento `AAAA-MM-DD`; existente, no posterior a hoy y no anterior a `birth_date`. |

**Salida** (no admite campos adicionales)

| Campo | Tipo | Descripción |
|---|---|---|
| `verified` | `bool` | `true` si la conversación queda (o ya estaba) verificada para ese `customer_id`. |
| `attempts_remaining` | `int` (0–3) | Intentos de verificación que le quedan a la conversación (3 − fallos acumulados). |
| `escalation_required` | `bool` | `true` si la conversación está bloqueada y el caso debe derivarse a un analista. |

Ejemplos:

- Éxito: `{"verified": true, "attempts_remaining": 3, "escalation_required": false}`
- Fecha incorrecta o cliente inexistente (1.er fallo): `{"verified": false, "attempts_remaining": 2, "escalation_required": false}`
- Bloqueada: `{"verified": false, "attempts_remaining": 0, "escalation_required": true}`
- Conversación verificada para otro cliente: `{"verified": false, "attempts_remaining": <sin cambios>, "escalation_required": false}`

**Errores** (formato `{code, message, retryable}`, `mcp-tools.md` §7)

| Código | Tipo | Reintentable | Cuándo ocurre |
|---|---|---|---|
| `INVALID_INPUT` | validación | No | Entrada que viola RN-002-07. No consume intentos. |
| `INTERNAL` | interno | No | Falla inesperada del core (RN-002-16). El consumidor debe escalar (Art. 10). |

### Consulta interna del estado de verificación

No es una herramienta MCP: es la capacidad del servidor que las herramientas futuras usarán para validar el Art. 7 (RN-002-13). Dado un `conversation_id`, devuelve el `customer_id` verificado o indica que la conversación no está verificada.

## 8. Casos de escalamiento

Esta feature no ejecuta escalamientos (`escalar_a_analista` está fuera de alcance); solo señala al consumidor cuándo debe derivar.

| Condición | Motivo | Datos del resumen estructurado |
|---|---|---|
| `verificar_identidad` responde `escalation_required = true` | 3 intentos fallidos de verificación en la conversación (RN-002-04/05) | Lo definirá la spec de `escalar_a_analista`; como mínimo `conversation_id`, `customer_id` intentado y motivo "verificación bloqueada". Nunca las fechas. |
| `verificar_identidad` devuelve `INTERNAL` (`retryable = false`) | Falla no recuperable del core (Art. 10) | Como mínimo `conversation_id`, `customer_id` y código de error. |

## 9. Clarificaciones

| Fecha | Pregunta | Respuesta | Secciones afectadas |
|---|---|---|---|
| 2026-10-17 | ¿Qué alcance tiene la feature? | Solo el servidor MCP: herramienta, contrato, estado de verificación por conversación y auditoría. El agente y el escalamiento quedan fuera. | §2, §7, §8 |
| 2026-10-17 | ¿Cómo responde una verificación no exitosa? | Respuesta exitosa `{verified, attempts_remaining, escalation_required}`, no un error. Los errores quedan para `INVALID_INPUT` e `INTERNAL`. | RN-002-03/05/06, AC-002-02/04/05/07, §7 |
| 2026-10-17 | ¿Cuánto dura la verificación? | Mientras viva el proceso del servidor MCP; en memoria, sin expiración ni persistencia. | RN-002-09, §2 |
| 2026-10-17 | ¿Los datos inválidos cuentan como intento fallido? | No: `INVALID_INPUT` no consume intentos ni cambia el estado. | RN-002-07, AC-002-08, AC-002-10 |
| 2026-10-17 | ¿Qué pasa si la conversación ya está verificada y se intenta verificar a otro cliente? | `verified = false`, sin contar intento ni derivar; el cliente verificado no cambia. | RN-002-10, AC-002-11 |
| 2026-10-17 | ¿En qué zona horaria se calcula "hoy"? | `America/Bogota`, a partir del reloj inyectado. | RN-002-08, AC-002-09 |
| 2026-10-17 | ¿Cómo se indica el cliente a verificar? | Con el `customer_id` devuelto por `buscar_cliente`; fechas en ISO `AAAA-MM-DD`. | RN-002-01, RN-002-07, §7 |
| 2026-10-17 | ¿Qué pasa si la conversación ya está verificada para el mismo cliente y llegan fechas incorrectas? | `verified = true` sin evaluar las fechas ni contar intentos. | RN-002-11, AC-002-12 |
| 2026-10-17 | La issue pide que las fechas intercambiadas sean un intento fallido, pero también que una expedición anterior al nacimiento sea un dato inválido. ¿Cuál prevalece? | Prevalece la validación: las fechas intercambiadas (expedición anterior al nacimiento) son `INVALID_INPUT` y no consumen intento. Confirmado por el usuario al aprobar la spec. | RN-002-07, AC-002-02, AC-002-03 |

## 10. Preguntas abiertas

Ninguna.

## 11. Historial de cambios

| Versión | Fecha | Cambio | Autor |
|---|---|---|---|
| 0.1.0 | 2026-10-17 | Versión inicial a partir de la issue #27 | Juangiov (con Claude Code) |
| 0.1.0 | 2026-10-17 | Spec aprobada por el usuario | Juangiov |

---

## Gate de salida

- [x] No quedan preguntas abiertas.
- [x] Cada clarificación está reflejada en las secciones afectadas.
- [x] Todos los criterios de aceptación tienen ID y formato Given/When/Then.
- [x] Cada regla de negocio está cubierta por al menos un criterio de aceptación.
- [x] Contratos MCP y casos de escalamiento completos o marcados "No aplica".
- [x] Estado cambiado a **Aprobada**.
