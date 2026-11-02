# Reparación conversacional: identidad, pertinencia y fallos

## Alcance y seguridad

Se continuó sobre los cambios existentes. Se verificó el respaldo
`backups/conocimiento_20261030_01`; se conservaron los demás respaldos.
No se modificaron `.env`, credenciales, MySQL, memoria literaria original ni
índices RAG. No hubo migraciones, paquetes nuevos, reconstrucciones Docker,
cambios visuales, commits ni push.

Las conversaciones HTTP/SSE usan MySQL local para lecturas y sesiones anónimas
de prueba, con copias desechables de los almacenes auxiliares. Cada turno
comprueba conteos MySQL y hashes originales. No incorporan hechos al catálogo
global. Las trazas sólo contienen las preguntas públicas fijadas para evaluación.

## Causas demostradas

1. **Jack:** en `baseline_jack_trace.json`, el clasificador sustituyó la consulta
   por Jekyll y Hyde. El generador recibió otras obras y produjo un borrador con
   confusiones entre películas. El validador rechazó una cita no recibida; la
   reparación falló en el transporte al agotarse su margen. La búsqueda sí se
   ejecutó. No era una ausencia demostrada de libros ni una excepción Django.
2. **Heinz Wuth:** la consulta libre no recuperaba una identidad fiable. Una
   consulta por el campo de autor sí encontró publicaciones. El clasificador
   había llegado a proponer un título ajeno como supuesto libro de ese autor.
3. **Similitud:** `ai_related_recommendations` prefería materias cortas y aceptaba
   cualquier intersección. «Science» podía justificar oceanografía después de
   ciencia culinaria. El recorrido pesado podía repetir ese defecto tras fallar
   la ruta rápida.
4. **Etiquetas de público:** la prueba independiente de filosofía encontró Babar
   por compartir «Juvenile Fiction». Esa etiqueta no demuestra afinidad temática.
5. **Tipo de obra:** una novela romántica etiquetada «Medical» podía aparecer
   después de un manual de microbiología. Se añadió consistencia entre el tipo
   de referencia y la propuesta, sin listas negras de títulos.
6. **Seguimientos:** la pregunta por género no tenía una ruta bibliográfica
   extractiva; «por qué se parece el primero» podía volver a recomendar libros;
   «dame otro que trate...» perdía la cantidad singular y la intención temática.
7. **Errores:** el transporte de Ollama agrupaba timeouts y desconexiones con JSON
   inválido. Resultados locales irrelevantes podían ocultar el fallo de un proveedor.
8. **Auditoría:** una materia no reconocida por el diccionario podía evitar el
   contrato de auditoría completa de recomendaciones, aun exigiendo fichas.
9. **Paráfrasis innecesaria:** la ejecución `final_http.json` detectó una inversión
   de la acción de Zero que pasó el auditor del modelo. La ruta literal ahora
   usa `publication_synopsis_answer`: selecciona frases recibidas, conserva la
   atribución y pasa los validadores sin regenerar acontecimientos. El mismo
   mecanismo se prueba con una exploradora de una obra sintética, sin excepciones
   para Jack. Los borradores intermedios se conservan como fallos reales.

## Correcciones y funciones

- `literary_research.publication_lookup_target`, `publication_search_queries` y
  `publication_matches`: conservan una identidad literal como hipótesis, buscan
  por autor cuando procede y comprueban títulos, autores o alias verificados.
  No inventan autores, equivalencias con películas ni publicaciones. Rechazan
  datos que el filtro de privacidad haya tenido que eliminar antes de normalizar.
- `literary_ai.simple_literary_route` y `_reply`: usan esa búsqueda sin routing
  inventado, filtran fichas antes y después de investigar, y distinguen ausencia
  comprobable de un fallo de dependencia. Mantienen los validadores.
- `ai_related_recommendations._topics` y `related_relevance`: usan la jerarquía
  literal de materias, alias bilingües existentes, país, disciplinas, tipo de obra
  y tema explícito dominante cuando sólo existe una categoría genérica. Público
  y formato no reemplazan el tema. Se priorizan componentes específicos y se
  ordenan candidatos antes de recortar. No se rellenan listas con rechazados.
- El recorrido pesado reutiliza `related_relevance`; la ruta rápida no puede
  quedar anulada por un fallback que vuelva a aceptar sólo la categoría amplia.
- `ai_quick_answers.catalogue_lookup_answer`: responde sobre temas expresados en
  una ficha ya recibida. No llama «subgénero confirmado» a una inferencia temática.
- `related_explanation_answer`: resuelve la opción ordinal de la lista anterior,
  conserva la referencia original y muestra evidencia de ambas obras. Si faltan
  descripciones, reconoce el límite. No inicia otra lista de recomendaciones.
- `requested_book_count` e `is_topic_recommendation`: reconocen el singular
  elíptico «otro que trate sobre...», sin ignorar calificadores desconocidos.
- `local_llm.OllamaJSON._generate`: diferencia transporte, timeout, presupuesto
  agotado y respuesta inválida. Los detalles internos no se publican al usuario.
- Una caída del modelo puede recuperar una lista de identidades bibliográficas
  auditadas. Conserva `provider_error` y marca `partial_recovery`; no publica el
  borrador fallido ni trata el error como inexistencia del libro.
- `_retrieval_failed` distingue también los fallos de búsqueda de alternativas;
  los resultados locales ajenos no ocultan un timeout de la fuente externa.
- Las recomendaciones con fichas obligatorias mantienen auditoría factual
  completa aunque la materia no figure en el diccionario temático.
- `ai_answer_cache.POLICY` V9 evita reutilizar respuestas de la política anterior;
  no se borran registros ni conversaciones.
- El respaldo exterior de `_model_answer` no reemplaza peticiones similares o
  del mismo autor por una búsqueda genérica que ofrezca la obra de referencia.
  `repeated_recommendation` excluye variantes literales bilingües de la lista
  cuando coinciden sus autores. Es un filtro conservador de presentación, no
  una fusión bibliográfica ni un alias persistido.

## Pruebas y resultados

Las regresiones se añadieron antes de corregir los defectos: fallaron con las
selecciones irrelevantes, la pérdida del singular, el género, el estado técnico
mal clasificado, la falta de recuperación parcial y la auditoría incompleta.
Se cubren también materias independientes (grabado y exploración polar), países,
romance, astronomía, fantasía, manga, idiomas, privacidad, tarjetas y validadores.

El comando reproducible, sin MySQL y con todos los SQLite auxiliares temporales:

```powershell
.\venv\Scripts\python.exe -B reports\reparacion_conversacional_20261030\run_directed.py reports/reparacion_conversacional_20261030/tests_nueva_ejecucion.json
```

Debe usarse un nombre de salida nuevo: el instrumento conserva resultados previos.
Los archivos `tests_*.json` son rondas distintas y no se suman. La ronda
`tests_release.json` registró **525 pruebas aprobadas**, cero fallos, cero
errores, 12,552 s de suite (13,782 s incluyendo preparación).

Una ejecución no aislada encontró tres fallos por interferencia de los almacenes
auxiliares del entorno en pruebas que esperaban sólo fixtures. La batería aislada
incluye esas mismas pruebas y las ejecuta sin modificar datos originales.

### Conversaciones reales

- `baseline_heinz_fresh.json`: cinco turnos frescos iniciales; la primera consulta
  no identificaba la obra y no era posible mantener ese referente inexistente.
- `baseline_jack_trace.json`: salida del modelo y corrección que explican el fallo.
- `after_literal_lookup.json`: sin Google Books habilitado, Jack pasó de error
  genérico (~35 s) a insuficiencia explícita (~3,6 s). No es recuperación exitosa.
- `after_google_jack_heinz.json`: recuperación real de tres publicaciones de Jack,
  con portadas y enlaces; ejecución intermedia, anterior al cierre de auditoría.
- `heinz_conversation_v2.json`, `heinz_conversation_v3.json`, `heinz_final.json`:
  ejecuciones intermedias que descubrieron fallos adicionales. No se presentan
  como una conversación final sin errores.
- `independent_conversations.json`: nueve escenarios de dos turnos. Descubrió las
  recomendaciones erróneas de Babar y la novela médica romántica; se conservaron
  como evidencia anterior a sus regresiones y correcciones.
- `holdouts_corrected.json`: ya no ofrece esas dos obras irrelevantes, pero dos
  seguimientos agotaron ~35 s o rechazaron la generación. Esto sigue siendo una
  limitación de recuperación/generación, no una prueba de respuesta completa.
- `final_http.json`: conversación de seis turnos anterior a la última corrección
  extractiva; sus tiempos no prueban fidelidad de todas las paráfrasis.
- `closure_http.json`: conversación posterior a esa corrección. El resumen medido
  todavía detectó un respaldo exterior que repetía la referencia. Se corrigió
  con una regresión directa de `_model_answer`.
- `verified_http.json`: última conversación completa tras bloquear ese respaldo.
  Los cinco turnos de Heinz respondieron con la referencia correcta. La consulta
  de Jack encontró un fallo temporal real de proveedores; informó ese fallo en
  lugar de fingir ausencia de publicaciones o inventar títulos.
- `jack_recheck.json`: repetición aislada de la consulta tras ese fallo transitorio.
  El resumen medido registra su resultado real, sin borrar la ejecución fallida.

Google Books está integrado y su clave existe, pero la configuración por defecto
lo mantiene deshabilitado. Las pruebas que lo usan habilitan **sólo en su proceso**
las dos banderas que el usuario ya autorizó tras confirmar ausencia de facturación.
No se cambió `.env`. No se atribuye únicamente al código una mejora que también
depende de activar esa fuente. Sus errores `unavailable` y `timeout` son reales.

## Uso local y limitaciones

Para arrancar con la conexión MySQL actual y Google Books previamente autorizado:

```powershell
.\venv\Scripts\python.exe -B iniciar_mysql_local.py --http-desarrollo --google-books-sin-facturacion
```

La contraseña se introduce en el prompt oculto. No debe colocarse en la línea de
comandos. El lanzador no reimporta datos ni cambia `.env`.

Las reglas de materias son conservadoras y explicables; no equivalen a un
reranker semántico entrenado. Pueden perder candidatos relacionados que no tengan
materias o descripciones suficientes. No se garantiza una cobertura total ni una
tasa de error inferior al 1 %. Algunos seguimientos complejos aún alcanzan el
límite de ~35 s. Los metadatos de proveedores pueden ser incompletos o erróneos.
Persisten fallos de español en ciertas traducciones y una comparación literaria
compleja documentada en `../calidad_literaria_20261030/`. No se reconstruyó el RAG
ni se añadió una nueva arquitectura para ocultar estos límites.

## Archivos de esta prioridad

Código: `core/ai_related_recommendations.py`, `core/ai_quick_answers.py`,
`core/literary_research.py`, `core/literary_ai.py`, `core/local_llm.py`,
`core/literary_ai_views.py`, `core/ai_answer_cache.py`.

Regresiones: `core/test_conversational_relevance.py`. Instrumentación pública:
`scripts/knowledge/search_narrative_check.py` y `run_directed.py` de este directorio.
Informes y continuidad se conservan en ambos directorios de calidad y en
`reportes/continuidad_opencode.md`. Los cambios anteriores en personajes,
cohesión y español se describen por separado; no se revirtieron ni se mezclan
sus resultados con los de esta prioridad.
