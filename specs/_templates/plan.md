# Plan: <Nombre de la feature>

<!-- Cómo se implementa la spec aprobada. No redefinir comportamiento: si falta algo, se corrige la spec primero (constitución §4.3.3). -->

| Campo | Valor |
|---|---|
| Feature | `NNN-feature-name` |
| Versión | 0.1.0 |
| Estado | Borrador \| En revisión \| Aprobado |
| Fecha | AAAA-MM-DD |
| Spec | [spec.md](./spec.md) — versión <x.y.z> aprobada |
| Tareas | [tasks.md](./tasks.md) |

---

## 1. Resumen técnico

<!-- Enfoque elegido en pocas líneas. -->

<...>

## 2. Componentes por capa

<!-- Respetar las reglas de dependencia de la constitución §3.2. -->

| App | Capa | Componente | Nuevo / Modificado | Cambio |
|---|---|---|---|---|
| `dispute_agent` \| `core_banking_mcp` | `domain` \| `application` \| `infrastructure/inbound` \| `infrastructure/outbound` | <clase / módulo> | <...> | <...> |

## 3. Puertos y adaptadores

| Puerto | Nuevo / Modificado | Adaptador(es) | Notas |
|---|---|---|---|
| <PortName> | <...> | <AdapterName> | <...> |

## 4. Modelo de datos

### Dominio

| Entidad / value object | Atributos | Invariantes |
|---|---|---|
| <...> | <...> | <...> |

### Persistencia (`core_banking_mcp`)

| Tabla | Columnas relevantes | Cambio |
|---|---|---|
| <...> | <...> | <...> |

### Semillas

<!-- Datos ficticios necesarios para los AC (Art. 1). -->

- <...>

## 5. Dependencias nuevas

<!-- Toda dependencia nueva se justifica aquí (constitución §2). Si no hay, escribir "Ninguna". -->

| Paquete | Versión | Justificación | Alternativa descartada |
|---|---|---|---|
| <...> | <...> | <...> | <...> |

## 6. Estrategia de pruebas

<!-- Niveles definidos en constitución §5.2. -->

| AC | Unit | Integración | Contrato | E2E |
|---|---|---|---|---|
| AC-NNN-01 | <qué se prueba> | <...> | <...> | <...> |

## 7. Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| <...> | Alto \| Medio \| Bajo | <...> |

## 8. Cumplimiento de la constitución

| Artículo | Estado | Justificación |
|---|---|---|
| Art. 1 — Datos ficticios | Cumple \| N.A. | <...> |
| Art. 2 — Spec-anchored | Cumple \| N.A. | <...> |
| Art. 3 — TDD | Cumple \| N.A. | <...> |
| Art. 4 — Arquitectura hexagonal | Cumple \| N.A. | <...> |
| Art. 5 — El dominio decide | Cumple \| N.A. | <...> |
| Art. 6 — Acciones vía MCP | Cumple \| N.A. | <...> |
| Art. 7 — Identificación antes que información | Cumple \| N.A. | <...> |
| Art. 8 — Auditoría | Cumple \| N.A. | <...> |
| Art. 9 — Secretos | Cumple \| N.A. | <...> |
| Art. 10 — Ante la duda, escalar | Cumple \| N.A. | <...> |

---

## Gate de salida

- [ ] Todos los AC de la spec tienen estrategia de prueba asignada.
- [ ] Ningún artículo de la constitución queda incumplido sin justificación.
- [ ] Dependencias nuevas justificadas o "Ninguna".
- [ ] Estado cambiado a **Aprobado**.
