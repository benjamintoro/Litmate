# Continuidad OpenCode — LitMate IA

Actualizado: 23 de octubre de 2026.
Rama: `feature/cuotas-ia-chatbot`.
Commits locales de esta sesión: `f12ee52` (seguridad), `057a687` (IA),
`2f8708f` (evaluación), `147c75e` (informe anterior), `935f2cb` (chat acotado y
respuestas verificadas rápidas), `1f3a7b7` (métricas honestas de timeout),
`45babb1` (descubrimiento en 30 segundos) y `4c08d83` (arquitectura
persistente y rutas rápidas verificadas; punto de control local de esta
intervención).

## Intervención vigente — arquitectura persistente y rutas rápidas verificadas

Objetivo: consultas literarias comunes en 1–5 s (caché/local), 3–10 s con
índice y 10–30 s con investigación externa, sin cambiar verdad factual por
velocidad ni publicar datos inventados.

- Se conserva y completa la arquitectura no confirmada de Codex: memoria
  literaria persistente, recuperación híbrida, investigación en segundo plano,
  aprendizaje de correcciones, enrutamiento, caché de respuestas privadas,
  streaming progresivo, auditorías y benchmarks reproducibles.
- Las preguntas simples sobre una obra nombrada explícitamente (sinopsis,
  personajes, protagonista) intentan una ruta determinista antes del modelo.
  Las consultas compuestas, privadas, de cita exacta o de materia general
  siguen usando el pipeline completo y sus validadores.
- La ruta externa acotada (`research_answer`) publica sólo pasajes literales
  atribuidos mediante `reference_answer`; no convierte una página tangencial
  en sinopsis ni una adaptación en la novela.
- Las páginas web se vinculan a una ficha bibliográfica y a su autor. Se
  rechazan homónimos, mangas, películas, musicales, series y páginas de
  streaming (Prime Video, Filmaffinity, IMDb, etc.). «Nana (Zola)» se acepta
  como desambiguación por autoría sólo si el autor aparece en la introducción
  y coincide con la ficha de Open Library.
- Si la API de Wikipedia falla o no devuelve la ficha, una segunda ruta acotada
  busca con título + autor + «protagonista/personajes/sinopsis» y exige que
  todas las fuentes publicadas mencionen al autor conocido. Para títulos de
  una sola palabra sin autoría comprobada no se publica nada (evita mezclar
  «Nana» novela y manga).
- Las preguntas de autoría priorizan la autoría estructurada de Wikidata
  cuando Open Library devuelve ediciones con traductores o ilustradores en el
  campo de autor. Si Wikidata también discrepa, no se elige por mayoría.
- La caché de Wikipedia sólo se activa dentro de un presupuesto de petición
  real; las pruebas y comandos offline no reciben páginas de otro contexto.
  La caché privada de respuestas acepta referencias web auditadas y vuelve a
  validar el texto sin las envolturas de interfaz ni las URL añadidas.
- No se modificó `.env`, no se instalaron paquetes, no se ejecutaron
  migraciones, no se alteraron datos de usuarios y no se hizo push.

### Pruebas ejecutadas (23 de octubre de 2026)

```text
.\venv\Scripts\python.exe -B verificar_proyecto.py core
-> 1297 pruebas OK en 16.406 s

.\venv\Scripts\python.exe -B verificar_proyecto.py core.test_persistent_router
-> 18 pruebas OK en 0.596 s

.\venv\Scripts\python.exe -B verificar_proyecto.py core.test_persistent_router core.test_web_search core.test_ai_answer_cache
-> 59 pruebas OK en 0.941 s (antes del filtro de desambiguación)
```

También se ejecutaron sondas HTTP reales aisladas (sin datos de usuario) y
comprobaciones directas de Wikipedia/Open Library. Las sondas externas
sufrieron `rate_limited` intermitente de Wikipedia; por eso las pruebas
deterministas usan mocks y el benchmark se repite con enfriamiento.

### Benchmark HTTP/SSE real de 4 preguntas

Matriz: `reportes/arquitectura_20261023/matriz_benchmark_4.json`.
Ejecución final: `reportes/arquitectura_20261023/despues_http_v7.json`.
Base anterior: `despues_http_v2.json` (misma matriz, antes de estas rutas).

| Ejecución | answered | <5 s | p50 | p95 / máx | Observación |
|---|---:|---:|---:|---:|---|
| v2 (antes) | 4/4 | 2/4 | 18,930 s | 35,178 s | «Nana» mezcló manga y novela; protagonista de *Los miserables* agotó ~35 s |
| v7 (después) | 4/4 | 3/4 | 3,697 s | 7,669 s | «Nana» sólo novela de Zola; protagonista de *Los miserables* con Jean Valjean en 7,669 s |

Turnos v7: autoría de *Orgullo y prejuicio* 2,680 s; personajes de *Nana*
4,714 s; sinopsis de *El nombre de la rosa* 1,296 s; protagonista de *Los
miserables* 7,669 s. `source_files_changed_during_run=false`; el benchmark no
certifica verdad factual de forma independiente.

### Benchmark ampliado de 8 preguntas y revisión de cobertura

Matriz: `reportes/arquitectura_20261023/matriz_benchmark_8.json`.
Ejecución: `reportes/arquitectura_20261023/despues_http_v8_matriz8.json`.
Ocho preguntas simples con obra explícita, `--repeat 2`, caché de respuestas
vaciada en cada turno (la caché de recuperación sí se conserva). 16 turnos,
16 `answered`, 12 por debajo de 5 s, todos por debajo de 10 s y de 30 s;
p50 0,968 s, media 2,323 s, p95 y máximo 7,356 s. La segunda repetición de una
misma pregunta suele ser más rápida por la caché de recuperación; no es una
medida independiente de latencia externa en frío.

| Caso | Respuesta publicada | Revisión |
|---|---|---|
| Autoría de *Cien años de soledad* | Gabriel García Márquez | Correcta |
| Autoría de *Rayuela* | Julio Cortázar | Correcta |
| Sinopsis de *La casa de los espíritus* | Primera novela de Isabel Allende; cuatro generaciones | Correcta, pasaje breve |
| Sinopsis de *Pedro Páramo* | Novela situada en Comala | Correcta, ficha muy breve |
| Protagonista de *El túnel* | Primera pasada: página de desambiguación y página de la novela; segunda: sólo contexto | Cobertura incompleta; no hubo invención |
| Protagonista de *Madame Bovary* | Emma Bovary | Correcta |
| Personajes de *La Regenta* | Pasajes sobre la obra, sin nombres de personajes | No responde la lista; referencia parcial |
| Personajes de *Fortunata y Jacinta* | Juanito Santa Cruz y contexto de la novela | Parcial; no es una lista completa |

La revisión confirma que «answered» no equivale a respuesta exhaustiva. Las
respuestas parciales se presentan como pasajes atribuidos y no como fichas
verificadas. No se detectaron citas inventadas ni mezcla de obras homónimas en
esta matriz; *La Regenta* y parte de *El túnel* no certifican la lista pedida.

Se añadió un filtro para no usar páginas de desambiguación aunque su título
coincida con la obra y su pasaje recuperado hable de la novela. La sonda
posterior `probe_tunel_v9.json` (2 turnos, caché de respuestas vaciada) nombró
a Juan Pablo Castel en ambas respuestas, en 3,820 s y 1,888 s, sin la página
«El túnel puede referirse a». La prueba unitaria nueva está en
`core.test_persistent_router`.

### Limitaciones actuales

1. Las listas de personajes siguen siendo parciales: *Nana* devuelve un pasaje
   sobre la novela de Zola y *La Regenta* puede devolver contexto sin nombres.
   Evitan homónimos y adaptaciones, pero no sustituyen una lectura de la
   sección de personajes.
2. Wikipedia puede responder `rate_limited`; en ese caso la ruta rápida puede
   caer a la búsqueda web acotada o al pipeline completo. La latencia externa
   sigue siendo variable.
3. El benchmark ampliado cubre ocho preguntas y dos repeticiones; no demuestra
   cobertura general ni exactitud factual. La revisión fue interna, no
   independiente.
4. La caché y la memoria usan SQLite temporal en las pruebas; no se midió
   MySQL remoto ni el coste del middleware de sesión.
5. Las referencias parciales se presentan como pasajes atribuidos, no como
   fichas verificadas ni como respuesta exhaustiva.

### Próximos pasos inmediatos

1. Añadir a la matriz consultas compuestas, de cita exacta y de materia general
   para comprobar que no entran en las rutas rápidas, y repetir con más obras.
2. Mejorar la extracción de listas de personajes cuando la página correcta no
   es la primera de Wikipedia, sin relajar la vinculación por autor.
3. Completar una revisión factual independiente de las respuestas publicadas y
   registrar las que no puedan certificarse.
4. Medir sesión/historial en MySQL aislado antes de cambiar la arquitectura.

## Intervención anterior — búsqueda amplia, no limitada a la captura

- Se amplía la recuperación para obras y materias arbitrarias: catálogo local,
  Open Library, Wikipedia en español/inglés y DuckDuckGo Lite. SearXNG queda
  como respaldo cuando los proveedores principales no devuelven resultados.
  Google Books sigue siendo opcional y no se habilita ningún proveedor de pago.
- Las primeras páginas pertinentes, incluidas editoriales y librerías, pueden
  aportar pasajes públicos cuando sus reglas lo permiten. Se conservan HTTPS,
  DNS público fijado para TLS, robots.txt (también comodines), límites de tamaño,
  tres lecturas por petición y rechazo de redirecciones/bloqueos/CAPTCHA.
- `CHAT_WORK_SECONDS=36`, `CHAT_RESPONSE_SECONDS=42`; descubrimiento ligero
  de seis segundos. La inferencia reserva un segundo para publicar un respaldo
  antes del límite externo. No se ha activado thinking ni cambiado el modelo 9B.
- Las listas rápidas verifican procedencia, tema, filtros, obras anteriores y
  auditoría de identidades. Sin sinopsis no inventan una explicación.
- Si sólo hay información web, se ofrecen pasajes cortos atribuidos y sus URL,
  con `books=[]` y advertencia de alcance parcial. La auditoría comprueba la
  copia literal; no se presenta como certificación independiente de la página.
- Las consultas sobre libros concretos también investigan en paralelo con
  Ollama. Si falla la generación, se reutilizan las fuentes recuperadas; no se
  publica el borrador fallido ni se reinicia un timeout de varios minutos.
- Se corrigió el error de argumentos posicionales de `ChatResult` que causaba
  HTTP 500 al recordar una respuesta web. Las pruebas cubren los tipos de
  `books`, `sources`, `basis` e `intent`, además de privacidad y cuotas.
- Se añadieron normalización de consultas naturales, consulta de ISBN con
  número comprobado en el registro y soporte correcto de títulos homónimos;
  una película no sustituye a la novela cuando se buscan sus contenidos.
- Última comprobación offline: **1167 pruebas core OK en 11,790 s**, **17 de
  pagos/cuotas OK en 0,108 s**, **198 comprobaciones JavaScript OK**.
  `manage.py check` y `diagnosticar_ia --sin-fuentes` ejecutados correctamente.
- Matriz real final: `reportes/busqueda_amplia_20261023/http_v4.json`, **10/10
  HTTP 200, SSE completo y `answered`**, todos antes de 42 s; mediana **4,802 s**,
  máximo **35,061 s**. **3 respuestas bibliográficas y 7 respaldos parciales**,
  no diez respuestas exhaustivas. En Guerra y paz se eliminó la biografía
  irrelevante. Hay resultados de Amazon/Casa del Libro y páginas públicas leídas.
  `source_files_changed_during_run=false`; sin revisión factual independiente.
- Control HTTP sin web: Revolución francesa, `unavailable` honesto en **0,163 s**,
  sin enlaces ni títulos inventados. Medición externa y limitaciones en
  `reportes/busqueda_amplia_20261023/`.
- No se modificó `.env`, no se instalaron paquetes, no se ejecutaron migraciones,
  no se modificaron datos existentes de usuarios y no se hizo push. Las pruebas nuevas
  usan tablas temporales; el diagnóstico lee SQLite auxiliares en modo sólo lectura.

## Histórico — objetivo anterior de 30 segundos y descubrimiento local

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
