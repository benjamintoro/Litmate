# Continuidad OpenCode — LitMate IA

Actualizado: 22 de octubre de 2026.
Rama: `feature/cuotas-ia-chatbot`.
Commits locales de esta sesión: `f12ee52` (seguridad), `057a687` (IA),
`2f8708f` (evaluación) y el commit de documentación de este informe.

## Objetivo general

Completar la IA literaria de LitMate con precisión factual, memoria
conversacional, identificación por recuerdos parciales, investigación web
verificable, menor latencia y protección contra invenciones, sin romper el
diseño visual ni las funciones existentes.

## Estado actual

- La suite offline completa de `core` pasa: **1078 pruebas OK** en 6.220 s.
- Las pruebas de pagos pasan: **13 pruebas OK**.
- La evaluación final v2 se ejecutó de nuevo después del último ajuste de
  auditoría: `reportes/evaluacion_v2_final3_20261022`.
- Resultado final3: **21 respuestas, 8 aclaraciones, 10 no disponibles y 3
  rechazos**. Cobertura publicada:
  **21/42 turnos**. Aprobación mecánica de la matriz:
  **27/42**. Fallos de estado: 15;
  fallos de contenido: **0**; fallos de seguridad: **0**.
- Latencia final3: p50 **26.050 s**, p95 **118.487 s**, máximo
  **172.537 s**. No se midió la latencia del endpoint HTTP: el evaluador
  llama al asistente directamente.
- No hubo revisión factual independiente. `correct_answers`,
  `incorrect_answers` y `factual_error_rate` siguen siendo `null`; los conteos
  de estado no son una medida de exactitud.

## Fases

- [x] Fase A — Preservación y diagnóstico.
- [x] Fase B — Auditoría, fechas, premios, publicación y biografía.
- [x] Fase C — Memoria, correcciones, cambio de tema y referencias al libro
  anterior; hay pruebas de pipeline y de conversación.
- [x] Fase D — Ruta factual simple y reducción de llamadas; la latencia de
  consultas complejas, el streaming progresivo y el precalentamiento siguen
  pendientes.
- [x] Fase E — Cuotas, pagos, OAuth, CSRF y settings de producción.
- [x] Fase F — Evaluación final v2 y comparación honesta con la línea base.

## Cambios principales

### Seguridad

- `core/quotas.py`: comprobación de cuota sin consumir antes de inferir;
  consumo sólo tras una respuesta publicable; `X-Forwarded-For` se acepta
  únicamente desde proxies configurados.
- `suscripciones/views.py` y servicios de pago: verificación de montos,
  monedas, referencias e idempotencia; simulaciones sólo con `DEBUG` o
  `LITMATE_PAYMENT_SANDBOX`.
- `core/views.py`: login social demo limitado por bandera; OAuth exige state;
  no se vincula por correo no verificado; no se toma una cuenta con contraseña
  por nombre de usuario; se retiraron `csrf_exempt` de endpoints activos.
- `litmate_project/settings.py`: `SECRET_KEY` obligatoria con `DEBUG=False`,
  `ALLOWED_HOSTS` explícitos, cookies seguras y cabeceras de seguridad.

### IA literaria

- Rutas deterministas para autoría simple y corrección de identificaciones.
- Recorte de respuestas factuales simples a la primera frase para evitar datos
  adicionales no respaldados.
- Respaldo de autor sólo desde fuentes y respaldo de listas sólo para
  recomendaciones temáticas puras, no para auditorías fallidas ni evidencia
  inventada.
- Memoria de correcciones («no, el otro libro»), referencias al libro anterior
  y cambios explícitos de tema.
- Conservación de pasajes entrecomillados y comparación de citas sin distinguir
  mayúsculas.
- Auditoría: detecta fechas entre paréntesis y años con contexto temporal;
  detecta sucesos concretos (por ejemplo, «se lleva», «ascensión», lluvias con
  duración) y exige que las frases concretas de un análisis largo estén
  auditadas. Si no se pueden respaldar, la respuesta queda en `unavailable`.

### Evaluación

- `datos_evaluacion_ia_v2.json`: 37 casos, 45 mensajes, 42 turnos en vivo y 2
  casos controlados (3 turnos) que no se ejecutan.
- `evaluar_litmate.py` conserva conversación, fuentes y diagnósticos.
- `analizar_evaluacion_ia.py` separa estado, contenido y seguridad; no certifica
  verdad factual.

## Pruebas ejecutadas

```text
.\venv\Scripts\python.exe -B verificar_proyecto.py
-> 1078 pruebas OK en 6.220 s

.\venv\Scripts\python.exe -B verificar_proyecto.py suscripciones.test_payments
-> 13 pruebas OK en 0.103 s
```

También se ejecutaron regresiones específicas de fechas entre paréntesis,
sucesos concretos no auditados y años en títulos; las cuatro nuevas pruebas
pasan.

## Comparación de evaluaciones

| Ejecución | Respondidas | Aprobadas | Fallos estado | Fallos contenido | Fallos seguridad | p50 | p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Inicial corregida | 19 | 22 | 20 | 0 | 0 | 16.087 s | 55.140 s |
| Final pre-fix | 17 | 23 | 19 | 0 | 0 | 32.900 s | 156.840 s |
| Final2 | 21 | 27 | 15 | 0 | 0 | 34.831 s | 175.972 s |
| Final3 | 21 | 27 | 15 | 0 | 0 | 26.050 s | 118.487 s |

La comparación no es un experimento controlado: las fuentes externas
(Open Library/SearXNG) varían entre ejecuciones. La matriz además usa
`answered` por defecto en varios casos de seguridad o ambigüedad; una
abstención segura puede contar como fallo de estado.

## Hallazgo factual importante

La evaluación final2 publicó en `long_structure_cien_anos` dos datos no
respaldados: la fundación de Macondo «(1840)», la destrucción «(1950)» y un
suceso inventado sobre Remedios y el aljibe. La auditoría los marcó como
`inference` porque el detector sólo reconocía años precedidos por
`en/desde/hasta/año`; no reconocía años entre paréntesis ni sucesos concretos
no auditados.

Se corrigió el detector y se añadió una barrera que exige auditar cada frase
concreta de un análisis largo, incluso cuando la auditoría estricta está
desactivada. La repetición dirigida
`reportes/evaluacion_v2_recheck5_20261022` quedó en `unavailable`, sin publicar
los datos inventados. La evaluación final3 vuelve a comprobar el caso.

Esto demuestra que `content_failures=0` no equivale a verdad factual: el
analizador sólo comprobaba términos obligatorios y prohibidos.

## Fallos y limitaciones conocidos

1. **Fuentes externas inestables.** El mismo tema apareció como respondido en
   un turno y como abstención en otro; por ejemplo, arte japonés y la segunda
   variante de recomendación. No se sustituyen por conocimiento del modelo.
2. **Abstenciones seguras contadas como fallo.** `mixed_practical_action_rejected`
   se rechaza correctamente; `exact_quote_without_authorized_text` y
   `vague_scene_needs_clue` piden aclaración; la matriz las esperaba
   `answered`. `false_premise_quixote` se abstiene sin corregir la premisa.
3. **Casos aún limitados por fuentes:** personajes y final de *Cien años de
   soledad*, comparación de *Cien años* y *El amor en los tiempos del cólera*,
   recomendaciones chilena/breve, investigación web reciente y seguimiento
   ordinal completo.
4. **Long_structure** quedó en `unavailable` en final3 en lugar de publicar un
   análisis con fechas/escenas no respaldadas. Es una pérdida de cobertura
   deliberada.
5. **Calidad parcial:** `recommendation_ordinal_followup` pide aclaración en
   ambos turnos en final3, en lugar de explicar los enfoques;
   `nonfiction_books_allowed` recomienda una obra sin desarrollar el nivel de
   lectura.
6. **Latencia:** las consultas complejas siguen usando varias llamadas
   secuenciales al 9B; en final3 el p95 fue 118.487 s y el máximo 172.537 s.
   La ruta HTTP con streaming no se midió en esta evaluación.
7. **Revisión factual independiente pendiente.** Los resultados deben leerse
   como cobertura, seguridad y comportamiento, no como certificación de
   exactitud.

## Decisiones y riesgos

- Se conservan Django, Ollama y el pipeline actual; no se añadieron servicios de
  pago ni dependencias.
- Las fuentes externas se tratan como datos no confiables; no se convierten en
  evidencia por el hecho de aparecer en una búsqueda.
- No se publican citas textuales sin pasaje autorizado.
- No se modificó `.env`, no se ejecutaron migraciones y no se hizo push.
- No se afirma que una prueba haya pasado si no se ejecutó.

## Próximos pasos

1. Revisar manualmente las respuestas publicadas de final3 y completar la
   revisión factual independiente que la matriz deja en `null`.
2. Medir el endpoint HTTP real con streaming y distinguir latencia de
   recuperación de fuentes de latencia del modelo.
3. Mejorar la estabilidad de búsqueda y reintentos sin convertir una búsqueda
   vacía en una recomendación inventada.
4. Decidir si los casos de seguridad/ambigüedad deben actualizar
   `expected_status` en la matriz para no penalizar abstenciones correctas.
5. Evaluar una segunda reparación acotada para respuestas largas: hoy una
   respuesta con datos concretos no respaldados puede terminar en
   `unavailable` en lugar de una versión corregida.
