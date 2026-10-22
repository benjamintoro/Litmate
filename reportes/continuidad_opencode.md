# Continuidad OpenCode — LitMate IA

Actualizado: 22 de octubre de 2026.
Rama: `feature/cuotas-ia-chatbot`.
Checkpoint: pendiente de confirmar en el historial de Git.

## Objetivo general

Completar y perfeccionar la IA de LitMate: precisión factual, memoria
conversacional, identificación por recuerdos parciales, investigación web
verificable, menor latencia y protección contra invenciones, sin romper el
diseño visual ni las funciones existentes.

## Estado inicial verificado

- El árbol tenía 21 archivos rastreados modificados y 28 archivos nuevos sin
  rastrear, además de este informe.
- La última evidencia histórica era de 989 pruebas generales y 37 pruebas de
  procedencia, pero había ediciones posteriores sin cubrir.
- La suite completa actual se ejecutó antes del checkpoint: **1032 pruebas OK**
  en 5.837 s, con SQLite en memoria y sin tocar la base principal.
- Se corrigieron dos regresiones reales detectadas por esa suite:
  1. `LiteraryAssistant.reply` trataba un `deadline` no numérico (Mock) como
     presupuesto válido y fallaba con `TypeError`.
  2. La memoria de tema conservaba una «y» final cuando la tarea incluía
     «por favor»; ahora separa la tarea sin validar secretos ocultos.

## Fases

- [x] Fase A — Preservación y diagnóstico.
- [ ] Fase B — Errores de auditoría y precisión de la IA.
- [ ] Fase C — Memoria, razonamiento e investigación.
- [ ] Fase D — Rendimiento y latencia.
- [ ] Fase E — Cuotas, seguridad y mantenimiento.
- [ ] Fase F — Evaluación final y comparación con la línea base.

## Pruebas ejecutadas

- `.\venv\Scripts\python.exe -B verificar_proyecto.py core.test_topic_task_boundaries`
  → 9 pruebas OK.
- `.\venv\Scripts\python.exe -B verificar_proyecto.py core suscripciones`
  → 1032 pruebas OK en 5.837 s; `System check identified no issues`.

## Decisiones técnicas

- Conservar Django, Ollama y el pipeline actual mientras no haya mediciones que
  justifiquen una migración.
- Mantener las rutas rápidas y la auditoría basada en evidencia literal.
- No añadir dependencias ni servicios de pago sin justificación y autorización.
- Las pruebas seguirán usando SQLite en memoria y entornos aislados.
- No se modificará `.env`, no se hará push y no se ejecutarán migraciones sin
  autorización específica.

## Problemas pendientes conocidos

1. Auditoría estricta con más de seis afirmaciones: el esquema puede exigir
   todos los hechos y `validate_audit` rechaza más de seis.
2. `done_reason='length'` se trata como fallo total; falta recuperación
   controlada.
3. Verificación semántica: la evidencia literal no garantiza implicación.
4. Recomendaciones rápidas pueden omitir auditoría factual de trama.
5. Latencia: llamadas secuenciales, guardián 9B, timeouts altos, ruta rápida de
   25 s, streaming no progresivo, precalentamiento no integrado.
6. Cuotas desactivadas por defecto, acopladas a rutas rápidas, consumidas después
   de inferir y con confianza en `X-Forwarded-For`.
7. Seguridad: bypass de pagos, settings inseguros por defecto, login demo,
   endpoints CSRF-exempt y dependencias legacy.

## Riesgos

- No afirmar que una prueba pasó sin ejecutarla.
- No aceptar afirmaciones sin evidencia para “mejorar” una respuesta.
- No aumentar la latencia con nuevas llamadas al modelo sin medición.
- No publicar ni desplegar mientras existan los bypass de pago verificados.

## Próxima acción concreta

Crear el checkpoint local y continuar con la Fase B: reproducir el fallo de
más de seis afirmaciones con una prueba de regresión, corregir la
incompatibilidad entre `local_llm.py` y `literary_quality.py`, y después
corregir el manejo de `done_reason='length'`.
