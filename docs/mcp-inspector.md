# Probar el servidor MCP con MCP Inspector

Guía para probar a mano `buscar_cliente` y `verificar_identidad`. Usa solo datos ficticios de las semillas (Art. 1). Esta guía no se ha probado con el Inspector; las respuestas esperadas salen de la spec 002 (AC-002-01/02/05/07/08/13).

## Requisitos

- Node.js (el Inspector se ejecuta con `npx`).
- Dependencias del proyecto: `uv sync`.

## Arranque

```
uv run mcp dev src/core_banking_mcp/server.py
```

## Avisos

- Si viene de la feature 001, borre `data/core_banking.db` antes de arrancar: el esquema cambió y no existe migración.
- La verificación y el contador de intentos viven en el proceso del servidor (RN-002-09). Al reconectar el Inspector se reinicia ese estado.
- La auditoría sale por `stderr` en JSON, una línea por evento.

## Semillas usadas

| Cliente | Documento | Nacimiento | Expedición |
|---|---|---|---|
| `C-0001` | `D-1001` | `1990-03-15` | `2008-04-20` |
| `C-0002` | `D-1002` | `1985-07-02` | `2003-08-10` |

## Llamadas de ejemplo

`conversation_id` es un argumento obligatorio de cada llamada a `buscar_cliente` y `verificar_identidad` (si falta, responde `INVALID_INPUT`). Escríbalo en cada llamada (p. ej. `conv-A`). Cada valor distinto es una conversación nueva con su propio contador de intentos, sin necesidad de reconectar. Solo reconectar el Inspector reinicia el estado de todas las conversaciones (RN-002-09).

| # | Herramienta y argumentos | Respuesta esperada |
|---|---|---|
| 1 | `buscar_cliente` con documento `D-1001` y `conversation_id = "conv-A"` | Devuelve el cliente `C-0001` |
| 2 | `verificar_identidad` con `customer_id = "C-0001"`, `birth_date = "1990-03-15"`, `document_issue_date = "2008-04-20"` (conversación `conv-A`) | `{verified: true, attempts_remaining: 3, escalation_required: false}` |
| 3a | `verificar_identidad` con `C-0001` y `birth_date = "1990-03-16"` (conversación nueva `conv-B`) | `{verified: false, attempts_remaining: 2, escalation_required: false}` |
| 3b | La misma llamada incorrecta repetida hasta el 3.er fallo | `{verified: false, attempts_remaining: 0, escalation_required: true}` |
| 3c | Después, con las fechas correctas de `C-0001` en `conv-B` | Sigue `{verified: false, attempts_remaining: 0, escalation_required: true}` (bloqueada, sin desbloqueo) |
| 4a | `verificar_identidad` con `conversation_id = "conv-D"` y `birth_date = "1990-02-31"` (fecha inexistente) | Error `INVALID_INPUT`, `retryable = false`, sin consumir intentos |
| 4b | En `conv-D`, `document_issue_date` anterior a `birth_date` (p. ej. `1990-03-14`) | Error `INVALID_INPUT`, sin consumir intentos |
| 4c | En `conv-D`, cualquier fecha posterior a hoy | Error `INVALID_INPUT`, sin consumir intentos |
| 5 | `verificar_identidad` para `C-0001` con `birth_date = "1990-03-16"` en otra conversación (`conv-C`) | La verificación de `conv-A` no aplica: `{verified: false, attempts_remaining: 2, escalation_required: false}` (contador propio) |
