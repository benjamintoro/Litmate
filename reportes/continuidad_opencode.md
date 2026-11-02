# Continuidad OpenCode — LitMate IA

Actualizado: 29 de octubre de 2026.
Rama: `feature/cuotas-ia-chatbot`.

## Expansión de conocimiento local y checkpoint (27 de octubre de 2026)

- Punto de partida de la unidad: HEAD `e142c63`; checkpoint de código de esta
  fase: `b3ac40d`, rama `feature/cuotas-ia-chatbot`. Se conservó todo el trabajo
  pendiente de Codex;
  no se hizo `reset`, `clean`, checkout destructivo ni push. El informe detallado
  está en `reportes/expansion_conocimiento_litmate.md`.
- Biblioteca: **12 libros activos**, **6.393 fragmentos de origen**, **561
  capítulos/secciones** y **9.656.545 bytes**. Se añadieron *La Regenta*
  (Gutenberg 17073) y *Marianela* (Gutenberg 17340), con SHA-256 y revisión de
  derechos en el manifiesto local. Los originales y bases están ignorados por
  Git.
- Catálogo: **300 registros españoles** aceptados de Project Gutenberg en
  **46.108** filas escaneadas, **0 errores** y **109,1553 s**. El ledger quedó
  con **2.298 registros** (2.296 Gutenberg + 2 Open Library), **0 relaciones**
  y **2.298 eventos de outbox en `done`**. Los checkpoints inglés
  (`offset=2.706`) y español (`offset=46.108`) siguen reanudables
  (`finished=0`).
- Índice: `data/biblioteca/rag.sqlite3` reconstruido para 12 libros:
  **11.289 fragmentos**, **11.289 vectores**, modelo `embeddinggemma:latest`,
  digest `85462619ee721b466c5927d109d4cb765861907d5417b9109caebc4e614679f1`,
  dimensión 768, `hybrid-v2`, **53,368181 s**. Se corrigió la idempotencia del
  comando con `CREATE TABLE IF NOT EXISTS` e `INSERT OR REPLACE`.
- Integración: la biblioteca local ahora alimenta también la ruta general de
  contenido, no sólo narración/personajes. Se corrigió el enlace cuando la
  ficha externa trae subtítulo o autor abreviado, se añadieron siete alias
  españoles con evidencia Open Library y se incluyó la revisión de la
  biblioteca y el flag semántico en la caché. El alias resuelve identidad, no
  certifica una sinopsis.
- Evidencia introductoria: `retrieve_library` marca `front_matter` sobre el
  fragmento completo antes del recorte; `assess_evidence` rechaza portadas,
  prefacios y listas de materias (`Temas del catálogo`) como sinopsis. Cuando hay
  una sinopsis web vinculada, `literary_ai` retira esos fragmentos locales del
  contexto; si no hay web, conserva el respaldo local sin convertirlo en trama.
- Investigación externa: se reconocen sufijos seguros de título web
  (`- Wikipedia`, `: resumen`, nombre del sitio) sólo con autoría coincidente, y
  el filtro de candidatos usa alias confirmados para no perder la obra local.
  Una tarjeta de libro no verificada se descarta si su título/autor aparecen en
  la web; una tarjeta inventada sigue el fallback seguro existente.
- Configuración: `LITMATE_LIBRARY_DB`, `LITMATE_LIBRARY_RAG_DB` y
  `LITMATE_LIBRARY_SEMANTIC_CHAT`. El último sigue **desactivado por defecto**.
- Pruebas: dirigidas de esta fase
  (`core.test_literary_research`, `core.test_hybrid_ai`,
  `core.test_literary_identity`, `core.test_literary_ranking`):
  **125/125 OK en 1,369 s**. Suite completa `core`: **1.636 pruebas, 4 fallos y
  2 errores en 228,839 s**; no está verde. Los casos abiertos están en
  `test_ai_public_details` y `test_chat_deadline`, archivos no modificados en
  esta fase. Log: `reportes/expansion_20261027/suite_core_20261027.txt`.
  Las advertencias de Wikipedia, TTS y semántica sí son pruebas de degradación
  controlada.
- Recuperación real de 12 libros: léxica Recall@5 **0,4333**, nDCG@10
  **0,3398**, p50 **0,2231 s**; híbrida Recall@5 **0,6333**, Recall@10
  **0,7333**, nDCG@10 **0,5542**, p50 **0,2837 s**, 30 llamadas de embedding y
  0 fallos. Es recuperación, no exactitud factual.
- Chat HTTP/SSE aislado, `qwen3.5:4b`, contexto 16.384, sin web, presupuesto
  75/90 s: léxico final **2/5 respondidas**, p50 **9,336 s**, máximo
  **12,863 s**; semántico final **2/5 respondidas**, p50 **9,782 s**, máximo
  **17,219 s**. Repeticiones idénticas dieron 3/5 y 2/5: el resultado no es
  determinista y no se debe presentar una sola ejecución como mejora estable.
- Revisión factual: en la ejecución semántica final, *Frankenstein* quedó
  `answered` pero atribuyó la carta a Elizabeth Lavenza; el fragmento local y
  la novela la atribuyen al padre, Alphonse. El estado `answered` **no es una
  certificación factual**. El caso se conserva como fallo de calidad.
- Investigación externa real: «¿De qué trata Orgullo y prejuicio?» ya no se
  detiene en el front matter. En `consulta_orgullo_web_20261027_run2.json`
  quedó `answered`, con una búsqueda web, cuatro fuentes (tres vinculadas) y
  `front_matter_excluded=4`; el texto fue una lista de pasajes atribuidos, no
  una sinopsis. Esa ejecución precedió al arreglo de alias y usó una identidad
  provisional, no el `work_id` local. `..._final.json` escaló y excluyó el front
  matter, pero la auditoría rechazó un acontecimiento sin respaldo
  (`quality_rejected`).
  `..._resumen_breve.json` respondió con un pasaje narrativo local, no con web.
  La escalada y el vínculo están demostrados; una sinopsis web coherente y
  estable no. `answered` no certifica verdad factual.
- Límite externo: `simple_literary_route` puede devolver `candidates=[]` para un
  resumen; una obra ausente de la biblioteca no tiene identidad local contra la
  que vincular páginas web. La web puede consultarse, pero no se garantiza una
  respuesta final. Queda como brecha conocida, no como cobertura completa.
- Learning-to-rank: candidato **experimental** con etiquetas
  `agent_reviewed`/`curated_test`, no activo y no elegible para producción.
  `training_readiness.ready=false` con cero pares/obras/consultas; la compuerta
  exige 200 pares, 20 obras y 80 consultas. Fixture de 16 obras: validación
  nDCG@10 0,9529 → 0,9590, prueba 0,8069 → 0,8069. Biblioteca de 5 obras:
  validación 0,8552 → 0,8552, prueba 0,9385 → 0,9385. Ambos rechazados por
  ganancia < 0,01; `human_labels=false`, `activation_eligible=false`,
  `model_activated=false`. No se cambiaron pesos de Ollama ni se instalaron
  dependencias.
- Checkpoint local: código de esta fase en `b3ac40d`; esta nota de continuidad
  se guarda en un commit documental posterior, sin push. Los corpus, bases e
  índices de `data/biblioteca/`, `data/adquisicion/` y
  `data/corpus_autorizado/` quedan fuera de Git.
- Siguiente paso: no activar semántica ni ranking por defecto. Primero hay que
  corregir la auditoría/atribución factual, cerrar la brecha de obras sin
  candidato local y recolectar etiquetas humanas verificadas.

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

## Corrección de protagonista (2026-10-27)

- Función modificada: `_facts` en `core/ai_character_answers.py` (extracción de roles desde descripciones cuando no hay `character_facts`), y `answer_from_sources` (fallback a fuentes web con rol narrativo explícito).
- Prueba: `core.test_protagonist_from_description` (2 tests OK).
- Resultado: protagonista se resuelve desde evidencia bibliográfica verificada; sin evidencia, no se inventa.
## Corrección de seguimiento (2026-10-27)

- Problema 3 corregido: "busca nuevamente" reutiliza la consulta original pendiente.
- Archivos modificados: core/literary_ai_views.py.
- Prueba: core.test_retry_followup OK.
- Problemas 1 y 2 (sinopsis/tramas) pendientes de investigación más profunda.
## Corrección definitiva (intento) — 2026-10-27

- Reproducción HTTP/SSE confirmó pérdida de contexto.
- Causa raíz no aislada en este lote (historial persistido no instrumentado).
- No se aplicaron cambios de memoria no verificados.
- Próxima acción: instrumentar history/active_work en el endpoint y repetir.
## Reproducción HTTP/SSE de memoria (2026-10-27)

- Endpoint real ejecutado con Ollama local.
- Resultado: 1 answered, 2 unavailable, 3 clarification, 4 answered, 5 unavailable,
  6 rejected, 7 answered, 8 clarification.
- Confirmado: pérdida de contexto de obra activa tras resumen y tras "Volvamos al primer libro".
- No se implementó corrección en este lote por falta de causa raíz mínima verificada.
- Próxima acción: instrumentar historial persistido y active_work en el endpoint.
## Validación final y memoria (2026-10-27)

- Funciones reconstruidas verificadas presentes.
- Pruebas dirigidas: 24 OK.
- Suite general: 1732 tests, 4 fallos + 2 errores, todos preexistentes/environmentales
  (red/BD), no introducidos por esta recuperación.
- Memoria: se analizó `.test-tmp/out_memoria`; 5 incidencias de aclaración.
  No se reprodujo un fallo mínimo en `request_for` con historial estándar.
  Se requiere reproducir por HTTP/SSE con el historial real para aislar la causa.
  No se aplicó corrección de memoria en este lote para evitar cambios no verificados.
## Recuperación de funcionalidad — object_relation_answer (2026-10-27)

- Causa: `git checkout` descartó cambios no confirmados en `core/ai_character_answers.py`,
  eliminando `object_relation_answer` (y `premise_answer`). La regresión afectaba
  `test_character_object_relation_uses_the_literal_role_not_the_generated_answer`.
- Funcionalidad reconstruida: `object_relation_answer` y soporte de tarea `object_relation`
  en `request_for`, más `premise_answer` para desbloquear pruebas.
- Archivos modificados: `core/ai_character_answers.py`.
- Pruebas ejecutadas:
  - `core.test_character_context_resolution`: 9 OK
  - `core.test_character_false_premise`: 8 OK
  - `core.test_character_quality_regression`: clases SimpleTestCase OK
  - `core.test_context_reference_scope`: 7 OK
- Limitaciones: implementación equivalente, no recuperación exacta del código original.
  `object_relation_answer` prioriza rol literal y pasajes con marcadores de relación;
  no inventa relaciones por coexistencia. Copia de seguridad en
  `G:/Proyecto/Litmate_security_backup`.
- Problemas pendientes: clase `CharacterProgressiveViewRegressionTests` (TestCase, BD)
  no se ejecutó en esta sesión.

## Codex — depuración específica de memoria HTTP/SSE (2026-10-27)

Se retomó el estado real de `feature/cuotas-ia-chatbot`, HEAD `28c7cab`, preservando modificaciones anteriores. No se usaron comandos destructivos de Git ni se tocó `Litmate_security_backup`. Se hicieron copias separadas antes de intervenir. Informe completo: `reportes/auditoria_conversacional/correccion_memoria_codex.md`.

Primera discrepancia comprobada: el primer turno de `.test-tmp/out_memoria/captura_001.json` sustituía «El Señor de los Anillos» por tres tarjetas de volúmenes generadas sin fuentes (`source_id=0`). `remember` persistía esas tarjetas y `_history_works` las interpretaba como tres obras activas: el siguiente personaje llegaba al resolvedor con título vacío/ambigüedad. El mínimo real con «Háblame de…» ya respondía antes (2,950/3,817 s); no se presenta como fallo. La variante «Habla de…» y la respuesta con tres tarjetas se reprodujeron con proveedores deterministas en dos solicitudes HTTP/SSE: 3 pruebas, 4 fallos antes; pasan después.

Cambios de esta tarea: módulo pequeño `core/literary_focus.py` sobre la sesión existente; selección del foco antes del worker; conservación separada de intención, metadatos y evidencia; preservación de foco ante `unavailable`; `work_order` acotado y retorno determinista sin LLM; no se mutan las fichas de turnos previos. Normalización conserva `context_work`. Parser reconoce «Habla de/Hablemos de/Ahora háblame de» y no convierte el título en personaje. Referencias de acción mantienen el alcance de la obra en el fallback web. Consulta del acompañante del protagonista exige evidencia de acompañamiento, reutilizando fuentes de la obra tras la navegación.

Instrumentación: se reutilizó `_memory_trace`, apagada por defecto, con contexto normalizado/resuelto, resultado y persistencia también en `chatbot_finalize`. Sólo se generaron trazas de conversaciones sintéticas. Archivos de producción intervenidos: `literary_focus`, `literary_ai_views`, `literary_ai`, `literary_identity`, `ai_narrative_answers`, `ai_character_answers`, `ai_quick_answers`. Pruebas: `test_http_work_focus`, `test_memory_trace`, `test_context_reference_scope`. El resto del diff preexistente se conservó.

Validación: 104 pruebas dirigidas OK; suite general del código final de producción, 1.731 pruebas OK en 25,407 s (luego se añadió una prueba de ventana/retorno aprobada en el lote dirigido). Tres regresiones inicialmente detectadas se corrigieron en código. SQLite temporal, sin migrar ni modificar bases del proyecto. Las seis incidencias de informes previos no aparecieron en esta ejecución; no se asumen ambientales sin evidencia.

Captura real definitiva con Ollama `litmate-qwen35-text:9b-q4_K_M`, HTTP/SSE/finalización y sesiones distintas: `memoria_codex_final.json`, matriz `memoria_codex_matriz.json`, trazas `memoria_codex_final_trazas.jsonl`. Código sin cambios durante la ejecución. 16 turnos: 12 answered, 4 unavailable, 0 clarification; media 3,962 s, p50 2,278 s, p95 35,074 s; 15/16 <30 s. Los cambios LOTR→Harry→LOTR y Quijote→Frankenstein→Quijote se conservaron. D (fallo controlado) y E (sesiones independientes) se probaron con proveedores simulados, no se presentan como conversaciones reales de Ollama.

Mejora puntual: C6 «¿Quién acompaña al protagonista?» bajó de 31,994 s/5 inferencias en `memoria_codex_BC.json` a 0,125 s/0 inferencias y 0 HTTP en la captura final; responde Sancho, retirando la inclusión indebida de Dulcinea. No extrapolar ese cambio a todo el asistente.

Pendientes explícitos: A3 recibe correctamente Frodo/Sam y LOTR pero no consigue evidencia específica suficiente; C3/C4 conservan Frankenstein pero fallan en la unión de identidad/contenido; B6 vuelve a LOTR pero el pipeline de ruta/plan/generación/auditoría/reparación alcanza 35 s y termina sin respuesta válida. El fallback ya no publica el resultado de Voldemort de la captura intermedia. El p95 <30 s y la tasa de error <1 % **no están acreditados**. Continuar desde esas capturas sin volver a auditar genéricamente ni convertir el contenido del modelo en hechos.

## Lote 01 — Generalización de alias e ingesta incremental (2026-10-27)

Encargo: adjunto `6794e393-781f-4d36-bca3-d7dc0ebc6f7d/Texto pegado.txt`. Se trabajó por un lote concreto, sin reescritura general ni reglas por título. Informe reproducible: `reportes/generalizacion_20261027_lote01/resultados.md`.

- Conservados rama `feature/cuotas-ia-chatbot`, HEAD `28c7cab` y cambios anteriores. Copia separada de código/diff en `reportes/diagnostico_para_revision/generalizacion_20261027_01/`. No hubo migraciones, instalaciones, cambios de .env, commits ni push.
- Defecto: las relaciones exigían nombres literales pese a disponer de alias explícitos en fichas de la misma obra. La memoria sólo conservaba alias entregados por el adaptador, sin extraer declaraciones literales. Se unificó `_character_aliases` en `literary_memory` y se agregó resolución de los dos participantes en `ai_character_answers`, con rechazo de alias compartidos y sin reescribir evidencias. La relación literal sin ficha del segundo participante sigue permitida; una regresión inicialmente detectada se corrigió conservando su prueba.
- Desarrollo sintético: 2 fallos iniciales / 3 casos; después pasan. Validación controlada independiente sobre entidades de cinco obras: 0/5 antes frente a 5/5 después usando el módulo de copia previa y los mismos validadores. **Son fixtures lingüísticos, no citas públicas ni exactitud factual real de esas novelas.** Negación, coaparición, ocupaciones, contaminación de obra y colisiones siguen rechazadas.
- HTTP/SSE real independiente: `chat_independiente.json`, 11 turnos, 7 answered y 4 unavailable, p50 2,460 s, p95 5,412 s, 0 llamadas LLM por uso de rutas extractivas. Pip responde; Sam, La Maga, Sméagol y Boo siguen sin evidencia suficiente. No se declara arreglada la cobertura general. Tras la corrección de compatibilidad se comprobó con código final Grandes esperanzas/Pip: 2/2, 2,642 y 2,124 s (`chat_final_compatibilidad.json`). Ambos archivos tienen código estable durante su captura.
- Ingesta mejorada: `_put(with_status=True)` distingue inserted/updated/duplicates/stale sin romper su interfaz booleana previa; `literary_gutenberg` registra estos contadores. `coverage_snapshot` mide sólo fuentes vigentes/permitidas y separa metadatos, descripciones, personajes y relaciones; no crea bases ausentes.
- Ingesta real, **sin descargar textos**: catálogo oficial Gutenberg ya descargado, SHA `ebf4f6e54a34dddbcd26ca8a5ef593c9cf3e0ab8b331628ea7a49170a196a07e`, lote español de 30 aceptados. 2.967 escaneados, 30 insertados/proyectados, 1.825 filtrados, 1.112 rechazados por formato/autoría/tipo, 0 errores, 7,9391 s. Cursor 46.108→49.075, reanudable. Antes de escribir se respaldaron las dos SQLite públicas en `backup_publico_previo/`; no se tocó la DB Django. Repetición exacta: 30 duplicados; proyección repetida: 0. Ledger 2.298→2.328, obras únicas 2.201→2.230, autores normalizados 817→828, fuentes 2.328→2.358. Personajes/relaciones/textos no crecieron.
- Recuperación de las 29 obras realmente nuevas, sólo título/autor: Recall@5 0→27/29 (0,9310), MRR@5 0→0,8966; p50 2,258 ms, p95 4,813 ms después. No es evaluación de argumentos ni mejora del ranking por sí misma. Faltan en top 5 Agua de Nieve (Novela) y Despertar Para Morir (Novela).
- **195 pruebas dirigidas OK; 1.742 generales OK en 27,582 s**. Primera suite detectó una regresión, reparada sin relajar el test. Logs y comparación en el directorio del lote. No se añadieron modelos, dependencias, conectores, facturación ni tareas permanentes.
- Siguiente lote: descubrimiento/vinculación de evidencia de alias con APIs existentes y validación con un nuevo grupo C; B ya fue observado. Después identidad bibliográfica general (Frankenstein y variantes), recuperación y ciclo lento de cinco inferencias del Anillo. No volver a ingerir ciegamente: `ingestar_lote.py` rechaza una repetición accidental si existe el informe; continuar con un informe/copia nuevos desde el checkpoint existente.

## Lote 2 — Profundidad e integración de memoria pública (2026-10-27)

Encargo: adjunto `be475916-0bc9-43e8-bd38-4465bd1e8950/Texto pegado.txt`. Informe específico con causas, capturas y comandos: `reportes/generalizacion_20261027_lote02/resultados.md`. Conservados rama, HEAD y cambios anteriores. Copias de código/diff en `reportes/diagnostico_para_revision/generalizacion_20261027_02/` y de SQLite públicas en el directorio del lote. Sin migraciones, instalaciones, .env, cambios visuales, commits o push.

- Extracción: se ignoraban párrafos de definición y el encabezado «Personajes relevantes»; se recortaba antes de priorizar al personaje pedido. Se corrige en `literary_web`, con 64 candidatos internos/12 fichas y 1.800 caracteres finales, sólo en secciones declaradas. Reproducción: 3 fallos de 4 antes; pasan después.
- Alias/perfiles: comprobación estricta de nombre completo con apodo entrecomillado intercalado, reutilizada en prueba literal y persistencia. `bind_character_profile` exige novela y autor concretos, no un universo o tomo por parecido. Sam queda respaldado por su perfil oficial y la relación con Frodo por el pasaje de la obra. La Maga/Lucía se recupera en Rayuela. Boo y Sméagol siguen pendientes: narrativa sin sección/ficha y vinculación al tomo/declaración de nombre original, respectivamente. No se escribieron excepciones por título.
- Identidad: prioridad de tipo publicado frente a adaptaciones con año; alias bibliográfico explícito «o simplemente X», con atribución/revisión/licencia y autoría, no recorte de prefijos. La sinopsis de Frankenstein ya responde desde la novela. No se reconstruyeron todos los ISBN/traducciones/ediciones.
- Anillo: `goal_answer` reutiliza la oración literal de una misión ya aceptada, con la misma auditoría estricta; no la usa para afirmar una acción consumada. Misma conversación de seis turnos: última pregunta 35,074 s/unavailable/5 inferencias → 0,070 s/answered/0 inferencias/0 HTTP. La conversación posterior aún tuvo una abstención sobre Harry; no ocultarla.
- Fallo compartido adicional demostrado por benchmark sin web: `quick_knowledge_sources` descartaba los libros devueltos separadamente por la memoria cuando sólo había fuentes web. La evidencia quedaba sin identidad bibliográfica. Se conserva esa identidad sin relajar validadores ni crear hechos. La nueva prueba fallaba antes y pasa después. Las futuras proyecciones Wikipedia retienen introducción bibliográfica y se comprueban inyecciones también en ella.
- Ingesta real: 8 consultas configurables, 6 aceptadas/5 obras con contenido; Wikipedia con cupo de 2 lecturas por consulta, no otros proveedores. 10 metadatos franceses Gutenberg desde archivo oficial ya existente; cursor francés 0→1.318, español permanece 49.075. Tiempo total 20,186 s. Ledger 2.328→2.343, pares título/autor 2.230→2.245, autores 828→832, fuentes vigentes 2.358→2.377; obras con descripción 2→7, con personajes 1→3, etiquetas canónicas con papel 12→37, alias respaldados 0→4. Relaciones estructuradas y textos completos añadidos: 0. Repetición de 5 registros finales: 5 duplicados; proyección repetida: 0. No confundir escrituras `inserted` históricas de query_acquisition con obras nuevas: usar estados del almacén.
- El nuevo `--memory-snapshot` copia sólo una memoria pública validada a la SQLite temporal del benchmark; origen RO, sesiones nuevas. Misma copia/SHA, mismas 11 preguntas, HTTP/SSE real y fuentes externas deshabilitadas: antes del puente 0 answered; después 8 answered y 3 unavailable; LLM 16→7; media 4,971→1,930 s; p95 35,045→12,020 s. Sam 0,462 s; La Maga 0,153 s. No es comparación directa con las distintas preguntas online del lote 1. No se acredita error <1 %.
- Grupo C independiente no se usó para ajustar el algoritmo: Jane Eyre sólo obtuvo introducción y no personajes (2 abstenciones), Narnia no se vinculó (1 abstención); La tregua se rechazó por desambiguación; El origen de las especies respondió desde contenido almacenado. Mantener estos fallos como evidencia, no afirmar generalización completa.
- 247 pruebas dirigidas OK (8,310 s) y 1.759 generales OK (27,594 s). Benchmark detectó un choque de nombre de variable en el runner, corregido. Conservar tanto las capturas fallidas como las posteriores. Código estable durante las capturas completas. Recall@5/MRR@5 1,0 sobre 10 consultas de nuevos metadatos franceses; no implica comprensión narrativa.
- Producción intervenida: literary_web/search/identity, ai_character_answers, ai_narrative_answers, ai_quick_answers, literary_memory/acquisition y literary_ai_views. Runner evaluar_chat_http ampliado. Nuevas pruebas de extracción, perfil, alias publicado, misión, puente persistente y copia de memoria pública. Modelos, embeddings, configuración y diseño conservados; APIs nuevas de pago: ninguna.
- Siguiente lote: grupo D nuevo para narrativa sin sección y nombres originales (Boo/Sméagol como desarrollo); desambiguación tipada y traducciones (La tregua/Narnia); profundidad de Jane Eyre; relaciones estructuradas respaldadas; estadísticas de escrituras de consultas. Continuar mediante otro directorio/informe/manifiesto, sin repetir accidentalmente este lote ni alterar el backup previo.

## Fase 1 — Estabilización, lote 1 (2026-10-27)

- Informe completo: `reportes/estabilizacion_20261027_lote01/resultados.md`. Antes de editar se revisaron el estado real y el lote 2 más reciente. Copias de los dos módulos y diff previo en `reportes/diagnostico_para_revision/estabilizacion_20261027_01/`; conservarlos junto a todos los respaldos anteriores.
- Dos correcciones de identidad: `_profile_name_in` deja de sustituir/omitir nombres intermedios y reutiliza la comprobación estricta con alias entrecomillado; `retrieve_character_entities` agrupa sólo equivalencias canónicas explícitas por obra, sin fusionar personajes por alias compartidos. La ambigüedad también protege la atribución de relaciones. No requiere migraciones ni reindexación.
- Regresión creada antes de corregir: siete pruebas iniciales, nueve fallos incluyendo subtests. Archivo final nuevo `core/test_identity_stabilization.py`, 11 pruebas. 119 dirigidas OK (4,327 s), 1.770 generales OK (28,906 s), diff sin errores de espacios. El envoltorio de consola de la suite falló al imprimir CP1252 después del OK; se conservaron el log completo y copia UTF-8. No confundirlo con un fallo de tests.
- Comparación reproducible cargando módulos previos desde el respaldo, mismas SQLite temporales, sin reemplazar código real: 4/9→9/9 comprobaciones controladas; recuperación p95 2,329→2,032 ms en 60 muestras por modo, 0 LLM/HTTP y bases sin cambios. No es exactitud literaria global ni prueba de aceleración general.
- HTTP/SSE real, misma copia pública SHA c6b158883dde1c028b81ed1263ee4107a1266cbd5c3eaa8532ce6832e0cfeb4a, sin Internet: primera captura 7/11 answered, p95 10,162 s; confirmación 8/11, p95 9,691 s; 7 LLM por captura, 0 HTTP, todos los turnos <30 s. Primera captura pudo coincidir parcialmente con la salida de la suite: usar confirmación para latencia aislada. Preservar ambas. Víctor volvió a abstenerse en una: generación/citas siguen inestables. Sam y La Maga responden. Jane Eyre y Narnia siguen sin evidencia suficiente.
- Revisión de pertinencia pendiente: resumen de Frankenstein centrado en la criatura y fuentes de novela/perfil mezcladas. `work_binding_verified` no prueba suficiencia para la tarea de resumen. No llamar correctas todas las respuestas sólo por tener fuentes/auditoría.
- Grupo D controlado: Montecristo, Fantasma de la ópera y Vuelta al mundo con fixtures lingüísticos auditados; no citas públicas verificadas. Prueba web real independiente de Montecristo/Dantès y Jekyll/Hyde: 4 abstenciones, 22 HTTP iniciados, 0 LLM, 0 páginas extraídas; SearXNG devuelve resultados, pero el cupo de tres lecturas ya está consumido antes de leer candidatos web. Congelar estos fallos como casos observados. Próximo grupo independiente: E.
- Próximo lote: reproducir agotamiento del cupo antes de evidencia útil y mejorar asignación/reutilización de lecturas; separar perfil/obra/sinopsis; después citas y reparaciones del pipeline general, Boo/Sméagol y traducciones. `premise_answer` es un helper no conectado con una inferencia negativa insegura: no activarlo sin arreglar/auditar.
- Sólo producción `ai_character_answers.py` y `literary_memory.py` modificados en este lote; se conservaron sus cambios previos. Diseño, personalidad, voz, avatares, modelos y validadores intactos. Memoria pública origen con SHA sin cambios. Sin instalaciones, .env, settings, migraciones, ingesta, commits/push ni APIs pagadas nuevas.

## Regresión de recomendaciones y tarjetas — cierre 2026-10-28

- Pedido adjunto repetido verificado como idéntico; se continuó sobre el árbol real, sin revertir avances. Informe completo `reportes/regresion_tarjetas_20261027/resultados.md` (directorio del inicio 27/10). Respaldo previo de módulos/docs, diff y pruebas antiguas en `reportes/diagnostico_para_revision/tarjetas_recomendaciones_20261027/`.
- Caso exacto reproducido por HTTP real: Colombia devolvía cuatro artículos, 0 tarjetas, 4,975 s. Causa principal `_simple_topic_request`: borraba «historia» antes de reconocer «historia de Colombia», no invocaba discovery y views publicaba web_reference_answer. Se consumen spans sobre el texto original. No se añadieron títulos/países especiales.
- Eliminada la sustitución de recomendaciones por artículos en fallback temprano, backup de modelo complejo y excepción allow_web_only_recommendations. Caché namespace `extractive-answer-v3-verified-book-cards` y guardia contra respuestas de artículos sin tarjetas; no se borraron datos. Nuevos candidatos desde pares literales web se confirman en catálogos, máx3; probado con mocks, no afirmar activación real de ese fallback en esta batería.
- Sinopsis opcionales OL: hasta2 registros, presupuesto2s/caché/cupo existente, sin perder fichas ante errores. Una captura detectó extensión física «316 p. :22 cm» como descripción: regresión y filtro físico general añadidos. No inventar sinopsis ni interpretar materias como trama.
- Memoria: remember_topic y remember_focus conservan active_work al recomendar; no se promueve automáticamente una sugerencia en la compatibilidad de sesiones. Intentrecommend persiste en historial; selección explícita usa tarjetas separadas del foco. Corregido «Háblame del segundo libro» que quedaba como «l segundo libro». F conserva Frankenstein tras recomendar; el segundo libro pasa a activo y Frankenstein a previous_work.
- Frontend conserva estética y contrato. Whitelist añade sólo OpenLibrary/Wikidata oficiales, botones de búsqueda Google/Amazon/Buscalibre explícitos, títulos seleccionables accesibles mediante envío existente. Fuentes con sufijo HTTPS inequívoco plegables; avisos/prosa/URLs inseguras nunca se ocultan. Voz/avatar intactos.
- Primera batería real 8/9: relacionados con Dune se abstuvo por autores abreviados en texto. Nueva ruta pura por materias específicas/autor completo usa validadores existentes, excluye base/ediciones/repetidos y no certifica semejanza argumental. Categorías genéricas no bastan. La descripción primaria no vuelca materias como sinopsis.
- Comprobación final `http_comprobacion_final.json`, código estable: Colombia3 tarjetas/3,523s; terror5/3,025s; Chile3/3,200s; romance catalogadoJapón3/3,039s; tres relacionados con Dune3/3,544s. Estas recomendaciones usan0LLM. Total9turnos:8answered/1unavailable, media6,293s, p95/máximo22,485s, todos<30s. La abstención es el resumen inicial de Frankenstein17,530s/0LLM; se conserva como pendiente, no ocultarla. Dune resumen22,485s/2LLM. Primeras/finales capturas y diagnósticos se conservan, sin extrapolar exactitud global.
- SSE directo Colombia3tarjetas/3,165s; igualdad exacta con payload progresivo finalización JSON. Capturas QA Edge con renderer/CSS reales: Colombia3portadas/12enlaces y terror5portadas/2sinopsis/20enlaces, callbacks correctos, passed=true. Son páginas QA locales, no navegación autenticada completa. Equivalencia visual con payload final y hashes en equivalencia_visual.json.
- 54 nuevas regresiones dirigidas OK (0,307s), 1.824 generales OK (28,498s), Node230OK. Cinco pruebas históricas que exigían artículos como recomendaciones o borrar foco se actualizaron a la política solicitada, con respaldos y regresiones nuevas; no se desactivaron validadores. Ver logs completos del directorio.
- Pendientes: contenidos/Frankenstein y fallos anteriores, cobertura de subgéneros y restricciones complejas, idiomas/nacionalidad/transliteraciones y sinopsis ausentes. Japón como materia no prueba autor japonés. No garantizar calidad literaria o error<1% por match de metadatos.
- Sin paquetes/modelos nuevos, .env/settings, migraciones, datos privados/producción, cambios globales de UI, commits/push o APIs pagadas. Reiniciar Django y Ctrl+F5 para cargar cambios; comandos y reproducción en el informe.

## Presentacion narrativa y dependencias - 2026-10-28

- Pedido adjunto 7a8e3eac-3e92-45cb-a22f-3417c097fb3b. Informe: reportes/presentacion_20261028/resultados.md. Arbol inicialmente limpio, HEAD 41cb98d; respaldos de modulos y pruebas anteriores en ese directorio.
- reference_answer reutiliza direct_answer con auditoria existente para preguntas narrativas; ya no reemplaza un fallo por fragmentos de buscador. Reconoce 'Cual es la trama', formato manga explicito y titulo de manga de una palabra con identidad documentada. Prompt prioriza argumento; no se desactivaron validadores ni se agregaron reglas por obra. Namespace de cache v4 sin borrar datos.
- Renderer: dominios cortos con href reales; pie narrativo plegable con atribucion. Limitacion parcial permanece en cuerpo. Tarjetas, voz, avatar y CSS intactos.
- Seis regresiones fallaban antes; 11 nuevas pasan despues. Ajustadas expectativas historicas que exigian fragmentos como respuesta factual; conservados controles de cache y desambiguacion. Suite final estable: 1845 OK en 71,876 s; Node 233 OK; diff check OK.
- HTTP/SSE real: http_codigo_final.json contiene Naruto answered 27,818 s, 2 LLM, y El principito answered 0,121 s desde ficha local. La ultima captura despues de mover la limitacion antes del pie volvio a agotar 36,009 s y queda unknown; tambien fallaron las dos capturas iniciales por proveedor/auditoria. Preservar todos los archivos. No declarar latencia resuelta ni exactitud global. Esa posicion del pie tiene validacion controlada, no entrega real final exitosa.
- Pendientes: respuesta final ausente al agotar auditoria; recuperacion de trama y clasificacion tipada de entidades Wikidata (se observo posible videojuego en personajes). No usar estado answered como certificacion factual.
- Pedido previo requirements completado: lista base de 13 paquetes, alias requirements-ia-pc y extra opcional legacy-ai con Pinecone/SentenceTransformer. Informe reportes/dependencias_20261028.md y respaldos/logs en diagnostico_para_revision/requirements_20261028. Tres dry-run offline exit 0 y pip check OK; no instalacion limpia. Python existente 3.14.7; no copiar paquetes de respaldos como dependencias activas.
- Sin instalaciones, migraciones, cambios de .env/modelos/bases, commits ni push. Reiniciar Django y Ctrl+F5 para cargar Python y JS.

## MySQL local, respaldo y contadores - 2026-10-28

- Encargo: preparar MySQL 8.0.46 sin perder datos; conservar todos los cambios de IA previos. Respaldo de configuracion/diff previo en reportes/mysql_20261028/. Informe completo resultados.md; procedimiento MYSQL_LOCAL.md.
- Origen real: TiDB remoto 8.5.3; NO existia db.sqlite3 en raiz. 36 tablas, 2943 filas (2917 datos + 26 historial). Diez SQLite auxiliares de IA siguen independientes; LocMem observado, Ollama/SearXNG externos sin cambios.
- Respaldo definitivo backups/mysql_preparacion_20261028_03: exportacion completa, DDL, restricciones, proximos IDs, SQLite Django portable, 88 archivos y diez copias SQLite online/WAL. Hash manifest 89e44e64babf9278643e5ef45c607a61de6e3e65973b050bccba7e1efccb1005; verificacion final confirma origen y archivos intactos. Preservar _01 y _02; _02 incompleto/TLS, no importable. No reutilizar _01 para el corte con continuidad de contadores.
- settings usa database_settings.database_config con DB_ENGINE explicito y compatibilidad USE_SQLITE/DB_HOST; .env intacto, seleccion predeterminada sigue TiDB. Ejemplo actualizado, mysqlclient 2.3.0 registrado, PyMySQL conservado para remoto. Native Windows TLS rechazo TiDB; auto conserva cliente anterior para remoto y prefiere native en localhost, sin quitar TLS.
- Incidente importante: el importador fallaba antes del DDL del destino al comparar contador reservado de TiDB 150001 (SHOW CREATE) contra SHOW TABLE STATUS=0, convertido a 1. La hipotesis de cache MySQL no fue la causa. Se comprobo que local seguia completamente vacio. SQLite de respaldo: seq=150000, max=120008, 132 permisos. Regresion exacta falla antes 1!=150001; next_id_value corregido por servidor y conversion SQLite ultimo+1. No hay excepcion por tabla.
- Tras 14 dirigidas OK se ejecuto importacion real con destino vacio, entrada getpass oculta. Informe mysql_importar-mysql_20261028_144909_715477.json: 36 tablas, 2917 filas copiadas, historial 26, huellas de contenido/claves y FK/indices verificadas antes y despues del commit. auth_permission mantiene132 filas/max120008/next150001; trazas de origen/precommit/postcommit con atomic/autocommit.
- Verificacion independiente REAL con mysqlclient nativo: mysql_verificar-mysql_20261028_145108_617506.json, integrity_verified=true, django_database_checks=ok, 36 tablas/2943 filas. Datos como179 usuarios,55 libros,50 conversaciones,190 mensajes,42 pagos preservados, incluidos hashes de passwords. No se guardaron credenciales ni se editaron secretos. Informes nuevos fuera de backups.
- Incidente comunicado: la construccion inicial del destino vacio reprodujo migraciones historicas con DeleteModel sobre estructuras temporales recien creadas. No se borraron datos originales, pero no respetaba la prohibicion literal de DROP. Se reemplazo para futuras restauraciones con create_final_schema directo desde estado final, sin reproducir DROP/TRUNCATE/DELETE. No se reconstruyo el MySQL ya poblado. Guardia de regresion y preview MySQL nativo:102 sentencias compiladas sin ejecutar,0 destructivas,datos nuevamente verificados.
- Cierre:14 dirigidas OK;1859 generales OK en76,003s;Node233 OK;pip check OK;makemigrations --check --dry-run sin cambios;diff check OK. Sin nuevas migraciones/modelos, instalaciones, commits ni push. Todos los cambios previos conservados.
- Pendiente MANUAL: seleccionar MySQL local al arrancar Django con el bloque PowerShell temporal/Get-Credential de MYSQL_LOCAL.md y revisar flujos de usuario. No afirmar corte de ejecucion realizado: .env sigue apuntando al remoto. No repetir importacion sobre datos existentes. Para volver a SQLite despues de nuevas escrituras MySQL, respaldar primero el estado actualizado; no hay sincronizacion bidireccional.

## Activacion real MySQL local - 2026-10-28

- Objetivo unico: ejecutar Django con MySQL local y probar la aplicacion, sin reimportar ni cambiar .env. Revisados MYSQL_LOCAL.md, informe de migracion y git status; todos los cambios anteriores conservados.
- Creado iniciar_mysql_local.py: variables DB_ENGINE=mysql, DB_MYSQL_DRIVER=mysqlclient, DB_NAME=litmate_db, DB_USER=litmate_app, DB_HOST=127.0.0.1, DB_PORT=3306, DB_SSL_CA vacio, password por getpass. Solo cambia su proceso, antes de cargar Django; revierte entorno al salir. Comprueba SELECT DATABASE()/VERSION()/@@port y migraciones pendientes sin aplicarlas.
- Creado core/mysql_activation.py y cuatro pruebas core/test_mysql_activation.py. Verificacion REAL con default MySQL, URLconf/middleware/templates originales, HTTP/SSE/finalizacion y sesiones DB reales. Lee catalogo e historial via ORM con joins, comprueba esquema/indices/FK/contadores y huellas antes/despues. No usa cuenta privada ni base temporal para las capturas reales.
- Dos intentos iniciales fallaron403 porque el entorno heredaba DEBUG=False y cookies Secure para HTTPS. Agregado --http-desarrollo explicito, DEBUG=True solo en proceso loopback; CSRF permanece activo (403 sin token,200 con token). No modificar la seguridad global ni usarlo como despliegue publico.
- Activacion exitosa activacion_20261028_181421_656984.json y repeticion exitosa activacion_20261028_181750_116637.json en reportes/mysql_activacion_20261028/. Tres turnos por sesion: trama El principito, sus personajes, autor de ese libro; answered3/3, contexto correcto, SSE y finalizacion200,0LLM. Latencias primera0,212/0,084/0,131s; repeticion0,212/0,088/0,160s. No es benchmark del LLM. Ollama API disponible.
- Cada verificacion creo una sesion anonima normal: DjangoSession76->78, total2943->2945. No se borraron sesiones. Otras tablas conservaron huellas:179usuarios,55libros,50conversaciones autenticadas y190mensajes importados. Historial autenticado leido via ORM, sin login/escritura bajo cuenta ajena. SessionStore realMySQL conserva3turnos y foco El principito por cliente; no cookies/sessionkeys en reportes.
- Conocimiento SQLite independiente sigue disponible:2255obras,841autores,2387fuentes vigentes,37personajes en3obras; recuperacion persistida de una ficha/fuente. RAG/biblioteca/vectores/adquisicion/cache/SSE no migrados ni recreados. .env y backup03 hashes intactos.
- Servidor dejado activo: http://127.0.0.1:8000/, PID observado13688, proceso iniciar_mysql_local.py --verificar-y-servir --http-desarrollo --puerto8000. GET /,/chat/,/libros/,/static/js/litmate_safe.js verificados200 sobre el puerto final. Comprobar PID actual antes de detener; puede cambiar/reutilizarse.
-40 pruebas dirigidasOK en6,041s (activacion,transferencia,conversacion) con SQLite temporal; no atribuir las1859 generales de la fase anterior a esta fase. Sin migraciones/importaciones/instalaciones ni DROP/TRUNCATE en datos reales; sin commits/push.
- MYSQL_LOCAL.md y LEEME.md actualizados: arranque explicito con .\venv\Scripts\python.exe -B iniciar_mysql_local.py --http-desarrollo; passwordoculta; --solo-verificar opcional anade sesion normal. Volver a TiDB: detener lanzador, nueva terminal sin variableslocales y ejecutar manage.py con configuracion anterior. No hay sincronizacion automatica; conservar escrituras nuevas de MySQL antes de cambiar fuente definitiva.
- Informe autocontenido reportes/mysql_activacion_20261028/resultados.md. No quedan pasos de activacion pendientes para el servidor actual; siguen fuera de esta prueba login real y todos los flujos autenticados/comerciales.

## 2026-10-28 — Español y limpieza de presentación del chat

- Alcance autorizado: idioma por defecto y retirada del pie «Fuentes de las fichas». Conservados los cambios anteriores; no se editaron .env, settings, MySQL, arranque, RAG, memoria, avatar ni estilos en esta fase. .env y manifest backup03 conservan hashes 1d8e35effc765d26ecb73f3e2ee26c886a1e3d98b1bc45590c356b8604008e74 y 89e44e64babf9278643e5ef45c607a61de6e3e65973b050bccba7e1efccb1005.
- Causa: rutas rápidas y tarjetas copian sinopsis bibliográficas sin pasar por generación; el prompt español no las afectaba. RenderMessage creaba el desplegable redundante de fichas.
- Nuevos literary_presentation_language.localize_result/prepare_presentation, response_language/narrative_language en literary_language: traducción local por lotes y verificación bilingüe, conservación de títulos/autores/ISBN/URLs/números/citas, política común antes de publicar todas las rutas. Fuentes y auditoría factual originales intactas, traducción identificada como presentación. Caché Django por contenido/modelo/idioma/versión/glosario, 30 días, sólo sinopsis públicas, no respuestas privadas; LocMem no sobrevive al reinicio.
- ai_presentation sólo sustituye sinopsis visibles después de comprobar identidad y enlaces originales; local_llm añade esquemas language_translate/language_verify con cliente y presupuesto existentes; literary_ai_views aplica presentación tras respuesta/caché. JS omite pies inequívocos de fichas sin ocultar limitaciones, licencias ni fuentes narrativas; tarjetas y botones conservados.
- Prueba real descubrió traducción incorrecta de High Middle Ages a Alta Edad Media que el verificador del modelo no detectó. Se creó mecanismo de glosario con procedencia universitaria (presentation_terminology.json: Plena Edad Media y Baja Edad Media), independiente de libros concretos, protegiendo títulos y citas. Regresiones nuevas para esto, idioma dentro de títulos, español sin inferencias, caché pública, identidades y enlaces.
- Cierre general: 1880 ejecutadas en78,534s,1879 aprobadas,1integración real optativa omitida; esa integración pasó explícitamente (8,788s última ejecución).16 regresiones de idioma OK; Node233 OK; git diff --check OK. Hubo fallos intermedios por detección demasiado agresiva del español, corregidos sin alterar expectativas antiguas. Una ejecución concurrente mostró sensibilidad previa a mtime de SQLite en test_ai_library_router; pasó aislada y en suite final, sin tocar RAG.
- HTTP/SSE real y Ollama litmate-qwen35-text:9b-q4_K_M, ficha REAL de API Open Library OL1388255W:7,216s primera traducción+verificación(2llamadas);0,034s repetida(0);0,040s sinopsis con fuente(0);0,036s inglés explícito(0). Una ejecución previa inicial dio3,659s; no prometer esos tiempos para búsquedas completas. La ficha se inyecta en límite previo a presentación; NO afirmar benchmark de ranking/SearXNG. Sesiones firmadas e índices temporales, sin MySQL.
- Informe reportes/idioma_20261028/resultados.md; conversación real http_sse_ollama_real.json; log general pruebas_generales_finales.txt. Reproducir: LITMATE_RUN_LANGUAGE_LIVE=1 y verificar_proyecto.py core.test_presentation_language_live.LanguageLiveHTTPTests. Detección heurística y verificación del modelo no garantizan traducción perfecta; fallo/timeout produce limitación, no nuevos hechos. Sin dependencias, migraciones, commits ni push. Para ver cambios, reiniciar Django con el lanzador previo y recargar navegador; no se alteró el mecanismo de arranque. El puerto8000 no tenía listener al comprobarlo durante esta fase; no asumir activo el servidor de la fase anterior.

## 2026-10-28 — Reorganización conservadora del repositorio, lote 1

- Solicitud en adjunto c194df16-a944-4372-b410-8de8bf1207e4: inventario y traslado por grupos pequeños, primero documentación/informes/herramientas; no mover toda la IA en esta intervención. Se revisó git status y se conservaron todos los cambios previos.
- Inventario AST previo:354 archivos,261 módulos Python,2703 imports,4 imports/recargas dinámicos,31 anclajes __file__,121 archivos test de core,10 archivos de migraciones incluidos init;46 candidatos de IA. core.literary_ai tiene88 archivos importadores, identity51, quality36. Inventario origen/destino/riesgos en reports/reorganization_20261028/inventory.md y JSON local. No se leyeron secretos ni bases en el inventario.
- Respaldo completo de13 originales en backups/reorganizacion_20261028_01/manifest.json, con hashes y282 archivos protegidos. Los originales permanecieron hasta validar copias,21 pruebas y43 enlaces. Después se trasladaron11 documentos/informes y2 implementaciones de análisis. Guías en docs/guides, arquitectura en docs/architecture, guía v3 y snapshot en docs/archive;6 informes en reports/archive; scripts en scripts/analysis.
- README.md nuevo y LEEME.md como índice compatible. README_ASISTENTE_IA.md y MYSQL_LOCAL.md de raíz son entradas a las guías completas; no buscar allí todo el contenido anterior. Dos scripts de raíz conservan CLI/imports mediante alias de un único módulo scripts.analysis, con pruebas desde otro CWD y resultados equivalentes. Scripts trasladados y snapshot histórico conservan bytes originales. Referencias documentales rebasadas.
- No se movieron módulos de IA, pruebas previas, modelos, migraciones, core/data, templates, static, litmate_project, requisitos, Docker ni lanzadores. Tampoco se renombró reportes/: es almacén operativo con salidas predeterminadas y evidencia ligada por SHA256. No crear todavía literary_ai/tests/config/requirements vacíos. .gitignore sólo amplía exclusiones de JSON/TXT derivados del lote; Markdown versionable.
- scripts/repository/inventory.py reproduce el inventario sin Django; check_layout.py valida respaldo/rutas/enlaces/huellas; verify_runtime.py hace comprobación local opcional con password oculta y lecturas MySQL. Para este último usar python -m scripts.repository.verify_runtime --output una_ruta_nueva.json desde raíz. No cambia .env ni imprime errores privados del driver.
- Pruebas:18 herramientas antes(0,232s);21 copias preparadas(1,381s);25 corte/compatibilidad(1,426s). Se corrigió sólo la prueba nueva de MigrationLoader porque el ejecutor aislado desactiva migraciones; se inspeccionan en disco con override temporal, sin aplicar ninguna. Suite completa1887 ejecutadas en82,377s:1886 aprobadas y1integración optativa omitida; aumento de7 casos, ninguno perdido. Node233 OK; diff check OK.
- MySQL REAL sólo lectura: mysqlclient/MySQL8.0.46/litmate_db/36tablas/2945filas; ORM55libros/50conversaciones/190mensajes;26migraciones aplicadas,0pendientes; manage.py check --database default OK. Imports IA y URL core.literary_ai_views correctos. Ninguna reimportación, borrado ni cambio de motor/credenciales. Ollama API real OK; SearXNG JSON real20resultados/0motoresfallidos en la consulta.
- HTTP/SSE real adicional aprobado(9,108s):Ollama+OpenLibrary reales con ficha inyectada en límite de presentación, sesiones firmadas y almacenes temporales; cuatro turnos answered, tarjetas conservadas.7,768s primera traducción y0,032/0,042/0,040s reutilización/sinopsis/inglés. Informe redirigido a reports/reorganization_20261028/http_sse_verified.json; no sobrescribió el informe de idioma anterior. No afirmar benchmark de investigación completa ni conversación de producción MySQL en este paso.
- Validación final de282 protegidos y46 enlaces OK;341 archivos iniciales ajenos a los13 movimientos tienen hashes idénticos. .env y respaldo MySQL03 intactos. Sin instalaciones, migraciones reales, commits, staging ni push. Informe autosuficiente reports/reorganization_20261028/README.md; estructura y siguiente lote docs/architecture/REPOSITORY_LAYOUT.md.
- Siguiente lote sugerido, NO ejecutado: pocas pruebas de herramientas a tests/tools con control de descubrimiento/fixtures; después un módulo hoja de IA con alias probado. No empezar por motor, identidad, calidad, memoria o RAG. Conservar respaldos y comparar hashes antes de cualquier reversión selectiva.

## 2026-10-28 — Conocimiento bibliográfico MySQL y RAG, primer lote real de 100

- Solicitud adjunta055e9e5c-fcaa-4ff0-84fa-ef208fe46ab1, luego continuidad explícita del usuario. Inspeccionados git status, core.models, acquisition/gutenberg, memory/knowledge/library/learning, identidad, consultas y políticas oficiales. Se conservaron todos los cambios anteriores. No se movió la IA a otro paquete.
- Respaldo ANTES de cambios de esquema: backups/conocimiento_mysql_20261028_01 verificado(36tablas,2945filas,88archivos,SQLite portable). Incluye archivos, metadatos, claves, FK/índices/counters y snapshots online de SQLite. Respaldo mysql_preparacion_20261028_03 conservado intacto. No modificar .env ni credenciales.
- Añadidos core.knowledge_models:KBRecord,KBName,KBRelation,KBVersion,KBProjection; registrados desde core.models. Migración0008_bibliographic_repository aplicada a MySQL LOCAL, sólo5CreateModel. Se verificó respaldo/frescura/plan exacto y SQL sin DROP/TRUNCATE/DELETE/RENAME antes de aplicar. manage.py check y makemigrations --check --dry-run OK. Django añadió5ContentTypes,20permisos y1historial; filas previas no se modificaron.
- Modelo: registros por proveedor+ID(SHA256), tipos obra/edición/autor, alias indexados sin fusionar homónimos, referencias de autor/obra/ISBN, JSON mínimo con procedencia/derechos y versiones. Gutenberg ebook es edición, no obra abstracta. No se crean autores canónicos a partir de nombres ni ejemplares físicos. Hechos narrativos/personajes/relaciones existentes siguen en SQLite/RAG; no se recrearon ni se declararon migrados.
- core.bibliographic_repository proyecta outbox ADMITIDO del ledger existente a MySQL. Cursor por rowid del productor INSERT OR REPLACE, UUID durable del ledger, checkpoint en la misma transacción que registros, lease global, lotes25(max100), timeout entre registros, cuota contable y lectura de prefijos64KiB antes de JSON. Rechaza corruptos/staged/checksums ajenos, datos LLM/privados y campos narrativos. Versiones viejas y conflictos preservados; no hay borrado de historia.
- Revisión explícita del operador con fuente primaria exacta, selección de versión admitida y --operator-confirmed; registra auditoría sin texto privado, sincroniza nombres/relaciones, invalida caché. No acepta votos anónimos como verdad ni autoriza sobreescritura silenciosa de correcciones. verified_at quedaNULL al importar; la revisión humana es declaración documentada, no certificación automática universal.
- Integrado a quick_knowledge_sources y search_catalog; cachés incluyen revisión SQL. Las fichas mínimas no desplazan narrativas verificadas. Admisión cerrada Gutenberg/BNE para identidad/autoría por host+ruta+policy+license; no autoriza tramas desde metadatos. Se conserva auditoría y búsqueda adicional. Activación automática sólo litmate_db local; LITMATE_STRUCTURED_KNOWLEDGE=0 desactiva lector sin borrar tablas (ejemplo público actualizado, .env intacto).
- Ingesta REAL reutilizó pg_catalog_20261027.csv.gz(5597116bytes,SHA ebf4f6e54a34dddbcd26ca8a5ef593c9cf3e0ab8b331628ea7a49170a196a07e):124filas leídas,100admitidas,24rechazadas por reglas existentes. Ledger nuevo data/adquisicion/mysql_pilot_20261028.sqlite3; ningún volcado gigante ni libro descargado. Proyección100insertados,0rechazos en1,3894s;100nombres,100versiones,0relaciones y2controles. Repetición100duplicados/0insertados sin crecimiento. Reanudación cursor100→100 completa para ese ledger en0,0413s, catálogo completo aún no agotado.
- Memoria antes/después2256obras/842autores/2388fuentes/7descripciones/37personajes en3obras: sin incremento porque ya contenía esos metadatos. No declarar cien nuevas tramas ni crecimiento de conocimiento narrativo. No se reindexaron todos los vectores ni se entrenaron pesos. Reutilizadas OpenLibrary/Gutenberg/BNE y consultas Wikidata existentes; no nuevo importador masivo Wikidata, no GoogleBooks masivo/persistencia narrativa nueva.
- La primera validación REAL guardó100registros pero falló respuesta(pilot_real.json passed=false):faltaba Gutenberg en admisión de lookup rápido. Se reprodujo con2regresiones fallidas, se corrigió cerradamente y se verificó rechazo de tramas, hosts falsos y licencias ajenas. No borrar ese informe ni ocultar el fallo; replay_verified/resume_final/http_mysql_verified/http_mysql_closing muestran corrección.
- HTTP/SSE REAL contra MySQL, sin fixtures de recuperación: ¿Quién escribió Thuvia, maid of Mars?→Edgar Rice Burroughs+URL Gutenberg72, tarjeta sqlkb:02092dcb..., no estaba entre55Libro.0,3536s al cierre(antes0,3166),0LLM. Cookies firmadas, CSRF y loopback; no nuevas filas de lectores. Integrity comprobó todas las2945filas anteriores byte/clave/fila antes y después; sólo se añadieron metadatos de esquema y repositorio.
- Recursos medidos: primera proyección Pythonpeak545536bytes; otra ejecución2,96MB de asignaciones/RSS58,13MiB/peak59,14MiB (no MySQL/Ollama). Cuota contable767306bytes; estimación DATA_LENGTH+INDEX_LENGTH557056bytes.12consultas: p50 10,81ms,p95/máximo35,71ms. No certificar capacidad de millones ni p95 global con esta muestra.
- Respaldo POSTERIOR backups/conocimiento_mysql_20261028_02 también verificado:41tablas,3273filas,89archivos ySQLite portable conKB. Total328filas extra=302repositorio+26framework;55Libro/50ConversacionIA/190MensajeIA originales conservados. Sin reimportación de la base vieja ni pérdida deIDs. .env SHA1d8e35effc765d26ecb73f3e2ee26c886a1e3d98b1bc45590c356b8604008e74 intacto; mysql03 manifest89e44e64babf9278643e5ef45c607a61de6e3e65973b050bccba7e1efccb1005 intacto.
- Cierre:1908ejecutadas en86,890s,1907aprobadas y1integración real optativa omitida;21regresiones KBaprobadas en4,507s;Node233OK;HTTP MySQL probado aparte;diff check/enlaces docs OK. Modelos migraciones y respaldo conPKchar también verificados de verdad en el snapshot02. Sin dependencias instaladas, APIs de pago, modificaciones de contraseñas, commits ni push.
- Herramientas: core.management.commands.proyectar_catalogo_mysql (proyección/listado/revisión), scripts.knowledge.mysql_control(password oculta, backup/esquema/piloto/proyección/http/revisión, límites CLI). Esquema y piloto YA APLICADOS; no repetir --prepare-schema ni --pilot-catalog. Reanudar --project-ledger con destino de informe nuevo. No revertir0008 para desactivar: deja tablas y usa flag0. No restaurar respaldo sobre datos más recientes sin reconciliar.
- Documentación actual: docs/architecture/KNOWLEDGE_REPOSITORY.md y reports/knowledge_20261028/README.md, índices y guíaMySQL actualizados. Pendientes explícitos: identificación canónica cruzada entre proveedores, volcados Wikidata directos, panel de revisión, cobertura narrativa autorizada y benchmarks1000/10000antes de más escala. Los hashes del lote de reorganización son históricos: los cambios de modelos/hooks de esta nueva fase están autorizados y documentados.
- Verificación final adicional:39 dirigidas de repositorio/transferencia/activación pasaron en13,794s. El lanzador permite --batch-size/--max-seconds/--max-storage-mb para proyectar ledgers ampliados; --pilot-catalog sigue limitado a100. No requiere tocar .env. Los dos respaldos de conocimiento y el anterior mysql03 permanecen completos y separados.

### 28/10/2026 — Expansión progresiva real: 1.000 + 10.000 registros

- Autorización explícita del usuario: expandir con importadores existentes, primer lote <=1000, evaluar y luego <=10000, sin mayores lotes. Revisados estado Git sucio, informe anterior, capacidad, respaldo y fuentes oficiales. No se descartaron cambios, no commits/push, .env intacto, sin dependencias ni migraciones.
- Respaldos nuevos y verificados: backups/expansion_20261028_01 (41 tablas/3273 filas/89 archivos), intermedio _02 (41/6274/90), final _03 (41/36275/91), con portable SQLite y snapshots auxiliares. Mantener todos, especialmente mysql_preparacion_20261028_03, sin restaurar encima de datos nuevos.
- Se reutilizó pg_catalog_20261027.csv.gz, SHA ebf4f6e54a34dddbcd26ca8a5ef593c9cf3e0ab8b331628ea7a49170a196a07e. Catálogo público oficial Gutenberg, 79674 filas; cero nuevas descargas/API pagadas/libros completos. Open Library requiere dumps para volumen, BNE devolvió403 respetado, LOC/NDL requieren adaptar formatos; no se afirma integrarlos aquí. Wikipedia/Wikidata/GoogleBooks conservan investigación existente.
- core.literary_gutenberg.import_catalog acepta selected_ids (<=10000), cursor separado por selección y checkpoints agrupados para filtros (cada250), atómicos por registro admitido, hash antes/después intacto. core.bibliographic_expansion selecciona reproduciblemente por idiomas/temas/fecha del autor sin inferir nacionalidad/publicación; excluye pares conocidos e IDs, evita repeticiones por idioma, audita recuperación/recursos/originales. Conserva identidad de edición por proveedor/ID, sin unificación canónica nueva.
- scripts.knowledge.expand_catalog: contraseña getpass/local MySQL sólo en proceso; planes congelados; ledger distinto por lote; gate1000 para10000; tiempo180s ingesta, proyección SQL25 por transacción/250 por ejecución/20s, pausas, cuota lógica256MiB, margen10GiB disco. Cursor CSV terminado no basta: exige outbox de memoria vacío (regresión específica). Lote10000 se reanudó dentro del mismo proceso: 6318+3682 proyectados a memoria, sin pérdida.
- Nuevos registros MySQL reales:1000+10000, cero duplicados insertados/conflictos/rechazos SQL. KBRecord/KBName/KBVersion=11100 cada uno; KBRelation=0; más2controles de ledger. Catálogo original55Libro/50ConversacionIA/190MensajeIA preservado. Todas las3273filas anteriores verificadas porPK/huellas; sólo controles KB avanzan. No se crearon datos privados en pruebasHTTP.
- Memoria:2256→13250 pares título/autor (+10994),2388→13383 fuentes (+10995),842→5776 autores normalizados. Cinco fichas PG47388/44358/44529/25054/48954 ya conocidas sin sufijo(Novela), otra pareja PG67205/73215 comparte título/autor en idiomas distintos. Identificado mecanismo, corregida selección futura con work_identity y regresión. No se borran ediciones ni se alteran planes ejecutados. Seis fuentes originales sólo renovaron timestamps monotónicos;URL/hash/contenido exactos, todas entidades/afirmaciones/obras originales intactas. Verificador de expansión distingue actualización de vigencia de modificación factual, con prueba negativa de cambio de hash.
- Diversidad42idiomas(321es,12ja);3344ficción/1634historia/1018poesía/444infantil-juvenil/209artes/166ciencia/148ensayo/4037otros. Manga0. 506autores genéricos Various342/Anonymous144/Unknown20. Etiqueta de autor100% no equivale a autor individual corroborado. verified_at SQL NULL. Sin nuevas sinopsis/personajes; siguen7descripciones y37personajes en3obras. No modelos entrenados ni nuevos embeddings del texto completo; índice de memoria incremental existente.
- Auditoría final scripts.knowledge.audit_expansion:240/240 autores esperados recuperados SQL,237/240 memoria top5,201respuestas rápidas correctas/39abstenciones/0erróneas. p95 SQL+autor11,70ms(lote1)/10,28ms(lote2); memoria9,11/11,26ms. Inicial lote1 respondió100/120; al final98/120 por mayor ambigüedad, no se debilitan validadores. Muestra sólo autoría, no tasa global<1% ni precisión de trama.
- HTTP/SSE real de cada lote, tarjetas SQL nuevas+CSRF: Ang Katipunan→G.B.(Gabriel Beato)Francisco/Gutenberg14205 en0,2774s; Elämän polulla→Niilo Mantere/Gutenberg24905 en0,1979s;0Ollama. Probe admite IDs del lote para no acreditar fichas viejas. Sesiones firmadas y servidor loopback efímero; puerto8000 no estaba activo al inicio, no afirmar servidor permanente activo.
- Almacenamiento: memoria11.628.544→60.592.128bytes (+46,70MiB); ledgers2.285.568+22.339.584bytes(23,48MiB); SQL cuota lógica767306→88281552bytes(+83,46MiB), NO espacio físicoInnoDB. information_schema.stats no se actualizó inmediatamente; no usar ese valor pequeño como tamaño real. PicoRSS importador192,82MiB, no incluye MySQL/Ollama. Disco final112099409920bytes libres(~104,4GiB); reevaluaciónRAM~11,1GiB libres.
- Selección evitó2383conocidas+177repetidas lote1,3391+170 lote2; escaneó mismo catálogo, no sumar como únicos.27338filas descartadas por reglas previas de autor/tipo/campos, ninguna era una de las11000seleccionadas. Tras normalización corregida quedan38773candidatos; siguiente muestra sóloen/de/fi/fr. No tercer lote. Recursos permiten proponer hasta10000más con >=1GiBreserva y nueva evaluación, no certificar millones; priorizar diversidad moderna/manga y contenido narrativo autorizado.
- Pruebas:64dirigidas aprobadas12,390s (expansión/Gutenberg/repositorio/transferencia/activación);233JSaprobadas. Suitegeneral1927ejecutadas102,896s:5fallos+2errores+1omisión. Mismos7problemas reproducidos en33dirigidas con memoriaactual y copiaAISLADA del respaldo previo(14,852s):Dune/endpoints,recuerdosPlatero/Metamorfosis,aliasQuijote,sinopsisTolkien. No atribuirlos al nuevo lote ni afirmar suiteverde. Un primer testnuevo falló porconexiónSQLite sin cerrar enWindows, corregido concontextlib.closing yrevalidado. No alterar esas rutas ajenas enesta fase.
- Documentación: reports/expansion_20261028/README.md y RESULTADOS.md; artefactosJSON/TXT ignoradosGit: lote1000/lote10000/auditoria_final/selecciones/capacidad_candidatos y salidaspruebas. Comandos de reanudación enREADME (no repetir si terminó, usar salidasnuevas). scriptsknowledgeaudit sóloverifica noingiere. .envSHA1d8e35effc765d26ecb73f3e2ee26c886a1e3d98b1bc45590c356b8604008e74 y mysql03manifest89e44e64babf9278643e5ef45c607a61de6e3e65973b050bccba7e1efccb1005 intactos.

### 28/10/2026 — Enriquecimiento narrativo, sin títulos nuevos

- Leído adjunto815d9166-aea9-4e71-bed8-d2fcae713407. Usuario pide profundidad, no más títulos. Git sucio inspeccionado/conservado; AGENTS y código/validadores/diagnosticar_ia verificados. No nuevas dependencias/modelos/migraciones/.env/commits/push. Trabajo autónomo autorizado por el encargo.
- Respaldos previos/finales backups/narrativo_20261028_01 y _02 completos y verificados:41tablas/36275filas/91archivos cada uno, SQLite portable y snapshots auxiliares. MySQL55Libro y11100KBRecord intactos; todas36275filas originales verificadas. No tablas narrativas MySQL nuevas.
- Almacenes reales: memoria13250pares, conocimientoSQLite4obras/5hechos yRAG4docs/vectores, biblioteca12originales/561capítulos yRAG12docs/11289fragmentos/vectores. Comparación lógica completa de los4SQLite/índices conrespaldo: sin cambios. No usarhashbinario de snapshotonline para compararoriginal: cabeceraspueden cambiar. Artefacto indices_integridad.json.
- Piloto17obras existentes (clásicos, sigloXX, latinoamericana, infantil/juvenil e intentoHistoriaChile);10confuentesnuevas. No haymanga localizado eninventarios revisados, no añadirunoparacumplircuota. Selecciónenplan.json; procesamiento genérico, CLIpermite --work-id repetiblehasta100existentes. No excepciones deprocesamiento porlibro.
- Métricas finales reevaluadas conmismafunción sobrebackup01 ymemoriaactual:13250→13250obras;0→8obrasconpasajesexplícitos detrama parcial;6→13descripcionesnarrativas;25→49paresobra/personaje conrolliteral;2→4obrasconroles;1→2obrasconprotagonistaexplícito(2→3menciones);12→11personajessólopertenencia;0→1relación;0→11anotaciones(8trama+2eventos+1relación);13383→13408fuentes(+25);0conflictos. No atribuir viejas métricas7descripciones/37personajes aroles verificables: incluíanP674. Primerplancontaba49roles sinreliteralizar; mantenerartefactos yusar metricas_entrega.json comocierrecondefiniciónconsistente.
- Nuevas fuentes:22snapshotsWikipedia porsección,1webWikidata pertenencia y2fichasWikidata (no roles).23snapshotsconscope en10obras;25fuentesincrementales enmemoria. Wikipedia CC-BY-SA4.0+revisión/atribución yWikidataCC0 comprobados enpolíticasoficiales; máximo1800caracteresguardados porpasaje, notextoscompletos deobras. MetadatosGutenberg/OLno se convierten ensinopsis. Redirects/secciones no se cuentan comocorroboraciónindependiente.
- Reutilizado run_refresh_batch/enqueue_refresh/claim_job. Nuevos parámetros opt-in narrative_pages=1/work_ids<=100, filtrado transaccional decola para no consumirtareas deotrasobras;defaultmetadata/pages0conservado. Consultas dirigidas porrequirement; Wikipedia leeuna sección, conserva license/URL/revision; hechoextractivo sinLLM. jobs<=20,120s/lote,12s/tarea,pausa>=1s(2Wikidata),leaseglobal,cooldown/backoff ydisk>=10GiB.47intentos:10ok,11no_verified_match,11no_evidence,5empty,10rate_limited. No forzarcuotas niagotarreintentos. LogsJSONLpersistenresultados/tarea.
- Defectos reproducidos antesdefix: fuenteURLúnicareemplazabasinopsis conpersonajes;_fetch_public_metadata no recibía requirement;budgetreal pages1pero adaptador consultaba settingglobal3 yeligióTextExtractsin tablas; relacióncoverage no contaba predicadosliterales españoles;Tolkienrecibía descripciónElanor comotrama. Regresiones fallaron ypasarontrascorreccionesgenerales.
- core.literary_enrichment extraehechosliterales deencabezadosysólo relacionespositivasconsujeto/vínculo/objetonombrados, niega coocurrencias/hipótesis/negaciones/adaptaciones. memorysepara IDs desnapshotporscope sinnecesidaddeesquema. canonical_sources mantieneevidencia/revisión porsección yseparalegacycharactermemory delatrama;_sentences nopresentaroles comosinopsis. No se inventanprotagonistas desdeP674.
- Auditoríapreservación narrativa exigeidentidades/fuentes/afirmaciones originales intactas.3metadatosdeobra enriquecidos:yearvacío omitido y2referenciasprincipales aWikidata, conservandofuentesoriginales.24entidadesgananenlacesdeevidencia sinperdercamposprevios. Fuentesoriginales0cambios/0borrados;afirmacionesoriginales0cambios/0borrados. No confundir cambiosaditivos deentidad conpérdida dedatos. Código verificador catálogo estrictoanterior no se relajó.
- Tramas explícitas nuevas:OrgulloyPrejuicio,Dune,Elprincipito,Rayuela,Frankenstein,Emma,Dracula,Siddhartha. Nana/LittleWomen sólotienencontenidoparcial/descripción;historia/manga/contextos/antagonistasgeneralizados siguenpendientes. Fallosreales identidades largasMobyDick,autorWells/Baum,DonQuijote,HistoriaChile; no se forzaronalias oautor distinto.
- Relaciónliteralalmacenada:EdwardLucas,hijo deSirWilliamLucas,OrgulloyPrejuicio. HTTP/SSErealprimero34,9367s/4Qwen;otrointento32,2518s/6Qwen(incluyerepair). Nueva _stored_relationship reconocepreguntassencillas yaliasconfirmados,sólorelaciónúnicaalmacenada,sininterpretaciones/múltiplespartes;validate_draft/evidence/auditstrict se mantienen. Regresiónaliasingles/español sintítulo inventado;negativa3personajes/auditrejected. ÚltimoHTTPnuevo wording,noexactcache:1,0302s/0LLM,fuente/tarjetaconservadas. No afirmaraceleraciónglobal.
- HTTPtramaOrgullo0,5144s/protagonistaElizabethBennet0,1781s,ambos0LLM. MySQLreal+SSE+CSRF+cookiesfirmadas;nolectores/historialMySQLcreados. Servidorefímero,noasegurarpuerto8000activo permanente. Ollama/qwen3.5:9b-q4_K_M usadodeverdadenlaspruebasderelación previas,sin cambiarpesos.
- Benchmarklocal34preguntasiguales(17obras,trama/personajes):3→12respuestasextractivasauditadas;22aúnsinrespuestalocalsuficiente. Recuperaciónp50 7,15→14,92ms,p9514,37→23,30ms,másevidenciaparaauditar,nomejoradevelocidadglobal. No probarerrorglobal<1%. RAGpiloto nuevo enreports:49fuentescandidatas,42docs,57chunks,BM25sinembeddings,8/8obrascontramarecuperadas,9,5–26,3ms. Reutilizabuild_memory_index conwork_ids;índiceparcialrequierearchivoNUEVO,nosustituyeoriginales. Índicepiloto311296bytes,noactivadocomo reemplazodelabiblioteca;chatrecuperavíasumemoriaFTS existente.
- Memoria60592128→60923904bytes(+331776,324KiB);RSSpicoauditor157,41MiB(excluyeMySQL/Ollama). SQLKBsincrecer. Disco>100GiB. Noescalado1000/10000todavía: primerootro pilotoindependientehasta100, solucionaridentidad/ratelimits,coberturayabstenciones;1kcomo10planes<=100 yrespaldo/evaluación;10krequierenuevaevaluacióndecondicionesyrecursos, no usarAPIscomocrawlerilimitado.
- Pruebas finales206dirigidasOK4,422s;233JSOK. SuitegeneralAISLADAen.testtmp/narrative_full/memory.sqlite3:1941pruebas92,052s,4fallos+2errores+1omisión,incidenciasconocidasDune/endpoints,Platero/Metamorfosis/aliasQuijote. TolkienYA PASA. Pruebasrelación/aliasagregadasdespués aprobadasen206dirigidas; no declararsuitecompletaverde.
- Entrega reports/narrative_20261028/README.md concobertura,obras,rechazos,fuentes,comandos ypendientes. Artifactsplan/piloto/piloto_reanudado/wikidata/auditoria/auditoria_cierre/metricas_entrega/indices_integridad/http_relacion*/tests ignoradosGit; conservarintentosfallidos. CLI scripts.knowledge.enrich_narrative (getpass,configlocalenproceso,requierebackup ysalida nuevas) yscripts.knowledge.audit_narrative (lecturacontroles+índicepiloto/HTTPoptativo). No repetirimportación11000. .envSHA ymysql03manifest originales intactos.


### 29/10/2026 ? Generos, variedad y seguimiento de recomendaciones MySQL

- Encargo bc99d328: reproducir cuatro errores y corregir causas generales sin reimportar 11000 fichas. Estado Git pendiente inspeccionado y conservado; sin commits/push, paquetes, migraciones ni cambios de .env/arranque/modelos. Detalle y comandos: reports/recommendations_20261029/README.md.
- Baseline HTTP/SSE REAL antes.json: crimen solo Crimen y castigo (0,3033s), mas crimen misma obra con variante del autor (3,5691s), otro que no sea ese pierde tema (9,8025s), fantasia devuelve Cien anos de soledad (0,1536s). Conservar artefactos intermedios: algunos fallaron y motivaron regresiones.
- Causas: busqueda por titulo/palabras sin aprovechar Libro.generos ni materias SQL; taxonomia ausente; variantes de autor sin ancla comun; seguimiento pierde intencion; encabezado vacio no retirado; links Google Books construidos con IDs locales no verificables. Defecto adicional reproducido: puntos/fechas dentro de un titulo bibliografico fragmentaban afirmaciones y hacian fallar la auditoria.
- core/literary_genres: ejes genero/formato/publico, sinonimos multilingues y jerarquia, VERSION literary-taxonomy-v1; no infiere genero desde palabras de sinopsis. Realismo magico separado de fantasia, hibridos solo con categorias explicitas. Calificadores no soportados conservan pipeline existente, no se borran restricciones.
- core/bibliographic_repository: classification_edges/index_classifications/genre_sources reutilizan KBRelation y su B-tree target_id, sin esquema nuevo. _sync_indexes conserva clasificaciones en actualizaciones. scripts.knowledge.index_genres permite checkpoint, version, lotes250 y respaldo/verificacion antes/despues. 11100 fichas escaneadas; 1104 relaciones derivadas y un control KBProjection, sin nuevos titulos. Originales/categorias/procedencia/fechas intactos; es clasificacion declarada por fuente, no corroboracion independiente.
- Respaldos verificados backups/recomendaciones_20261029_01 (41tablas/36275filas/91archivos) y _02 (41/37380/91). Todas las 36275filas originales verificadas por claves/huellas; 55Libro y11100KBRecord intactos, relaciones validas. Delta1105filas aditivas. Conservar mysql_preparacion_20261028_03 y SQLite/RAG originales. .env SHA 1d8e35effc765d26ecb73f3e2ee26c886a1e3d98b1bc45590c356b8604008e74; manifest mysql03 SHA 89e44e64babf9278643e5ef45c607a61de6e3e65973b050bccba7e1efccb1005 sin cambios.
- core/genre_recommendations recupera M2M local (3queries con prefetch) y SQL (1query actual), filtra preferencias y obras vistas, prioriza autores diferentes sin perder pertinencia. Estado privado acotado200obras/20exclusiones por tipo; sin publicar preferencias como conocimiento. same_work requiere titulo/alias y ancla bibliografica primaria para variantes; no fusiona homonimos por similitud. Exclusion Gutenberg se aplica antes del limite SQL; memory_verified impide readmitir metadatos SQL como evidencia nueva.
- literary_conversation y literary_ai_views conservan tema/intent, cambios de genero, rechazo de libros/autores, y estado en el mecanismo existente de sesion. Regresion con dos DjangoClient y backend DB en base aislada: primera conversacion mantiene7obras vistas y segunda comienza3sin contaminarse. HTTP administrativo real usa cookies firmadas para no crear lectores/historial en produccion; no afirmar que se guardaron turnos privados en MySQL durante ese probe.
- Presentacion: introduccion/lista numerada/pregunta, sin duplicar sinopsis ni encabezado Fuentes de las fichas; tarjetas/botones/voz/avatar conservados. ai_presentation da enlace Gutenberg o busqueda Google por titulo/autor, no fabrica volumen desde IDs antiguos. literary_quality.factual_statements conserva unidad titulo en negrita con puntos sin quitar afirmaciones de la auditoria. validate_draft/evidence/audit estricto siguen ejecutandose; politica cache versionada para invalidar resultados anteriores.
- HTTP/SSE REAL despues_entrega.json:10/10answered+done,28tarjetas distintas/28recomendaciones,0LLMcalls. Turnos crimen3/mas3/otro1/diferentes3/fantasia3/mas3/romance3/excluirKing3/yalei3/nogusto3. Tiempos0,2950/0,1701/0,1477/0,1558/0,4302/0,6326/0,2376/0,4256/0,4420/0,4381s; p50 0,3603s,p95 y max0,6326s. Muestra pequena de recuperacion local, no velocidad global ni error<1%.
- Consultas_mysql.json:20mediciones por categoria; crimen35candidatos p50/p95 4,54/5,22ms, fantasia59 6,69/6,92ms, romance55 7,25/7,59ms, scifi120 11,86/18,50ms. EXPLAIN real usa target_id ref (35relaciones crimen) y KBRecord eq_ref PRIMARY; no recorre11100JSON por mensaje. Limites de candidatos, sin N+1. Hay categorias sin datos (manga, varios subgeneros); no afirmar cobertura por existir etiqueta.
- Cierre ejecutado:268pruebas dirigidas aprobadas5,835s (pruebas_finales.txt),234comprobacionesJSaprobadas. Incluye identidad/homonimos/hibridos, formatos, restricciones, falta de candidatos, auditoria negativa, titulo con puntos, idioma/cards, sesiones y conteoSQL/idempotencia. No suite general completa nueva; incidencias previas ajenas no declaradas resueltas. Sin servicios de pago ni busquedas externas necesarias para estas recomendaciones.
- Herramienta scripts.knowledge.recommendation_check --after / --sql-only con salida nueva y password oculta; arranque iniciar_mysql_local.py --http-desarrollo intacto. No repetir importacion11000 ni migracion. Pendientes: enriquecer categorias ausentes con evidencia autorizada, autoridad cruzada de traducciones/volumenes no vinculados, verificar portadas antiguas individualmente; no sobreprometer exactitud de metadatos heredados. Consultas complejas siguen investigacion previa y no quedan medidas por este benchmark.


### 29/10/2026 - SearXNG y narracion: dos lotes verificados

- Encargo 6b0f00d2: recuperar busquedas y producir narracion espanola sin perder datos. Git/AGENTS/continuidad inspeccionados; cambios previos conservados. Informes reports/search_narrative_20261029/README.md, LOTE_1.md y LOTE_2.md; operacion searxng/README.md. Sin paquetes, pesos nuevos, cambios .env, migraciones, importaciones, commits/push ni borrado de volumenes.
- Lote1: Docker healthy no bastaba. Busquedas reales general/novela/manga y motores aislados; El nombre de la rosa reprodujo openlibrary unexpected crash. Traza real ResultContainer.extend->publishedDate.strftime con lista: publish_date no vacio sin fecha analizable, fallback de first_publish_year omitido. Regresion offline 3casos/2errores antes; seis casos pasan al cierre, incluyendo campos mal formados. Mwmbl respondio antes/despues; sus timeouts historicos y add_unresponsive_engine after close no se reprodujeron y no se declara su causa exacta resuelta.
- searxng/engines/openlibrary.py conserva codigo/AGPL upstream con None/fallback de fechas, campos API explicitos en vez fields=*, tipos opcionales seguros, documentos invalidos aislados y URL sin doble slash. Compose monta solo este modulo ro como litmate_openlibrary manteniendo nombre openlibrary, imagen digest ddd642cae6ea y volumen. Primera tentativa sobre modulo original seguia cargando bytecode precompilado y fallo; preservada evidencia, resuelto con nombre de modulo nuevo sin borrar pyc. Timeout OL10s heredado ahora4s, mwmbl/Wikipedia3s, cliente6s, retries0.
- limiter.toml explicito trusted_proxies=[] elimina archivo ausente, sin cambiar limiter ni confiar redes para ocultar advertencias. Aviso X-Forwarded-For/X-Real-IP permanece una vez por arranque: conexion directa usa REMOTE_ADDR. No falsificar cabeceras. Wikipedia devolvio429 temporal en un arranque; respetada suspension. Logs finales solo aviso IP, sin AttributeError/timeout/missingfile. No prometer disponibilidad externa permanente.
- Adaptador literary_search.search_searx valida filas/sobre, no descarta hallazgos bibliograficos sin snippet, distingue empty/fallo, conserva parcial y cachea por origen/consulta/motores (parciales30s, errores no son vacios). Sin debilitar SSRF/robots/redirecciones, proveedor directo OL conservado. Cierre real OLaislado El nombre10resultados1,027s, mwmbl109/0,721s, Narutomanga56/0,312s, literaturachilena31/0,306s; sin motores fallidos. Diagnosticar_buscador real: tres consultas20/139/138resultados y adaptadorDjango5candidatoscadauna, no hechos verificados por el mero resultado.
- Lote2 baseline HTTP/SSE MySQL: Harry con Hola cae en referencias/pasaje crudo6,0412s/0LLM; Anillos unavailable por auditoria34,9595s/2LLM; Papelucho+Det funciona0,149s; Naruto unavailable21,7738s/2LLM. Preservados http_antes y todos intentos intermedios. No confundir esos fallos con Docker solo por coincidir temporalmente.
- request_for normaliza saludo antes de clasificar; plural serie de novelas y manga reconocido sin confundir anime. _task_content cambia regla de parada de recuperacion: identidad/membresia/biografia no son trama. Continuan proveedores existentes cuando falta contenido. Los originales editoriales/ingleses siguen completos para auditoria; proyeccion de generacion no entrega membresia como trama. qualification literal de formato manga explicita el original; no se hardcodean obras.
- Defecto nuevo demostrado: LLM aprobo lista de personajes con prueba que no contenia sus nombres. Regresion fallo antes; literary_quality.unsupported_character_list_claim/validate_audit ahora exige nombres en prueba citada incluso dentro de trama. Synthesis degrada esas afirmaciones y vuelve a validar salvamento existente. Guardia acotada, no NER universal. Otros intentos LLM aprobaron detalles excesivos: conservarlos como evidencia de limitacion, no declarar eliminadas alucinaciones de consultas abiertas.
- _sentences permite omitir un complemento final opcional de proposito introducido por coma si conserva oracion principal completa (no corte arbitrario). Naruto tenia premisa303caracteres y gastaba2LLM innecesariamente. Nuevo test largo fallo antes/pasa despues; prueba literal de toda la parte publicada se conserva. No aumentados limites de auditoria ni afirmaciones generadas guardadas como hechos. _publish enlaza solo fuentes de afirmaciones respaldadas, originales completos internos. Cache policy extractive-answer-v6-narrative-content invalida respuestas antiguas sin borrar datos. Estado recommendation_state solo se inyecta cuando existe.
- Presentacion comun Python/JS retira Fuentes consultadas/Fuentes de las fichas y no crea details/summary. Enlaces discretos, atribucion CC, limitaciones y datos backend conservados. Tarjetas/voz/avatar/layout/colores sin cambios. Historia y redibujado SSE prueban renderer compartido, no se afirma inspeccion visual de todas las conversaciones antiguas.
- HTTP/SSE cierre real http_cierre.json con memoria copiada y cache nueva: Harry2,8960s, Anillos2,9631s, Papelucho0,1454s, Naruto1,9333s;4answered+DONE/0LLMcalls. Premisas revisadas contra evidencia, Narutomanga sin anime/roles/citas inventadas, Papelucho conserva Det. evaluacion_manual.json registra revision y pruebas literales disponibles. No es benchmark p95 ni precisionglobal<1%. Script scripts.knowledge.search_narrative_check (getpass, salida nueva) envuelve funciones reales para trazar sin simular proveedores/modelos, no corre en funcionamiento habitual ni guarda conversaciones privadas.
- --local-only real con fuentes externas desactivadas: SQL Elaman polulla/Niilo Mantere/Gutenberg24905 tarjeta sqlkb0,4016s; trama Orgullo local0,6038s,0LLM ambos. MySQL41tablas37380filas conserva conteos en todas pruebas; memoria original conserva hash. Pruebas administrativas cookiesfirmadas/copia temporalSQLite no crean lectores/historial en produccion. Arranque iniciar_mysql_local.py --http-desarrollo intacto.
- RAG lectura real readonly sin reindexar: conocimiento4docs/4chunks devuelve1 en1,3ms, biblioteca12docs/11289chunks devuelve2 en1,9ms; ambos hashes iguales. RAGgenerico y memoriaRAG no existen en configuracion actual, no creados. No afirmar que HTTP utilizo vectores por existir indices. .envSHA1d8e35effc765d26ecb73f3e2ee26c886a1e3d98b1bc45590c356b8604008e74 y mysql03manifest89e44e64babf9278643e5ef45c607a61de6e3e65973b050bccba7e1efccb1005 intactos; respaldos previos conservados.
- Pruebas cierre371dirigidasOK6,796s,18regresionesnuevas,6regresionesmotorofflineOK,240JSOK. No suite general completa nueva. Compatibilidad inicial tuvo4fallos+1error por filtro demasiado estricto, corregido sin cambiar expectativas. Una tanda370tuvo StopIteration en test robots/presupuesto existente; aislado pasa y repeticion371pasa, causa intermitente no demostrada (conservar pruebas_entrega.txt). Pendientes: auditoria semantica de afirmaciones compuestas, observacion cuotas/red, investigar intermitencia si vuelve y benchmark independiente amplio. No servicios de pago, scraping Google, datos masivos ni redis nuevo.

## 2026-10-29 — Reparación literaria y conocimiento continuo

- Se conserva el árbol Git previo, .env, arranque MySQL, recomendaciones por género, tarjetas, avatar, voz y CSS. Sin paquetes/modelos nuevos, migraciones de producción, commits ni push.
- Informes principales: `reports/literary_answers_20261029/README.md`, `reports/continuous_20261029/README.md`; operación manual y programación Windows en `docs/CONOCIMIENTO_CONTINUO.md`.
- Causas corregidas: sección narrativa sustituida por introducción; premisa/fechas confundidas con cobertura; selección del primer snapshot aunque otro tuviera más evidencia; identidad de poemas/autor atribuido; papeles explícitos en argumentos/perfiles no recuperados; aposición que invadía otra cláusula; variantes de apellidos mostradas como otro personaje; adaptación/título sin espacios no resuelto. Pruebas sintéticas anteriores reproducen los defectos; no hay reglas por título.
- `direct_answer` prioriza las oraciones completas utilizables y mantiene pruebas originales al retirar notas editoriales de presentación. `bound_sources` conserva contexto narrativo. Película/libro se mantienen separados; solo se describe relación literaria publicada y se aclara el medio.
- Renderer común: narración primero; enlace complementario corto real; créditos/licencia accesibles en details. No dominios ni listas técnicas insertadas en párrafos; procedencia backend y botones de las tarjetas conservados. Caché de respuestas `extractive-answer-v8-literary-coverage`.
- Cierre HTTP/SSE real `cierre_7.json`: Naruto2,1917s; ReyLeón3,2913s (aclaración con relación literaria); Odisea3,1941s (cinco oraciones); BladeRunner2,3177s (película/novela separadas); Frankenstein0,5172s; personajesFrankenstein0,2284s; personajesOdisea3,9734s. Cinco answered/dos clarification, DONE, cero LLM. Memoria copiada/cachés nuevas; MySQL y memoria originales sin cambios durante pruebas. No p95 ni 99% global.
- Contexto real `contexto_cobertura.json`: trama Frankenstein0,6820s → ¿Y sus personajes?0,2795s en misma sesión. Se conservan fallos intermedios y una salida Ollama con detalles insuficientemente respaldados; síntesis libre compleja sigue pendiente de evaluación independiente. Consultas externas pueden fallar y no se sustituyen por hechos de memoria.
- Se amplió la infraestructura existente: `continuous_knowledge` observa fallos/partes insuficientes y correcciones pendientes solo para identidades públicas conocidas; guarda categorías/IDs/códigos, nunca mensajes privados. Cola `memory_jobs`, señales agregadas `memory_usage`, cursor y guardas en `memory_meta`. No nuevas tablas ni duplicación de índices.
- `actualizar_conocimiento --continuous`: un lote, sin residente; hasta25obras/20tareas/120s; predeterminado5obras/2tareas/30s/8s por tarea, pausa2s en wrapper. Lease global más propiedad de tareas, cuarentena de payloads corruptos, backoff, revisión tras5fallos, reuso y parada por marcador/disco/RSS. CPU de prioridad baja; límites de admisión suaves, no cuotas duras del SO.
- `scripts.knowledge.continuous_worker` configura MySQL SOLO en proceso con getpass/credencial de entorno efímera; rechaza remoto. `enrich_once.ps1` permite DPAPI creado manualmente fuera de Git. No se creó tarea Windows ni archivo de credencial.
- Piloto real6obras conocidas,12tareas iniciales,3completadas iniciales/9diferidas/8operaciones de snapshots,0LLM. Siete descripciones literales de roles en3obras; incluyen2variantes de VanHelsing, no siete personas distintas. Presentación filtra el apellido abreviado y marca lista parcial. Sin tramas/relaciones nuevas verificadas. Siddhartha0roles→4, HTTP sin web unavailable0,3917s→answered0,3281s. Dracula unavailable15,3532s→un papel parcial0,2573s. No se ocultan cobertura insuficiente ni fallos.
- MySQL:3KBRelation memory_evidence y1KBProjection nuevos; todos los37.380registros anteriores idénticos, claves y relaciones comprobadas. Total41tablas/37.384filas. Pasajes/roles permanecen SQLite con enlaces SQL exactos; no afirmar que fueron migrados íntegramente a MySQL.
- Trabajador inicial98,839s/CPU53,609s/pico108,336MiB reveló selección correlacionada costosa en export_index_sources. Consulta de conjunto corrige complejidad; regresión601docs reproduce interrupción SQLite anterior y pasa nueva. Índice500fuentes1,363s/CPU0,859s. Reanudación5,832s/CPU1,562s/pico108,660MiB,0nuevasrefsSQL. Índice operativo494docs/510chunks BM25; no embeddings activados en chat. Nueva sesión rehidrata evidencia vigente; FTS se actualiza transaccionalmente.
- Cuatro snapshots de desambiguación, incluso previos al lote, se excluyen de recuperación/RAG sin borrarlos. `same_work` no acepta la mención de un autor en un índice de homónimos. La consulta de descubrimiento omite esos candidatos antes de gastar lecturas.
- Incidente aislado y documentado: prueba antigua de endpoint sin override de memoria guardó una fuente sintética Dune (revision1234,5roles). Se comprobó que no estaba en respaldo01 y se puso solo ese hash en cuarentena (`quarantine_source`), sin borrar fuentes/hechos/versiones ni cambiar las13.258identidades previas. Prueba aislada en temporales y suite general también. No contar fixture como conocimiento nuevo. `aislamiento_pruebas.json` conserva evidencia. Nueva revisión pública con hash distinto no queda bloqueada por esa cuarentena.
- Respaldos verificados: continuo_20261029_01(41/37380/91archivos), _02(41/37384/92), **_03 cierre(41/37384/92, incluye anotación de cuarentena)**. mysql_preparacion_20261028_03 y todos los anteriores intactos; .env y manifiesto mysql03 conservan hashes previos. SQLite integrity ok/FK0. Sin libros nuevos:13.258obras originales conservadas.
- Pruebas: cierre definitivo core2.006ejecutadas en71,818s, OK con1omitida (=2.005aprobadas); logs `pruebas_finales.txt`. 24regresiones de conocimiento continuo más18 de profundidad, identidad y fuentes; 242JS OK. Suite inicial detectó tests de endpoint que simulaban ruta antigua sin clasificación/licencia y expectativa de género obsoleta; se actualizaron contratos verificando la ruta auditada, no se relajaron validadores ni se modificó recomendador. Parser PowerShell OK; programador Windows no activado. La última regresión también comprueba que trabajos prioritarios fuera del cursor se incluyen entre las referencias MySQL. `integridad_cierre.json` conserva comparación de las37.380filas originales y `memoria_cierre.json` verifica10tablas idénticas al respaldo final.
- Pendientes: ampliar extracción multilingüe y perfiles/roles en Emma, LittleWomen, NanaZola y Dracula; resolver fuentes adicionales con evidencia; tareas review requieren revisión. No entrenamiento de pesos ni aprendizaje de correcciones no comprobadas. La auditoría semántica de afirmaciones complejas y un benchmark independiente amplio siguen pendientes. La programación diaria requiere decisión y credencial DPAPI local del usuario, instrucciones ya preparadas.

## 2026-10-29 — continuación integral, relaciones, recuperación y atribución

Se revisaron git status/diff y se conservaron todos los cambios previos. Detalle y artefactos: `reports/integral_20261029/README.md`. No reconstruir ni revertir la rama; el árbol sigue incluyendo mucho trabajo anterior ajeno a este lote.

- Tres regresiones iniciales fallaban antes y pasan después: relación «qué relación tiene X con Y», conservación del pasaje estructural con pruebas de personajes, y descubrimiento con artículo sin registrar alias ni unir obras. Nuevas regresiones reprodujeron KeyError de character_count, héroe/protagonista de sujeto tácito, perfil con ficha en caché y obra web sin catálogo, selección de panoramas narrativos y parada por evidencia específica.
- Conversación real original: antes 2/6 respuestas, cuatro indisponibilidades; cierre 6 respuestas, **dos parciales de personajes principales**. Media 10,425→1,981s; mediana 5,505→1,750s, máximo posterior4,209s; cero inferencias en esos seis turnos. Datos en conversacion_antes.json y conversacion_cierre.json. No confundir responded con lista completa ni extrapolar p95/99%.
- Independientes El principito/Dracula/Siddhartha: detectaron cuento antepuesto presentado como novela, materias catalográficas como sinopsis y biblioteca detenida en índices/créditos. Regresiones previas al arreglo y nuevas pruebas reales conservadas. Dracula trama ya usa la novela; principales aún unavailable (32,330→5,971s al evitar generación/auditoría sin clasificación). Siddhartha trama narrativa corregida; principales aún unavailable4,895s. El principito sólo un principal confirmado0,497s.
- Nuevo core/literary_entity_facts.py extrae definiciones y relación creador/vida/experimento literales; diferencia autoría y ficción, valida sujeto/obra, negación y denominaciones publicadas. Se mantienen validate_draft/evidence/audit estrictos. No aceptar texto del modelo por sonar verosímil; el fallo original de relación registraba ollama_sin_respuesta_valida tras4llamadas, no se verificó un borrador válido rechazado por metadatos.
- persist_sources conserva anclas cacheadas al admitir perfiles nuevos y permite identidad web verificada sin inventar ISBN/tarjeta. Fuente ya cacheada no actualiza fechas. Clasificación principal puede venir de perfil épico con sujeto tácito y mismo título/autor; no de otro sujeto o de otra obra.
- RAG/memoria/continuo existentes ampliados con main_characters y relaciones explícitas, --requirement repetible hasta6 categorías. Comando, límites y procedimiento manual en docs/CONOCIMIENTO_CONTINUO.md. No nueva tabla, migración, daemon ni tarea Windows. Código project_references usa URLs catalográficas exactas vigentes si cambia la preferida; si hay dos anclas candidatas no une nada.
- Piloto de5 obras existentes, dos lotes5jobs y uno1job: clasificaciones explícitas de Víctor y el principito; 7→19 etiquetas con roles en5identidades; una relación creador/criatura. No nuevas tramas. Nueva métrica reconoce personaje principal además de protagonista. La tarea de relaciones quedó pendiente en el piloto porque pedía también una lista; se reprodujo y corrigió la cobertura por requisito, manteniendo auditoría del lector. No repetir consultas inmediatas para borrar ese estado: backoff permanece.
- Tiempos de lotes22,504/21,792/4,906s; CPU2,656/3,016/1,484s; picoRAM<109MiB; crecimiento archivo SQLite+77.824bytes. Índice último492docs/510chunks, BM25, máximo500fuentes, no todos los libros. Ninguna nueva referenciaSQL en lotes; no afirmar que se creó grafo narrativoMySQL completo.
- Verificación fresca verificacion_persistencia.json: MySQL41tablas/37.384filas. Filas originales comparadas con respaldo; sólo campos derivados del checkpoint continuo avanzaron, sus otras5filas permanecen estrictamente comprobadas. SQLite integrity ok/FK0/cuarentena vigente. Cola done14/pending40. Piloto5obras:25fuentes,19etiquetas,2protagonistas,1relación,4argumentosprevios. RAG rehidrató5/3/3/4/1 fuentes vigentes por obra en otro proceso.
- SearXNG local healthy8080 JSON, sin reinstalar. Wikipedia0/4 consultas detalle vs4/4 títulos; título Frankenstein devolvía monstruo, lo que confirma necesidad de identidad. Mwmbl4/4 con ruido. OpenLibrary2/4 detalle; en segunda serie timeout/suspended. No atribuirlo a Docker roto. APIs oficiales de Wikipedia siguen siendo recuperación temática; fragmentsSearx no prueban hechos. No motor comercial ni GoogleHTML.
- «Créditos y licencia» eliminado de burbujas en litmate_safe.renderMessage. Enlace general Atribuciones y diálogo accesible en base.html; fuentes específicas, autores/historial, CC BY-SA y aviso adaptación fuera del mensaje, nodos actuales sin registro persistente privado. Lectura complementaria real se conserva. Tarjetas/avatar/diseño/voz sin cambios. Cache-buster chat-v8. 246 comprobaciones JS pasan, incluyendo manejador real de apertura; sin inspección gráfica de navegador.
- Telemetría cuenta intentos reales /api/chat en ai_progress.record_model_call, incluso si otro cliente falla y se devuelve una ruta diferente. Antes independientes marcaban model_calls0 pese a generación/auditoría; se corrigió contador por turno y merge, no se falsean métricas.
- Suite definitiva **2.026 ejecutadas,2.025aprobadas,1opcionalomitida**,76,480s, logs pruebas_definitivas.txt. SQLite y9almacenes temporales, sin tocar producción. Rondas previas2017/2025 OK también conservadas. Regresiones dirigidas posteriores53 OK. No afirmar activación del caso omitido; servicios reales se probaron por HTTP/SSE aparte.
- Respaldo previo integral_20261029_01 verificado41/37384/92archivos. Respaldos continuo03 y mysql_preparacion03 conservados. .env SHA2561d8e35effc765d26ecb73f3e2ee26c886a1e3d98b1bc45590c356b8604008e74 y manifiesto mysql03 SHA25689e44e64babf9278643e5ef45c607a61de6e3e65973b050bccba7e1efccb1005 sin cambios. No paquetes, pagos, push, commits, borrados ni migracionesMySQL.
- Pendientes: listas principales completas Frankenstein/Odisea y principales Dracula/Siddhartha; argumentos más proporcionados más allá del planteamiento; JaneEyre sin completar; reconciliación SQL inequívoca con más fuentes; benchmark independiente amplio y repetido; posible configuración manual del ProgramadorWindows. No declarar reparación universal ni precisión99%.

- Cierre adicional: respaldo posterior integral_20261029_02 completado y verificado,41tablas/37.384filas/92archivos; conserva memoria enriquecida/índice. Frontend246 OK en última ejecución. No quedan procesos de prueba o trabajadores iniciados por este lote en ejecución.

## Continuación narrativa y recomendaciones, 2026-10-29 (en curso)

- Prioridad vigente: adjunto 584a3f44, conversación Chile y seguimiento de recomendaciones; conservar avances narrativos del adjunto 61d8b594. Respaldo previo narrativa_20261029_01 verificado (41/37.384/92). Detalle breve y evidencias en reports/narrative_20261029/README.md.
- Pruebas sintéticas previas al arreglo reprodujeron pérdida de metadatos al deduplicar Open Library, falta de prefijo «Dime de qué trata» y partículas del autor, y nombre corto de creador no resuelto en relación. Reglas generales, ninguna respuesta por título.
- Corregidos encabezados Descripción personaje, definición inversa de protagonista, deduplicación de alias explícitos y verificación de autor dentro del papel. Conservados validadores; un parcial no cierra investigación. Seguimiento de desarrollo de argumento y filtrado opcional de requisitos de cola existente; no otro RAG ni migración.
- Chile antes: recomendación12,738s; contenido35,101s/fallo; autor1,870s/clarificación; períodos35,057s/fallo; comparación35,066s/fallo. Último chile_lote05.json: 8,016/6,237/0,225/0,641/8,502s. Cinco answered, pero contenido/períodos/comparación son **alcance bibliográfico parcial**, no sinopsis completa. Se conservan ambos subtítulos originales y fuentes; no afirmar reparación completa del contenido.
- Google Books existente desactivado por control explícito de no facturación, clave no utilizada. Consulta pública sin clave429. Pregunta opcional pendiente al usuario para confirmar proyecto sin cuenta de facturación; no editar .env ni desactivar control mientras tanto. Open Library oficial aporta subtítulos; descripción del primer libro sólo «316 p.:22 cm». Crossref se evaluó con una consulta pública, resultados incorrectos, NO integrado.
- Piloto02 de5 obras existentes:10jobs/4done/6deferred,35,563s,0LLM,13 operaciones de almacenamiento (no13hechos),0referenciasSQLnuevas. Scope de plot se perdía por clave duplicada en salida y normalizador; corregidos después, pendiente nueva medición. Pruebas dirigidas77 OK y35 OK posteriores; primera general2036 con2errores corregidos y1omitida, pendiente ronda final. No presentar esa general como aprobada.
- Conversación B inicial: trama2,620s, principales3,501s (sóloVíctor, parcial), relación con nombre cortoVíctor5,676s/unavailable. Regresión sintética de nombre corto pasa tras arreglo; bloquea dos personajes con el mismo nombre, no almacena alias inferido. Pendiente reproducir B después y C (proceso actual).
- Todos los HTTP/SSE emplean copias auxiliares y verifican conteosMySQL/hashmemoriaoriginal. Sin interfaz, .env, secretos, migraciones ni push. Próximo: comprobar B/C, cerrar fuentes/descripciones si se confirma Google, evaluación acotada OL, ronda final aislada y reporte conciso.

### Cierre del lote narrativo y recomendaciones

- Reparación adicional confirmada: remember ahora prioriza las fuentes realmente citadas antes del recorte a seis/ocho; se perdía el pasaje que documentaba la denominación «criatura». Regresión sintética falló antes y pasa después. B en conversacion_b_memoria.json: trama2,695s; principales3,437s/parcial; relación Víctor/criatura **answered0,478s,0LLM**. No atribuir el arreglo sólo al nombre abreviado: también requería retener evidencia.
- Selección de libro ahora prefiere contenido de identidad ya verificada sobre ficha vacía; prueba con volumen Google con ID real sintético reprodujo el descarte. Cliente volume_source conserva procedencia de sinopsis. Recuperación narrativa reutiliza search_google solamente si está habilitado por el control de no facturación. Sin uso real de la clave; consulta opcional al usuario sigue pendiente.
- Chile_lote05: cinco answered, pero contenido, períodos y comparación son parciales de alcance bibliográfico, no sinopsis completa. Recomendación/comparación registran dos llamadas de traducción de presentación, no cero. Rutas de contenido/autor/períodos sí0LLM. No se cambió el idioma de títulos originales.
- Independientes personajes_final: Dracula2rolesprincipales0,415s; Siddhartha1principal2,985s/listaparcial; Frankenstein4nombres0,258s; Odisea7roles3,397s. ConversaciónC_final: trama2,904s/extracto; principales4,154s/sóloOdiseo/listaparcial. Persisten faltantes de clasificación principal y coherencia/profundidad de argumentos.
- Primera ronda final detectó4fallos por introducir el estado de lista parcial como claim sin prueba y1por cambiar contrato events→plot. Corregido: estado presentacional «Lista parcial» y preservación conjunta de hechos plot/events; prueba mantiene seguimiento Det con evidencia. Sin relajar validadores. 109dirigidas pasan. **Cierre2051ejecutadas,2050aprobadas,1opcionalomitida,70,928s**, SQLite+9DBaux temporales; pruebas_cierre.txt. 246JS OK. No modificaciones de código posteriores a esa ronda.
- OLdump oficialresuelve2026-09-30,4.073.320.823bytes,metadatosSHA1publicado verificados enArchiveAPI, no descarga nihashlocal. ~102GiB libres. 11.100 registrosSQLconautor/ID,sinsinopsisporpolítica;0obrasOLenSQL. MuestraAPI2obras y esquemaimportador no prueban beneficio narrativo de cargar4GB; no nuevaimportaciónbibliográficaSQL. Piloto02previo:19→27etiquetasroles,25→29fuentes,2→4obrasprincipalexplícito;0argumentosdesarrolladosnuevos.
- Respaldo posterior narrativa_20261029_02 **verificado41tablas/37.393filas/92archivos**. Comparación de respaldos: +9eventosanalíticos y sesiónactualizada mientrasappactiva; resto de filas originales intactas, salvo avance controlado del checkpoint. Dos fichasOLreales adicionales observadasenmemoria (PaleBlueDot/Hegel), no atribuidasalpilotoniaprendizajedepruebas. No borrar ni revertir datos vivos. SQLiteintegrityOK/FK0. .env ymanifestmysql03 conservanSHA256originales.
- ContenedorSearxng healthy8080; composeps directo sin entorno falla por secreto requerido, usar iniciar_buscador existente, no reinstalar. No trabajadores/pruebas de este lote quedan activos. El servidor del usuario no se reinició: cargar cambios al reiniciar con .\venv\Scripts\python.exe -B iniciar_mysql_local.py, contraseña oculta. Informe breve, fuentes, archivos y pendientes en reports/narrative_20261029/README.md. No declarar reparación integral ni precisión99%.

### Google Books: confirmación recibida y prueba real

- El usuario confirmó explícitamente que el proyecto de su clave no tiene facturación vinculada. Se probó la clave existente sólo en memoria; sin imprimirla ni modificar .env. No se verificó la consola de facturación mediante API. Búsqueda exacta título/autor e ISBN devolvió vacío; GET del volumen _zR9AAAAMAAJ y búsqueda por autor devolvieron la ficha/autor/ISBN y descripción española concordantes. Evidencias google_confirmado_01/02/03.json.
- Se añadió una ampliación acotada por autor en _google_work_sources, manteniendo bound_sources para rechazar otras obras y autores. search_google conserva estado de errores; quota/clave/acceso no provoca otra búsqueda. Casos sintéticos y clienteHTTP cubren ausencia, cuota y aislamiento.
- La descripción real «Esta obra es una historia…» no entraba en _task_content porque no tenía los verbos narrativos esperados; ahora reconoce alcance no ficticio con procedencia. Pregunta de períodos conserva summary_focus, usa subtítulo como evidencia y no una cita tangencial. volume_source añade subtítulo al texto auditable.
- Descripción editorial extensa se sintetiza/audita con el motor existente y presupuesto18s; si falla queda el extracto literal breve auditado. Una prueba reproduce la falla de síntesis y verifica ese respaldo. No nuevas reparaciones en bucle. Se normalizó history=None en narrative_answer.
- Nueva opción iniciar_mysql_local.py **--google-books-sin-facturacion** activa ambos indicadores sólo en el proceso y restaura entorno después; sin flag no cambia configuración habitual. Clave sigue local. Arranque recomendado: .\venv\Scripts\python.exe -B iniciar_mysql_local.py --http-desarrollo --google-books-sin-facturacion. Usuario debe detener/reiniciar su servidor; no se reinició automáticamente. Guía en docs/guides/MYSQL_LOCAL.md.
- Conversación real chile_google_confirmado_02: recomendación1,222s; sinopsis20,945s/dosLLM/auditapprove; autor0,298s; períodos0,763s; comparación0,520s/unavailable (esta vez segundo libro fue Historia económica de Chile colonial; no confundir con A Nation of Enemies). Lista dinámica y referencia ordinal correctas, comparación pendiente por falta de evidencia. Cierre nuevo proceso chile_google_cierre.json: síntesis20,929s y períodos0,664s, sin mensaje falso de ausencia de descripción. No se cuenta unavailable como éxito ni se infiere p95 de dos ejecuciones. ConteosMySQL/hashmemoriaoriginal sin cambios durante los turnos.
- Validación posterior **159dirigidas OK; 2057ejecutadas,2056aprobadas,1opcionalomitida,77,196s**, SQLite+9DBaux temporales, pruebas_google_confirmado.txt. .env conserva SHA2561d8e35effc765d26ecb73f3e2ee26c886a1e3d98b1bc45590c356b8604008e74. Sin migraciones, importación de libros, servicios pagados, modificaciones frontend ni cambios de código posteriores a esa ronda. No quedan procesos de prueba de esta continuación activos. Informe narrativo actualizado; no afirmar que Google está activo en el servidor antiguo sin reiniciarlo con el flag.

## 2026-10-30 — Contenido recomendado, SearXNG y piloto controlado

- Solicitudes 21fe5668 y b40d9f95 leídas completas. No reiniciar el trabajo ni revertir el árbol pendiente. Informe breve y artefactos: reports/search_narrative_20261029_peru/README.md. No nuevas dependencias, modelos, servicios de pago, .env, migraciones, UI, commits o push.
- Causas corregidas: rol bibliográfico incrustado en authors, subtítulos sin alias de volumen, actas/compilaciones rechazadas como contenido, identidad de página perdida al recortar, tablas de catálogo omitidas, drama/crítica literaria admitidos como historia general y límite prematuro de 24 fuentes que expulsaba detalles nuevos en conversaciones largas. Se conserva cap80 de entrada/cap8 de salida y auditoría factual.
- Ranking compartido books_google.content_coverage/genre_recommendations: pertinencia primero, cobertura útil después, publicidad/snippets/materias no equivalen a sinopsis. Descripción breve con varios hechos intenta síntesis auditada acotada, con fallback literal <=25 palabras. No copiar texto editorial entero.
- Memoria: ordinal elíptico hereda tarea previa, omite turnos context_only y puede usar intención pendiente tras un fallo; el ordinal nuevo no hereda la identidad pendiente anterior. Petición de otro libro explicable conserva el tema. Personajes separa del autor/de la autora y exige autor contra homónimos. Consultas de identidad OL usan operadores; sqlkb conserva su ID y permite recuperar detalles por URL OL oficial.
- SearXNG: un motor general nuevo activo (DuckDuckGo), Qwant evaluado y desactivado por acceso denegado. Originales Wikipedia/OL/Mwmbl conservados. Ruta web Django separada, consultas específicas y relajadas, deduplicación de páginas, máximo2lecturas/presupuesto8s, pausas por motor. CAPTCHA también pausa endpoint directo DDG. No evadir bloqueos, proxies inventados ni robots. OL pide5hits y proyección reducida; timeout3s dentro del presupuesto global. Docker reiniciado/configurado efectivamente; /config confirma enabled y puerto127.0.0.1:8080. Warning de forwarded headers ya documentado; no falsificar IPs.
- Google lector seguro PublicFetchError ya no confunde quota con unavailable; mapea códigos y pausa rechazos por clave hasheada. Prueba simulada reproduce error anterior y evita segunda petición. No atribuir a cuota los fallos reales que sólo devolvieron unavailable: hubo disponibilidad intermitente. Clave nunca registrada.
- Mensaje solicitado de información insuficiente sólo ante falta real de evidencia; conserva título/foco. Sólo menciona tiendas si hubo ficha anterior (status unavailable no crea tarjetas nuevas). Fallos de proveedor/modelo conservan mensaje temporal y diagnóstico retrieval_unavailable; no ocultarlos como desconocimiento.
- Respaldos verificados previos contenido_20261030_01(41tablas/37393filas/92archivos) e intermedio _02(41/37393/93); **_03 terminado y verificado:41tablas/37407filas/93archivos**. Conservar mysql_preparacion_20261028_03 y todos los anteriores.
- Piloto continuo existente 5obras/10tareas:1completada9diferidas,46,190s CPU3,625s pico109,117MiB,0LLM,3operaciones de almacenamiento. Emma gana5roles literales;0descripciones nuevas/0tramas desarrolladas/0relaciones nuevas. No forzar backoff. RAG existente actualizado por el trabajador, sin reemplazo por una biblioteca nueva. Emma HTTP en proceso nuevo/sinInternet: unavailable0,495s antes(snapshot01,mismo código)→5personajes/answered0,497s después,0LLM.
- Ingesta OL real:4registros por dos consultas pequeñas, no un volcado. Primer lookup sin operadores se reinterpretó temáticamente y produjo Prescott +2libros introductorios de Perú; son bibliografía real, no volumen de César. Segundo lookup exacto con title/author aporta colección de César, sin sinopsis ni adjudicar sus tomos al volumen Inca. CLI mediante call_command estructurado evita comillas perdidas por PowerShell5. Ledger data/adquisicion/contenido_20261030.sqlite3. Proyección MySQL con project_content_pilot reutiliza project_ledger/auditor de expansión:3+1insertados,0conflictos/rechazos,cursor4. Replay4duplicados/0cambios, completo. Primer intento de mysql_control con cuota4MiB no importó; su auditor de migración tampoco es el de expansión. No relajar ese auditor; wrapper de piloto usa el auditor aditivo existente y cuota total128MiB,ledger<=25.
- Integridad:41tablas originales comprobadas; memoria_sources13431→13434,0ausentes;2contenidos renovados archivados exactamente en memory_history y2renovaciones de fechas. memory_assertions13567→13575,ninguna original ausente/cambiada; historial13→15. Auditor estricto de memoria señaló versiones renovadas; no se desactivó ni relajó. Memoria61263872bytes sin crecimiento físico; índice1306624→1302528; ledger73728; SQL lógico88281552→88311806(+30254bytes), no espacio físico. Disco>100GiB. Hash.env original intacto.
- Pruebas ejecutadas: revisión amplia516OK/17,356s con SQLite+9auxiliares temporales; última ronda241OK/10,880s tras arreglos finales; JS246OK; motor OL7OK en imagen fijada. No sumar rondas como pruebas únicas. Regresiones nuevas en core/test_recommended_content.py fallaron antes de cada corrección. No se ejecutó otra batería de miles.
- HTTP real: antes3abstenciones en libros objetivo (7,098/5,187/5,171s). Lote03 dio Escritos13,409s y Historias12,488s con síntesis auditada; Inca siguió sin contenido. Rondas posteriores tuvieron fallos técnicos y no reprodujeron ambos éxitos. Aceptación no completa. Último ordinal corregido alcanzó motor narrativo/0LLM/5,331s, identidad segundo libro correcta, pero unavailable por proveedor. No contar abstención como éxito. Comparación compleja pendiente (35s en ronda previa). Otra recomendación conserva tema pero sigue admitiendo fichas con poca cobertura si no hay mejores.
- Volcados:11.100SQLGutenberg ya existían; no se reimportaron. No Works/Authors/Editions global OL ni Wikipedia/Wikidata mundial descargados. Obras/Autores masivos no prueban mejoría narrativa y no justifican GB para este fallo. APIs selectivas y CSV Gutenberg local reutilizados; no scrapeo comercial ni libros completos.
- Pendiente principal: evidencia útil de Inca y quechua, estabilidad Google/DDG y cobertura para explicar todas las recomendaciones. Páginas públicas se leen con guardas; UNS quedó robots_unavailable; control El infinito recuperó biografía de autora y se rechazó para explicar libro. No fingir recuperación narrativa exitosa. Ampliar otras4obras del piloto y comparación de dos recomendaciones sólo con evidencia. No declarar tarea completa ni exactitud/p95 global a partir de esta muestra.
- Cierre: catalogo_nuevo_http_20261030.json confirma autoría de la colección de César en0,355s, proceso nuevo/sinInternet; ficha OL nueva recuperable. No prueba argumento del volumen. Última verificación de código105pruebas de books_google +regresiones nuevas OK/3,325s, incluyendo cooldown cuando search_google inyecta el lector con use_cache=True. Ningún cambio de código después. Todos los procesos de prueba/piloto/respaldo de esta continuación finalizaron; SearXNG quedó activo y healthy. .env/hash original intacto, sin push/commits.

### 2026-10-30 — Volcados oficiales y reparación de continuidad (en curso)

- Respaldo inicial verificado: `backups/volcados_20261030_01`, 41 tablas y 37.417 filas; se preservan respaldos anteriores y `.env`.
- Descargados Works y Authors oficiales Open Library 2026-09-30 completos: 4.073.320.823 y 782.352.949 bytes. SHA1 publicados coinciden; SHA256 y recibos en `data/adquisicion/openlibrary/*.verified.json`. No Editions ni historial completo.
- Piloto existente/importador: 200 obras y 207 autores admitidos y proyectados a MySQL; 0 conflictos/rechazos en proyección. Segundo lote: otras 1.000 obras admitidas; autores y proyección pendientes en este checkpoint.
- Se corrigen ordinal tercero, comparación de dos recomendaciones con evidencia, homónimos de Wikipedia, alias de traducción publicados y autores con expansión explícita de iniciales. No hay respuestas por título.
- Worker existente: 3 obras antes sin argumento explícito ganaron pasajes de argumento (Time Machine, Little Women, Nana); otras 7 obras existentes ganaron desarrollo. No se añadieron personajes ni relaciones en estos lotes. Informes `reports/volcados_20261030/enriquecimiento_*.json`.
- Licencia: los metadatos de Open Library no autorizan automáticamente copiar todas las descripciones. Se conservan en el volcado legítimo y se implementa lectura transitoria con puntero verificado, sin duplicar prosa en MySQL/memoria. Integración y comprobación HTTP pendientes.
- Primera conversación Perú real contiene fallos pendientes, incluyendo una inversión de la persona capturada aprobada por el auditor. Se añade control determinista general y regresión; NO se considera esa respuesta un acierto.
- 106 pruebas dirigidas aprobadas antes de cambios finales de cantidad/exclusión. Dos nuevas regresiones reprodujeron esos defectos. Una ejecución posterior tuvo un error de nombre de módulo de pruebas; aún no es validación final.
- No se modificaron interfaz, voz, avatares, credenciales ni arranque. No commits ni push. Continuar con autores lote02, proyección, recuperación offline de descripción nueva, conversación final y reporte de integridad/recursos.

### 2026-10-30 — Cierre de proyección y comprobaciones reales

- Informe detallado: `reports/volcados_20261030/README.md`. Volcados completos conservados, 4.855.673.772 bytes, SHA1 oficiales y SHA256 comprobados. Ledger `data/adquisicion/ol_20260930.sqlite3`.
- MySQL: 1.200 obras y 1.214 autores nuevos, 2.414 registros KB; 0 actualizaciones/conflictos/rechazos SQL. Works examinados10.212:1.200admitidos/80rechazados/8.932filtrados. Authors15.446.415líneas, dos recorridos selectivos;207duplicados. No contar líneas recorridas como entidades nuevas.
- Descripciones92enarchivo,74conpuntero localverificado;0prosaOLcopiadaaMySQL/memoria. Lectura local limitada64MiB/1,5s usa procedencia y hash; los primeros200registros aúnno tienenpuntero. No llenar10kmetadatos sin mejorar cobertura7,67%.
- Memoria dirigida a16obras:argumentos8→11,descripciones9→11,desarrollo0→10,hechos12→27. Roles68yrelaciones2sin cambio. Pasajes incompletos, no tramas completas ni corroboración universal.
- Nuevo defecto corregido:trasresolverobra, consultar memoria por identidad+requisito. Emma fallaba con argumento ya guardado. También se excluyen fragmentos que empiezan a mitad de oración; iniciales del autor no parten la pregunta; título/subtítulo histórico no se trata como personaje.
- Referencias:tercero reconocido; ordinal fuera de rango pide aclaración sin reutilizar primero; última recomendación determina índices. «Otro libro» conserva uno; «ya leí ese» excluye previos. Comparación limita investigación6s/obra y comprueba ambas coberturas antes de generar; limitación separada de títulos con puntos para no engañar al auditor.
- Auditoría:cita literal no basta para una inversión de cautivo; guardia general con regresión. Otras inversiones de sujeto siguen posibles; una comparación real anterior confundió quién huía/fundaba. NO contar ese answered como correcto. Última comparación sin evidencia:unavailable6,251s/0nueva trama. Comparaciones conocidas en español/alcance parcial pasan pruebas; falta demostrar comparación compleja completa en vivo.
- Pruebas:347OK/12,410s con SQLite+9auxiliares temporales; tras cambios finales94OK/4,077s. No sumar rondas. Fallos de módulo de prueba y de comando diagnóstico se conservan como fallos, no éxitos.
- HTTP/SSE real:con red pública bloqueada, JadeCabinet antes unavailable0,800s;después explicación español19,309sdesdevolcado. Emma0,790s/TimeMachine0,722s/Papelucho personajes0,220s. LittleWomen0,629spero superficial. Otro libro27,317s/1opción y YaLeí0,401s/no repetición. Posición inexistente2/3:clarificación0,498/0,373s;comparaciónsin2obras0,040s. Inca yquechua sigue unavailable6,272scon identidad correcta; UnfinishedNation sin evidencia; Tolkien sin argumento local en ensayo inicial.
- Instrumento offline corregido:las banderas no cubrían una ruta auxiliar. `search_narrative_check --local-only` ahora bloquea DNS/conexiones públicas y Google; permite Ollama/MySQL/HTTP locales. No usar `jade_antes_offline.json` como baseline; usar `jade_antes_red_bloqueada.json`.
- Integridadfinal:41tablas/46.798filas;respaldoverificado `backups/volcados_20261030_02`,98archivosincluidosdumps. Inicial01conservado. 13.431fuentesoriginalesactivas+7archivadasexactas/0perdidas;9hechosderivadossustituidosconhecho+pasajeoriginalexactosenhistorial/0sinarchivo. No restaurar hechos antiguos contra fuentes actuales distintas. SQLite quick_check yrelacionesMySQL OK;hash.envigual. Muestra120:120autoríascorrectas/p95SQL12,587ms;memoriatop5:119/120. No extrapolar a narración.
- DockerSearXNGhealthy, consultas unavailable/empty;Google yOLintermitentes. Ningunaevasión,CAPTCHA,borrado,paquete,migración,APIpagada,tareapermanente,commitopush. Disco libre después del respaldo98.057.826.304bytes.
- Pendiente: cobertura de libros recomendados incompletos, profundidad narrativa/cronología, traducciones, atribución semántica compleja y motores externos. No afirmar aceptación completa ni p95 del chat inferior a 30 segundos.

### 2026-10-30 — Último checkpoint confirmado

- El primer intento adicional usó pausa 0 y fue rechazado por el mínimo de seguridad de 1 segundo. La comprobación de sólo lectura pasó; se ejecutó después con pausa 1, sin cambiar el validador.
- Tolkien: una fuente y un hecho nuevos; premisa aceptada, tarea `plot_development` diferida porque no se obtuvo desarrollo suficiente. Lote 5,345 s, CPU 1,406 s, pico 121,672 MiB, 0 llamadas al modelo, índice actualizado incrementalmente. HTTP/SSE en proceso nuevo y red pública bloqueada: **El Señor de los Anillos respondió en 0,8402 s** con Frodo, Anillo y Sauron. Artefactos `enriquecimiento_tolkien.json` y `tolkien_offline_cierre.json`.
- Cobertura final de 17 obras (`cobertura_cierre17.json`): argumentos explícitos 8→12, descripciones 10→12, desarrollo 0→10, hechos 12→28; roles 81→81 y relaciones 2→2. No se equiparan pasajes a argumentos completos corroborados.
- Respaldo de cierre **`backups/volcados_20261030_03` verificado**, 41 tablas, 46.798 filas, 98 archivos; se conservan `_01` y `_02`. `integridad_cierre.json`: 1.200 obras con autores resueltos, 120/120 autorías correctas en muestra, p95 SQL 9,286 ms, memoria top5 119/120; fuentes originales 13.431 activas+7 archivadas exactas, 0 perdidas; 9 hechos sustituidos conservados exactamente en historial, 0 sin archivo; 8 SQLite quick_check OK, relaciones MySQL OK, `.env` intacto. Disco libre 92.888.084.480 bytes.
- Última ronda de código **113 pruebas aprobadas / 4,590 s**, además de la ronda amplia previa 347/12,410 s; no sumar rondas. Control de cautivo admite abreviación del nombre documentado, pero rechaza apellidos distintos. Sintaxis de 16 módulos comprobada; `git diff --check` sin errores. No hubo más cambios de código después de esa ronda, sólo informes.
- Todos los procesos de importación, enriquecimiento, pruebas HTTP y respaldo de esta ejecución finalizaron. Sin tareas permanentes, cambios de diseño, credenciales, paquetes, migraciones, commits ni push. Continuar desde el informe `reports/volcados_20261030/README.md`, sin reiniciar ni reimportar el lote. La aceptación total sigue pendiente por los límites documentados.

### 2026-10-30 — Revisión acotada de SearXNG y tolerancia a fallos

- Solicitud actual y adjunto leídos; se priorizó exclusivamente el problema de proveedores indicado en el mensaje. No se repitió la auditoría narrativa completa ni se descargaron datos. Informe: `reports/searx_20261030/README.md`.
- Estado real: misma imagen fijada, configuración montada y contenedor healthy; publicación exclusivamente `127.0.0.1:8080`. Qwant sigue deshabilitado y fuera de las listas efectivas de Django. Sin reinicios, reconstrucciones, borrados ni cambios de Compose/settings.yml/motor personalizado.
- Los errores previos de DDG (CAPTCHA explícito con plazo0), timeout Open Library y registro tras cierre no reaparecieron en la ventana de pruebas: cero errores nuevos en `logs_cierre.json`. La advertencia de IP sólo se emite una vez por arranque; acceso local directo conserva REMOTE_ADDR y proxies de confianza vacíos, sin cabeceras ficticias ni cambios de protecciones. El núcleo SearXNG no se modificó: la interfaz directa mantiene su comportamiento de suspensión upstream.
- Fallos reproducidos antes del cambio: pausa perdida al vaciar caché/cambiar proceso; motores bibliográficos ausentes de fallback cuando DDG estaba pausado; procedencia de motores descartada al normalizar; páginas generales SearXNG que no pasaban al lector; corte prematuro de candidatos; fragmentos vacíos/idénticos que eliminaban URLs distintas; catálogos API que consumían el cupo HTML. Corregidos en ai_concurrency.py, literary_search.py y canonical_sources de literary_ai.py. Todas las validaciones SSRF/DNS/redirección/robots/inyección conservadas y probadas. No se inventa contenido desde snippets.
- Pausas de LitMate usan leases del runtime existente, sin tablas nuevas; CAPTCHA pausa DDG1h entre procesos y rutas directa/SearXNG. Fallo de un motor conserva los demás. Pruebas de proceso nuevo, expiración, no acortamiento y leases de trabajo aprobadas. Runtime de simulación temporal; no se pausó artificialmente el proveedor en producción.
- Matriz real:12/12 consultas sin fallo de proveedor. Wikipedia dio resultados2/4 (título exacto, no búsqueda libre); OL4/4,0,372–2,308s; Mwmbl4/4,0,258–0,743s,con ruido; DDGuna consulta adicional10resultados/1,045s. Metabúsqueda fallback real con DDG simulado pausado funciona, pero sólo manga acreditó contenido suficiente en el chequeo aislado de páginas. No confundir veinte candidatos con cuatro respuestas narrativas correctas. No se añadieron motores alternativos ni se ampliaron timeouts sin causa actual.
- HTTP/SSE real normal y con DDG pausado:5/5 answered en cada ronda. Con pausa: novela2,151s/manga5,8s/historia16,085s/ensayo1,550s/Emma0,684s. Emma y ensayo no necesitaron Wikipedia/SearXNG ni LLM; novela/manga usaron Wikipedia oficial directa. SearXNG no hizo falta en estas cinco conversaciones; no atribuirles éxito narrativo de metabúsqueda. Historia varió por fallo de Google Books y2llamadas al modelo. Primer progreso12–38ms, no es respuesta completa. Sin SLA/p95 ni99% demostrados.
- Última ronda204 pruebas dirigidas OK/1,584s con SQLite y auxiliares aislados;7 regresiones offline de OL OK dentro de la imagen. Nuevos tests en core/test_searx_resilience.py y aislamientos de caché en tres módulos previos. Instrumentos scripts/knowledge/searx_quality_check.py y search_narrative_check.py --pause-duckduckgo; sólo consultas públicas y copias temporales, sin escritura de conocimiento.
- Integridad: todas las peticiones conservan conteos MySQL y hash de memoria original; comparación lógica con respaldo03,16tablas de memoria y10deRAG idénticas, quick_check OK. Hash físico de snapshot SQLite puede diferir del vivo aunque tablas coincidan; no hubo pérdida ni restauración. .env intacto; respaldo03 conservado. Sin paquetes, tareas, migraciones, datos nuevos, cambios visuales, commits ni push.
- Pendiente fuera de este lote: profundidad/atribución narrativa y optimización de JadeCabinet descritas en el adjunto. Fuentes externas siguen siendo intermitentes; algunas fichas, reseñas o prólogos no bastan. Cargar cambios reiniciando Django si estaba abierto sin autoreload; este lote no requiere reiniciar Docker. Todos los procesos de prueba de esta revisión terminaron.

### 2026-10-30 ? Conocimiento progresivo y estabilizaci?n de recuperaci?n (continuaci?n)

- Informe principal `reports/conocimiento_20261030/README.md`; detalle del ?ltimo c?digo y pruebas en `continuacion_estabilizacion.md`. Se conservaron cambios previos, volcados y todos los respaldos. No reiniciar la ingesta ni sobrescribir resultados anteriores.
- Campa?a: 120 candidatas existentes examinadas; 118 tareas reclamadas, 18 completadas, 25 fuentes admitidas por el trabajador. Una ingesta p?blica expl?cita de Dandadan a?adi? una obra y su fuente, contrastada con editorial. 26 identidades tocadas no significa 120 obras enriquecidas. Bajo la misma pol?tica V3: descripciones 17?41, argumentos expl?citos 13?26 (no completos), roles 81?94, hechos narrativos 30?61, relaciones 2?2. MySQL recibi? 23 referencias aditivas, sin reescribir filas originales. Cat?logo total 14.467 obras; 14.466 originales conservadas. Fuentes originales 14.645 activas exactas, cero faltantes.
- Datos/procedencia: se reutilizaron los 4,855 GB de volcados oficiales; sin nueva descarga de volcados ni textos completos. Se corrigi? suficiencia tem?tica, secciones/introducciones y contabilidad de premisas. Memoria 67.436.544 bytes; crecimiento de 389.120 bytes respecto al inicio. RAG BM25, sin embeddings nuevos ni entrenamiento.
- Evaluaci?n congelada de 22 consultas, 12 ausencias iniciales conservadoras tras revisi?n de variantes e ?ndice antiguo. Ronda fr?a hist?rica 13/22 answered, media 13,443 s y p95 35,058 s; ronda posterior 12/22, media 5,392 s y p95 9,360 s: no mejor? la cobertura. Offline v?lido s?lo guard_version=2 (proveedores, incluido SearXNG, desactivados + sockets p?blicos bloqueados). Dandadan global offline 0,762 s / 0 LLM; Little Women personajes 0,464 s / 0 LLM. No promover respuestas del perfil privado a conocimiento global. Google convencional no comparado: referencias editoriales independientes en `referencias.md`, sin superioridad declarada.
- Jade Cabinet: 4?2 llamadas por reutilizaci?n de sinopsis espa?ola auditada para su tarjeta; repetici?n 13,964 s frente a 18,795 s inicial. Otra fr?a 20,843 s; no es SLA ni precisi?n del 99 %. Persisten problemas de atribuci?n/idioma y edici?n/colecci?n en conversaci?n compleja de fantas?a.
- Continuaci?n de c?digo: controles generales para art?culos del t?tulo, `; or,`, iniciales, a?o/g?nero antes de `novel`, `Plot summary` y premisas inglesas ?tiles para auditor?a. Autor?a se acota antes de revista/editorial/ilustrador; ambig?edad no se resuelve por conjetura. Auditor conserva diferencia contradicci?n/falta de prueba y rechaza parentescos espec?ficos sin evidencia y orfandad atribuida a la muerte propia del menor. Resumen r?pido no recibe preguntas expl?citas por el final.
- Dos defectos reproducidos y corregidos en el ?ltimo lote: `search_wikipedia` descartaba la p?gina literaria `Odisea` por el art?culo `La`; ahora conserva una p?gina independientemente identificada, sin fusionar cat?logos. `profile_relationship_answer` resuelve `la criatura` como referencia contextual s?lo para una creaci?n viva ?nica del creador dentro de la obra; no persiste alias ni inventa entidades. Pruebas con obra sint?tica, dos creaciones y nombre no documentado.
- HTTP/SSE actual antes/despu?s en la misma secuencia: 4/6?6/6 answered. Relaci?n V?ctor/criatura abstenci?n 4,186 s?respuesta 0,497 s; La Odisea abstenci?n 7,700 s?respuesta 3,302 s. Media 3,696?2,297 s; cero llamadas al modelo. ?ltima repetici?n con todos los ?ndices p?blicos copiados: 6/6, media 2,631 s, m?ximo 5,683 s, cero LLM, conteos SQL/hash de memoria y cinco auxiliares originales iguales. Archivos `continuacion_actual_06*.json` y `continuacion_comparacion.json`. Las dos listas de personajes siguen parciales (un perfil), y las tramas extractivas no son explicaciones completas.
- Interidioma: se aprovechan enlaces oficiales Wikipedia con mismo Wikidata, autor, revisi?n, licencia y evidencia espec?fica para la pregunta. P?gina espa?ola sin trama no reemplaza evidencia inglesa. Oz 1,789 s y Portrait of a Lady 2,653 s con fuentes espa?olas. Garden gener? parentescos falsos en rondas iniciales; ?ltima premisa revisada 16,139 s / 2 LLM sin esos a?adidos. Moby-Dick ruta correcta, pero ronda 26,434 s y otra fr?a fall? en 36,070 s. Casos y limitaciones conservados, no afirmar soluci?n general de traducci?n.
- Prototipo `--foreign-literal` evaluado y NO activado por defecto por fallos de traducci?n. Glosario revisado con fuente Cambridge, cach? de idioma V5 limitada a pasajes p?blicos literalmente probados; respuestas privadas no compartidas. Traducci?n narrativa totalmente rechazada devuelve unavailable y no se recuerda. No se a?adieron modelos/paquetes ni se cambiaron settings/.env.
- Pruebas: aplicaci?n completa 2.157 ejecutadas, 2.156 aprobadas, una omitida; suite 73,523 s, proceso 75,083 s (`tests_core_continuacion_cierre.json`). Despu?s s?lo instrumento de evaluaci?n + una regresi?n de aislamiento: 174 dirigidas OK / 3,614 s. No sumar rondas ni declarar 2.158 en la suite completa. `git diff --check` OK; advertencias CRLF normales.
- Integridad: respaldo completo/verificado `backups/conocimiento_20261030_01`, 41 tablas / 46.821 filas, anteriores retenidos. Ninguna ingesta global adicional durante la continuaci?n de c?digo. `continuacion_integridad_final.json`: SQLite quick_check OK, cero FK, MySQL intacto en conversaciones, .env hash igual. RAG vigente 498 documentos / 526 fragmentos, revisi?n 14841/V3; 1.658.880 bytes posteriores a la reindexaci?n V3, no comparar ese tama?o como si el checkpoint anterior ya fuera V3. Los hashes se conservaron durante la ?ltima prueba aislada. Docker healthy s?lo 127.0.0.1:8080, sin cambios/reinicio.
- Pendiente: listas de personajes y roles m?s amplias, cohesi?n de argumentos, ediciones/colecciones verificadas, conversaci?n compleja, cobertura tem?tica/no ficci?n y fidelidad biling?e. El prototipo extranjero sigue desactivado. No se alcanzaron cobertura completa ni 99 % de precisi?n. Sin migraciones, APIs pagadas, paquetes, cambios de UI/voz/tarjetas, tareas permanentes, commits o push. Todos los trabajadores y pruebas finitos terminaron; el arranque existente se conserva.

- Cierre adicional del mismo lote: la equivalencia interidioma conservaba s?lo el t?tulo corto de la p?gina y perd?a un subt?tulo literalmente publicado en la introducci?n original. Se transfieren ?nicamente esas variantes verificadas, con prueba de introducci?n + Wikidata + revisiones; una continuaci?n inventada no se acepta. `moby_titulo_publicado_final.json`: misma consulta completa, 2,9258 s / 0 LLM / fuente espa?ola, frente a 26,4342 s / 2 LLM antes; original MySQL/memoria/cinco auxiliares intactos. No se persiste ning?n alias inferido ni se activa el prototipo extranjero.
- Validaci?n posterior al ?ltimo cambio de aplicaci?n: 351 pruebas de 24 m?dulos afectados aprobadas / 8,077 s de suite (`tests_affected_ultimo_alias.json`); 175 dirigidas en la ronda inmediatamente anterior. La suite general de 2.157 pertenece al punto previo al ajuste final del subt?tulo; no sumarlas ni llamarla una suite completa posterior. Informe de continuidad t?cnica actualizado. Quedan las limitaciones de personajes, cohesi?n narrativa, comparaciones/ediciones y fidelidad biling?e all? detalladas.


## 2026-10-30 - Cierre de reparacion conversacional bf415ec9

- Se conservaron todos los cambios previos. El lote anterior de personajes/cohesion esta documentado en reports/calidad_literaria_20261030/README.md; siguen pendientes algunas traducciones y comparaciones complejas.
- Nueva prioridad implementada: identidad literal de autores/franquicias, consultas bibliograficas acotadas, pertinencia compartida entre ruta rapida y pesada, exclusion de publico/formato como tema y de variantes probables repetidas, contexto de genero y ordinales, singular eliptico, clasificacion de fallos, recuperacion parcial auditada y auditoria completa de recomendaciones con fichas obligatorias. No se fusionan entidades por parecido ni se introducen respuestas para titulos particulares.
- Se encontro y bloqueo un respaldo exterior que volvia a ofrecer la obra de referencia. Una parafrasis de Zero aceptada indebidamente por el auditor motivo la ruta extractiva publication_synopsis_answer, con pruebas generales. Se conservan los fallos intermedios.
- Validacion dirigida final: 525 pruebas Django aprobadas / 12.552 s de suite (tests_release.json), mas 246 comprobaciones JavaScript existentes. El modulo nuevo completo aprobo 27 pruebas, incluyendo el subcaso final de puntuacion natural. No sumar rondas de pruebas.
- HTTP/SSE real, MySQL local y auxiliares copiados: cinco turnos de Heinz correctos en 2.1543, 0.4698, 6.7351, 6.6127 y 3.3543 s. Jack encontro un fallo temporal real en 4.3589 s; repeticion aislada posterior recupero tres publicaciones y tarjetas en 2.7011 s / 0 LLM. No se oculta la ejecucion fallida.
- Matriz adicional de nueve conversaciones encontro errores de publico y tipo de publicacion, corregidos y reproducidos con datos sinteticos. Seguimientos de filosofia y microbiologia aun pueden rechazar o agotar unos 35 s; no se declaran resueltos ni se afirma exactitud del 99 por ciento.
- Informes, causas, archivos, comandos, medidas y limites: reports/reparacion_conversacional_20261030/README.md y resultados.md. Evidencia: verified_http.json, jack_recheck.json, measured_summary.json, integrity_final.json. Backup verificado al inicio: backups/conocimiento_20261030_01.
- .env y hashes originales de memoria/RAG intactos; quick_check OK y cero problemas FK. Conteos MySQL y auxiliares originales conservados en todos los turnos finales. Sin migraciones, importaciones globales, paquetes, modelos, cambios visuales/voz/avatar, reconstrucciones Docker, commits o push.
- Google Books permanece deshabilitado por defecto; las pruebas lo activaron solo por proceso tras la confirmacion previa del usuario de no facturacion. Arranque existente: .\venv\Scripts\python.exe -B iniciar_mysql_local.py --http-desarrollo --google-books-sin-facturacion (clave solo en prompt oculto; no cambiar .env).

## 2026-10-31 - Detective literario y preparacion remota para el 3 de noviembre

- Continuacion del adjunto a882980f, conservando todo el estado local previo. Informes vigentes: reports/demo_20261103/resultados_actuales.md, servidor_remoto.md y guion_8_minutos.md. El README de esa carpeta conserva la ronda historica con una advertencia de actualizacion; no usar sus antiguas afirmaciones sobre autenticacion MySQL o aislamiento.
- Correcciones generales: conservar intent identify; explicacion extractiva de pistas; relaciones con clausula relativa; filtrar simbolismo inequivoco sin borrar hechos; referencias locales combinadas recuperadas desde el original por identidad+URL; preferencias/lecturas/rechazos privados; bloquear caida de elipsis similar a recomendaciones genericas; reconocer Cuéntame mas del segundo, actualizar foco antes de generar y reutilizar sinopsis recibida; enlaces sin inventar stock/precio; no emitir pie de fuentes vacio. Categoria Fiction sola no acredita publico adulto. Pruebas sinteticas antes de los ultimos arreglos reproducen los fallos; no hay respuestas programadas para titulos concretos.
- HTTP/SSE de cierre: recorrido_cierre.json, diez turnos utiles (9 answered y un acuse social), media 0.7465 s, mediana 0.3319 s, maximo/p95 muestral 3.1537 s, cero LLM. Ordinal de la misma lista de fantasia: antes unavailable 35.1067 s; despues El Hobbit 0.3467 s y donde encontrarlo 0.2804 s. Explicacion de pistas 32.6427 -> 0.1283 s. No comparar preguntas distintas como mejora global ni declarar SLA/99 por ciento.
- Limite conservado: dos similares en espanol encontro solo una opcion en una ronda y ninguna fiable en otra (12.4221 s). La continuacion corregida se abstuvo en 0.2514 s sin recomendar manuales ajenos. Filosofia se comprobo otra vez: trama 16.2833 s, sugerencia por materia 7.7688 s; no afirmar similitud narrativa profunda. Microbiologia no reevaluada en este lote.
- Obra ausente La mala costumbre de Alana S. Portero: cero coincidencias iniciales en memoria, biblioteca, fichas y catalogo Libro; cero tambien en registros/nombres KB de MySQL al cierre. Respuesta externa 4.4338 s, identidad Open Library y premisa Wikipedia; una obra/dos fuentes persistidas SOLO en copia de demo. Nueva sesion/proceso con proveedores apagados y sockets publicos bloqueados: misma premisa 0.6212 s / cero LLM. Evidencias obra_externa_*.json; no se incorporo globalmente a los originales ni al MySQL.
- Perfil independiente iniciar_demo.py y demo_settings/demo_urls/demo_gateway: Waitress loopback, DEBUG False, MySQL en sesion read only, sesiones de archivo y copias auxiliares persistentes bajo .testtmp. Usuario demo y claves solo por prompts ocultos. Admin, cuentas, pagos y media no autorizado bloqueados. HTTPS con host exacto, CSRF, cookies Secure y HSTS; no confiar en cabeceras proxy del solicitante. No modifica .env ni arranque habitual.
- Instalaciones autorizadas expresamente: waitress 3.0.2 y whitenoise 6.12.0 en venv (requirements-demo.txt); Tailscale Windows 1.104.4, despues el usuario inicio sesion. DNS xato.taila70665.ts.net. Funnel status siempre {}: NO se publico ni se activo Serve/Funnel. Pruebas https_cierre.json son SOLO backend loopback tras terminacion TLS simulada, no certificado/conectividad exterior. Falta autorizacion de publicacion y prueba movil/instituto.
- El usuario respondio SOLO DEJAR PREPARADA la regla de firewall. No aplicar ProtegerServicios.ps1 -Aplicar ni elevar sin nueva autorizacion. MySQL ya escuchaba en 0.0.0.0:3306; no se corrige silenciosamente ni se declara aislado. Revisar ese punto antes de publicar. SearXNG Docker sigue healthy, publicado unicamente 127.0.0.1:8080; no se reconstruyo ni se reinicio Docker en este lote.
- Fallo propio de demo reproducido en Edge: desafios Basic de recursos sin credenciales llenaban el contador de claves fallidas. Corregido sin desactivar protecciones. Ensayo simultaneo encontro bloqueo transitorio 409 de cuota/IP en finalizacion; cliente reintenta como maximo dos veces solo con Retry-After acotado, mismo token/deadline, nunca vuelve a buscar/generar. Version del helper chat-v9; cambio de referencia del asset unicamente, sin rediseno.
- Validacion final: scripts.demo.test_demo, 210 pruebas SQLite/auxiliares temporales aprobadas, 3.348 s suite/4.589 s proceso (tests_release.json). JS existente 246 comprobaciones y cuatro casos nuevos de finalizacion idempotente/deadline OK. pip check y git diff --check OK. No sumar rondas historicas. La primera seleccion de tests tenia un nombre de modulo inexistente; fue corregida, no fue un fallo de aplicacion.
- Grabacion autentica recomendada grabacion_defensa/funcionamiento_real.webp, 27 capturas y ocho turnos, 16 respuestas HTTP 200, sin excepcion JS; identificacion y botones inspeccionados. Sin audio. Las carpetas de capturas anteriores documentan fallos y NO son la grabacion de defensa. Voz externa devolvio 503; fallback del navegador cubierto en tests, audio/microfono real remoto pendiente. No se cambiaron voz, avatar, colores, tarjetas ni layout.
- Integridad: integridad_final_verificada.json, MySQL local 41 tablas/46822 filas observadas, Libro55; consulta sin red con conteos SQL antes/despues iguales. No inferir inmutabilidad de cada fila durante todo el dia ni borrar filas para igualar un informe historico. .env, memoria/RAG originales con SHA256 iguales, quick_check OK y cero FK; cinco auxiliares originales iguales en arnes sin red. Respaldos previos conservados, unos 78.57 GiB libres al medir. Sin migraciones, importaciones globales, tareas Windows, entrenamiento, APIs pagadas, commits ni push.
- Al cerrar, detener solo los servidores Waitress de prueba y navegadores propios. Mantener el servidor habitual 8000 y MySQL/Ollama/Docker/Tailscale del usuario. Reanudar con los comandos del informe; no repetir la auditoria anterior ni la suite general de miles de pruebas. Publicacion exterior, aislamiento de servicios, audio remoto y cobertura de similitud profunda siguen pendientes y no deben declararse completados.
- Cierre efectivamente comprobado en estado_cierre.json: 8002/8003 cerrados, ningun navegador propio abierto, Funnel {}, 3306/11434/8080 accesibles en localhost y hashes originales iguales. El puerto 8000 tampoco escuchaba en ese instante; no se termino ningun proceso ajeno. Para iniciar la aplicacion usar el procedimiento documentado. No afirmar que queda un servidor web abierto tras esta revision.

## 2026-10-31 - Preflight HTTPS 02501f96 y aplazamiento explicito del firewall

- Adjunto leido y trabajo local reutilizado. Informe vigente reports/https_preflight_20261031/README.md. No se cambiaron servicios literarios ni UI. Se agrego --comprobar-despliegue al lanzador y herramientas de auditoria de lectura; no se instalo nada ni se modifico .env.
- IMPORTANTE: ante la solicitud de permiso para AislarMySqlDemo.ps1, el usuario eligio SOLO DEJAR PREPARADA porque controla el PC remotamente y no tendra acceso fisico hasta el lunes. NO aplicar reglas, pedir UAC, reiniciar servicios/Windows, desconectar Tailscale ni activar Funnel. No repetir la solicitud de aplicar reglas mientras mantenga esta restriccion. La publicacion sigue sin autorizar.
- MySQL real bind_address=* y mysqlx_bind_address=*, Libro55. Escuchar no prueba exposicion publica. RevisarProteccionMySql.ps1 examino 204 reglas activas, cero sin resolver; excluyo 20 permisos de paquetes PFN que no son permisos globales a mysqld. Todos los perfiles habilitados y bloqueo entrante predeterminado. No se encontro permiso aplicable de MySQL por la interfaz publica/LAN; si dos Tailscale-In para las IP privadas IPv4/IPv6, todos los puertos en Dominio/Privado. ShieldsUp=False: posible acceso de otros dispositivos autorizados de tailnet sujeto a ACL; no se probo desde otro dispositivo ni Internet. Tabla portproxy vacia; router no auditado. No confundir reglas condicionadas a otro usuario con bloqueo global de MySQL.
- Acceso remoto: chromoting Running/Auto/LocalSystem y Tailscale Running/Auto; reglas existentes intactas. UAC EnableLUA1, PromptOnSecureDesktop1, ConsentPromptBehaviorAdmin5/User3. Chromium contempla UAC, pero NO se comprobo interactivamente ni puede garantizarse que su sesion controle el escritorio seguro con solo lecturas. No abrir UAC para probarlo sin permiso/recuperacion.
- Script anterior ProtegerServicios.ps1 es amplio (incluye8080/WSL), no certificarlo seguro para Docker ni aplicarlo. Alternativa AislarMySqlDemo.ps1 limitada a mysqld.exe/TCP3306/33060/no-loopback, descripcion y nombre propios. Plan de lectura y sintaxis verificados. -Revertir solo deshabilita su regla validada; no se ejecuto ni se probo una aplicacion/reversion real. No existe ninguna de las dos reglas de LitMate en el firewall al comprobar.
- Servidor HTTPS logico Waitress127.0.0.1:8003 probado, DEBUGFalse y copias auxiliares .testtmp/https-preflight-20261031. Clave de ensayo efimera solo en memoria; no publicar con ella. Host/CSRF exactos, cookies Secure/HttpOnly/SameSite apropiadas, admin/cuentas/pagos/privados bloqueados. Check --deploy real: solo W005 subdominios HSTS y W021 preload, deliberadamente no habilitados para demo. No se silenciaron validaciones.
- Conversacion real de seis turnos correcta, 0.1995-2.3329s (conversacion.json). Consulta con modelo 20.8886s, primer progreso0.0499s, fases search/writing/review antes de ready20.8309s; seguimiento0.1011s. Progreso en vivo, texto factual solo tras auditoria; no prometer tokens del modelo sin verificar. Controles ampliados seguridad_sse.json correctos; dos portadas200/imagenvalida sin enviar BasicAuth a proveedores. RAG498docs/526chunks/9FTS/quickcheckOK. Qwen9b ejecucion real listo9.0119s. SearXNG59resultados1.0859s/OpenLibrary+Mwmbl/sin motores no disponibles en la muestra; relevancia mixta. Dockerhealthy,8080solo127; Compose sin dependenciaMySQL.
- Pruebas focalizadas ejecutadas:11Django (7gateway+4preflight) OK;246JSexistentes+4reintentos OK; sintaxisPowerShell OK; gitdiffcheck OK. No repetir210pruebasliterarias sin regresion. Primer error del nuevo test500 fue por URLConf de fixture incompleto, corregido incluyendo URLs reales; no era fallo del servidor vivo.
- Tailscale1.104.4/MagicDNStrue/DNSxato.taila70665.ts.net; CertDomainsnull y capFunnel noanunciado, Serve/Funnel{}. No generar certificados/cambiar politica hasta autorizacion. Comandos futuros --https443 hacia127.0.0.1:8003 y off, sin --bg/down/reset. CadenaSSEexterna pendiente, no declarar HTTPSpublico probado.
- Cierre.json: Waitress propio detenido, procesos remotos preservados, reglas/perfiles relevantes iguales, Tailscaleconectado, fuenteslocales3306/11434/8080responden, hashesoriginales.env/memoria/RAGiguales. Sinadmin/UAC/firewall/push/commits/migraciones/reinicios/publicacion. Continuar desde estos informes y respetar aplazamiento hasta acceso fisico o nueva instruccion explicita.

## 2026-10-31 - Listo localmente para solicitar autorizacion final de Funnel

- Nueva instruccion del usuario acepta la revision de red, mantiene AislarMySqlDemo.ps1 SIN aplicar y prohibe UAC/firewall. Pide comprobaciones finales y autorizacion explicita antes de Funnel. Informe: reports/https_preflight_20261031/activacion_pendiente.md. Aun NO existe autorizacion de publicacion.
- Se confirmo Tailscale1.104.4, Running/MagicDNS, DNSxato.taila70665.ts.net, Serve/Funnel{}. No se sobrescribe ni resetea nada. Certificados/permisos HTTPS/Funnel todavia por habilitar al autorizar; no declarar URL publica lista.
- Unico ajuste del lanzador iniciar_demo.py: misma fabrica create_server de Waitress, verifica socket.getsockname ==127.0.0.1:8003 y falla cerrado ante otra escucha; imprime actual_listener. Ensayo real con DEBUGFalse/MySQLreadOnly55/libro, modo HTTPS y --comprobar-despliegue: W005/W021 intencionales, resto correcto. No se modifico el asistente ni diseño.
- verificacion_final_funnel.json: controles ampliados correctos, cinco turnos answered, 1.0681/0.1416/0.1184/0.0994/20.5913 s; ultimo2LLM, primerprogreso0.0553s, ready20.5257s. Autenticacion, CSRF, cookies, admin/privados/respaldos, host y JSactual correctos. Once pruebasDjango y cuatro casosJS ejecutadosOK; gitdiffcheckOK. Hashes.env/memoria/RAGoriginales iguales.
- Clave de ensayo efimera no almacenada ni publicada; se detuvo SOLO el ensayo para liberar8003. Se pidio al usuario iniciar iniciar_demo.py en su propia PowerShell, con clave MySQL y nueva clave demo>=16 en prompts ocultos. El usuario respondio YA ESTA INICIADO Y LA CONSOLA SIGUE ABIERTA. NO volver a pedirle la clave ni el mismo arranque sin un fallo comprobado.
- MUY IMPORTANTE: el servidor actual es DEL USUARIO, con su clave privada; no detenerlo como ensayo. Procesos observados32692/4620 (verificar vigencia antes de operar), flagsmodohttps/hostesperado/puerto8003. servidor_privado_confirmado.json: localhost8003 responde401 chat y JSsinclave,404admin/backups/.env,400hostajeno. No se conoce ni registro su contraseña. No se ha probado login con su nueva clave por no solicitarla al chat; el perfil autentico fue probado antes y el telefono lo comprobara despues de autorizar.
- Siguiente paso: pedir/recibir autorizacion FINAL para ejecutar & "$env:ProgramFiles\Tailscale\tailscale.exe" funnel --https=443 http://127.0.0.1:8003, SIN --bg. No ejecutar hasta respuesta afirmativa explicita. Antes comprobar Serve/Funnel siguen{} y servidor responde; si aparece otro servicio no reemplazarlo. Si requiere UAC/firewall, detenerse sin pedirlo ni cambiarlo. HTTPS/permisos de la cuenta pueden requerir aprobacion del usuario en Tailscale.
- Apagar solo la publicacion propia con CtrlC o funnel --https=443 off; verificarstatus. Nunca down/logout/reset ni detenerChromeRemoteDesktop/Tailscale. MySQL3306/33060, Ollama11434 y SearXNG8080 no son destinosdelFunnel. Luego verificarURL/certificado/auth/SSE/imagenes/contexto y pedirpruebatelefono conWiFiyVPN Tailscaleapagados. No afirmar exito externo antes de esa prueba.

## 2026-10-31 - Funnel autorizado y activado, esperando prueba movil

- El usuario respondio SI AUTORIZO PUBLICAR UNICAMENTE LITMATE. Regla MySQL sigue SIN aplicar; prohibidos UAC/firewall/desconexionTailscale/controlremoto. Se revalido localhost8003=401 y Serve/Funnel{} antes de actuar.
- Se ejecuto & 'C:\Program Files\Tailscale\tailscale.exe' funnel --https=443 http://127.0.0.1:8003 en primer plano, SIN --bg. Sesion exec75209 (verificar vigencia antes de operar). NO detener ese proceso como limpieza automatica: es la publicacion autorizada. Waitress privado es del usuario, no detenerlo ni pedir su clave.
- CLI espero porque Funnel no estaba habilitado. El usuario abrio el enlace oficial mostrado por CLI y respondio YA HABILITE FUNNEL PARA ESTE DISPOSITIVO. La misma orden esperando informo Success y URL https://xato.taila70665.ts.net/. No repetir la habilitacion ni ejecutar otro funnel sobre la misma configuracion.
- Evidencia https_activado_sin_credenciales.json: TLS1.3/certificadoLetEncryptYE1 valido/nombreSANcorrecto/vence29ene2027; URL/chat yJS401conBasic, admin/.env/backups404. ConfigForeground solo443HTTPS y proxy127.0.0.1:8003. MySQL/Ollama/SearXNG siguen locales; no fueron destinos. Tailscale/chromoting Running. Prueba originada en servidor perteneciente a tailnet, NO prueba independiente desdeInternet. Herramienta web externa no inspeccionoURL protegida; no concluir fallo/éxito con eso.
- Se pidio prueba movil conWiFiapagado yVPN Tailscaleapagada SOLOtelefono, manteniendoPCconectado. Usuario demo yclaveprivada conocida SOLOporusuario. Cinco pasos: interfaz/login,planeta/rosa, dosfantasiasconportadas,segundo, tramaSofia conprogreso. Respuesta pendiente; no declarar completada la publicacion/validacionexterna hasta recibir resultado. Si hay fallo investigar antesdeafirmar exito.
- check_demo.py ahora admite --publico --host DNSesperado HTTPS443 verificacionTLSestandar, nunca redireccionesotroorigen/downgrade/credencialesURL. test_public_transport.py cuatropruebassinredOK; hostinvalido rechazadoantesdepedirclave. No se ejecuto prueba publicaautenticada porque no se solicita clavealchat. Comando opcionaloculto y detalle en publicacion_20261031.md.
- Riesgooperativo: Funnel en sesion de esta ejecucion, no servicio persistente; puede terminar si cierraCodex/terminal. Procedimiento para consola propia y apagadoespecifico443 documentado. No activar --bg ni crear tarea sin solicitud. Para apagar solo Funnel propio usar off443/CtrlC; nunca down/logout/reset ni detener servicios de acceso remoto.
- Verificacion posterior mas fuerte: dns_publico_funnel.json muestra A/AAAA globales del releFunnel. Conexión directaalApublico209.177.145.97:443 conSNIxato.taila70665.ts.net/TLSestandar verificado recibioHTTP401conBasicen1.1945s, sincredenciales (relay_publico_verificado.json). Asi secomprueba la ruta publica sin resolverporMagicDNSprivado; sigue siendoPCorigen, no telefonoindependiente. No dar por ejecutado login/chat/SSEmovil hasta respuesta del usuario.
- Confirmacion posterior DEL USUARIO: TODO FUNCIONO DESDE DATOS MOVILES CON WIFI Y VPN APAGADOS. validacion_movil_confirmada.json registra por confirmacion humana accesoautenticado/interfaz/avatar/portadas/tarjetas/ordinal/contexto/progreso; no inventar cifras de latencia movil ni afirmar que el agente introdujo su clave. Publicacion actual validada por el usuario; conservaractiva sesionFunnel75209 y servidorprivadodelusuario.
- Observacion operativa: texto de funnel status mostro No serve config mientras JSONForeground seguiaactivo yHTTPS401. Usar status --json y pruebasHTTP, no esa frase aislada para confirmar apagado. No corregir binarioTailscale ni cambiarimagen/servicios. Para apagar flujo propio, CtrlC delprocesoFunnel o off443 y verificarqueJSONretireForeground; no down/logout/reset ni tocarChrome/Tailscale.

## 2026-10-31 - Web completa preparada; reinicio publico pendiente de permiso

- Adjunto vigente 8982c8e7-826c-451d-bc37-c8e9c11a312d: habilitar frontend real en HTTPS sin publicar rutas privadas. Revisados git status/diff y URLconf/vistas/plantillas; preservados todos los cambios previos. Funnel Foreground443 ya publica raiz hacia127.0.0.1:8003: NO se reconfiguro, no se toco servidor8003, firewall/UAC, Tailscale o Chrome Remote Desktop. Usuario reitero continuar al recargarcreditos durantelaspruebas; eso NO autoriza reiniciar.
- Causa: DemoGateway permitia solo chat/apoyos y demo_urls redirigia inicioalchat. Implementada lista cerrada de paginas/metodos y portada original; nuevas vistas previas seguras solo para demo. GET/POST login/registro/password-reset/contacto muestran aviso persistente, no autentican cuentas personales, crean usuarios, mandan correos o guardan mensajes. Checkout/OAuth vuelven a paginaspublicas sin procesos externos; conversion tracked=false. Perfiles/favoritos/listas/pagos/callbacks/debug/admin/backups/privados siguen404. Basic demo y passwordprivada delusuario no cambiados.
- Detectadas escrituras indirectas de portada/precios/analitica: guardas LITMATE_DEMO_READ_ONLY en core/views.py y core/scraper.py; comparador usa cache, ignora force=true, no scrapea/persiste ni grafica historial sintetico en demo. Perfilnormal preservado. Sin cambios en IA/RAG/memoria/recomendaciones/voz, .env o credenciales. templates/base.html solo aviso contextual de vista previa usando estilo existente.
- Codigo: core/demo_gateway.py, core/demo_frontend.py(nuevo), litmate_project/demo_urls.py, core/views.py, core/scraper.py, templates/base.html. Pruebas: core/test_demo_frontend.py(nuevo), test_demo_gateway.py y test_demo_preflight.py. Herramientas: scripts/demo/frontend_checks.py(nuevo), check_demo.py(--web-completa), capturar_demo.py/.mjs(--puerto y --navegacion, clics reales, compara cookie sin guardarla). Corregido aislamiento de ruta temporal de SessionStore en fixtures, sin cambiar backend de sesiones de la aplicacion.
- Cuatro regresiones iniciales reproducidasfallando antes del arreglo. Despues:25Django dirigidasOK,210regresionesdemoIAOK,246JSchatOK,4reintentosOK,4transporteredireccionesOK, diffcheckOK. Sin consultas productivas en testsautomaticos; SQLite temporal cuando requerido. reports/https_fullsite_20261031/regresiones_frontend.json y regresiones_210.json.
- Servidores PROPIOS de ensayo:8004 perfilHTTPS terminado en loopback/logicalHostpublico,8005 modoHTTP local para Edge; ambos MySQL sesionread_onlytrue,auxiliaresycookiesaislados. No son la publicacion8003. 14paginas200,23recursoslocalesOK,4destinosextra, buscadorDune/quicksearch/comparadorOK; cuatroPOSTformsvistapreviasinpersistir. recorridos guardados en recorrido_formularios_sse.json y navegacion_sse.json.
- Edge real en navegador_enlaces/captura.json: clicsmenureales, no imagenconsrcnovaciofallida ni excepcionesJS; catalogo41imagenes. Capturas inicio/catalogo inspeccionadas. Dosfantasiasrespondidas0.5213s; navegarabout/catalogoyvolveralchat; masdelsegundo identifica Choque de Reyes en0.5114s. sessionPreservedAcrossNavigation=true; nunca almacenar valorcookie/credenciales. Rutas rapidas existentes, no atribuir esos tiempos a inferencia completa deQwen.
- Limites reales: ensayoHTTP Elprincipitorespondido1.0474s, seguimiento Quienloescribio pidemasdatos15.8063s; NOcorregidoenestatarea. Servidorvozopcionaldesactivado LITMATE_TTS_ENABLED=False,503esperado; fallbackbrowserexistente sin cambios, audicionnoverificadaenheadless. No declarar que todas las preguntas o vozexternafuncionan. Datosmovilesdelusuarioanteriorvalidabanchat, NO aun webampliada.
- Integridad: .env/memoria/RAGoriginal mismosSHA256, SQLitequick_checkOKy0FKissues, MySQL41tablas46822filas55Libros, sololectura. integridad_lectura.json, integridad_final.json y publicacion_preservada.json. Recuento y fuentes conservadas, sinmigracion/importacion/instalacion/push/commits.
- PENDIENTE OBLIGATORIO: pedir permiso antes de reiniciar8003 (adjunto expresoloexige). El lanzador genera SECRET_KEY aleatoria porarranque: archivos conservados PERO firmas/contextodeconversacion pueden invalidarse. No prometer conservarhilo atravesreinicio; no extraerclave delproceso ni omitir firmas. Para mantener BasicAuth operador debe reintroducir MISMApassworddemoprivada en terminal, nuncachat. README.md de este lote tiene comando exacto existente y pasos seguros para reiniciar SOLOconsolaWaitress8003 manteniendoFunnel/serviciosremotos; luego nueva prueba raiz/chat/mobile. No actuar sobre8003sinrespuestaexplicita.
- Cierre de ensayos: detenidos SOLO servidores propios8004/8005; cierre_ensayos.json confirma ambos sinescucha y8003activo. integridad_final.json cotejada con integridad_lectura.json: todoslosconteosMySQLexactamenteiguales yhashesoriginalesiguales. SesionFunnel75209 yservidordelusuario conservados.
- AUTORIZACION POSTERIOR RECIBIDA: usuario respondio "Si, autorizo; puedo reiniciar desde mi consola" para SOLOWaitress8003. No volver a pedir permiso. Como la contrasena privada Basic solo la conoce el usuario, debe CtrlC en SUconsolaWaitress y relanzar comando README con MISMApassword, nuncachat. Verificacion trasautorizacion: raiz/chat401,about404,admin404; sigueperfilanterior, no afirmar reiniciado. FunnelForegroundmismoproxy127.0.0.1:8003 yserviciosMySQL80/Tailscale/chromotingRunning. Pendientes arranqueefectivo ypruebaspublicastrasreinicio; sin cambios de firewall/red/credenciales.

## 2026-10-31 - Web ampliada confirmada en HTTPS; conservar version para defensa

- Confirmacion explicita DEL USUARIO: reinicio Waitress correctamente, consola abierta con actual_listener127.0.0.1:8003; probo desde su celular la direccion HTTPS publica y TODA LA PAGINA funciona, incluida navegacion entre secciones. Funnel y acceso remoto continuan funcionando. Registrar como prueba REAL satisfactoria de la web ampliada por usuario, sin atribuirla a automatizacion autenticada del agente ni inventar latencias o repeticion individual de SSE/voz. La red de ESTA ultima prueba no se especifico; no copiar automaticamente WiFi/VPN apagados del ensayo anterior.
- Nueva instruccion vigente: NO reiniciar servicios ni introducir modificaciones importantes; conservar version estable hasta defensa3noviembre. Solo preparar checklist y recuperacion Waitress/Funnel. No hace falta otra activacion ni pruebas pesadas. No cambiar codigo, .env, credenciales, firewall, red, tareas programadas, dependencias o procesos.
- Solo lectura actual: Tailscale1.104.4, mismo Foreground443/proxyraizhttp://127.0.0.1:8003; MySQL80,Tailscale,chromotingRunning. Raiz/about/post/libros/planes/contact/login/chat ahora401sincredenciales (aboutantes404), privadosadmin/.env/backups404. La prueba autenticada publica es la del usuario; esta lectura confirma puerta de acceso sin solicitar su password.
- Documentacion: reports/https_fullsite_20261031/validacion_web_publica_confirmada.json, README.md actualizado a activado/validado, y DEFENSA_20261103.md con checklist20-30minantes, URL/recorrido, limitesvistaprevia/sololectura, vozfallback, cuidadosdeconsolas y recuperacion condicional SOLOdelproceso caido. Funnel actual sin --bg depende de proceso/sesionprimerplano; no duplicarlo ni moverlo ahora. Si se detiene, comprobar JSON/Serve sin conflicto y abrir nuevo proceso foreground en consola propia. Waitress recuperacion pide MISMApassworddemoprivada en terminal; clavefirmaaleatoria implica nuevaconversaciontrasreinicio.
- No se reinicio ni paro ningun servicio/proceso en esta actualizacion. No se ejecutaron tests de IA adicionales: cambio solo documental, comprobado por lectura y diffcheck. Mantener la publicacion estable; pendientes exclusivamente checklistdia3 y recuperacion SI ocurre una caida.

## 2026-10-31 - Cuentas, cuotas y movil en perfil AISLADO; despliegue no autorizado

- Adjunto vigente d1148e53-db1b-4719-8114-d97a7218fedc autoriza implementacion aislada. Base Git f38650a inicialmente limpia. Prohibido reiniciar servidor PUBLICO 8003, Funnel, Tailscale, escritorio remoto, Docker/MySQL/Ollama. No .env, paquetes, push, commits ni borrado/movimiento. El permiso final de despliegue todavia NO existe.
- Auditoria MySQL SELECT read-only:179usuarios,158perfiles,157suscripciones,42pagos historicos,50conversaciones,190mensajes. Planes reales Gratis15/dia0CLP,Pro100/dia4990CLP,VIP0=ilimitado9990CLP. Control antiguo apagado, cache por IP y campo fallback incorrecto; sesiones demo/SECRET_KEY efimeras.
- Nuevo perfil OPTATIVO reader_settings/reader_accounts; auth.User y modelos actuales reutilizados con router accounts privado SQLite. Catalogo MySQL protegido read-only, RAG original intacto. Ledger atomico lifetime invitado1, cuenta por dia America/Santiago, operacion idempotente, SSE factual obligatorio y recuperacion auditada ante rollback historial/cuota. Migracion0001 nueva SOLO aplicada en ensayos. DPAPI clave privada estable; arranque con --cuentas-db no migra. Almacen real data/accounts todavia NO creado.
- Login/registro->Planes; gratis POST CSRF sin tarjeta; contrasenas Django, correos nuevos unicos, grupo historico de correos duplicados preservado con login por username. Plan pagado no se concede por flag historico ni URL; contratacion desactivada, recibo requiere confirmacion independiente futura. No cobros ni pruebas sandbox de red. Correo dummy, favoritos/listas/fotos fuera de perfil por separacion privada; pendientes explicitos.
- Copia PRISTINA de ensayo .testtmp/reader-copy-final-20261031/accounts.sqlite3,557056bytes,785filas de cuentas/historial coincidentes con origen (incluye5HistorialChatbot), claves/huellas/FK verificados; NO usada con usuarios sinteticos. Recibo copia_cuentas_final_ensayo.json. No trasladar el stage usado en HTTP a produccion. Promocion segura implementada y probada con ROOT temporal, NO ejecutada en almacenamiento real.
- Aceptacion cierre41/41 pruebas nuevas OK; compatibilidad42 yregresiones210 existentes OK; JS246+4OK. HTTP/SSE REAL en servidor PROPIO8006: http_sse_final.json doce criterios todosTrue, incluido progress=false, gratuito15, bloqueo invitado, reinicio con MISMA sesion/plan/cuota/contexto y logout/login sin reinicio consumo. Solo se reinicio ensayo8006.
- Movil: intentos01-06 conservados; matriz anchos320/360/375/390/414/430/tablet768/horizontal844/escritorio1280 y dos portadas cargadas OK. Intento06 aun fallo lectura anterior y simulacion teclado; investigacion final en curso, NO declarar movil completo. Correcciones CSS/JS nuevas SOLO perfil optativo; assets compartidos del chat publico no modificados. Probar eventos reales/render de Chromium y comprobar ultimo JSON antes de concluir. No se probo teclado fisico Android/Safari.
- Manual MANUAL_DE_USUARIO_LITMATE.md35secciones; informe reports/accounts_20261031/README.md y inventario sin borrar; caches aproximadamente4.3MB solo candidatos, no se elimino nada. Documentacion de despliegue/reversion preparada, requiere autorizacion final y misma password Basic privada introducida por operador, nunca chat.
- Auditoria cierre MySQL mismos conteos y planes (auditoria_cierre_solo_lectura.json). Falta cierre de prueba movil, hashes/servicios finales, actualizar README y pedir autorizacion de despliegue sobre resultado concreto sin tocar publico. Store funciones reader_stage_pw conserva password SOLO ensayo en RAM; nunca imprimir. Publico/Funnel sesion75209 no tocar. Ultimo ensayo8006 detenido para cargar assets de prueba actuales.
- CIERRE POSTERIOR: movil_08/captura.json14/14criteriosTrue,ceroexcepcionesJS,2portadascargadas,nueveanchosOK,lecturaanteriortop0 y teclado simulado campo inferior351.97<=360. Causa carrera escritura scrollTop SSE anterior a evento de gesto; proteccion SOLO instancia nuevo perfil, sin cambiar Element.prototype/chatbot.js compartido. scripts/accounts/test_reader_scroll.cjs4regresionesOK. CSS root/inner auto evita demora del scroll al enfocar teclado. Chromium captura/render tras resize; no equivale a teclado fisico/Safari.
- EnsayoPROPIO34477/8006 detenido al terminar. cierre_ensayo.json:8006sin escucha,8003activo y401conHostvalido. NO cerrar75209Funnel ni servidor publico. Pendiente autorizacion final del usuario para crear NUEVO data/accounts y desplegar; no tomar continuar/recargarcreditos como permiso de reinicio.
- Aceptacion_cierre41/41OK otra vez, JS246+4reintentos+4scrollOK,29PythonASTOK,gitdiffcheckOK. preservacion_cierre.json confirma hashes.env/memoria/RAGiguales,conteos/planesMySQLiguales,FunnelForeground05619147116f0c78igual,puerta401paginas/404privados. Consulta loopback requiere Hostxato.taila70665.ts.net (otroHost400porproteccion), no interpretar400inicial como caida. README actualizado. Pendiente solo detener ensayo PROPIO34477/8006 y solicitar autorizacionfinal para almacenamiento real/reinicio8003; servicios publicos permanecen intactos.
