# LitMate — correcciones y ampliación real, 30 de octubre de 2026

Se implementó y ejecutó un lote de ampliación real. **La aceptación funcional completa sigue pendiente**: disponer de más metadatos no garantiza argumentos completos ni elimina los errores semánticos del modelo. No se afirma una tasa de error del 1 %, un p95 conversacional menor a 30 segundos ni respuestas generales de tres segundos.

## Datos realmente incorporados

| Medida | Resultado comprobado |
|---|---:|
| Obras Open Library nuevas en MySQL | 1.200 |
| Autores nuevos con identificador oficial | 1.214 |
| Registros bibliográficos nuevos, obras + autores | 2.414 |
| Actualizaciones/conflictos/rechazos en proyección SQL | 0 / 0 / 0 |
| Obras con autor resuelto mediante el volcado Authors | 1.200/1.200 |
| Obras cuyo registro original incluye descripción | 92/1.200 (7,67 %) |
| Descripciones con puntero local verificado, consultables sin API | 74 |
| Descripciones Open Library copiadas a MySQL/memoria como texto permanente | 0 |
| Obras nuevas con trama desarrollada independientemente verificada | No se deduce del catálogo |

Las primeras 200 obras fueron importadas antes de añadir punteros por registro. Sus 18 descripciones requieren el detalle API o una actualización futura del puntero mediante el mismo importador. No se inventaron licencias ni se marcaron como CC0 todas las descripciones: [Open Library advierte sobre derechos preexistentes de las contribuciones](https://openlibrary.org/developers/licensing).

En el conjunto narrativo final de **17 obras existentes**, comparado con el respaldo inicial:

- Obras con pasaje explícito de argumento: **8 → 12**.
- Obras con descripción admitida: **10 → 12**.
- Obras con pasajes de desarrollo: **0 → 10**.
- Hechos narrativos literales registrados: **12 → 28**.
- Personajes con roles: **81 → 81**; relaciones: **2 → 2**. No se atribuyen los cinco personajes de Emma del lote anterior a esta ejecución.

Las cuatro obras que ganaron evidencia de argumento son The Time Machine, Little Women, Nana y El Señor de los Anillos. Son **pasajes publicados**, no cuatro tramas completas corroboradas independientemente. Little Women sigue teniendo una explicación demasiado breve; algunos pasajes de Time Machine y Nana carecen de transiciones suficientes. Ver `cobertura_cierre17.json` y `enriquecimiento_*.json`. La medición anterior de 16 obras queda preservada en `cobertura_final.json`.

El lote adicional de Tolkien guardó una fuente y un hecho, sin llamadas al LLM: 5,345 s totales, 1,406 s CPU y pico del proceso de 121,672 MiB. `plot_development` quedó deferred porque una premisa no satisface desarrollo profundo. No se reiniciaron intentos ni se marcó como completo lo que no lo está. La primera invocación con pausa 0 se rechazó antes de crear tareas; se ejecutó con el mínimo permitido de 1 segundo.

## Volcados descargados y procesamiento

Se siguieron los enlaces de la [documentación oficial](https://openlibrary.org/developers/dumps), que en esta ejecución apuntaron a la versión **2026-09-30**. El listado oficial de Archive.org se conserva en `archivos_oficiales.json`.

| Archivo en `data/adquisicion/openlibrary/` | Bytes | SHA1 oficial comprobado |
|---|---:|---|
| `ol_dump_works_2026-09-30.txt.gz` | 4.073.320.823 | `b5492661c5ce6d62aae87e1c14945d22826ee26b` |
| `ol_dump_authors_2026-09-30.txt.gz` | 782.352.949 | `9e72c055725af370110c5c7def69fc4428b8e4ca` |

Total comprimido: **4.855.673.772 bytes**, aproximadamente 4,52 GiB. También se calcularon SHA256, conservados en los recibos `.verified.json`. Descargas reanudables HTTPS con `.part`, límite de velocidad y validación antes de publicar. No se descargaron Editions completo, historial mundial, Wikipedia completa ni textos de libros.

- Works: **10.212 registros examinados**, 1.200 admitidos, 80 rechazados por forma/tipo y 8.932 filtrados por selección temática. Cursor descomprimido **5.685.547**, no final del archivo.
- Authors: dos recorridos completos, **15.446.415 líneas cada uno**, seleccionando únicamente dependencias de las obras. 1.214 autores únicos incorporados; el segundo recorrido detectó **207 duplicados**. No son 30 millones de autores nuevos.
- Piloto: 200 obras + 207 autores; lote siguiente: 1.000 obras + 1.007 autores adicionales. Ambas proyecciones SQL terminaron completas y sin conflictos.
- Ledger: `data/adquisicion/ol_20260930.sqlite3`, **3.821.568 bytes**, 2.414 registros, sin pendientes ni registros staged. Conserva filtros, checksum, cursores y outbox existentes.
- Muestreo bibliográfico determinista de 120 obras: **120/120 recuperan el autor esperado en MySQL**, cero respuestas de autoría equivocadas en esa muestra. Memoria top 5: **119/120**; falta una transliteración con caracteres combinados. No es una evaluación de exactitud narrativa universal.

No se continuó hacia 10.000 obras: la disponibilidad descriptiva del lote es baja y las fuentes externas siguen siendo inestables. Antes de aumentar metadatos otra vez conviene priorizar obras incompletas ya consultadas y medir cobertura útil. Los volcados completos quedan disponibles sin necesidad de descargarlos de nuevo.

## Causas corregidas y código

| Archivo | Cambio |
|---|---|
| `core/ai_narrative_answers.py` | Tercer ordinal; ordinal inexistente pide aclaración; consultas con iniciales del autor; encabezados título/subtítulo; recuperación de memoria por identidad y tarea; acceso local a descripciones; extracción sin biografía ni fragmentos cortados; comparación con evidencia de ambas obras y limitaciones explícitas. Se comprueban ambas coberturas antes de generar nuevas descripciones para comparar. |
| `core/ai_character_answers.py` | Un encabezado bibliográfico histórico no se convierte en personaje de la obra anterior. |
| `core/literary_identity.py` | Expansiones de iniciales declaradas por catálogo; traducciones publicadas con licencia/revisión; calificadores de autor; ordinales ligados a la última recomendación sin tomar una posición de listas anteriores. No se infieren identidades por apellido solamente. |
| `core/literary_search.py` | Descarta desambiguaciones también en el fallback exacto de Wikipedia; comprueba autor antes de gastar la lectura; conserva el título traducido documentado; preserva varias oraciones de la premisa; usa detalle local verificado antes del HTTP. |
| `core/literary_acquisition.py` | Selección acotada de IDs de autores en streaming; checkpoints eficientes; procedencia con offset/longitud/hash por registro; registro del volcado en metadatos existentes; lector local acotado a 64 MiB y 1,5 segundos. No hay segunda base de conocimiento paralela. |
| `core/literary_ai.py`, `core/ai_quick_answers.py` | «Otro libro» conserva cantidad uno en respaldos; «ya leí ese» excluye recomendaciones previas. |
| `core/literary_conversation.py`, `core/literary_ai_views.py` | Continúan el tema en solicitudes de alternativas explicables y conectan la comparación con el backend existente. |
| `core/literary_quality.py` | Rechaza una inversión explícita de la persona capturada aunque el auditor cite un fragmento literal. Es un control limitado, no un verificador universal de acontecimientos. |
| `core/test_completion_batch.py`, `core/test_literary_acquisition.py` | Regresiones sintéticas de identidad, contexto, extracción, descargas, punteros y auditoría. |
| `scripts/knowledge/download_openlibrary.py` | Descarga oficial reanudable y verificable. |
| `scripts/knowledge/import_openlibrary_batch.py` | Orquesta el importador/proyector existentes y verifica conservación de filas antes/después. |
| `scripts/knowledge/verify_openlibrary_batch.py` | Auditoría local, recuperación de muestra, integridad y respaldo final. Versiones sustituidas sólo se aceptan si el hecho y pasaje originales siguen exactamente archivados. |
| `scripts/knowledge/search_narrative_check.py` | La modalidad offline bloquea conexiones y resolución de destinos públicos; permite sólo HTTP/SSE, MySQL y Ollama locales. Las banderas de proveedores por sí solas no eran una demostración suficiente de funcionamiento sin Internet. |
| `reportes/continuidad_opencode.md` | Checkpoints y cierre verificables. |

Se conservaron los cambios previos de `genre_recommendations.py`, `test_chat_deadline.py` y `_content` de `ai_narrative_answers.py`. No se modificaron tarjetas, avatares, voz, plantillas, colores, `.env`, credenciales ni arranque.

## Conversaciones reales y límites observados

HTTP/SSE real contra el backend existente, MySQL local y Ollama. Los ensayos usan copias de memoria y runtime para no convertir respuestas del benchmark en conocimiento público.

| Caso | Antes / fallo observado | Después comprobado |
|---|---|---|
| Novela nueva The jade cabinet | Con memoria inicial y **red pública bloqueada**: unavailable, 0,800 s | Memoria actual, proceso nuevo y red pública bloqueada: explicación en español, **19,309 s**, usando el registro local verificado. Autoría independiente: Rikki Ducornet, 0,200 s en el ensayo anterior. |
| Emma | Argumento persistido no recuperado; unavailable, 0,571 s | Recuperación por identidad/tarea: respuesta literal en español, **0,790 s**, sin red. Se retiró además un fragmento que comenzaba a mitad de oración. |
| The Time Machine | Snapshot inicial: unavailable, 0,638 s; con autor abreviado se desviaba al pipeline lento | Con argumento nuevo: **0,722 s sin red**. Las iniciales ya no se interpretan como varias preguntas. La explicación aún puede resultar fragmentaria. |
| Papelucho y el marciano | Conserva la evidencia editorial existente | Personajes y roles: **0,220 s sin red**. No se atribuye como contenido nuevo. |
| Little Women | Conocimiento previo en inglés: 17,096 s | Pasaje español: 0,629 s; **insuficientemente profundo**, no se considera una trama completa mejorada. |
| Nana | Snapshot inicial: unavailable, 0,415 s | Pasaje español: 0,362 s; fidelidad a la fuente, sin corroboración independiente de cada detalle. |
| «Otro libro que puedas explicarme» | Devolvía tres | Una opción, tema conservado; **27,317 s** en una conversación real. |
| «Ya leí ese» | Repetía opciones anteriores | Siguiente lista excluye las obras anteriores, **0,401 s** en esa conversación. |
| Segundo/tercero de lista con una sola obra | Repetía erróneamente el primer libro | **Aclaración en 0,498 / 0,373 s**, sin inventar posiciones. Comparación de esa lista: aclaración en 0,040 s. |
| Comparación de dos recomendaciones con evidencia desigual | Caía al pipeline pesado y llegó a generar un error de atribución; 31–35 s | Último ensayo: unavailable honesto en **6,251 s**, sin nueva trama generada cuando faltaba contenido de una obra. Comparaciones de dos pasajes españoles y comparación parcial: regresiones aprobadas; no se acredita una comparación literaria compleja completa en vivo. |
| Tercer libro real en lista de tres | No interpretaba «Explícame el tercer libro» | Identificó Escritos fundacionales correctamente; explicación parcial, **15,883 s**. No significa que siempre pueda recuperarlo: otras rondas fallaron por proveedores. |
| Inca y quechua | Llegó a tratarlo como personaje del libro anterior | Ruta bibliográfica correcta; último ensayo **unavailable, 6,272 s**. Sigue sin contenido suficiente del volumen exacto. |
| Historias paralelas | Homónimos | Solicita elegir autor entre candidatos reales. No se cuenta una aclaración como explicación exitosa. |
| The Unfinished Nation | Sólo metadatos; editorial no accesible | Sigue sin descripción suficiente. No se inventó su contenido. |
| El Señor de los Anillos | Local: personajes disponibles pero argumento no recuperable | Tras el lote adicional: premisa de Frodo, el Anillo y Sauron en español, **0,840 s sin red pública**, 0 LLM. Sigue sin desarrollo profundo. `tolkien_offline_cierre.json`. |

Artefactos prioritarios: `jade_antes_red_bloqueada.json`, `offline_final_red_bloqueada.json`, `tolkien_offline_cierre.json`, `continuidad_cierre_http.json`, `peru_tres_final.json`, `comparacion_http_final.json`.

**No usar `jade_antes_offline.json` como baseline offline**: todavía permitía una consulta auxiliar externa. Se conservó para mostrar el fallo del instrumento y se repitió con red bloqueada.

Se detectaron dos inversiones de papeles en respuestas auditadas sobre The Last Days of the Incas. La inversión explícita del cautivo tiene regresión correctiva; el control no cubre toda relación de persecución, huida o fundación. La comparación final evita generar una explicación nueva cuando falta una de las dos evidencias. **Sigue pendiente reforzar la atribución semántica general y volver a medirla; HTTP 200/answered no se considera evidencia de verdad.**

## Fuentes, búsqueda, RAG y rendimiento

- Open Library: dumps oficiales completos, proyección selectiva; API con fallos intermitentes. Lectura local no necesita ese servicio.
- Wikipedia/Wikimedia: pasajes selectivos con revisión, vínculo a obra y CC BY-SA 4.0. Se reutilizó `scripts.knowledge.continuous_worker`; no se descargaron enciclopedias completas.
- Project Gutenberg: se conservaron los **11.100 registros SQL previos**; no se repitió importación ni se descargaron libros completos.
- Wikidata: integración existente conservada; **no se acredita un nuevo lote** de entidades durante esta ejecución.
- Google Books: hubo resultados reales útiles y fallos `unavailable`/timeout. La confirmación de ausencia de facturación sólo se activó en procesos autorizados; no se editó `.env` ni se muestra la clave.
- Docker: `litmate-searxng-1` activo y **healthy**, puerto local 127.0.0.1:8080. Dos consultas del adaptador dieron unavailable/empty: un contenedor sano **no demuestra motores externos operativos**. Se conservaron cooldowns y no se evadieron restricciones.
- Recuperación: índices SQL y FTS existentes para el catálogo; indexación narrativa incremental mediante el worker. **No se generaron embeddings completos de los 1.200 libros** ni se reconstruyó RAG.
- Muestra local MySQL de 120 autorías, verificación de cierre: p50 **8,252 ms**, p95 **9,286 ms**; memoria p95 **8,436 ms**. La ronda anterior dio p95 SQL 12,587 ms. Es recuperación/autoría sin LLM ni Internet, no latencia total de chat.
- Importación: Works piloto 8,949 s; Authors piloto 192,446 s; Works siguiente 14,810 s; Authors siguiente 222,128 s; proyecciones SQL 4,124 y 14,549 s, incluyendo comprobaciones del wrapper. Pico del proceso importador aproximadamente **111 MiB**; no representa RAM total de MySQL/Ollama/Docker. No se instrumentó consumo de CPU de todo el equipo.

## Integridad, almacenamiento y pruebas

`integridad_final.json` y la repetición de cierre `integridad_cierre.json` verifican:

- **41 tablas, 46.798 filas** en respaldo final `backups/volcados_20261030_03`; original `backups/volcados_20261030_01`: 37.417 filas. Se conserva además `_02`, anterior al último enriquecimiento. Ninguna fila SQL original se modificó o eliminó; las adiciones son tablas de conocimiento y control.
- Fuentes originales de memoria: **13.431 conservadas activas + 7 versiones originales archivadas exactamente; cero perdidas**.
- Nueve afirmaciones derivadas de argumentos fueron sustituidas por el worker existente. Cada hecho y su pasaje original permanecen exactamente en el snapshot de su fuente; **cero sin archivo verificable**. La primera comprobación, que asumía que todos los hechos seguían activos, se detuvo e investigó esto; no se restauraron hechos antiguos sobre pasajes nuevos ni se descartó el historial.
- `PRAGMA quick_check` aprobado en los almacenes SQLite encontrados y relaciones MySQL comprobadas.
- Memoria SQLite: **61.444.096 → 67.047.424 bytes** durante los lotes bibliográficos. Ledger: 3,82 MB. SQL lógico KB: **107.725.312 bytes** al cerrar la proyección; no confundir con espacio físico de InnoDB.
- Los respaldos `_02` y `_03` incluyen cada uno los volcados y sus recibos, aproximadamente 4,86 GB por copia además de bases e índices. Se conservaron ambos puntos de recuperación; el margen libre posterior se registra en continuidad. No se duplicaron las descargas desde Internet.
- Hash de `.env` idéntico al inicial. Ninguna migración, paquete, API pagada, commit, push o tarea programada permanente.

Pruebas: una ronda amplia dirigida **347 aprobadas / 12,410 s** con SQLite y los nueve almacenes auxiliares temporales; la última ronda tras las correcciones fue **113 aprobadas / 4,590 s**. No sumar esas cifras como pruebas únicas. `core.test_completion_batch` incluye regresiones que fallaron antes de las correcciones. El control de captura conserva abreviaciones explícitas del nombre completo y rechaza apellidos contradictorios. Hubo una invocación fallida por nombre de módulo inexistente y se corrigió la selección; no se cuenta como prueba aprobada. `pruebas_finales.txt` conserva la ronda amplia. La consola PowerShell etiquetó stderr de unittest como `NativeCommandError`, pero el resultado del runner fue `OK`.

## Reanudar sin reiniciar ni descargar otra vez

Ejecutar desde `G:\Proyecto\Litmate` con PowerShell 5.1. Cada script pide la contraseña de MySQL de forma oculta. No escribirla en comandos ni archivos.

```powershell
# Comprobación de datos y recuperación, sin importar.
.\venv\Scripts\python.exe -B -m scripts.knowledge.verify_openlibrary_batch --backup backups/volcados_20261030_01 --output reports/volcados_20261030/verificacion_nueva.json

# Sólo después de evaluar cobertura y recursos: siguiente lote, mismo checkpoint.
.\venv\Scripts\python.exe -B -m scripts.knowledge.import_openlibrary_batch --stage works --backup backups/volcados_20261030_03 --max-records 1000 --output reports/volcados_20261030/works_siguiente.json
.\venv\Scripts\python.exe -B -m scripts.knowledge.import_openlibrary_batch --stage authors --backup backups/volcados_20261030_03 --max-records 10000 --output reports/volcados_20261030/authors_siguiente.json
.\venv\Scripts\python.exe -B -m scripts.knowledge.import_openlibrary_batch --stage project --backup backups/volcados_20261030_03 --max-records 10000 --output reports/volcados_20261030/proyeccion_siguiente.json

# Prueba real sin red pública, manteniendo Ollama/MySQL locales.
.\venv\Scripts\python.exe -B -m scripts.knowledge.search_narrative_check --local-only --output reports/volcados_20261030/chat_nuevo.json --question 'Dime la trama de The jade cabinet de Rikki Ducornet'

# Arranque existente, sin cambiar .env.
.\venv\Scripts\python.exe -B iniciar_mysql_local.py
```

Usar nombres de salida nuevos: los scripts rechazan sobrescribir informes. Ctrl+C conserva checkpoints del importador; una pausa durante verificación mantiene staged sin proyectar. La siguiente ejecución con las mismas rutas, fuente y filtros continúa. No modificar manualmente cursores, leases, filtros ni checksums para forzar un resultado.
