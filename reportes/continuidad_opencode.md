# Continuidad OpenCode — LitMate IA

Actualizado: 22 de octubre de 2026.
Rama: `feature/cuotas-ia-chatbot`.
Commits locales de esta sesión: `f12ee52` (seguridad), `057a687` (IA),
`2f8708f` (evaluación), `147c75e` (informe anterior), `935f2cb` (chat acotado y
respuestas verificadas rápidas), `1f3a7b7` (métricas honestas de timeout) y
`45babb1` (descubrimiento en 30 segundos).

## Intervención vigente — objetivo de 30 segundos y descubrimiento local

- Punto de partida: `253e029`, etiqueta local
  `checkpoint/antes-descubrimiento-30s-20261022`. Commit del código de esta
  intervención: `45babb1`. Sin push, sin migraciones y sin cambios en
  `.env`.
- El chat dispone de **29 s de trabajo** y el navegador corta a los **30 s**.
  Antes de generar, consulta un diccionario local de materias, lugares, alias y
  etiquetas (**230 facetas, 252 temas y 929 alias**, ~117 KB) y descubre fichas
  verificadas con `retrieve_discovery_books()`, aceptación temprana y
  presupuesto anidado de 18 s.
- La secuencia exacta de la captura responde **sin modelo** en
  0,078 / 0,024 / 0,063 s (Segunda Guerra Mundial, seguimiento de Primera
  Guerra Mundial y Antigua Grecia), con tres obras y tres fuentes por turno.
  Con el presupuesto anterior de 9 s, los turnos 2 y 3 quedaban en
  `unavailable` a 9,0 s
  (`reportes/descubrimiento_30s_20261022/antes_captura.json`).
- Benchmark HTTP/SSE real v2
  (`reportes/benchmark_30s_descubrimiento_20261022_v2.json`): **8/8 turnos por
  debajo de 30 s**, p50 2,475 s, p95 y máximo 29,014 s; **6 answered y 2
  unavailable**. v1: 3 answered, 3 unavailable y 2 aclaraciones, también 8/8
  por debajo de 30 s. `source_files_changed_during_run=false` en ambas; sin
  revisión factual independiente.
- Revolución Francesa respondió en 26,8 s; Corea del Sur y aventuras espaciales
  en ~2-3 s con cero llamadas al modelo. Guerra Fría y «Guerra y Paz» agotaron
  el presupuesto y quedaron en `unavailable`, sin títulos inventados. Open
  Library respondió `timeout`/`cooldown` en el sondeo del mismo día.
- Si el descubrimiento no devuelve ninguna ficha de libro, la respuesta es
  `unavailable` inmediata (`provider_error: sin_fuentes_verificables`) en lugar
  de esperar al 9B o permitir una recomendación sin fuente.
- Pruebas: **1134 core OK** con `--keepdb` (252,578 s), **17 de pagos y cuotas
  OK** (13 + 4) y **198 comprobaciones JavaScript OK**.
- Informe completo: `reportes/descubrimiento_30s_20261022/INFORME.md`. El
  informe de diez segundos se conserva como histórico.

## Objetivo general

Completar la IA literaria de LitMate con precisión factual, memoria
conversacional, identificación por recuerdos parciales, investigación web
verificable, menor latencia y protección contra invenciones, sin romper el
diseño visual ni las funciones existentes.

## Intervención actual — espera de cinco minutos y objetivo de diez segundos

- Se preservó `147c75e` con la etiqueta local
  `checkpoint/ia-antes-limite-10s-20261022`.
- Había **25 s + hasta 360 s** de presupuestos sucesivos. Ahora el trabajo del
  chat tiene un deadline único de **9 s** y el navegador corta la espera a los
  **10 s**. No se han quitado auditorías para publicar antes de verificarlas.
- El caso exacto de la captura ya devuelve tres libros, autores, explicaciones
  y fuentes sin modelo: **0,080 s por HTTP/SSE real aislado** en la primera
  comprobación. No es una medición en la cuenta ni la base MySQL del usuario.
- Nuevos módulos: `core/ai_quick_answers.py`, `core/literary_language.py` y
  `core/data/verified_readings.json`. Superposición factual de solo lectura;
  no se importaron fichas a la base del usuario ni se ejecutaron migraciones.
- `core/ai_budget.py` acota la espera incluso ante dependencias no cooperativas,
  con dos slots sin cola ilimitada. Los trabajos tardíos mantienen su slot y
  lease hasta terminar; sus respuestas no se publican ni se cobran.
- Las rutas rápidas funcionan con cuotas activas. Se añadieron controles de
  cantidad, autores distintos, nuevas opciones y de títulos con ordinales
  («El segundo sexo» no es el segundo libro de la lista).
- Se reutilizan hechos documentados para seguimientos de personajes y autorías;
  las citas sin texto local piden el pasaje sin esperar al modelo. Las búsquedas
  cortas usan FTS sin cargar un modelo de embeddings adicional.
- Clientes principal/flotante comparten timeout y conservan diseño, tarjetas,
  CSRF y renderizado seguro. Assets versionados `chat-v6`.
- Última suite general ejecutada después de los arreglos:
  **1119 pruebas core OK en 7,507 s**; **13 de pagos OK en 0,112 s**;
  **198 comprobaciones JavaScript OK**.
- La primera matriz HTTP real (`http_matriz_v1.json`) completó 46 turnos en
  menos de 10 s (máximo 9,019 s), pero tuvo 27 `unavailable`, 9 `answered`,
  4 aclaraciones, 3 rechazos y 3 HTTP 503. **No se considera una IA terminada.**
- Se corrigieron autorías simples, aclaraciones innecesarias, seguimientos,
  cierres tardíos y prioridad de una ficha propia aunque sea más breve.
- Evaluación vigente: **`http_matriz_v4.json`**, tras el último arreglo, sin
  cambios de código durante la ejecución. **46/46** completaron SSE en menos
  de 10 s: p50 **0,0465 s**, p95 **9,017 s**, máximo **9,025 s**. Estados:
  **21 answered, 17 unavailable, 5 clarification y 3 rejected**; cero HTTP 503.
- En la matriz original son **17/42 respuestas publicadas**; las otras cuatro
  corresponden al caso nuevo de la captura y sus variantes/seguimiento. No
  comparar 21/46 con el antiguo 21/42 como si fueran la misma cobertura.
- La consulta exacta reportada completó HTTP en **0,016 s** en la última matriz;
  el seguimiento «Cuéntame más del segundo», **0,028 s**. Fuentes y libros
  documentados, sin llamada al modelo. No es una medición sobre la sesión
  MySQL del usuario.
- Todos los turnos publicados pasan las comprobaciones mecánicas de términos;
  no hay revisión factual independiente. `analisis_v4.json` mantiene exactitud
  factual en `null`, y las inferencias de trabajos vencidos en desconocido.
- Pendiente inmediato: estabilizar fuentes y aumentar cobertura de consultas
  complejas **sin relajar auditorías ni fingir que un timeout es una respuesta
  correcta**. El 9B aún no completa esas respuestas en este presupuesto.
- Informe: `reportes/latencia_10s_20261022/INFORME.md`.

## Estado histórico anterior a esta intervención

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
- [ ] Fase B — Hay arreglos de auditoría, fechas, premios y biografía; falta
  certificar la calidad factual de todas las respuestas y ampliar cobertura.
- [ ] Fase C — Memoria y referencias implementadas; investigación autónoma y
  estabilidad de fuentes siguen parciales.
- [ ] Fase D — Rutas rápidas y presupuesto interactivo implementados; completar
  razonamiento complejo verificado en diez segundos sigue pendiente.
- [x] Fase E — Cuotas, pagos, OAuth, CSRF y settings de producción.
- [ ] Fase F — Evaluaciones técnicas ejecutadas; revisión factual independiente
  y cumplimiento integral de la misión todavía pendientes.

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

1. Revisar las 21 respuestas publicadas en la matriz HTTP v4 y completar una
   revisión factual independiente; no basta el estado ni los términos.
2. Reproducir las 17 abstenciones, especialmente investigación reciente,
   comparaciones, fragmentos y análisis largos. Evaluar un modelo/transportes
   más ligeros con las mismas fuentes y pruebas de calidad antes de cambiar
   el 9B. No resolver el problema desactivando verificaciones.
3. Mejorar la estabilidad de búsqueda y reintentos/caché sin convertir una búsqueda
   vacía en una recomendación inventada.
4. Medir sesión/historial en un MySQL **aislado**, sin escribir en la cuenta
   real. El benchmark HTTP ya incluye CSRF y SSE, pero usa SQLite temporal;
   no demuestra el coste del middleware ni la persistencia en MySQL remoto.
5. Decidir criterios de estado de seguridad/ambigüedad antes de otra evaluación,
   sin alterar expectativas para ocultar fallos de servicio.
6. Evaluar una segunda reparación acotada para respuestas largas: hoy una
   respuesta con datos concretos no respaldados puede terminar en
   `unavailable` en lugar de una versión corregida.
