# Reparación literaria: continuación del estado existente

Fecha de trabajo del cliente: 29 de octubre de 2026. Se conservaron todos los cambios anteriores, incluidos documentos reorganizados, archivos sin seguimiento y respaldos. No se reconstruyó el proyecto ni se cambió `.env`.

## Resultado comprobado y límites

La conversación HTTP/SSE original pasó de **dos respuestas y cuatro indisponibilidades** a **seis respuestas**. Las listas de personajes principales siguen siendo **parciales: un personaje confirmado en cada obra**; no equivalen a listas completas. El conjunto independiente conserva dos abstenciones: personajes principales de Dracula y Siddhartha. Este lote no demuestra precisión global del 99 % ni un p95 representativo.

Se mantuvieron las tarjetas, avatares, voz, memoria y recomendaciones. El desplegable «Créditos y licencia» desapareció de las burbujas. La atribución de los artículos mostrados se consulta mediante **Atribuciones**, en el pie general de la página.

## Causas y correcciones

1. **Relación X con Y sin reconocer.** `request_for` en `ai_character_answers.py` no reconocía «Qué relación tiene X con Y». Se preservan ambos participantes y la obra activa, incluida la ruta anterior de relaciones con objetos. El caso real anterior consumía cuatro inferencias y terminaba con `ollama_sin_respuesta_valida`; no se acreditó que existiera una respuesta generada válida rechazada únicamente por falta de catálogo.
2. **Evidencia literal descartada al recortar otra vez.** El adaptador estructural Wikipedia ya elegía pasajes que contenían las pruebas de personajes. Un segundo `relevant_passage` eliminaba algunas. Se conserva el pasaje estructural y se comprueba que cada prueba devuelta esté en él.
3. **Artículos iniciales en títulos.** Las variantes con/sin artículo se usan sólo para descubrir candidatos. No se registran como alias ni se fusionan obras. Siguen vigentes las comprobaciones de autor, forma literaria, saga y adaptación.
4. **Clasificación principal confundida con pertenencia.** Se consultan hasta dos perfiles de nombres ya respaldados, con presupuesto compartido de cuatro segundos. Se admite la definición de un héroe seguida de una oración de sujeto tácito que lo identifica como protagonista de la misma obra. Una oración sobre otro sujeto no puede aportar esa clasificación.
5. **Relación explícita en perfiles.** `literary_entity_facts.py` extrae la relación de creación/vida/experimento cuando el texto publicado identifica a ambos participantes y la obra. Las denominaciones genéricas requieren equivalencias explícitas entrecomilladas en la fuente. Se diferencia autoría de ficción y creador dentro de la historia. Se aplican `validate_draft`, `validate_evidence` y `validate_audit` estrictos.
6. **Fallo técnico después de generar una relación correcta.** Faltaba `character_count` en el diagnóstico; el acceso posterior provocaba `KeyError` y un error SSE. Se agregó el dato y una regresión que reproduce el fallo.
7. **Nueva evidencia sin persistir.** `persist_sources` eliminaba las fichas procedentes de memoria antes de usarlas como anclas para un perfil nuevo. También requería una ficha de catálogo aunque hubiese una identidad literaria verificable en un artículo autorizado. Ahora conserva las anclas, guarda sólo evidencia nueva admitida y no actualiza fechas por releer la caché. No inventa ISBN, edición ni tarjetas a partir de un perfil.
8. **Resumen limitado al inicio de la fuente.** La selección examina el pasaje acotado antes de elegir cinco oraciones. Prioriza panoramas explícitos del desarrollo cuando existen. En Naruto la respuesta incorpora ahora crecimiento y Equipo 7, conservando pruebas literales.
9. **Defectos descubiertos con obras independientes.** Un cuento antepuesto a una novela no es su argumento: se requiere la frontera publicada que inicia la novela. Una lista de materias precedida por título/autor tampoco es sinopsis. Se corrigieron `main_work_plot`, `_task_content`, `source_synopsis` y la ruta rápida.
10. **Biblioteca local deteniendo la búsqueda con índices/créditos.** Se excluyen encabezados aislados de capítulos y páginas de créditos reconocibles. La clasificación de personajes principales no invoca síntesis/auditoría local si el pasaje sólo contiene menciones sin clasificación. Esto evitó dos inferencias infructuosas en el caso independiente medido.
11. **Métricas que perdían inferencias de otro cliente.** Se cuentan los intentos HTTP de inferencia en el scope compartido del turno, incluidos clientes que no producen la respuesta final. Se fusionan y publican sólo contadores; no se registran prompts ni conversaciones privadas.

## Conversación original: antes/después

Una sesión con cookies firmadas, servidor Django local real, MySQL `litmate_db`, transporte SSE y finalización HTTP. Ollama estaba disponible. Las rutas comprobadas resolvieron estas seis consultas sin inferencia. El cuerpo HTTP conserva procedencia para el renderizador; los créditos se presentan fuera de la burbuja.

| Turno | Antes | Cierre | Tiempo antes → después |
| --- | --- | --- | --- |
| Trama de Frankenstein de Mary Shelley | Respondida | Respondida, planteamiento y conflicto | 0,567 → 0,783 s |
| Sus personajes principales | No disponible | Víctor; **parcial** | 5,747 → 0,405 s |
| Relación Víctor/criatura | No disponible, cuatro inferencias | Creador, vida experimental y rechazo respaldados | 35,090 → 0,488 s |
| Trama de La Odisea | No disponible | Regreso de Odiseo y situación en Ítaca | 13,713 → 3,283 s |
| Sus personajes principales | No disponible | Odiseo; **parcial** | 5,262 → 4,209 s |
| Trama del manga Naruto | Respondida con detalles del inicio | Añade desarrollo y compañeros | 2,169 → 2,717 s |

Media de esos seis turnos: **10,425 → 1,981 s**; mediana **5,505 → 1,750 s**. No son un benchmark global. Cambiaron las fuentes disponibles y se realizó enriquecimiento entre mediciones; no se atribuye toda la diferencia a la arquitectura. Durante cada prueba la memoria original y los conteos MySQL permanecieron iguales: el servidor de prueba trabaja con una copia SQLite consistente, cachés temporales y sesiones firmadas.

Artefactos locales: `conversacion_antes.json`, `conversacion_lote_a.json`, `conversacion_lote_a2.json` (incluye el error técnico intermedio), `conversacion_lote_a3.json`, `conversacion_final.json` y `conversacion_cierre.json`. Se conservaron las ejecuciones fallidas.

## Comprobación independiente

Obras distintas de las usadas para desarrollar los primeros arreglos: El principito, Dracula y Siddhartha, con trama y continuación sobre personajes principales.

- El principito: trama breve correcta y un principal confirmado; continúa parcial. La lectura de esa clasificación persistida pasó de 4,111 a 0,497 s.
- Dracula: la primera comprobación devolvía el cuento antepuesto. El cierre recupera el comienzo de la novela, el huésped y su cautiverio; **2,163 s**, sin presentar el cuento como la novela. El resumen sigue concentrado en el inicio, no cubre todo el desarrollo.
- Personajes principales de Dracula: abstención antes y después; **32,330 → 5,971 s**. La ejecución anterior hizo generación y auditoría, aunque su diagnóstico final indicaba erróneamente cero llamadas. El nuevo contador compartido corrige esa pérdida. No se considera este caso resuelto en contenido.
- Siddhartha: antes se mostraban materias del catálogo como argumento; el cierre usa narrativa publicada sobre búsqueda espiritual, Govinda y samanas, **1,034 s**. Los personajes principales siguen sin suficiente clasificación: abstención, **4,895 s**.

Estos resultados corresponden a `independientes_antes.json`, `independientes_despues.json` (fallos intermedios conservados) e `independientes_cierre.json`. No se cuenta `answered` como exactitud factual sin revisar el contenido.

## SearXNG y fuentes reales

No se reinstaló ni recreó Docker. `litmate-searxng-1` funciona mediante JSON en `127.0.0.1:8080`. Se midieron doce solicitudes con consultas detalladas y doce con títulos, cuatro por motor, con pausas y top cinco acotado.

- Wikipedia del metabuscador: **0/4** consultas largas y **4/4** consultas de título devolvieron candidatos. El resultado de Frankenstein por título fue un perfil del monstruo; obtener un resultado no acredita la obra pedida.
- Mwmbl: candidatos en **4/4** consultas de cada variante; hay resultados ajenos a literatura. Se conserva la validación bibliográfica y la lectura segura posterior.
- Open Library: **2/4** consultas largas; la segunda serie alcanzó timeout y suspensión temporal. No se considera una caída de Docker. Se mantiene backoff y la consulta oficial independiente desde Django.
- Para detalles se reutilizan las APIs oficiales Wikipedia de búsqueda, introducción y sección/estructura; los fragmentos de SearXNG siguen siendo descubrimiento, no prueba suficiente por sí solos.

Artefactos: `searx_antes.json`, `searx_identidades.json` y sus agregados de logs. Los contadores heurísticos de descripciones no son exactitud factual. No se copiaron respuestas IA de buscadores, ni se extrajo HTML de Google, ni se agregaron servicios pagos. Referencia de capacidad del motor: [implementación oficial de Wikipedia en SearXNG](https://github.com/searxng/searxng/blob/master/searx/engines/wikipedia.py).

## Conocimiento continuo, MySQL y RAG

Se extendieron la cola, memoria, proyector y trabajador existentes. No se crearon tablas ni migraciones. `main_characters` distingue clasificación de simple pertenencia; el requisito `relationships` exige una relación literal con sujeto, predicado y objeto. Que exista una relación permite cerrar una tarea general de enriquecimiento, pero no acredita cualquier pregunta sobre relaciones: la respuesta al lector mantiene su auditoría específica.

Un perfil conocido puede recuperarse nuevamente desde la API para extraer una relación explícita. No se modifica la fecha de verificación por una lectura de caché. Las tareas incompletas conservan backoff y límites. No se registró ninguna tarea automática de Windows.

MySQL conserva anclas y referencias; los pasajes narrativos permanecen en la memoria auxiliar autorizada y se rehidratan en RAG. `project_references` admite también URLs exactas de fichas vigentes de esa misma identidad cuando cambió la URL preferida. Rechaza uniones por semejanza y más de un ancla candidata. No se prometió una migración de todos los hechos a MySQL.

Piloto: cinco identidades existentes, sin importar libros nuevos: Frankenstein, Siddhartha, Dracula, El principito y Jane Eyre. Dos lotes de hasta cinco tareas y otro de una tarea de relaciones. Hubo **una clasificación principal nueva para Víctor, una para el principito y una relación creador/criatura**. Las etiquetas con roles literales pasaron de **7 a 19** en esas cinco identidades; son etiquetas de personajes, no doce biografías completas ni una reconciliación global de alias. No se incorporaron nuevas tramas verificadas en esos lotes.

Los contadores de la primera ejecución no contaban «personaje principal» como protagonista. Se corrigió la métrica usando el mismo clasificador validado, con regresión. La ejecución de relaciones almacenó la relación pero dejó el trabajo pendiente porque su comprobación pedía además una lista de personajes; también se reprodujo y corrigió ese criterio de parada. Se conserva el informe de ese resultado previo, sin reescribirlo.

| Lote | Tiempo | CPU del proceso | Pico RAM | Cambio del archivo narrativo |
| --- | --- | --- | --- | --- |
| `piloto_01.json` | 22,504 s | 2,656 s | 108,227 MiB | 0 bytes |
| `piloto_02.json` | 21,792 s | 3,016 s | 108,422 MiB | +65.536 bytes |
| `piloto_relaciones.json` | 4,906 s | 1,484 s | 108,828 MiB | +12.288 bytes |

Los tamaños de archivo incluyen reutilización de páginas; no son la suma de texto añadido. El último índice reconstruido declara **492 documentos / 510 fragmentos**, BM25, sin embeddings nuevos. El índice es acotado a un máximo de 500 fuentes y no representa todas las identidades del catálogo. Los lotes añadieron **cero referencias MySQL**: las anclas exactas disponibles no permitieron nuevas asociaciones inequívocas. El checkpoint derivado existente avanzó; se conserva la comparación estricta de las demás filas.

## Presentación y licencias

`static/js/litmate_safe.js::renderMessage` mostraba el desplegable. Ahora registra la atribución únicamente en los nodos de los mensajes mostrados, sin almacenamiento persistente del historial de lectura. `renderAttributions` construye el panel externo desde esos nodos y deduplica URLs. Al redibujar o retirar un mensaje no mantiene atribuciones privadas fuera de esa conversación.

`templates/base.html` añade el enlace general y un diálogo nativo con nombre accesible y botón de cierre. Conserva artículos originales, colaboradores, enlace CC BY-SA y aviso de selección/adaptación. El diseño interno del chat, sus tarjetas y botones no se modificó. La licencia permite atribución en una forma razonable: [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).

## Pruebas y seguridad

Las tres regresiones iniciales se reprodujeron fallando y después pasaron. Las regresiones nuevas cubren el `KeyError`, perfiles épicos, sujeto tácito, otra obra/otro sujeto, autor frente a creador ficticio, negación, sinopsis editorial frente a catálogo, cuento antepuesto, persistencia y perfiles con ficha en caché, conteo de inferencias, clasificación de enriquecimiento y comparación de checkpoints.

Suite general aislada inicial de este lote: **2.017 ejecutadas, OK, una omitida**, 89,546 s. Ejecución posterior: **2.025 ejecutadas, OK, una omitida**, 73,989 s. **Cierre definitivo: 2.026 ejecutadas, 2.025 aprobadas y una omitida, 76,480 s**, sin fallos (`pruebas_definitivas.txt`). Frontend: **246 comprobaciones aprobadas**, incluidas apertura real del manejador del diálogo, formato, XSS/URLs, tarjetas, HTTP/SSE, CSRF y voz. No se realizó una inspección visual en un navegador gráfico.

La comprobación posterior en un proceso nuevo (`verificacion_persistencia.json`) confirmó SQLite `integrity_check=ok`, cero errores de claves foráneas y cuarentena vigente de snapshots excluidos. MySQL conserva **41 tablas / 37.384 filas**; los registros previos se compararon con el respaldo, permitiendo sólo avanzar los campos derivados del checkpoint del trabajador. Sus otras cinco filas de checkpoints y todos los datos bibliográficos/de lectores conservan la comprobación estricta. La cola conserva 14 tareas finalizadas y 40 pendientes. En las cinco identidades del piloto hay **25 fuentes vinculadas, 19 etiquetas con roles, dos protagonistas explícitos y una relación**, con cuatro argumentos ya existentes. RAG rehidrató respectivamente 5/3/3/4/1 fuentes vigentes para las cinco obras. No es una verificación independiente de todos sus hechos.

Respaldo previo verificado: **`backups/integral_20261029_01`**, 41 tablas, 37.384 filas, 92 archivos. Se conservan `backups/continuo_20261029_03` y `backups/mysql_preparacion_20261028_03`. Las pruebas generales usan SQLite y nueve almacenes auxiliares temporales; no ejecutan migraciones sobre MySQL de la aplicación. `.env` conserva SHA256 `1d8e35effc765d26ecb73f3e2ee26c886a1e3d98b1bc45590c356b8604008e74`.

**Respaldo posterior verificado: `backups/integral_20261029_02`**, también 41 tablas / 37.384 filas / 92 archivos. Incluye la memoria enriquecida y el índice; se creó en una carpeta nueva, sin sobrescribir respaldos anteriores.

## Archivos de este lote

- Recuperación y respuestas: `core/ai_character_answers.py`, `core/literary_entity_facts.py`, `core/literary_search.py`, `core/ai_narrative_answers.py`, `core/ai_persistent_router.py`, `core/ai_library_router.py`, `core/literary_identity.py`, `core/ai_quick_answers.py`, `core/books_google.py`.
- Persistencia/enriquecimiento: `core/literary_memory.py`, `core/literary_enrichment.py`, `core/literary_learning.py`, `core/continuous_knowledge.py`, `scripts/knowledge/continuous_worker.py`.
- Mediciones: `core/ai_progress.py`, `core/local_llm.py`, `core/literary_ai_views.py`, `core/bibliographic_http_probe.py`, `scripts/knowledge/search_narrative_check.py`, `scripts/knowledge/audit_search_sources.py`.
- Interfaz: `static/js/litmate_safe.js`, `templates/base.html`, `verificar_chat_seguro.js`.
- Pruebas: `core/test_integral_retrieval.py`, `core/test_continuous_knowledge.py`, `core/test_bibliographic_repository.py`, `core/test_ai_library_router.py`.
- Informes/guía: este archivo, `docs/CONOCIMIENTO_CONTINUO.md`, `reportes/continuidad_opencode.md` y reglas de exclusión de artefactos en `.gitignore`.

## Reproducción

Desde PowerShell en la raíz, sin modificar `.env`, con contraseña introducida sólo en el prompt oculto:

```powershell
.\venv\Scripts\python.exe -B iniciar_mysql_local.py
.\venv\Scripts\python.exe -B -m scripts.knowledge.search_narrative_check --conversation --output reports/integral_20261029/conversacion_nueva.json
.\venv\Scripts\python.exe -B -m scripts.knowledge.audit_search_sources --identity-only --output reports/integral_20261029/searx_nuevo.json
node verificar_chat_seguro.js
```

Cada salida debe tener nombre nuevo. El primer comando conserva el arranque local ya existente; consulta su ayuda para opciones de servidor. Para enriquecimiento manual acotado, consultar la guía `docs/CONOCIMIENTO_CONTINUO.md` y los parámetros nuevos `--requirement`. No se deben ejecutar pruebas de proveedores sintéticos con rutas de memoria de producción.

## Pendientes reales

- Completar las listas de principales de Frankenstein/Odisea sin convertir pertenencia en protagonismo; Dracula y Siddhartha todavía se abstienen en el conjunto independiente.
- Ampliar la cobertura de desarrollo de argumentos: los resúmenes pueden seguir concentrándose en el planteamiento. El nuevo muestreo de panoramas mejora algunos casos, no todos.
- Obtener más fuentes autorizadas y relaciones verificables; el piloto no completó Jane Eyre ni todas las tareas de los otros títulos.
- Extender reconciliación inequívoca entre catálogo SQL y memoria; en este piloto no hubo nuevas referencias MySQL. No existe un grafo narrativo completo centralizado en MySQL.
- Medir un conjunto independiente mucho mayor y múltiples repeticiones para precisión, p95 y variación por red/modelo. No se evaluaron modelos nuevos ni se cambió Qwen.
- La programación diaria de Windows sigue siendo una decisión manual; no se instaló una tarea ni se guardaron credenciales.
