# Piloto de conocimiento continuo verificado — 29 de octubre de 2026

Implementación sobre la cola y memoria narrativa existentes. No se crearon tablas, migraciones, servicios de pago, tareas de Windows, pesos de modelo ni un segundo sistema de conocimiento.

La primera parte del encargo está documentada en `reports/literary_answers_20261029/README.md`. Las instrucciones operativas están en `docs/CONOCIMIENTO_CONTINUO.md`.

## Arquitectura implementada

`remember` → observación de carencia pública conocida → `memory_jobs` → trabajador de un lote → lectores oficiales existentes → identidad/licencia/prueba literal/conflictos → snapshots y FTS/entidades → índice BM25 atómico → referencias opcionales a MySQL.

`memory_jobs` conserva deduplicación, prioridad, estado, intentos, próximo intento, propiedad del lease y fechas de comprobación. Se añadieron cuarentena de trabajos con payload dañado, estados de revisión tras fallos repetidos, reuso de evidencia vigente, backoff persistente, parada por marcador y control de recursos. La observación del chat es auxiliar: un fallo de su SQLite no rompe la conversación.

`memory_usage` conserva sólo señales agregadas por obra, requisito y proveedor. No es entrenamiento ni evidencia de verdad. Las correcciones del lector se registran como pendientes de comprobación, sin guardar su texto ni promoverlo a conocimiento global.

El cursor de selección es persistente y reserva recorrido para obras menos consultadas. Las obras frecuentes reciben prioridad sin eliminar ese recorrido. La selección del piloto no aparece como una regla especial en los procesadores.

MySQL mantiene el catálogo existente y relaciones `memory_evidence` a snapshots admitidos, mediante URL de catálogo exacta. Los roles y pasajes permanecen en el almacén narrativo SQLite, con su procedencia; no se duplicaron pasajes en MySQL ni se afirmó una migración de todos los hechos.

## Piloto real y procedencia

Se escogieron **seis obras que ya existían**: Nana de Émile Zola, Emma, Dracula, Little Women, Siddhartha y Frankenstein. La lista quedó registrada mediante sus IDs en `piloto_01.json`. No se incorporaron títulos nuevos.

El trabajador utilizó los adaptadores existentes de Wikipedia y los trabajos ya pendientes de Wikidata. No usó respuestas de Qwen como evidencia. Open Library y el catálogo autorizado de Gutenberg siguen disponibles en la arquitectura, pero no se presentan como nuevas fuentes narrativas exitosas de este piloto.

Primer lote: **12 tareas reclamadas, tres completadas inicialmente, nueve diferidas, ocho operaciones de almacenamiento y cero llamadas al LLM**. «Ocho almacenamientos» incluye verificaciones/actualizaciones de snapshots existentes; no significa ocho obras o hechos nuevos.

La medición de cobertura de las seis obras pasó de **cero a siete descripciones literales de roles**, distribuidas en tres obras. Las siete etiquetas no equivalen a siete personas distintas: dos corresponden a variantes de Van Helsing. La corrección posterior evita presentarlas como personas diferentes y conserva esa lista como parcial. No se incorporaron nuevos argumentos explícitos ni relaciones entre personajes en este lote.

Datos recuperables del piloto:

- Siddhartha: Govinda, Kamala, Kamaswami y Vasudeva, con roles de la sección publicada.
- Dracula: un papel verificable de Abraham Van Helsing; su mención abreviada no se cuenta como otro personaje en la respuesta.
- Frankenstein: un papel literal de Víctor; el chat puede complementar desde perfiles ya vinculados, pero el trabajador no completó automáticamente una lista exhaustiva.

Fuentes reales con revisión, licencia y atribución conservadas:

- [Siddhartha, novela](https://es.wikipedia.org/wiki/Siddhartha_(novela)).
- [Drácula](https://es.wikipedia.org/wiki/Dr%C3%A1cula).
- [Frankenstein o El moderno Prometeo](https://es.wikipedia.org/wiki/Frankenstein_o_El_moderno_Prometeo).

`verificacion_final.json` registra fuentes, pruebas de roles y rehidratación RAG desde un proceso nuevo. La verificación es de fuente/identidad/licencia/literalidad/cobertura; no es corroboración independiente de cada afirmación mediante varias fuentes.

La reanudación real (`reanudacion.json`) no duplicó referencias MySQL: **cero referencias nuevas**, una tarea resuelta con conocimiento fresco y otra diferida. Se respetaron los tiempos de espera de los trabajos anteriores.

## Respuestas HTTP/SSE antes y después

Se usaron copias de la memoria, cachés nuevas y MySQL local real, con fuentes externas desactivadas para probar reutilización local. La línea base procede del respaldo anterior al piloto.

| Consulta | Antes | Después del cierre |
| --- | --- | --- |
| Personajes de Siddhartha | `unavailable`, 0,3917 s | Cuatro roles, 0,3281 s; cero llamadas al modelo. |
| Personajes de Dracula | `unavailable`, 15,3532 s | Abraham Van Helsing, 0,2573 s; parcial, sin duplicarlo bajo su apellido. |

Evidencia en `chat_antes.json` y `chat_cierre.json`. Un resultado parcial no se contabiliza como lista completa de personajes. Los conteos MySQL y la memoria original permanecieron iguales durante estas pruebas HTTP.

## Recursos y corrección de rendimiento

El primer lote completo demoró **98,839 s**, con **53,609 s de CPU**, pico de RAM del proceso de **108,336 MiB** y aumento inicial del archivo narrativo de **36.864 bytes**. Esto incluye indexación inicial; no es la latencia de una respuesta de chat ni incluye procesos de MySQL/Ollama.

La indexación inicial reveló una consulta correlacionada sobre todo el catálogo. `export_index_sources` pasó a seleccionar el conjunto de fuentes narrativas una sola vez. La regresión con **601 documentos sintéticos y presupuesto de instrucciones SQLite** reproduce la interrupción de la consulta anterior y pasa con la nueva (`regresion_indice.json`).

El índice equivalente de 500 fuentes tardó **1,363 s / 0,859 s de CPU**, leído del almacén real y construido en un destino temporal. La reanudación completa posterior, incluyendo dos tareas y actualización de política del índice, tardó **5,832 s / 1,562 s de CPU**, con pico de RAM de **108,660 MiB**. No son lotes equivalentes para calcular una aceleración global; la mejora comparable es la selección/indexación.

El índice operativo posterior contiene **494 documentos / 510 fragmentos**, sólo BM25. La memoria contiene **13.258 obras**, igual que antes del piloto. No se activaron embeddings nuevos en el chat. Las búsquedas FTS/por identidad existentes siguen siendo la recuperación inmediata; el índice auxiliar también se verificó rehidratando fuentes actuales en otro proceso.

## Integridad y rechazos

- Respaldo previo `backups/continuo_20261029_01`: **41 tablas, 37.380 filas, 91 archivos**, verificado antes de escribir.
- Comparación posterior: **las 37.380 filas SQL anteriores conservan exactamente sus valores y claves**; sólo se añadieron tres `KBRelation` y un control `KBProjection`. Total: **41 tablas / 37.384 filas**. También se comprobó integridad referencial.
- `PRAGMA integrity_check`: **ok**; `foreign_key_check`: **cero errores**.
- Cuatro snapshots de desambiguación detectados, incluidos registros anteriores al piloto, quedan excluidos de recuperación y RAG sin borrarlos. Mencionar a Émile Zola dentro de una lista de homónimos no identifica la novela.
- Proveedores sin resultados, evidencia insuficiente, ausencia de roles, y descripciones inglesas sin sección de argumento no completan falsamente sus tareas.
- Una introducción vigente sin argumento explícito ya no evita que el trabajador intente recuperar esa sección: se corrigió también ese ciclo de reuso insuficiente.
- `.env` y el manifiesto de `backups/mysql_preparacion_20261028_03` conservan sus hashes originales. Los respaldos anteriores permanecen intactos.

Incidente de pruebas documentado en `aislamiento_pruebas.json`: una prueba antigua del endpoint no aislaba la memoria auxiliar y guardó un snapshot sintético de cinco roles con revisión ficticia `1234`. Se identificó por su contenido exacto y ausencia en el respaldo previo; se aisló la prueba y se puso **sólo ese snapshot** en cuarentena técnica. No se borraron fuentes, afirmaciones ni versiones, y las **13.258 identidades originales son idénticas** al respaldo. El registro sintético no se cuenta como conocimiento incorporado. La cuarentena conserva el hash del snapshot y permite una revisión futura legítima con contenido distinto.

El respaldo posterior verificado `backups/continuo_20261029_02` conserva el piloto previo a esa anotación. **Respaldo final verificado: `backups/continuo_20261029_03`, 41 tablas, 37.384 filas y 92 archivos**, incluyendo la memoria, la cuarentena y el índice. Se registra en `respaldo_cierre.json`; no se sobrescribieron los anteriores.

## Pruebas

Se ejecutaron regresiones de cola/persistencia/reinicio, duplicados, dos trabajadores, leases vencidos, corrupción de payload, errores de MySQL, fallo y ausencia de licencia, consulta ambigua, corrección del lector, privacidad, guardas de recursos, actualización RAG y conocimiento utilizable posteriormente. Las suites existentes cubren contradicciones, expiración, identidad de adaptaciones, SSRF y fallos de red. Los casos simulados no se presentan como proveedores reales.

La suite general inicial detectó cuatro expectativas antiguas: tres pruebas del endpoint simulaban la ruta anterior y carecían de la clasificación/licencia que exige la ruta auditada; otra esperaba una consulta vacía al cambiar a ciencia ficción. Se actualizaron las pruebas para comprobar la ruta vigente, la clasificación explícita, atribución, cero inferencia/cuota, separación entre lectores y cambio de género sin heredar arte japonés. No se relajaron los validadores ni se alteró el comportamiento de recomendaciones.

Después de actualizar esos contratos: **2.004 pruebas generales ejecutadas, OK, una omitida**, 72,911 s (`pruebas_generales.txt`). La siguiente suite, con cuarentena e aislamiento, ejecutó 2.005 casos (`pruebas_cierre.txt`). **Cierre definitivo: 2.006 pruebas ejecutadas, 2.005 aprobadas y una omitida, 71,818 s**, incluyendo la regresión de referencias MySQL para trabajos prioritarios fuera del recorrido (`pruebas_finales.txt`). El módulo continuo tiene 24 regresiones dirigidas. Frontend: **242 comprobaciones**, incluyendo tarjetas, voz, seguridad, formato e historial/SSE. La prueba omitida requiere activación explícita de servicios reales; éstos se comprobaron por separado en los informes HTTP del lote. El lanzador PowerShell se validó con el parser de PowerShell; no se ejecutó como tarea de Windows ni se creó una credencial cifrada automáticamente.

## Archivos de este frente

- Nuevo `core/continuous_knowledge.py`: observación, cola, selección incremental, límites y referencias MySQL.
- `core/literary_memory.py`: payloads, leases, finalización, tipos de evidencia, selección eficiente y cuarentena de snapshots.
- `core/literary_learning.py`: reuso, parada, intentos, errores diferenciados y cobertura por requisito.
- `core/literary_enrichment.py`, `core/literary_memory_rag.py`: secciones tipadas y política del índice derivado.
- `core/literary_ai.py`, `core/literary_ai_views.py`: preservación de scopes y registro auxiliar de carencias.
- `litmate_project/ai_settings.py`: interruptor de observación, sin editar `.env`.
- `core/management/commands/actualizar_conocimiento.py`: modo continuo de un lote, conservando los modos anteriores.
- Nuevos `scripts/knowledge/continuous_worker.py` y `scripts/windows/enrich_once.ps1`.
- `core/test_continuous_knowledge.py`, `core/test_literary_memory.py`, `core/test_ai_public_details.py`, `core/test_literary_conversation.py`.
- Documentación, informes, herramienta de prueba HTTP, `.gitignore` y continuidad.

## Pendientes

No se instaló una tarea de Windows ni se guardó una credencial DPAPI automáticamente. Para uso diario debes decidir programarla y crear la credencial cifrada localmente según la guía.

Nana de Zola, Little Women y Emma continúan con cobertura narrativa insuficiente en las tareas verificadas; no se afirmó completar esos requisitos. Dracula conserva cobertura parcial. Debe ampliarse la extracción multilingüe y la recuperación desde perfiles vinculados, manteniendo atribución e identidad. Las tareas agotadas requieren revisión; no existe un rastreo ilimitado que vuelva a intentarlas permanentemente.

No se evaluó precisión global del 99 %, un p95 representativo ni un entrenamiento nuevo. Los resultados son un piloto medido y reanudable con límites conservadores.
