# Continuidad OpenCode — LitMate IA

Actualizado: 26 de octubre de 2026.
Rama: `feature/cuotas-ia-chatbot`.

## Personajes verificados y límite de Wikipedia (26 de octubre de 2026)

- Punto de partida: HEAD `5039697`, rama `feature/cuotas-ia-chatbot`, cuatro
  commits por delante de `origin`. Se conservaron los cambios pendientes de la
  unidad anterior; no se restauró ni se sobrescribió trabajo existente.
- Objetivo: que las preguntas de personajes de cualquier obra recuperen
  evidencia publicada y respondan con procedencia y auditoría, sin depender de
  *El Señor de los Anillos* ni de respuestas preparadas.
- Causa del fallo intermitente reproducida: Wikimedia aplica desde 2026 un
  límite de **10 solicitudes/minuto** a clientes sin identificar y **200** a
  clientes con un `User-Agent` que incluya contacto. `_agent()` enviaba
  `LitMate/Local-1.0` sin URL ni correo. Una sonda real recibió HTTP 429 tras
  diez peticiones, con `Retry-After: 37`; el mismo lote con un `User-Agent`
  identificado completó 20/20 respuestas HTTP 200.
- Se corrigió `_agent()` para incluir el contacto configurado en
  `LITMATE_BOOKS_CONTACT` y, si falta, la URL pública del repositorio. No se
  añadieron credenciales ni se modificó `.env`.
- `PublicFetchError` conserva ahora el `Retry-After` del 429. `cooldown_seconds`
  acepta segundos o fecha HTTP y lo limita a 5–600 s; ya no sustituye un plazo
  oficial de 37 s por el valor genérico de 30 s.
- El cooldown pasó de una clave global a una clave por host
  (`es.wikipedia.org` / `en.wikipedia.org`). Un 429 en español ya no impide
  probar inglés: si hay resultados ingleses la respuesta es `partial`; si no
  hay datos y ambos hosts están en pausa, el estado sigue siendo `cooldown`.
- La ruta de personajes añade `external_research` a sus diagnósticos: número de
  solicitudes HTTP, lecturas reservadas y eventos acotados, sin consulta ni
  contenido del lector. Esto permite medir búsquedas y lecturas sin depender
  sólo del estado final.
- Se preservó la lectura estructural: TextExtracts primero y Parse siempre en
  consultas de personajes; anexos vinculados por título exacto, listas `<dt>`,
  enlaces wiki iniciales y rechazo de navegación, adaptaciones y secuelas.
- Pruebas actualizadas para el comportamiento real: las consultas de personajes
  hacen tres llamadas a la API (búsqueda, artículo completo y Parse) y consumen
  dos lecturas oficiales; una prueba de 429 ya no contamina el cooldown de la
  siguiente. No se relajó ninguna validación.

### Comprobaciones ejecutadas

```text
.\venv\Scripts\python.exe verificar_proyecto.py core
-> 1486 pruebas OK en 19.492 s

.\venv\Scripts\python.exe manage.py test core.test_character_extraction core.test_character_memory core.test_character_quality_regression core.test_wikipedia_character_tables core.test_web_search --keepdb
-> 157 pruebas OK en 3.779 s
```

La suite usa SQLite en memoria y almacenes temporales; no migra ni toca datos de
producción. Las pruebas dirigidas anteriores (168) también pasaron antes de
añadir el diagnóstico de investigación; la cifra final verificada es la de
arriba.

### Benchmark HTTP/SSE real

`core/data/character_benchmark.json`, 14 turnos reales, Ollama local y fuentes
públicas reales, bases auxiliares vacías. Salida:
`reportes/personajes_20261026/benchmark_final.json`.

| Medición | Resultado |
|---|---:|
| Turnos answered | 14/14 |
| p50 / media / p95 / máximo | 0,1125 / 3,698 / 19,602 / 19,602 s |
| Turnos <5 s / <10 s / <30 s | 12 / 12 / 14 |
| Solicitudes HTTP externas | 25 iniciadas y 25 OK |
| Lecturas de página reservadas | 14 |
| Llamadas al modelo | 4 (dos respuestas de antagonistas/relación) |
| HTTP 429 / cooldown | 0 |

Los 12 turnos de personajes tienen auditoría `approve` y todas sus afirmaciones
quedaron `supported`; los otros dos turnos resuelven recomendación y sinopsis
sin modelo. Las respuestas con síntesis (antagonistas y relación Frodo/Sam)
conservan sus fuentes y la auditoría; no se presentan como certificación
factual independiente. La recuperación directa devolvió 12 hechos para *Cien
años de soledad*, *Orgullo y prejuicio* y *Don Quijote de la Mancha*, 10 para
*Harry Potter y la piedra filosofal* y 0 para *Papelucho y el marciano*; este
último se respondió desde conocimiento local con dos hechos auditados.

`source_files_changed_during_run=false`. No se ejecutaron migraciones, no se
instalaron paquetes, no se modificó `.env`, no se borraron datos y no se hizo
push. Checkpoint local: `checkpoint/personajes-verificados-20261026`.

Limitaciones: el p95 de 19,6 s corresponde a dos síntesis con el modelo 9B; no
demuestra el p95 de toda la aplicación ni exactitud factual independiente. El
contacto público del `User-Agent` puede sustituirse por
`LITMATE_BOOKS_CONTACT` en un despliegue. La siguiente revisión debe mantener
el límite por host y repetir la matriz con arranque frío y fuentes externas
distintas.

## Sinopsis y Docker: unidad completada (26 de octubre de 2026)

- Se retomó HEAD `7810561` y se conservaron las modificaciones pendientes de
  `ai_narrative_answers.py` y `literary_ai_views.py`; no se restauraron archivos.
- Confirmados los errores: la vista no pasaba configuración al sintetizador;
  el motor descartaba su contador/uso LLM; la búsqueda genérica agotaba páginas
  antes de la ruta narrativa; el autor explícito quedaba dentro del título;
  los subtítulos editoriales se comparaban después de borrar los dos puntos.
- Se corrigieron esos vínculos, se preservan los homónimos para aclaración y
  se evita asociar el texto de Tolkien a la ficha homónima de Gary Russell.
  Se retiró la plantilla histórica no auditada: materias/título no autorizan
  afirmar que el libro carece de personajes o de trama.
- La búsqueda narrativa reutiliza las herramientas existentes y consulta
  SearXNG/DuckDuckGo y páginas públicas permitidas cuando Wikipedia/catálogo
  no aportan contenido. No modifica `.env` ni utiliza servicios de pago.
- Docker Desktop/Engine estaban activos. El contenedor `litmate-searxng-1`
  estaba healthy, sin OOM. Wikipedia devolvía infoboxes que Django ignoraba;
  `searxng/settings.yml` ahora usa `display_type: [list, infobox]`. Se reinició
  sólo ese contenedor. Tres búsquedas mediante Django: 0,461–1,385 s.
  El motor OpenLibrary de la imagen todavía produce fallos en algunas consultas.
- Fuente editorial real recuperada: ficha McGraw Hill de The Unfinished Nation,
  HTML permitido por robots, extracción correcta y autor Alan Brinkley literal.
  Se corrigió su descarte por subtítulo. No se almacena permanentemente esa
  página ni se convierten respuestas generadas en hechos.
- Diagnósticos reproducibles nuevos: `diagnosticar_buscador.py` y
  `diagnosticar_sinopsis.py`; usan Django/SQLite aislados. El segundo puede
  registrar generación/auditoría reales con `--synthesize`; su traza es local,
  no se incorpora al texto visible ni a la base de conocimiento.
- Se recupera el índice editorial desde paneles HTML del mismo documento,
  incluidos acordeones cerrados. En la ficha real de McGraw Hill aparecen 31
  títulos de capítulos. Se apartan publicidad y biografías de la redacción.
- Las pruebas reales detectaron citas tangenciales aprobadas por el auditor.
  La ruta de índices selecciona un bloque contiguo de temas y restringe el
  pool de pruebas a pasajes literales de esa fuente. No se unen citas distantes.
  Siglos/rangos sin respaldo se rechazan; los siglos del título no se confunden
  con periodos. Se puede retirar una oración rechazada y revalidar íntegramente
  las restantes; jamás se cambia un veredicto no verificado a supported.
- Se conserva sólo la petición tras un fallo narrativo, separada del historial
  aceptado. El seguimiento no pierde la obra ni secuestra recomendaciones
  nuevas. Las fuentes aceptadas en inglés se reutilizan antes de buscar otra vez.
- Validación final `pruebas_final_v2.txt`: **1405 pruebas OK, 17,472 s**;
  JavaScript: **210 comprobaciones OK**; `git diff --check` sin errores.
- Medición HTTP/SSE real final `http_final_v4.json`, código estable y SQLite
  temporal: siete turnos answered; Brinkley 14,266 s y seguimiento 8,211 s;
  Papelucho 0,084 s; Tolkien 2,567 s. Siete bajo 30 s, p95 muestral 14,266 s.
  La muestra no demuestra precisión global del 99 % ni el p95 de toda la app.
  Modelo local 9B previamente residente; precarga separada de 0,072 s.
- Se conservan mediciones fallidas intermedias: `http_final_v1.json` perdió el
  ensayo tras un rechazo; `http_final_v2.json` detectó approve con una oración
  inference. Ambos errores se corrigieron y v3/v4 completaron siete turnos.
- Comprobación final real de Docker `docker_final.json`: running/healthy, sin
  OOM, sólo loopback. Tres JSON HTTP 200 (0,894–1,145 s); Django 0,431–1,380 s.
  Open Library sigue fallando parcialmente para El nombre de la rosa; no se
  confunde salud del contenedor con relevancia o disponibilidad de cada motor.
- Informe, archivos y comandos: `INFORME_SINOPSIS_DOCKER_20261026.md`.
  Matriz reproducible sin respuestas preparadas: `core/data/narrative_benchmark.json`.
  Evidencia local: `reportes/sinopsis_20261026/` (trazas sólo por opt-in).
- Checkpoint Docker: `0fc5990`. Checkpoint conjunto local:
  `checkpoint/sinopsis-docker-20261026`; no se publicó ni se hizo push.
- Próximas mejoras: evaluación amplia con arranque frío, más idiomas/obras y
  concurrencia; revisar el defecto del motor Open Library sin sustituir la
  imagen a ciegas. El RAG, conocimiento persistente y worker se conservan;
  esta unidad no entrena pesos ni modifica embeddings.
- Sin migraciones, cambios de credenciales, instalación de paquetes, borrado de
  datos, publicación ni push. Se mantienen diseño, tarjetas, voz y avatares.

## Recuperación del checkpoint y fase 1 de tramas (23 de octubre de 2026)

### Estado del repositorio al retomar

- El árbol estaba limpio en `2c73692` (`origin/feature/cuotas-ia-chatbot`).
  Las siete modificaciones de la fase interrumpida ya estaban guardadas en ese
  commit: `ai_narrative_answers.py`, `ai_persistent_router.py`,
  `literary_ai.py`, `literary_ai_views.py`, `literary_identity.py`,
  `literary_learning.py` y `test_narrative_answers.py`.
- Se conservó intacto el checkpoint previo
  `checkpoint/antes-fase1-tramas-20261023`; no se restauraron ni sobrescribieron
  archivos desde Git. El checkpoint de recuperación y el checkpoint final se
  conservan como `checkpoint/fase1-tramas-recuperada-20261023` y
  `checkpoint/fase1-tramas-recuperada-final-20261023`.
- Se verificó `core/literary_quality.py`, `validate_audit` y el comando
  `core/management/commands/diagnosticar_ia.py`.

### Revisión y correcciones

- La fase interrumpida añadió parser y motor de recuperación para `O Exército
  na história do Brasil`, pero la prueba de título tras una aclaración llamaba
  al motor directamente: no comprobaba que la sesión transmitiera
  `pending_clarification` al worker. La cobertura también dependía de una
  fuente bibliográfica remota; los casos ahora usan una fixture local y
  determinista.
- Se completó la memoria de aclaraciones: el estado `pending_clarification`
  que la sesión ya guardaba ahora viaja al worker privado y permite interpretar
  el título exacto que responde el lector. No se inserta la aclaración como
  respuesta aceptada ni como evidencia.
- Se corrigió la lista de palabras de encuadre que impedía seleccionar una
  obra anterior después de «otro parecido a Dune» o «otro del mismo autor de
  Dune».
- Se acotó la clasificación automática: «¿De qué trata la historia de Chile?»
  vuelve al router completo; «Cuéntame sobre la trama de O Exército na
  história do Brasil» conserva la clasificación de consulta sobre obra.
- Se retiró la llamada narrativa redundante dentro de `LiteraryAssistant`.
  Esa ruta refería `self.config`, atributo inexistente, y repetía recuperación;
  el worker de conversación ya invoca el motor narrativo antes del pipeline
  completo y conserva su fallback.
- La prueba de rendimiento usa ahora *El principito*, ficha local incluida,
  en vez de esperar una ficha de *Orgullo y prejuicio* que no estaba en el
  catálogo de arranque.

### Comprobaciones de recuperación

`verificar_proyecto.py` configura SQLite `:memory:`, desactiva migraciones
Django y dirige los almacenes auxiliares a un directorio temporal. No se usó la
base del proyecto ni se ejecutaron migraciones.

```text
.\venv\Scripts\python.exe -B verificar_proyecto.py core.test_narrative_answers
-> 24 pruebas OK en 0.269 s

.\venv\Scripts\python.exe -B verificar_proyecto.py core
-> 1341 pruebas OK en 17.469 s
```

La ruta rápida, las verificaciones de fuentes y los límites existentes se
conservan. Esta suite no certifica por sí sola la exactitud independiente de
cada respuesta web ni la cobertura de capítulos de obras históricas.

Commits locales de esta sesión: `f12ee52` (seguridad), `057a687` (IA),
`2f8708f` (evaluación), `147c75e` (informe anterior), `935f2cb` (chat acotado y
respuestas verificadas rápidas), `1f3a7b7` (métricas honestas de timeout),
`45babb1` (descubrimiento en 30 segundos), `4c08d83` (arquitectura
persistente y rutas rápidas verificadas; punto de control local de esta
intervención), `33d1d47` (filtro de páginas de desambiguación y benchmark
ampliado) y `b08e841` (comparaciones reservadas al pipeline completo).

## Unidad vigente — matriz integral e instrumentación (23 de octubre de 2026)

Se retoma el trabajo existente, sin sustituir Ollama, reescribir la arquitectura,
alterar el diseño, instalar paquetes ni modificar `.env` o datos personales.

### Estado comprobado

- Existen `literary_memory.py` (fuentes/identidades/procedencia/cola),
  `literary_memory_rag.py` + `local_rag.py` (FTS5/BM25 y embeddings opcionales),
  `literary_learning.py` (priorización agregada, sin entrenamiento de pesos),
  `ai_persistent_router.py`, `ai_answer_cache.py` y trabajos SSE privados.
- Existen `core/literary_quality.py`, `validate_audit` y `diagnosticar_ia`.
  Los validadores y límites de afirmaciones se conservan.
- Las tareas automáticas ya disponibles actualizan identidades conocidas en
  lotes limitados; no constituyen todavía descubrimiento autónomo general de
  obras nuevas ni certificación de todas las relaciones literarias solicitadas.
- Modelos instalados leídos con `ollama list`: Qwen 3.5 9B Q4, variante local
  sólo texto de 9B, Qwen 3.5 4B, Qwen 3 8B y EmbeddingGemma.
  GPU leída: RTX 4060, 8188 MiB. No se cambió el modelo de la aplicación.

### Cambios de esta unidad

- Tiempos explícitos de clasificación/plan determinista (`intent`), extracción
  de páginas (`extraction`) y recuperación semántica (`semantic_retrieval`).
- `evaluar_chat_http.py` registra etapas, sobrecarga entre trabajo y entrega,
  RSS/peak y CPU del proceso Python. No mide memoria/CPU de Ollama ni GPU.
  Todas sus bases auxiliares son temporales; sólo conserva el catálogo de
  arranque incluido normalmente en la aplicación, no respuestas preparadas.
- Matriz reproducible `arquitectura_20261023/matriz_integral_20261023.json`:
  13 casos / 16 turnos, incluyendo los ejemplos solicitados, memoria,
  recomendaciones, identificación por escena, relación, discrepancia de fecha,
  citas y materia general. La discrepancia de fechas es una alegación del
  lector; no garantiza que los proveedores reales devuelvan fuentes opuestas.
- `resumir_benchmark_ia.py` agrega categorías/rutas, percentiles, etapas,
  llamadas conocidas/desconocidas, caché y recursos. Los tiempos de etapas son
  inclusivos y pueden solaparse; sumarlos no equivale a latencia de pared.
- Se retiró instrumentación de depuración temporal de las pruebas. Los casos
  de conversación con proveedor simulado fallido deshabilitan la web real.
  Las pruebas SSE deshabilitan la caché ajena al componente simulado y cierran
  el stream igual que el cliente de pruebas de Django, sin cerrar la conexión
  que contiene la transacción de `TestCase`.

### Comprobaciones ejecutadas

```text
.\venv\Scripts\python.exe -B verificar_proyecto.py core.test_ai_progress_stream core.test_literary_conversation core.test_hybrid_ai core.test_simple_factual_context
-> 99 pruebas OK en 2.241 s

.\venv\Scripts\python.exe -B verificar_proyecto.py core
-> 1302 pruebas OK en 16.892 s
```

El ejecutor configura SQLite y todas las tablas/almacenes en un entorno temporal,
sin migrar ni conectarse a la base del proyecto. La ejecución anterior mediante
`manage.py test core --keepdb` tuvo 5 fallos y 8 errores; no se presenta como
verde. El respaldo web real explica respuestas inesperadas en los mocks y el
cierre manual de SSE explica la transacción rota. MySQL no se ha vuelto a medir.

### Primera medición integral real

Checkpoints locales: `7628746` (instrumental/matriz), `2bd78f9`
(identidad de referencias, caché publicada y comparación documentada).
Salida: `arquitectura_20261023/integral_progressive_v1.json`, con
`source_files_changed_during_run=false`.

| Medición | Resultado |
|---|---:|
| Turnos | 16 |
| Estados | 11 answered / 4 unavailable / 1 clarification |
| p50 / media / p95 | 2,415 / 12,313 / 35,169 s |
| <5 / <10 / <30 s | 10 / 10 / 13 |
| Publicadas <30 s | 10, sin certificar cobertura/verdad |
| Primer progreso p50 | 0,017 s |
| Sobrecarga de entrega p50 | 123,305 ms |
| Llamadas LLM / aciertos de caché exacta | 25 / 0 |
| RSS máximo / CPU del servidor Python | 84,906 MB / 3,109 s |

Costes inclusivos acumulados: generación 68,355 s; routing/plan 33,096 s;
reparación 32,733 s; auditoría 32,715 s; recuperación 16,616 s;
web 11,756 s; extracción 1,196 s. La inspección de modelos suma sólo 0,186 s.
En el primer turno que necesitó Ollama, la carga del 9B consumió 11,484 s.
No se suman etapas anidadas/paralelas para calcular latencia total.

La comparación `integral_sin_cache_v1.json` vació sólo respuestas en cada turno:
Rayuela 1,173 / 0,143 s y El principito 0,158 s. La repetición rápida usa memoria
de evidencia, no un acierto de caché exacta; ambas ejecuciones dieron cero hits.
La categoría de El principito utiliza fichas incluidas con la aplicación, no una
base semántica ya poblada. No se demuestra aún latencia RAG semántica real.

**Revisión interna de cobertura (no certificación factual independiente):**

- Autorías de Orgullo y prejuicio, Rayuela y El túnel, y ficha de El principito:
  responden al dato básico solicitado.
- Nana: pasaje sobre la serie del autor, sin lista de personajes.
- El nombre de la rosa: inicio de sinopsis, truncado a un pasaje breve.
- Los miserables: referencia a una banda chilena homónima. **Error de identidad**,
  no éxito factual aunque el estado diga answered.
- Relación Emma/Charles: página general de adulterio, no la relación pedida.
- Fecha de El túnel: referencia a Julio Cortázar, no resuelve la discrepancia.
- Seguimiento del protagonista de El túnel: «El Narrador y protagonista de la
  historia», sin nombre. Respuesta incompleta.
- Identificación por escena, cita y materia general: no se completaron. La
  recomendación no tuvo obra de referencia porque falló su primer turno.

### Correcciones motivadas por esta medición

- El respaldo web filtra la identidad de la obra **antes** de redactar/citar y
  vuelve a comprobar todas sus fuentes. Se rechazan también bandas homónimas.
- Las referencias de autoría/publicación/personajes con título literal deben
  mencionar ese título en el texto recuperado; una coincidencia temática o URL
  no basta. Una relación entre dos entidades nombradas requiere ambas en la
  fuente, no solamente un artículo sobre el tema general.
- Regresión reproducida y corregida: la caché se guardaba antes de añadir el
  turno al historial, por lo que la repetición no encontraba su clave. Ahora
  las autorías explícitas y verificadas sin LLM pueden guardarse también bajo
  el estado publicado. No se proyecta la clave de pronombres/ordinales; se
  conservan propietario, contexto completo, TTL y revisión de evidencia.
- `.\venv\Scripts\python.exe -B verificar_proyecto.py core`:
  **1310 pruebas OK en 17,028 s** tras estas correcciones.
- Se cambia el namespace de caché a `extractive-answer-v2`: las respuestas
  admitidas por los filtros anteriores dejan de reutilizarse sin borrar filas
  ni conversaciones. Regresión nueva ejecutada primero en rojo y después verde.
- El resumidor admite una revisión interna por turno vinculada al SHA256 del
  informe, rechaza duplicados/hash incorrecto y separa cobertura de `answered`.
  Revisiones: `revision_integral_v1.json`, `v2.json` y `v3.json` en la misma carpeta.
- Última suite de esta unidad: **1312 pruebas OK en 16,820 s**.

### Comparación real de modelos, con precarga declarada

Misma matriz, código y runner (hashes idénticos), contexto 16384,
`--prewarm --progressive`; ejecuciones secuenciales, sin cambiar código durante
ninguna. La precarga usa prompt vacío y se excluye de los tiempos de consulta.

| Ejecución | p50 | Media | p95/máx | <30 s | answered / unavailable / clarification | LLM |
|---|---:|---:|---:|---:|---|---:|
| `integral_progressive_v2_9b_warm.json` | 2,425 s | 11,103 s | 35,114 s | 13/16 | 9 / 5 / 2 | 25 |
| `integral_progressive_v3_4b_warm.json` | 2,342 s | 7,664 s | 24,647 s | 16/16 | 9 / 5 / 2 | 27 |

Precarga: 9B 5,819 s; 4B 5,579 s. Reducción observada del p95: 29,8%; media:
31,0%. No es una garantía ni una comparación con evidencia idéntica: internet
varió y el primer Rayuela pasó al LLM en el 4B, con 15,297 s frente a 1,348 s
por catálogo en el 9B. El número de llamadas no bajó con el modelo menor.

Revisión interna v2: cinco respuestas básicas adecuadas, cuatro referencias
incompletas, cinco unavailable y dos aclaraciones. Ya no aparece la banda ni
las dos referencias ajenas a la pregunta. V3 conserva sólo cuatro básicas sin
reservas; el primer Rayuela añade afirmaciones no suficientemente respaldadas.
**No se cambia el modelo de la aplicación**: el 4B cumple el umbral temporal en
esta muestra, pero no demuestra respuestas completas/verificadas bajo 30 s.

Caché exacta v2: un hit real en 0,145 s. La sonda posterior
`cache_entrega_antes_v4.json` repitió Rayuela seis veces: primera investigación
1,385 s; siguientes turnos 0,141–0,153 s. Es la base de la comparación de
entrega siguiente, separada de las llamadas al modelo.

### Entrega SSE por aviso de finalización — resultado medido

Se sustituye la espera periódica del iterador por una señal interna del
`Future.add_done_callback`. No se reduce ningún presupuesto ni se muestra
contenido sin auditar. La cola sigue acotada; cancelación, cuotas, aislamiento
de sesión y POST de finalización permanecen. No es streaming real de tokens.

Matriz Rayuela `--case cache_exacta --repeat 3 --progressive`, sin respuestas
preparadas y con la primera investigación real incluida en ambos informes:

| Medición | Antes v4 | Después v5 |
|---|---:|---:|
| Primera investigación, no comparable como mejora de caché | 1,385 s | 1,183 s |
| Aciertos exactos posteriores | 5/5 | 5/5 |
| p50 de los cinco hits | 0,146 s | 0,042 s |
| p95 de los cinco hits | 0,153 s | 0,053 s |
| Sobrecarga de entrega p50 de los hits | 141,169 ms | 38,013 ms |
| Llamadas LLM | 0 | 0 |

Reducción observada del p50 de hits: **71,2%**. No es una mejora del 71% de todas
las consultas ni del p95 integral. Informes `cache_entrega_antes_v4.json` y
`cache_entrega_despues_v5.json`; sin cambios de código durante ninguna ejecución.

Control `cache_vaciada_despues_v5.json`, con
`--empty-answer-cache-each-turn`: nueve answered, cero hits y cero llamadas
LLM. Primer Rayuela 1,112 s; cinco repeticiones por memoria de evidencia con
p50 0,103 s / p95 0,107 s. Tres consultas de El principito desde las fichas de
arranque: p50 0,071 s. Vaciar respuestas **no** vacía memoria ni la recuperación.

Pruebas nuevas: aviso aunque el trabajador termine antes de consumir SSE,
ausencia de sondeo posterior al fin y error del trabajador sin token ready ni
detalles privados. Se mantienen las pruebas de cancelación, cuota, repetición
de ACK, signed cookies y propietario ajeno.

```text
.\venv\Scripts\python.exe -B verificar_proyecto.py core.test_ai_progress_stream core.test_chat_deadline core.test_ai_answer_cache
-> 84 pruebas OK en 6.455 s

.\venv\Scripts\python.exe -B verificar_proyecto.py core
-> 1314 pruebas OK en 16.885 s
```

La matriz integral no se ha vuelto a ejecutar tras este cambio de entrega;
los p95 integrales anteriores no son una nueva medición de la versión final.
Los JSON/revisiones se conservan con sus bytes originales mediante
`.gitattributes`, para que los SHA256 de revisión no cambien por CRLF/LF.

### Telemetría HTTP de conversación y finalización

- `merge_metrics()` une snapshots saneados con desplazamientos de reloj
  explícitos, filas acotadas y sin copiar mensajes, URLs o prompts arbitrarios.
- La lectura de estado/contexto conversacional se conserva al pasar al worker,
  también si responde la caché. La finalización añade sus tiempos al mismo
  origen HTTP, sin perder las etapas del trabajador ni duplicar todo su reloj.
- Sonda `probe_scopes_http_v6.json`, sin web y con todas las bases temporales:
  autoría de El principito 0,193 s desde fichas de arranque; repetición 0,045 s
  con hit exacto y cero llamadas LLM. El segundo turno registra conversation
  0,239 ms, cache_lookup 4,223 ms y finalization 5,927 ms.
- Desde v6 el elapsed agregado incluye conversación/finalización. Por ello el
  campo derivado delivery_overhead_ms ya no es directamente comparable al de
  los informes v1–v5, que incluía también etapas HTTP entonces ausentes.
- Suite final: **1316 pruebas OK en 16,964 s** con el ejecutor aislado.
  `manage.py check`: sin problemas. `diagnosticar_ia --sin-fuentes`: configuración
  revisada sin conexiones; 9B/9B, contexto 16384 y auditorías activadas.
  Lectura de sólo consulta: RAG de documentos ausente, RAG de fichas con cuatro
  fragmentos y conocimiento persistente con cuatro obras/cinco datos. Esto no
  equivale todavía a una base literaria amplia ni a descubrimiento autónomo.

Reproducción (rutas de salida nuevas para no sobrescribir resultados):

```powershell
.\venv\Scripts\python.exe -B verificar_proyecto.py core
.\venv\Scripts\python.exe -B evaluar_chat_http.py --matrix reportes\arquitectura_20261023\matriz_integral_20261023.json --prewarm --progressive --output reportes\arquitectura_20261023\nueva_integral.json
.\venv\Scripts\python.exe -B resumir_benchmark_ia.py reportes\arquitectura_20261023\integral_progressive_v2_9b_warm.json --review reportes\arquitectura_20261023\revision_integral_v2.json
```

### Siguiente paso

1. Priorizar evidencia/identificación y cobertura de personajes: bajar el p95
   devolviendo errores más rápido no cumple el objetivo de respuestas completas.
2. Revisar las autorías que caen al LLM y añaden valoración no solicitada; no
   promover el 4B sin un ensayo con las mismas evidencias y mayor cobertura.
3. Medir un índice semántico realmente poblado y ampliar conocimiento mediante
   fuentes permitidas, no confundir las fichas de arranque con ese benchmark.
4. Aún pendiente: streaming real de tokens (Ollama usa `stream=False`),
   cobertura completa de personajes/comparaciones y sesión MySQL aislada.

## Intervención anterior — arquitectura persistente y rutas rápidas verificadas

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
-> 1298 pruebas OK en 16.369 s

.\venv\Scripts\python.exe -B verificar_proyecto.py core.test_simple_factual_context core.test_persistent_router core.test_literary_ai
-> 99 pruebas OK en 0.956 s

.\venv\Scripts\python.exe manage.py check
-> System check identified no issues (0 silenced).

.\venv\Scripts\python.exe manage.py diagnosticar_ia --sin-fuentes
-> configuración revisada; sin conexiones externas
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

### Consultas compuestas, citas y materia general

Matriz: `reportes/arquitectura_20261023/matriz_benchmark_complejas.json`.
Primera ejecución: `despues_http_v10_complejas.json` (una repetición por caso,
caché de respuestas vaciada). Resultado real: la comparación se respondió en
4,625 s con una referencia web de una sola obra y 0 llamadas al modelo; la
cita exacta y la materia general quedaron `unavailable` en 35,018 s y 35,016 s
tras respuestas inválidas de Ollama; la pregunta de memoria sin contexto pidió
aclaración en 7,394 s. La comparación reveló un fallo: la ruta rápida aceptaba
una coordinación de dos obras como si fuera una sola.

Se corrigió con `compound_literary_request()`: comparaciones, diferencias,
«frente a», «versus», «ambos» y coordinaciones como «... y el de ...» o
«... con el de ...» se rechazan en `simple_literary_route`,
`simple_research_plan`, `indexed_answer` y `research_answer`. La sonda
posterior `probe_compuesta_v11.json` usó el pipeline completo (6 llamadas al
modelo) y tardó 35,060 s. Publicó sólo pasajes atribuidos de *El túnel* y no
inventó la comparación con *Madame Bovary*; la respuesta sigue siendo parcial,
no una comparación completa. Las pruebas nuevas están en
`core.test_simple_factual_context` y `core.test_persistent_router`.

### Limitaciones actuales

1. Las listas de personajes siguen siendo parciales: *Nana* devuelve un pasaje
   sobre la novela de Zola y *La Regenta* puede devolver contexto sin nombres.
   Evitan homónimos y adaptaciones, pero no sustituyen una lectura de la
   sección de personajes.
2. Wikipedia puede responder `rate_limited`; en ese caso la ruta rápida puede
   caer a la búsqueda web acotada o al pipeline completo. La latencia externa
   sigue siendo variable.
3. El benchmark cubre ocho preguntas simples con dos repeticiones y cuatro
   casos complejos con una; no demuestra cobertura general ni exactitud
   factual. La revisión fue interna, no independiente.
4. La caché y la memoria usan SQLite temporal en las pruebas; no se midió
   MySQL remoto ni el coste del middleware de sesión.
5. Las referencias parciales se presentan como pasajes atribuidos, no como
   fichas verificadas ni como respuesta exhaustiva.
6. Una comparación puede terminar publicando referencias de una sola obra si
   el modelo no completa la síntesis; no se inventa la comparación, pero la
   respuesta queda incompleta.

### Próximos pasos inmediatos

1. Mejorar el respaldo de comparaciones para incluir ambas obras o declarar
   explícitamente que no puede completar la comparación.
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
