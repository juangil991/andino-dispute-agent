---
paths:
  - "tests/contract/**"
  - "tests/e2e/**"
  - "tests/integration/**"
---

# Convención de tests de herramientas MCP

1. **Contrato**: toda herramienta tiene test en `tests/contract/` verificado en ambos lados (servidor y cliente) contra el mismo esquema (§5.2).
2. **Casos obligatorios por herramienta**: camino feliz, entrada inválida, sin identificación (Art. 7), no encontrado y error no recuperable ⇒ escala (Art. 10).
3. **Nombrado** (inglés, §2): `test_<tool>__<condition>__<expected_outcome>`, p. ej. `test_iniciar_disputa__amount_above_threshold__escalates`. En parametrizados, `ids=` legibles y una fila por regla.
4. **Comentario de trazabilidad obligatorio** sobre cada test, en español, con la regla de negocio, el AC y el artículo:

   ```python
   # Regla: RN-003 — un monto sobre el umbral no se resuelve automáticamente.
   # AC-003-02 · Art. 10 (ante la duda, escalar)
   def test_iniciar_disputa__amount_above_threshold__escalates() -> None: ...
   ```

   - Línea `Regla:` con el ID y un enunciado corto tomados de la tabla de decisión de la spec.
   - Línea `AC-NNN-XX · Art. N`.
   - En casos límite, nombrar el borde en el comentario ("umbral exacto", "fuera de plazo").
   - Un test sin `Regla:` ni `AC-` no pasa revisión.
5. **Invariantes**: los tests de invariantes (sin identificación, límite del loop) citan el Artículo en lugar de una RN.
6. **Datos y determinismo**: fakes y builders en `tests/fakes/`; e2e con `FakeLLM` y servidor MCP real por stdio; sin red ni reloj real (§5.3).
7. **Snapshot de catálogo**: un test compara nombres y esquemas de las herramientas expuestas con la spec y falla ante herramientas no declaradas.
