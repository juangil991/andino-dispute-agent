# Tareas: Derivar un caso a un analista humano con un resumen estructurado

| Campo | Valor |
|---|---|
| Feature | `006-analyst-escalation` |
| Spec | [spec.md](./spec.md) — versión 0.1.0 |
| Plan | [plan.md](./plan.md) — versión 0.1.0 |
| Fecha | 2026-10-17 |

**Estados:** `[ ]` pendiente · `[~]` en curso · `[x]` terminada

Rutas relativas a la raíz del repositorio.

- Los `__init__.py` de los paquetes ya existen (`domain/models`, `application/ports`, `application/use_cases`, `infrastructure/inbound/mcp` y `infrastructure/outbound/persistence`).
- Solo T-006-02 escribe en `tests/fakes/`; las demás tareas reutilizan los fakes sin modificarlos.
- Las tareas que cambian un contrato que usan los tests de 001–005 adaptan esos tests en la misma tarea, para que la suite siga en verde al terminar cada oleada. T-006-02 incluye los campos nuevos de `AuditEvent`, su serialización JSON y `find_by_id` en los fakes de disputas.
- **mypy transitorio:** T-006-02 añade `find_by_id` al puerto `DisputeRepository`; el adaptador SQL lo implementa en T-006-06. Entre ambas, `mypy --strict src` puede marcar `SqlAlchemyDisputeRepository` como incompatible con el puerto. pytest no se ve afectado, y la verificación final (T-006-10) lo comprueba.

**TDD evidenciable (Art. 3, §5.1):** en cada tarea, ejecutar primero el test y comprobar que falla por el motivo indicado en **Red** antes de escribir código de producción; informarlo en el resultado.

**Comentarios de trazabilidad** (`mcp-testing.md` §3–5; lecciones de las auditorías de 002–005):

1. Un test llamado `test_ac_006_NN_*` lleva **encima del `def`** `# Regla: RN-006-XX — <enunciado literal completo de spec §4>`, una línea por RN. Cada RN citada debe figurar en la línea `Cubre:` de AC-006-NN. Debajo va `# AC-006-NN · Art. N`. Solo se usa ese prefijo si el test ejecuta el Given/When/Then de ese AC, o una de sus filas, con su Arrange real: un parámetro que no entra en el Arrange no reproduce el Given.
2. Un test de invariante (Art. 7, sin identificación) cita `# Invariante: Art. N — <enunciado>` y la línea `AC-006-NN · Art. N` del AC al que da soporte, con las mismas condiciones.
3. Un test de soporte puro (fakes, builders, mapeos técnicos sin AC) no lleva el prefijo `ac_006_` y declara `# Soporte de tests: <qué> · Art. 3`. Queda fuera de la trazabilidad de AC. Un test de soporte en `tests/integration/` cita además una RN y un AC que realmente ejecute, o una `Invariante:`.
4. Los tests de `tests/contract/` y `tests/integration/` se nombran `test_ac_006_NN_<tool o componente>__<condición>__<resultado>`. Los parametrizados llevan `ids=` legibles.
5. Las aserciones del test reproducen el **Then** completo del AC, incluidas las líneas `And`, no un subconjunto.
6. Antes de citar una RN o un AC, comprobar en `spec.md` el `Cubre:` del AC y copiar el enunciado literal de la RN. No citar RN inexistentes: la spec llega a RN-006-16.

---

## Tareas

### [x] T-006-01 — Value objects `EscalationReason`, `PriorAction`, `EscalationStatus`, `EscalationRequest` y `Escalation`

- **Cubre** (a nivel de dominio): AC-006-02 (motivos permitidos), AC-006-03 (motivo inválido), AC-006-07 (acciones previas incoherentes), AC-006-09 (nota), AC-006-10 (nota sin PAN) y AC-006-16 (datos inválidos). Habilita AC-006-01…20 (plan §4 Dominio).
- **App / capa:** `core_banking_mcp` / `domain`
- **Depende de:** —
- **Archivos:** `src/core_banking_mcp/domain/models/escalation.py`, `tests/unit/core_banking_mcp/domain/test_escalation.py`
- **Test primero:** `tests/unit/core_banking_mcp/domain/test_escalation.py::test_ac_006_03_escalation_request_rejects_invalid_reason`
- **Red:** falla con `ImportError` porque `escalation.py` no existe. Tests:
  - `test_ac_006_03_...`: `"FRAUD"`, `"fraud_suspected"`, `"sospecha de fraude"`, `""` y `None` lanzan `InvalidInputError` con `field = "reason"`.
  - `test_ac_006_02_escalation_request_accepts_every_reason`: los 7 códigos de RN-006-02 crean un `EscalationRequest` con ese `EscalationReason`.
  - `test_ac_006_07_escalation_request_rejects_incoherent_prior_actions`: las 7 filas de AC-006-07 lanzan `InvalidInputError`:
    - `DISPUTE_OPENED` sin `dispute_id`;
    - `DISPUTE_OPENED` sin `transaction_id`;
    - `dispute_id` sin `DISPUTE_OPENED`;
    - `CARD_BLOCKED` sin `card_id`;
    - un código repetido;
    - `"CARD_CANCELLED"`;
    - `"card_blocked"` en minúsculas.
  - `test_ac_006_09_escalation_request_normalizes_note`, con las 6 filas de AC-006-09:
    - 1 carácter y 300 caracteres se conservan;
    - 300 caracteres rodeados de espacios se guardan recortados;
    - 301 caracteres lanzan `InvalidInputError` con `field = "note"`;
    - ausente, `None`, `""` y solo espacios dan `note = None`.
  - `test_ac_006_10_escalation_request_redacts_card_numbers_in_note`: `"Cliente dicta la tarjeta 4111111111114321 y pide ayuda"` queda como `"Cliente dicta la tarjeta [REDACTED] y pide ayuda"`.
  - `test_ac_006_16_escalation_request_rejects_invalid_fields`: las 9 filas de AC-006-16 lanzan `InvalidInputError` con el `field` correspondiente. 64 caracteres (borde exacto) es válido en cada id.
  - Soporte (`# Soporte de tests: invariantes de EscalationRequest y Escalation · Art. 3`):
    - Los valores se guardan recortados.
    - `has_customer_data` es verdadero solo con `transaction_id`, `card_id` o `dispute_id`.
    - `Escalation` rechaza textos obligatorios vacíos, `escalated_at` sin zona y un resumen limitado con datos del cliente (`identity_verified = False` con `customer_id`, ids o `prior_actions`).
    - `Escalation.same_request(request)` es `True` solo si coinciden `reason`, `transaction_id`, `card_id`, `prior_actions` (como conjunto, en cualquier orden), `dispute_id` y `note` normalizados.
    - `ordered_prior_actions()` devuelve los códigos en el orden del catálogo (`DISPUTE_OPENED`, `CARD_BLOCKED`).
- **Green:** todos `dataclass(frozen=True)` y solo stdlib.
  - `EscalationReason(Enum)` con los 7 códigos; `PriorAction(Enum)` con `DISPUTE_OPENED` y `CARD_BLOCKED`, en ese orden; `EscalationStatus(Enum)` con `PENDING`.
  - `EscalationRequest.create(conversation_id, reason, idempotency_key, transaction_id=None, card_id=None, prior_actions=None, dispute_id=None, note=None)`:
    - acepta `str | None` en los textos y `Sequence[str] | None` en `prior_actions`;
    - usa `MAX_ID_LENGTH` y `_require_text` de `domain/models/dispute.py`;
    - define `MAX_NOTE_LENGTH = 300`;
    - redacta la nota con `redact_card_numbers` de `domain/masking.py`.
  - `Escalation(...)` con los atributos del plan §4, las invariantes en `__post_init__`, `same_request` y `ordered_prior_actions`.
- **Refactor:** extraer la validación de un id opcional (`None` o 1–64 caracteres tras recortar) a una función privada.

### [x] T-006-02 — Puertos `EscalationRepository` y `DisputeRepository.find_by_id`, error, `AuditEvent` ampliado, serialización JSON y fakes

- **Nota:** el subagente no ejecutó en Red aislado los dos tests de `test_json_audit_log.py` (los escribió antes del código, pero solo observó el Red del test de fakes); el ciclo de esos dos no es evidenciable. `test_fake_dispute_repositories_find_by_id` es débil para `FailingDisputeRepository`: solo comprueba `None` en un repositorio vacío. `mypy --strict src` marca `server.py:76` (`SqlAlchemyDisputeRepository` sin `find_by_id`): transitorio esperado hasta T-006-06.

- **Cubre:** AC-006-20, a nivel de integración del adaptador de auditoría. Es regresión de AC-001-13, AC-002-15, AC-003-17, AC-004-17 y AC-005-15, y habilita AC-006-01…20 en unit e integración (plan §3 y §6).
- **App / capa:** `core_banking_mcp` / `application` (más el ajuste de `infrastructure/outbound/audit`, para no dejar en rojo la auditoría de 001–005)
- **Depende de:** T-006-01
- **Archivos:** `src/core_banking_mcp/application/ports/escalation_repository.py`, `src/core_banking_mcp/application/ports/dispute_repository.py`, `src/core_banking_mcp/application/errors.py`, `src/core_banking_mcp/application/ports/audit_log.py`, `src/core_banking_mcp/infrastructure/outbound/audit/json_audit_log.py`, `tests/fakes/escalation_builder.py`, `tests/fakes/fake_escalation_repository.py`, `tests/fakes/failing_escalation_repository.py`, `tests/fakes/fake_dispute_repository.py`, `tests/fakes/failing_dispute_repository.py`, `tests/unit/core_banking_mcp/application/test_escalation_fakes.py`, `tests/integration/core_banking_mcp/audit/test_json_audit_log.py`
- **Test primero:** `tests/unit/core_banking_mcp/application/test_escalation_fakes.py::test_fake_escalation_repository_finds_by_key_and_adds`
- **Red:** falla con `ImportError` porque no existen el puerto ni los fakes. Tests de soporte (`# Soporte de tests: ... · Art. 3`):
  - `EscalationBuilder().build()` crea una `Escalation` válida y admite `with_id`, `with_conversation`, `with_key`, `with_reason`, `with_escalated_at`, `verified_for(customer_id)` (resumen completo), `with_transaction`, `with_card`, `with_prior_actions`, `with_dispute` y `with_note`.
  - `FakeEscalationRepository`:
    - `find_by_key(conversation_id, key)` solo encuentra la derivación de esa conversación.
    - `add(...)` asigna `ESC-000001`, `ESC-000002`, …, guarda y devuelve la `Escalation`.
    - Respeta la unicidad por `(conversation_id, key)` y expone las derivaciones guardadas y si se llamó a `add`.
  - `FailingEscalationRepository`: `add` lanza `RuntimeError` sin registrar nada; `find_by_key` funciona; `repair()` hace que el siguiente `add` funcione.
  - `FakeDisputeRepository.find_by_id(dispute_id)` devuelve la disputa o `None`; `FailingDisputeRepository` también lo implementa. Los tests existentes de los fakes de disputas siguen en verde.
  - `EscalationDataNotFoundError` existe.
  - `AuditEvent` se construye sin los campos nuevos (por defecto `None` y `prior_actions = ()`).
  - En `test_json_audit_log.py`, dos tests nuevos:
    - `test_ac_006_20_json_audit_log__escalation_event__serialized_without_pan`: un evento de `escalar_a_analista` con `escalation_reason`, `escalation_id`, `prior_actions`, `note = "tarjeta [REDACTED]"`, `card_id = "[REDACTED]"`, `idempotency_key`, `masked_card` e `identity_verified = false` escribe una línea JSON válida con esos campos (`identity_verified` presente como `false`), sin ningún PAN ni documento.
    - `test_ac_006_20_json_audit_log__escalation_event_without_optional_fields__omits_keys`: con los campos nuevos a `None` y `prior_actions = ()`, la línea no trae esas claves. Las líneas de 001–005 no cambian de claves y nada sale por `stdout`.
- **Green:**
  - Puerto `EscalationRepository` con:
    - `find_by_key(conversation_id, idempotency_key) -> Escalation | None`
    - `add(conversation_id, idempotency_key, reason, escalated_at, identity_verified, customer_id, transaction_id, card_id, prior_actions, dispute_id, note) -> Escalation`, documentado como atómico.
  - `DisputeRepository.find_by_id(dispute_id) -> Dispute | None`.
  - `EscalationDataNotFoundError` en `application/errors.py`.
  - `AuditEvent` gana al final `escalation_reason`, `escalation_id`, `note` (`str | None = None`), `prior_actions` (`tuple[str, ...] = ()`) e `identity_verified` (`bool | None = None`). Los cinco se añaden a `_OPTIONAL_KEYS` de `JsonAuditLog`: se omiten si son `None` o `[]`, y `false` se conserva (`prior_actions` se serializa como lista).
  - Los builders y fakes descritos.
- **Refactor:** —

### [x] T-006-03 — Caso de uso `EscalateToAnalyst` (comportamiento)

- **Nota:** los tests de AC-006-12 y AC-006-17 agrupan todas las filas en un solo test con fakes y un único mensaje fijo; la herramienta y la auditoría los vuelven a comprobar en T-006-08. Se omitieron RN-006-12 y RN-006-13 en las citas de AC-006-01 y AC-006-10 porque son reglas de la capa de respuesta.

- **Cubre:** AC-006-01, AC-006-02, AC-006-03, AC-006-04, AC-006-05, AC-006-06, AC-006-07, AC-006-08, AC-006-09, AC-006-10, AC-006-11, AC-006-12, AC-006-13, AC-006-14, AC-006-15, AC-006-16, AC-006-17, AC-006-19
- **App / capa:** `core_banking_mcp` / `application`
- **Depende de:** T-006-02
- **Archivos:** `src/core_banking_mcp/application/use_cases/escalate_to_analyst.py`, `tests/unit/core_banking_mcp/application/test_escalate_to_analyst.py`
- **Test primero:** `tests/unit/core_banking_mcp/application/test_escalate_to_analyst.py::test_ac_006_01_escalates_verified_case_with_full_summary`
- **Red:** falla porque `EscalateToAnalyst` no existe.
  - **Fixtures comunes:**
    - `FakeTransactionRepository`: `C-0001` con `TX-L1`, `CONFIRMED`, de `85000.00 COP` en "Tienda Aurora" el `2026-10-10T12:00:00-05:00` sobre `CARD-L1`.
    - `FakeCardRepository`: `C-0001` con `CARD-L1`, `ACTIVE`, terminada en `4321`.
    - `FakeDisputeRepository` vacío y `FakeEscalationRepository`.
    - `FakeVerificationStore`: conversación `A` verificada para `C-0001` salvo que se indique.
    - `FakeAuditLog` y `FixedClock` en `2026-10-17T15:00:00Z`.
  - **Tests:**
    - `test_ac_006_01_...`: con `TX-L1` y `CARD-L1` devuelve `EscalationResult` con `outcome = "escalated"`. La `Escalation` trae `status = PENDING`, `escalated_at` igual al reloj, `identity_verified = True` y `customer_id = "C-0001"`; el resultado incluye la `Transaction` y la `OwnedCard`. Hay 1 derivación en el fake. El almacén no cambia y no se escribe en transacciones, tarjetas ni disputas.
    - `test_ac_006_02_...` (7 códigos).
    - `test_ac_006_03_...`, `test_ac_006_07_...`, `test_ac_006_09_...` (fila de 301 caracteres) y `test_ac_006_16_...`: las entradas inválidas lanzan `InvalidInputError` sin consultar el almacén ni los repositorios.
    - `test_ac_006_04_...`: las 3 situaciones sin datos del cliente dan `escalated` con resumen limitado (`identity_verified = False`, `customer_id = None`, ids `None` y `prior_actions` vacío). No se consultan transacciones, tarjetas ni disputas, y el almacén no cambia.
    - `test_ac_006_05_...`: las 6 situaciones con datos del cliente lanzan `IdentityNotVerifiedError` sin consultar los repositorios; el almacén queda igual.
    - `test_ac_006_06_...`: las 4 filas, con `D-1` `OPEN` en el fake de disputas y `CARD-L1` `BLOCKED` donde aplique. Se comprueban `prior_actions` y `dispute_id` de la derivación, y `ordered_prior_actions()`.
    - `test_ac_006_08_...`: las 4 filas lanzan `EscalationDataNotFoundError` sin llamar a `add`. Son `D-2` de `TX-L2`, `D-P1` de `C-0002`, `D-9999` inexistente y `CARD_BLOCKED` con la tarjeta `ACTIVE`.
    - `test_ac_006_09_...`: las filas válidas guardan la nota normalizada.
    - `test_ac_006_10_...`: la derivación guardada tiene la nota redactada.
    - `test_ac_006_11_...`: con la nota "de instrucción", `D-1` sigue `OPEN`, `CARD-L1` `ACTIVE` y `TX-L1` sin cambios. El único método de escritura invocado es `EscalationRepository.add`.
    - `test_ac_006_12_...`: las 5 filas (transacción y tarjeta ajenas o inexistentes, y `TX-L1` con `CARD-L2`) lanzan `EscalationDataNotFoundError`. Los repositorios se consultan con el `customer_id` del almacén.
    - `test_ac_006_13_...`: las 3 filas. La segunda ejecución, con el reloj una hora después, devuelve la misma `Escalation` con `outcome = "replayed"` y deja 1 sola derivación; la transacción y la tarjeta se rehidratan.
    - `test_ac_006_14_...`: las 5 variaciones con `K-1` lanzan `InvalidInputError` sin llamar a `add`.
    - `test_ac_006_15_...`: `K-2` en `A`, y `K-1` en `B` verificada para `C-0001`, crean una segunda derivación con otro `escalation_id`; la primera no cambia.
    - `test_ac_006_17_...`: las 6 filas devuelven el primer resultado según RN-006-11. La quinta es una repetición tras pasar la tarjeta a `ACTIVE` en el fake, y devuelve `replayed` con la derivación original.
    - `test_ac_006_19_...`: con `FailingEscalationRepository` lanza `CoreUnavailableError` sin el texto de la excepción y sin derivación. Tras `repair()`, la misma solicitud con `K-1` da `escalated`.
- **Green:**
  - `EscalateCommand(conversation_id, reason, idempotency_key, transaction_id, card_id, prior_actions, dispute_id, note)`, con textos `str | None` y `prior_actions: Sequence[str] | None`.
  - `EscalationResult(escalation, transaction, card, outcome)`.
  - `EscalateToAnalyst(transactions, cards, disputes, escalations, store, audit_log, clock).execute(command)`, en el orden de RN-006-11 y el plan §1:
    1. `EscalationRequest.create`.
    2. `store.get`; si `has_customer_data` y no está verificada, `IdentityNotVerifiedError`.
    3. `find_by_key`: con `same_request` es una repetición y rehidrata con el `customer_id` guardado; si no coincide, `InvalidInputError`.
    4. Resuelve la transacción, la tarjeta y su coherencia → `EscalationDataNotFoundError`.
    5. Contrasta las acciones previas → `EscalationDataNotFoundError`.
    6. `add(..., clock.now(), ...)`.
  - Las excepciones inesperadas posteriores a la validación (incluida una rehidratación fallida) se convierten en `CoreUnavailableError`.
  - Nunca llama a `store.save` ni a métodos de escritura de transacciones, tarjetas o disputas.
  - El constructor ya recibe `audit_log`, pero esta tarea no lo usa (lo cubre T-006-04).
- **Refactor:** extraer métodos privados por paso (`_replay`, `_resolve_customer_data`, `_check_prior_actions`) si `execute` supera ~30 líneas, como en `BlockCard`.

### [x] T-006-04 — Auditoría de `EscalateToAnalyst`

- **Nota:** el subagente solo ejecutó en Red el parametrizado de 9 casos (fallaron los 9); los 3 tests extra del mismo AC (`conversation_id` ausente, `dispute_id` y `prior_actions` recibidos, `prior_actions` inválidas) se escribieron junto al código. `masked_card` queda con la tarjeta en `INTERNAL` si ya se resolvió (spec RN-006-16 solo la define como «de la tarjeta del cliente verificado», sin tratar este caso); se revisa en la auditoría de AC (fase 5.5).

- **Cubre:** AC-006-20
- **App / capa:** `core_banking_mcp` / `application`
- **Depende de:** T-006-03
- **Archivos:** `src/core_banking_mcp/application/use_cases/escalate_to_analyst.py`, `tests/unit/core_banking_mcp/application/test_escalate_to_analyst_audit.py`
- **Test primero:** `tests/unit/core_banking_mcp/application/test_escalate_to_analyst_audit.py::test_ac_006_20_each_invocation_records_exactly_one_event`
- **Red:** el parametrizado con los 9 casos de AC-006-20 falla porque no se registra ningún evento.
  - En cada caso debe quedar exactamente un evento con:
    - `conversation_id` (vacío si no llegó), el instante del `FixedClock`, `tool = "escalar_a_analista"` e `input = None`.
    - `escalation_reason`, `idempotency_key`, `transaction_id`, `card_id`, `dispute_id`, `prior_actions` y `note` recibidos. Cada uno vacío si no llegó o no es válido según RN-006-10, y los textos libres redactados con `redact_card_numbers`.
    - `masked_card = "**** 4321"` solo si la tarjeta del cliente verificado ya se resolvió; `None` en `NOT_FOUND`, `INVALID_INPUT` y sin verificación.
    - `identity_verified`: `True` o `False` según el almacén, y `None` si la validación falló antes de leerlo.
    - `outcome` `escalated` o `replayed`, con `escalation_id`; o `error` con `error_code` `INVALID_INPUT`, `IDENTITY_NOT_VERIFIED`, `NOT_FOUND` o `INTERNAL`.
    - `rule` y `reason` según el plan §1.
  - Casos concretos:
    - Con `reason = "FRAUD"`, `escalation_reason` es `None`.
    - Con `card_id = "4111111111114321"`, el evento trae `"[REDACTED]"`, `NOT_FOUND` y `masked_card = None`.
    - Con `note = "tarjeta 4111111111114321"`, trae `"tarjeta [REDACTED]"` y `escalated`.
    - En la conversación `B` sin verificar y sin datos, trae `escalated` con `identity_verified = False`.
  - Ni el evento serializado con `dataclasses.asdict` ni su texto contienen `4111111111114321` ni `D-1001`.
- **Green:** `EscalateToAnalyst` llama una vez a `audit_log.record(AuditEvent(...))` en cada salida.
  - Usa las reglas del plan §1, un motivo en español y el `customer_id` verificado cuando ya se conoce.
  - Los textos libres se auditan con un `_audited_id` / `_audited_note` equivalente al de `block_card.py`; `escalation_reason` y `prior_actions` solo con códigos del catálogo.
- **Refactor:** consolidar la construcción del evento en un método privado `_record`, como en `BlockCard`.

### [x] T-006-05 — Esquemas MCP de salida de `escalar_a_analista` (contrato)

- **Nota:** las citas `# Regla:` de AC-006-03 (RN-006-02) y AC-006-07 (RN-006-05) son un fragmento del enunciado, y la de RN-006-08 en AC-006-04 es una versión abreviada, no el literal de spec §4. Los tests de AC-006-04, 06, 07 y 09 prueban solo el esquema, no el Given/When/Then completo, que cubren las tareas posteriores. Queda para la auditoría de AC (fase 5.5).

- **Cubre:**
  - AC-006-18: campos exactos y `additionalProperties: false` en `EscalarAnalistaOut`, `EscalationSummaryOut` y `EscalationCardOut`.
  - AC-006-01: la salida cumple `EscalarAnalistaOut`.
  - AC-006-02: enum de `reason` en la salida.
  - AC-006-04 y AC-006-09: `null` admitido en `customer_id`, `transaction`, `card`, `dispute_id` y `note`.
  - AC-006-06: enum de los elementos de `prior_actions`.
  - AC-006-12: catálogo con `NOT_FOUND`.
  - AC-006-16 y AC-006-19: sobre `ToolErrorOut`.
  - AC-006-03 y AC-006-07: constantes que publican los `enum` de entrada.
- **App / capa:** `core_banking_mcp` / `infrastructure/inbound`
- **Depende de:** —
- **Archivos:** `src/core_banking_mcp/infrastructure/inbound/mcp/schemas.py`, `tests/contract/core_banking_mcp/test_escalar_a_analista_contract.py`
- **Test primero:** `tests/contract/core_banking_mcp/test_escalar_a_analista_contract.py::test_ac_006_18_escalar_a_analista__output_schema__has_exactly_spec_fields`
- **Red:** falla con `ImportError` porque `EscalarAnalistaOut` no existe. Además:
  - `EscalarAnalistaOut` tiene `additionalProperties: false` y exactamente `escalation_id`, `status`, `escalated_at`, `reason` y `summary`.
    - `status` admite solo `PENDING`.
    - `reason` admite solo los 7 códigos (`test_ac_006_02_...`).
  - `EscalationSummaryOut` tiene `additionalProperties: false` y exactamente `conversation_id`, `identity_verified`, `customer_id`, `transaction`, `card`, `prior_actions`, `dispute_id` y `note`.
    - `transaction` es `TransactionItemOut` o `null`.
    - `card` es `EscalationCardOut` o `null`.
    - `prior_actions` es una lista de `DISPUTE_OPENED` / `CARD_BLOCKED`.
    - Los demás campos admiten `null` según la spec §7 (`test_ac_006_04_...`, `test_ac_006_06_...`, `test_ac_006_09_...`).
  - `EscalationCardOut` tiene exactamente `card_id` y `masked_card`.
  - El esquema de entrada de la herramienta se probará en el catálogo (T-006-09). Aquí se prueban las constantes `ESCALATION_REASON_CODES` (7 códigos) y `PRIOR_ACTION_CODES` (2 códigos) (`test_ac_006_03_...`, `test_ac_006_07_...`).
  - `ErrorCode` sigue siendo exactamente el catálogo de 7 códigos de 005 e incluye `NOT_FOUND` (`test_ac_006_12_...`).
  - `ToolErrorOut` sigue con `code`, `message` y `retryable` (`test_ac_006_16_...`, `test_ac_006_19_...`).
- **Green:** en `schemas.py`:
  - `ESCALATION_REASON_CODES` y `PRIOR_ACTION_CODES`.
  - `EscalationCardOut`, `EscalationSummaryOut` y `EscalarAnalistaOut`, con `extra="forbid"`, `status: Literal["PENDING"]`, `reason` y `prior_actions` como `Literal`, y todos los campos con `Field(description=...)`.
  - `ErrorCode` no cambia.
- **Refactor:** —

### [x] T-006-06 — Tabla `escalations`, adaptador `SqlAlchemyEscalationRepository` y `SqlAlchemyDisputeRepository.find_by_id`

- **Nota:** el subagente solo ejecutó en Red aislado `test_ac_006_13_...` y `test_ac_006_08_...`; los otros cuatro tests de `test_sqlalchemy_escalation_repository.py` comparten módulo con el `ImportError` y no se observaron fallar por separado, por lo que su ciclo Red → Green no es evidenciable. Los tests usan una disputa real (`DSP-000001`) en lugar del literal `D-1`.

- **Cubre** (a nivel de repositorio):
  - AC-006-04: `identity_verified = false` con los datos nulos.
  - AC-006-06: `prior_actions` en texto canónico y de vuelta.
  - AC-006-08: `find_by_id` de una disputa ajena o inexistente.
  - AC-006-10: la nota se guarda tal como llega (ya redactada).
  - AC-006-13: búsqueda por clave.
  - AC-006-15: varias derivaciones por conversación.
  - AC-006-19: rollback; no queda la fila.
- **App / capa:** `core_banking_mcp` / `infrastructure/outbound`
- **Depende de:** T-006-02
- **Archivos:** `src/core_banking_mcp/infrastructure/outbound/persistence/models/tables.py`, `src/core_banking_mcp/infrastructure/outbound/persistence/sqlalchemy_escalation_repository.py`, `src/core_banking_mcp/infrastructure/outbound/persistence/sqlalchemy_dispute_repository.py`, `tests/integration/core_banking_mcp/persistence/test_sqlalchemy_escalation_repository.py`, `tests/integration/core_banking_mcp/persistence/test_sqlalchemy_dispute_repository.py`
- **Test primero:** `tests/integration/core_banking_mcp/persistence/test_sqlalchemy_escalation_repository.py::test_ac_006_13_escalation_repository__find_by_key__returns_only_same_conversation`
- **Red:** falla porque `EscalationRow` y el adaptador no existen. Entorno: SQLite `:memory:`; clientes, tarjetas y transacciones creados con builders vía `SqlAlchemyCustomerRepository` y `SqlAlchemyTransactionRepository`; disputas con `SqlAlchemyDisputeRepository.add`. Tests:
  - `test_ac_006_13_...`:
    - `add` de una derivación completa (`C-0001`, `TX-L1`, la tarjeta `4321`, `prior_actions = {DISPUTE_OPENED, CARD_BLOCKED}`, `D-1` y una nota) asigna `ESC-000001`.
    - `find_by_key("A", "K-1")` la devuelve con todos los datos, `escalated_at` en UTC con `tzinfo=UTC` y `prior_actions` como conjunto.
    - `("B", "K-1")` devuelve `None`.
    - La pareja `(conversation_id, idempotency_key)` es única.
  - `test_ac_006_04_...`: una derivación limitada se guarda con `identity_verified = 0` y columnas de datos nulas, y se lee igual.
  - `test_ac_006_06_...`: la columna `prior_actions` guarda `"DISPUTE_OPENED,CARD_BLOCKED"` (orden de catálogo) o `""`.
  - `test_ac_006_10_...`: la columna `note` guarda el texto recibido sin modificarlo.
  - `test_ac_006_15_...`: dos `add` en la misma conversación con claves distintas dan `ESC-000001` y `ESC-000002`.
  - `test_ac_006_19_...`: un `add` que viola el índice único hace `rollback`, no deja la fila y la sesión sigue usable (una lectura y un `add` válido posteriores funcionan).
  - En `test_sqlalchemy_dispute_repository.py`, `test_ac_006_08_dispute_repository__find_by_id__returns_dispute_or_none`: devuelve la disputa con su `transaction_id` y su estado, y `None` para un id inexistente.
- **Green:**
  - `EscalationRow`, según el plan §4:
    - `escalation_id` como PK `String`.
    - FK nulas a `customers`, `transactions`, `cards.card_id` y `disputes`.
    - `identity_verified` `Boolean`, `prior_actions` `String` y `note` nula.
    - Índice único `ux_escalations_conversation_key`.
  - `SqlAlchemyEscalationRepository(session)` implementa el puerto:
    - mapea `card_ref` ↔ `card_id` de dominio y `prior_actions` ↔ texto canónico;
    - genera `ESC-NNNNNN` con el recuento, como `DSP-NNNNNN`;
    - `add` hace `INSERT` + `commit`, y `rollback` y relanza ante cualquier excepción.
  - `SqlAlchemyDisputeRepository.find_by_id`.
- **Refactor:** —

### [x] T-006-07 — Herramienta `escalar_a_analista` (camino exitoso)

- **Nota:** en los tests el `card_id` real es `CARD-0001` (lo genera el repositorio de clientes al insertar) y `D-1` es el `dispute_id` que devuelve `iniciar_disputa`; `CARD-L1` y `D-1` de la spec son simbólicos. El harness usa `FakeAuditLog` y no comprueba eventos de auditoría (lo hace T-006-08).

- **Cubre:** AC-006-01, AC-006-02, AC-006-04, AC-006-06, AC-006-09, AC-006-10, AC-006-11, AC-006-13, AC-006-15, AC-006-18
- **App / capa:** `core_banking_mcp` / `infrastructure/inbound`
- **Depende de:** T-006-03, T-006-05, T-006-06
- **Archivos:** `src/core_banking_mcp/infrastructure/inbound/mcp/escalation_tools.py`, `tests/integration/core_banking_mcp/mcp/test_escalar_a_analista_tool.py`
- **Test primero:** `tests/integration/core_banking_mcp/mcp/test_escalar_a_analista_tool.py::test_ac_006_01_escalar_a_analista__verified_conversation__returns_full_summary`
- **Red:** falla porque `register_escalation_tools` no existe.
  - **Entorno:** el mismo que `test_bloquear_tarjeta_tool.py`:
    - sesión MCP en memoria (`mcp.shared.memory`);
    - SQLite `:memory:` con clientes, tarjetas y transacciones de builders;
    - el `InMemoryConversationVerificationStore` real con la conversación `A` verificada para `C-0001`;
    - `FakeAuditLog` y `FixedClock` en `2026-10-17T15:00:00Z`.

    El servidor de prueba registra también `iniciar_disputa`, `bloquear_tarjeta`, `verificar_identidad` y `buscar_cliente` sobre los mismos repositorios y el mismo almacén, para preparar el estado previo.
  - **Casos:**
    - AC-006-01: con `TX-L1` y `CARD-L1`, todos los campos de la spec:
      - `escalated_at = "2026-10-17T10:00:00-05:00"`, `status = "PENDING"`;
      - `summary` con `customer_id = "C-0001"` y `identity_verified = true`;
      - `transaction` completo y `card = {"card_id": ..., "masked_card": "**** 4321"}`.

      Hay 1 fila en `escalations`, `TX-L1` sigue sin disputas y `CARD-L1` sigue `ACTIVE`.
    - AC-006-02: los 7 códigos.
    - AC-006-04: las 3 situaciones en la conversación `B`:
      - nunca verificada;
      - agotada con 3 `verificar_identidad` fallidos;
      - solo un `buscar_cliente` sin coincidencias.

      Resumen limitado con todos los campos nulos y `prior_actions = []`; el almacén no cambia.
    - AC-006-06: las 4 filas, con `D-1` creada por `iniciar_disputa` y el bloqueo hecho con `bloquear_tarjeta` en `A`.
    - AC-006-09: las 5 filas válidas (`summary.note` y la columna `note`).
    - AC-006-10: la nota redactada en la respuesta y en la fila, sin `4111111111114321`.
    - AC-006-11: tras la nota "de instrucción", `D-1` sigue `OPEN`, `TX-L1` `CONFIRMED` y `CARD-L1` `ACTIVE`; no hay filas nuevas en `disputes` ni en `card_blocks`.
    - AC-006-13: las 3 filas. La segunda llamada con `K-1` y el reloj una hora después devuelve la misma respuesta, y hay 1 fila.
    - AC-006-15: las 2 filas (`K-2` en `A`; `K-1` en `B` verificada con `verificar_identidad`). Hay 2 filas y la primera no cambia.
    - AC-006-18: la respuesta serializada solo tiene los campos de RN-006-12 y no contiene `4111111111114321`, `D-1001` ni `Laura Méndez`.
- **Green:** `register_escalation_tools(mcp, escalate)` registra `escalar_a_analista`.
  - Firma `str | None` en los textos y `list[str] | None` en `prior_actions`, con `Field(description=...)`. `reason` publica `json_schema_extra={"enum": list(ESCALATION_REASON_CODES)}` y `prior_actions` publica `{"items": {"enum": list(PRIOR_ACTION_CODES)}}`.
  - Docstring en español según la spec §7: no exige identidad salvo con datos del cliente, cuándo usarla y cuándo no, cómo actuar ante cada respuesta, efectos e idempotencia.
  - Devuelve `CallToolResult` con `structuredContent` de `EscalarAnalistaOut`:
    - `escalated_at` en Bogotá;
    - `summary.transaction` con `to_transaction_item`;
    - `summary.card` con `mask_card`;
    - `prior_actions` con `ordered_prior_actions()`.
  - Registra `ErrorPassthroughMetadata`, como `card_tools.py`.
  - El mapeo de errores queda para T-006-08.
- **Refactor:** —

### [x] T-006-08 — `escalar_a_analista`: errores, identidad y auditoría

- **Nota:** el test de AC-006-20 del caso `invalid` espera que la línea de auditoría no traiga `identity_verified` (el caso de uso lo deja en `None` si la validación falla antes de leer el almacén); la spec RN-006-16 no define ese caso, se revisa en la auditoría de AC (fase 5.5). Los ids simbólicos de la spec se traducen a los reales del core (`CARD-L1` → `CARD-0001`, `CARD-P1` → `CARD-0003`, disputas `DSP-00000N`). El nombre del test de AC-006-05 supera 100 caracteres y lleva `# noqa: E501`.

- **Cubre:** AC-006-03, AC-006-05, AC-006-07, AC-006-08, AC-006-09 (fila de 301 caracteres), AC-006-12, AC-006-14, AC-006-16, AC-006-17, AC-006-19, AC-006-20
- **App / capa:** `core_banking_mcp` / `infrastructure/inbound`
- **Depende de:** T-006-04, T-006-07
- **Archivos:** `src/core_banking_mcp/infrastructure/inbound/mcp/escalation_tools.py`, `tests/integration/core_banking_mcp/mcp/test_escalar_a_analista_errors.py`
- **Test primero:** `tests/integration/core_banking_mcp/mcp/test_escalar_a_analista_errors.py::test_ac_006_05_escalar_a_analista__customer_data_without_verification__returns_identity_not_verified`
- **Red:** falla porque las excepciones del caso de uso se propagan sin sobre de error. Con la misma sesión MCP en memoria:
  - AC-006-05: las 6 situaciones devuelven `isError=true`, `IDENTITY_NOT_VERIFIED` y `retryable = false`. No hay filas en `escalations` y el almacén queda igual. En la situación de dos conversaciones, `A` se verifica con `verificar_identidad` y la solicitud se hace en `B`.
  - `INVALID_INPUT` con `retryable = false` y ninguna fila adicional en estas filas:
    - AC-006-03 (5 filas);
    - AC-006-07 (7 filas);
    - AC-006-09 (301 caracteres);
    - AC-006-14 (5 filas);
    - AC-006-16 (9 filas).
  - AC-006-08 (4 filas) y AC-006-12 (5 filas) devuelven `NOT_FOUND` con `retryable = false`. Todos los sobres son iguales entre sí campo a campo y no contienen datos de `C-0002`; ninguna fila en `escalations`.
  - AC-006-17: las 6 filas devuelven el resultado esperado. En la quinta, `cards.status` se cambia a `ACTIVE` directamente en la base tras la primera derivación, y la repetición devuelve la derivación original.
  - AC-006-19: con `FailingEscalationRepository` → `INTERNAL` con `retryable = false`, sin el texto de la excepción, trazas ni SQL, y sin filas.
  - AC-006-20: con un `JsonAuditLog` real sobre un `StringIO`, cada uno de los 9 casos deja una sola línea JSON con la herramienta, los datos recibidos, `masked_card`, `identity_verified` y el resultado esperado. Ninguna línea contiene `4111111111114321` ni `D-1001`.
- **Green:** en `escalation_tools.py`, todos con `retryable=False`. Ningún mensaje incluye el texto de la excepción ni el valor recibido.

  | Excepción | Código | Mensaje |
  |---|---|---|
  | `InvalidInputError` | `INVALID_INPUT` | `"Los datos de la solicitud no son válidos (campo: {error.field})."` |
  | `IdentityNotVerifiedError` | `IDENTITY_NOT_VERIFIED` | fijo |
  | `EscalationDataNotFoundError` | `NOT_FOUND` | constante única del módulo |
  | `CoreUnavailableError` y *catch-all* defensivo | `INTERNAL` | fijo, p. ej. `"El caso no pudo derivarse a un analista."` |
- **Refactor:** —

### [x] T-006-09 — Cableado del servidor, catálogo y smoke por stdio

- **Nota:** el test de `stdout` (`test_escalar_a_analista__audited_call__stdout_carries_only_protocol`, renombrado en T-006-11) es un invariante que no puede fallar en Red (el servidor ya responde JSON-RPC aunque la herramienta no exista); lanza el servidor como subproceso y comprueba que cada línea de stdout es JSON-RPC válido. Cierra la deuda de 005 solo para 006; los smoke de 002–005 siguen sin esa aserción.

- **Cubre:**
  - AC-006-01: por stdio real, resumen completo sobre la tarjeta semilla `CARD-0001`.
  - AC-006-04: derivación sin verificar.
  - AC-006-05: almacén compartido con `verificar_identidad`.
  - AC-006-18: esquemas en el catálogo.
  - Catálogo de herramientas (`mcp-testing.md` §7).
- **App / capa:** `core_banking_mcp` / arranque
- **Depende de:** T-006-08
- **Archivos:** `src/core_banking_mcp/server.py`, `tests/contract/core_banking_mcp/test_tool_catalog.py`, `tests/integration/core_banking_mcp/test_server_module.py`, `tests/integration/core_banking_mcp/test_stdio_smoke.py`
- **Test primero:** `tests/contract/core_banking_mcp/test_tool_catalog.py::test_ac_006_18_catalog_exposes_escalar_a_analista_with_spec_schemas`
- **Red:**
  - **Catálogo:** falla porque `list_tools` no incluye `escalar_a_analista`.
    - El test espera las seis herramientas y falla ante herramientas no declaradas.
    - Compara el esquema de entrada (8 campos con descripción, el `enum` de `reason` y el de los elementos de `prior_actions`) y el de salida con `EscalarAnalistaOut.model_json_schema()` (`additionalProperties: false`).
    - Los tests existentes de 001–005 del archivo pasan a esperar las seis herramientas.
  - **`test_server_module.py`:** `server.mcp` expone las seis herramientas.
  - **`test_stdio_smoke.py`**, por stdio real y con la base sembrada:
    - `test_ac_006_04_escalar_a_analista__stdio_server__unverified_conversation_gets_limited_summary`: sin verificar, con `IDENTITY_VERIFICATION_FAILED`, devuelve `status = "PENDING"` e `identity_verified = false`.
    - `test_ac_006_01_escalar_a_analista__stdio_server__verified_conversation_gets_full_summary`: tras `verificar_identidad` de `C-0001`, con `card_id = "CARD-0001"`, devuelve `customer_id = "C-0001"` y `card.masked_card = "**** 4321"`.
    - `test_ac_006_05_escalar_a_analista__stdio_server__customer_data_without_verification_is_rejected`: otra conversación con `card_id` recibe `IDENTITY_NOT_VERIFIED`.
    - `stdout` solo lleva protocolo: se comprueba con una aserción explícita, pendiente desde la auditoría de 005.
- **Green:** `build_server` crea `SqlAlchemyEscalationRepository(session)` y construye `EscalateToAnalyst` con los repositorios SQL de transacciones, tarjetas, disputas y derivaciones, la **misma** instancia de `InMemoryConversationVerificationStore` que las demás herramientas, `JsonAuditLog()` y `SystemClock()`. Después llama a `register_escalation_tools`. `main()` y el `__getattr__` no cambian.
- **Refactor:** —

### [x] T-006-10 — Verificación final

- **Cubre:** Definition of Done (§5.5): AC-006-01…20 en verde, cobertura, lint, formato y tipado.
- **App / capa:** `core_banking_mcp` / todas
- **Depende de:** T-006-01, T-006-02, T-006-03, T-006-04, T-006-05, T-006-06, T-006-07, T-006-08, T-006-09
- **Archivos:** — (solo verificación; no modifica archivos)
- **Test primero:** `uv run pytest --cov` (suite completa de 001–006)
- **Red:** si algún comando falla, la tarea queda `[ ]` con el motivo y se corrige en la tarea que corresponda.
- **Green:** pasan sin errores:
  - `uv run pytest --cov` (umbral global ≥ 80 %)
  - `uv run coverage report --include="src/core_banking_mcp/domain/*,src/core_banking_mcp/application/*" --fail-under=90`
  - `uv run ruff check .`
  - `uv run ruff format --check .`
  - `uv run mypy --strict src`
- **Refactor:** —

## Correcciones de la primera auditoría de AC (fase 5.5, veredicto «No cumple»: 0 Bloqueantes, 1 Mayor y 2 Menores)

Cambios de trazabilidad en los tests, sin cambio de comportamiento ni de `src/` (§4.3.5): no hay Red de pytest; el Red es el hallazgo de `verify-ac-coverage` (`H-01…H-03`). La suite debe seguir en verde. Regla única de la cabecera: cada RN o AC citado debe corresponder a lo que el test verifica, y los comentarios van **encima** del `def`.

### [x] T-006-11 — H-01 y H-02: test de `stdout` con cita de AC que no verifica y nombre fuera del patrón

- **Cubre:** corrige H-01 y H-02
- **App / capa:** `core_banking_mcp` / arranque (tests)
- **Depende de:** T-006-10
- **Archivos:** `tests/integration/core_banking_mcp/test_stdio_smoke.py`
- **Test primero:** el mismo test existente `test_ac_006_04_server_stdio__audited_call__stdout_carries_only_protocol` (debe seguir en verde, ya renombrado)
- **Red:** H-01: el test (`:640-641`) cita `AC-006-04 · Art. 7`, pero solo comprueba que cada línea de `stdout` es JSON-RPC válido; no verifica el resumen limitado ni el estado de verificación que exige AC-006-04. H-02: su nombre no incluye `escalar_a_analista`, a diferencia de los demás tests de 006 de ese archivo (`:486`, `:546`, `:607`).
- **Green:** mantener `# Invariante: Art. 12 / mcp-tools §12 …` y sustituir la línea `# AC-006-04 · Art. 7 (soporte…)` por `# Soporte de tests · Art. 12`; quitar «Soporte de AC-006-04» del docstring. Renombrarlo a `test_escalar_a_analista__audited_call__stdout_carries_only_protocol`, sin el prefijo `ac_006_04`, y actualizar cualquier referencia al nombre antiguo (por ejemplo la nota de T-006-09).
- **Refactor:** —

### [x] T-006-12 — H-03: parametrizar el test del orden de las comprobaciones

- **Cubre:** corrige H-03 (AC-006-17)
- **App / capa:** `core_banking_mcp` / `application` (tests)
- **Depende de:** T-006-10
- **Archivos:** `tests/unit/core_banking_mcp/application/test_escalate_to_analyst.py`
- **Test primero:** `tests/unit/core_banking_mcp/application/test_escalate_to_analyst.py::test_ac_006_17_checks_are_evaluated_in_order` (ahora parametrizado, con una fila por resultado)
- **Red:** H-03: el test (`:815`) es un único test con seis bloques secuenciales, pero el plan §6 pide el caso de uso «parametrizado con las 6 filas» de AC-006-17. Una falla en la fila 2 oculta las filas 3 a 6.
- **Green:** convertirlo en un `@pytest.mark.parametrize` con las 6 filas de AC-006-17 de la spec §6 y `ids=` legibles, como hace `test_escalar_a_analista_errors.py` (`:527`). Cada fila prepara su propio Arrange, comprueba el mismo resultado que hoy y conserva los comentarios `# Regla:` y `# AC-006-17 · Art. N` encima del `def`. El nombre del test no cambia.
- **Refactor:** —

## Matriz de trazabilidad

| AC | Tareas | Tests |
|---|---|---|
| AC-006-01 | T-006-03, T-006-05, T-006-07, T-006-09 | `test_ac_006_01_escalates_verified_case_with_full_summary`, `test_ac_006_01_escalar_a_analista__verified_conversation__returns_full_summary`, `test_ac_006_01_escalar_a_analista__stdio_server__verified_conversation_gets_full_summary`, `test_ac_006_01_*` (contrato) |
| AC-006-02 | T-006-01, T-006-03, T-006-05, T-006-07 | `test_ac_006_02_escalation_request_accepts_every_reason`, `test_ac_006_02_*` (caso de uso, contrato y herramienta) |
| AC-006-03 | T-006-01, T-006-03, T-006-05, T-006-08 | `test_ac_006_03_escalation_request_rejects_invalid_reason`, `test_ac_006_03_*` (caso de uso, contrato y herramienta) |
| AC-006-04 | T-006-03, T-006-05, T-006-06, T-006-07, T-006-09 | `test_ac_006_04_*` (caso de uso, contrato, repositorio y herramienta), `test_ac_006_04_escalar_a_analista__stdio_server__unverified_conversation_gets_limited_summary` |
| AC-006-05 | T-006-03, T-006-08, T-006-09 | `test_ac_006_05_escalar_a_analista__customer_data_without_verification__returns_identity_not_verified`, `test_ac_006_05_escalar_a_analista__stdio_server__customer_data_without_verification_is_rejected`, `test_ac_006_05_*` (caso de uso) |
| AC-006-06 | T-006-03, T-006-05, T-006-06, T-006-07 | `test_ac_006_06_*` (caso de uso, contrato, repositorio y herramienta) |
| AC-006-07 | T-006-01, T-006-03, T-006-05, T-006-08 | `test_ac_006_07_escalation_request_rejects_incoherent_prior_actions`, `test_ac_006_07_*` (caso de uso, contrato y herramienta) |
| AC-006-08 | T-006-03, T-006-06, T-006-08 | `test_ac_006_08_dispute_repository__find_by_id__returns_dispute_or_none`, `test_ac_006_08_*` (caso de uso y herramienta) |
| AC-006-09 | T-006-01, T-006-03, T-006-05, T-006-07, T-006-08 | `test_ac_006_09_escalation_request_normalizes_note`, `test_ac_006_09_*` (caso de uso, contrato y herramienta) |
| AC-006-10 | T-006-01, T-006-03, T-006-06, T-006-07 | `test_ac_006_10_escalation_request_redacts_card_numbers_in_note`, `test_ac_006_10_*` (caso de uso, repositorio y herramienta) |
| AC-006-11 | T-006-03, T-006-07 | `test_ac_006_11_*` (caso de uso y herramienta) |
| AC-006-12 | T-006-03, T-006-05, T-006-08 | `test_ac_006_12_*` (caso de uso, contrato y herramienta) |
| AC-006-13 | T-006-03, T-006-06, T-006-07 | `test_ac_006_13_escalation_repository__find_by_key__returns_only_same_conversation`, `test_ac_006_13_*` (caso de uso y herramienta) |
| AC-006-14 | T-006-03, T-006-08 | `test_ac_006_14_*` (caso de uso y herramienta) |
| AC-006-15 | T-006-03, T-006-06, T-006-07 | `test_ac_006_15_*` (caso de uso, repositorio y herramienta) |
| AC-006-16 | T-006-01, T-006-03, T-006-05, T-006-08 | `test_ac_006_16_escalation_request_rejects_invalid_fields`, `test_ac_006_16_*` (caso de uso, contrato y herramienta) |
| AC-006-17 | T-006-03, T-006-08 | `test_ac_006_17_*` (caso de uso y herramienta) |
| AC-006-18 | T-006-05, T-006-07, T-006-09 | `test_ac_006_18_escalar_a_analista__output_schema__has_exactly_spec_fields`, `test_ac_006_18_catalog_exposes_escalar_a_analista_with_spec_schemas`, `test_ac_006_18_*` (herramienta) |
| AC-006-19 | T-006-03, T-006-05, T-006-06, T-006-08 | `test_ac_006_19_*` (caso de uso, contrato, repositorio y herramienta) |
| AC-006-20 | T-006-02, T-006-04, T-006-08 | `test_ac_006_20_json_audit_log__escalation_event__serialized_without_pan`, `test_ac_006_20_each_invocation_records_exactly_one_event`, `test_ac_006_20_*` (herramienta) |

- **Casos de escalamiento (spec §8):**
  - Motivos de cada condición: AC-006-02 (T-006-01, T-006-03, T-006-07).
  - Derivación sin verificación: AC-006-04 (T-006-03, T-006-07, T-006-09).
  - `INTERNAL` de la propia herramienta: AC-006-19 (T-006-03, T-006-06, T-006-08).
- **Art. 7 (datos del cliente sin identificación previa):** AC-006-05 (T-006-03, T-006-08, T-006-09), con la comprobación de que la herramienta no escribe en el almacén (RN-006-14).
- **Tabla `DP-`:** no aplica.
- **Tareas de soporte sin AC propio:** ninguna (T-006-02 cubre AC-006-20 en el adaptador de auditoría). T-006-11 y T-006-12 son correcciones de trazabilidad de la auditoría de AC; no añaden cobertura.

---

## Cierre de la feature

Definition of Done según constitución §5.5:

- [x] Todos los AC trazados a tests en verde.
- [x] Umbrales de cobertura cumplidos.
- [x] Lint, formato y tipado sin errores.
- [x] Spec actualizada al comportamiento implementado.
- [x] Sin secretos ni datos reales.
