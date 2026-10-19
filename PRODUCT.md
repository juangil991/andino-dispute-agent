# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Clientes de Banco Andino (banco completamente ficticio) que detectan un cobro que no reconocen o con el que no están de acuerdo y quieren reportar una disputa o solicitar un contracargo. Suelen llegar preocupados, a menudo desde el móvil, y necesitan saber rápido qué se hizo con su caso. Audiencia secundaria (inferida de la naturaleza del repositorio, no confirmada): evaluadores de la prueba técnica que revisan el demo.

## Product Purpose

Agente de IA que atiende por chat web las disputas de transacciones y solicitudes de contracargo. Identifica al cliente, consulta sus transacciones, decide por cada transacción disputada (resolver, rechazar o escalar) y actúa sobre el core bancario simulado. Éxito: máxima resolución en primer contacto, cero casos resueltos automáticamente que debían escalarse, trazabilidad total y respuestas que explican qué se hizo, por qué y cuáles son los próximos pasos.

## Positioning

La decisión sobre cada disputa la toma un motor de reglas determinista en el dominio (`DisputePolicy`), no el LLM: el modelo conversa, el dominio decide. Toda acción sobre el core pasa por herramientas MCP, nada se expone sin identificar al cliente, y ante la duda se escala a un humano.

## Operating Context

Chat web → API FastAPI (`dispute_agent`) → servidor MCP por stdio (`core_banking_mcp`) → SQLite con datos sintéticos reproducibles. Las respuestas del agente se muestran en streaming, palabra por palabra. Flujo SDD: specs en `specs/NNN-*/`.

## Capabilities and Constraints

- Front: HTML + CSS con JavaScript vanilla mínimo (solo `fetch`/streaming), servido por FastAPI como estáticos desde `src/dispute_agent/infrastructure/inbound/web/static/`.
- Mensajes al cliente y documentación en español; código e identificadores en inglés.
- Fuera de alcance: integraciones reales con bancos o pasarelas, dinero o PII reales, bandeja de trabajo para analistas humanos.
- Fuente de verdad: `docs/constitution.md`.

## Brand Commitments

Banco ficticio: sin logos ni marcas reales. Voz en español claro y empático, sin jerga bancaria, que informa qué se hizo, por qué y los próximos pasos.

## Evidence on Hand

Constitución y specs 001–009 (`docs/`, `specs/`). No existen testimonios, métricas ni casos de clientes reales; no deben fabricarse.

## Product Principles

1. Claridad ante la ansiedad: el cliente siempre entiende en qué punto está su caso.
2. Transparencia de las decisiones: toda resolución, rechazo o escalamiento se explica con su motivo.
3. Seguridad primero: identificación antes que información.
4. Ante la duda, escalar a una persona.
5. Nada inventado: datos sintéticos declarados, sin pruebas sociales ficticias.

## Accessibility & Inclusion

WCAG 2.2 AA y móvil primero: contraste suficiente, uso completo con teclado, soporte de lector de pantalla incluyendo respuestas que llegan en streaming.
