# Contenido de recomendaciones y ampliación controlada — 30-10-2026

## Cambios comprobados

- `core/books_google.py`: conserva el título/subtítulo publicado como alias del mismo volumen; separa etiquetas de responsabilidad de los nombres sin borrar su procedencia. El ranking prioriza contenido utilizable entre resultados temáticamente pertinentes. Publicidad extensa, materias y snippets no equivalen a sinopsis. Conserva los errores tipados del lector HTTP y pausa una cuota rechazada.
- `core/ai_narrative_answers.py`: acepta contenidos documentales y actas; evita que las primeras 24 fichas del historial expulsen descripciones nuevas; mantiene la identidad del lector de páginas. Busca identidades con operadores bibliográficos, amplía consultas acotadamente, deduplica páginas y sintetiza descripciones breves con varios datos, con auditoría y fallback literal limitado.
- `core/literary_web.py`: recupera título, autor e índice explícitos de tablas de catálogo. No mezcla tablas ni descarga capítulos.
- `core/literary_conversation.py`, `core/genre_recommendations.py`: conserva el tema al pedir otro libro explicable y comparte la prioridad por contenido. Los ordinales conservan la tarea previa, incluyendo turnos auxiliares de foco y solicitudes fallidas; un ordinal nuevo no reutiliza la identidad pendiente anterior.
- `core/ai_character_answers.py`: separa «del autor/de la autora» del título y conserva el filtro de autor para evitar homónimos.
- El mensaje solicitado para información insuficiente sólo se usa tras agotar la recuperación sin fallo técnico. Sólo menciona sitios de venta cuando hubo una ficha anterior identificada. Los errores técnicos mantienen un mensaje temporal y códigos internos.

## SearXNG y páginas

Se conservan Wikipedia, Open Library y Mwmbl. Se evaluaron DuckDuckGo y Qwant; DuckDuckGo queda habilitado y Qwant desactivado por rechazos reiterados. Django tiene una ruta web separada de los motores bibliográficos y pausas por motor. Un CAPTCHA también pausa el fallback directo del mismo proveedor: no se prueban endpoints alternativos para evadirlo.

`motores_20261030.json`: historia 1,980 s; ensayo 0,778 s; novela 0,777 s; manga 0,992 s. Hubo resultados de DuckDuckGo/Mwmbl/Wikipedia y de Open Library según la consulta; Qwant rechazó las cuatro. DuckDuckGo también presentó CAPTCHA en otras ejecuciones: **no se considera un proveedor permanentemente reparado**. Los cinco hits de una búsqueda no prueban cobertura narrativa.

El motor local Open Library pide cinco resultados y menos campos, evitando listas extensas de ISBN/fechas de todas las ediciones. Siete regresiones se ejecutaron dentro de la imagen fijada. No se aumentaron todos los timeouts, falsificaron cabeceras de proxy ni eludieron CAPTCHA/robots. El puerto sigue limitado a `127.0.0.1:8080`.

La lectura de páginas utiliza las protecciones existentes DNS/TLS/SSRF, robots, límites y datos no confiables. La biblioteca UNS devolvió `robots_unavailable`: no se forzó el acceso. El control *El infinito en un junco* recuperó una página de su autora y la rechazó para explicar el libro. No se declara extracción narrativa exitosa por encontrar una biografía o un snippet.

## Datos realmente incorporados

- Respaldo previo verificado: `backups/contenido_20261030_01`, 41 tablas, 37.393 filas y 92 archivos. Respaldo intermedio `_02`: 41 tablas, 37.393 filas, 93 archivos.
- Piloto continuo existente: cinco obras, diez tareas; una completada y nueve diferidas; 46,190 s totales, CPU 3,625 s, pico del proceso 109,117 MiB, cero llamadas LLM. **Cinco personajes con roles nuevos para Emma; cero nuevas tramas desarrolladas, cero nuevas descripciones y cero relaciones nuevas.** Tres operaciones de almacenamiento no significan tres hechos nuevos.
- Open Library: dos consultas pequeñas autorizadas, reutilizando `adquirir_literatura`, admitieron cuatro registros bibliográficos en el ledger `data/adquisicion/contenido_20261030.sqlite3`. Tres llegaron de una consulta temática: Prescott y dos títulos introductorios sobre Perú; una consulta posterior con operadores identificó la colección de César Toro Montalvo. **La colección no se presenta como el contenido de su volumen Inca y quechua.**
- Proyección real MySQL: 3 + 1 registros insertados, cero conflictos/rechazos; cursor 0→3→4. Las 41 tablas originales se verificaron con el auditor aditivo existente. SQL almacena metadatos; los roles y pasajes siguen en memoria/RAG existentes.
- Dos fuentes se actualizaron (metadatos de Prescott y personajes de Emma); sus versiones anteriores están archivadas exactamente en `memory_history`. El auditor de inmutabilidad estricta señaló esas actualizaciones; se conservaron sus resultados y se comprobó el historial, sin relajar ese auditor.
- El catálogo Gutenberg existente ya había alimentado 11.100 registros SQL antes de esta tarea. No se volvió a descargar ni importar. **No se descargaron volcados completos de Open Library, Wikipedia ni Wikidata.** Las APIs selectivas no se anuncian como volcados. El Works de ~4,07 GB, Authors y Editions no resolverían por sí solos las sinopsis ausentes; no se justificó una descarga masiva para este fallo. Se conserva el importador comprimido con checkpoints existente.

Fuentes oficiales evaluadas: [Open Library](https://openlibrary.org/developers/dumps), [catálogos Gutenberg](https://www.gutenberg.org/ebooks/offline_catalogs.html), [Wikidata](https://www.wikidata.org/wiki/Wikidata:Database_download), [Wikimedia](https://dumps.wikimedia.org/). Se mantiene recuperación selectiva con licencias; no se incorporaron biografías/descripciones OL como si fueran CC0.

## Conversaciones y límites

`conversacion_antes.json`: recomendaciones en 13,194 s y tres abstenciones en 7,098 / 5,187 / 5,171 s. La lista real obtenida fue distinta de la lista original del usuario; incluía una obra teatral que el filtro nuevo excluye.

`conversacion_despues_lote03.json`: *Escritos fundacionales* respondió con contenido editorial auditado en 13,409 s y *Historias paralelas* en 12,488 s; *Inca y quechua* siguió sin respuesta suficiente. No se cuentan como una mejora de velocidad las abstenciones rápidas. Otra ronda (`aceptacion_20261030.json`) sufrió fallos técnicos de Google Books y no reprodujo esos dos éxitos: **la cobertura externa sigue siendo intermitente**.

La ronda larga detectó y motivó las correcciones de ordinales, tarea pendiente y continuidad temática. También dejó pendiente la comparación compleja de dos recomendaciones. No se publica una tasa de exactitud ni un p95 global con esta muestra.

Control de conocimiento persistente, mismo código y sin Internet: `emma_local_antes_controlado.json` no respondió (0,495 s); `emma_local_despues.json` devolvió cinco personajes y roles respaldados (0,497 s, cero llamadas LLM), en un proceso nuevo. No se utilizó una respuesta preparada para el benchmark.

Pruebas: `pruebas_finales_20261030.txt`, **516 aprobadas**, SQLite Django y nueve almacenes auxiliares temporales. Tras las correcciones posteriores se ejecutaron las regresiones de memoria/ordinales y proveedor; sus resultados deben leerse por lote, no sumarse como pruebas únicas.

## Operación

Arranque existente, sin modificar `.env`:

```powershell
.\venv\Scripts\python.exe -B iniciar_mysql_local.py --http-desarrollo --google-books-sin-facturacion
```

El trabajador incremental sigue disponible en `scripts.knowledge.continuous_worker` y `actualizar_conocimiento --continuous`. No se creó una tarea de Windows. Sus estados y backoff permiten continuar en otra ejecución; no se fuerzan reintentos de las nueve tareas diferidas.

Pendientes: recuperación suficiente del volumen *Inca y quechua*, estabilidad externa de Google/DuckDuckGo, explicaciones completas de todas las recomendaciones, comparación compleja y ampliación narrativa de las cuatro obras del piloto sin nueva cobertura. No se debe escalar a miles de obras contando únicamente metadatos.

## Cierre de verificaciones

- `ordinal_http_corregido_20261030.json`: «¿Y el segundo?» conservó *The Last Days of the Incas*, llegó al motor narrativo y usó **cero llamadas LLM, 5,331 s**. No generó una nueva lista ni cambió de libro; **no respondió su contenido** por fallo técnico de fuentes. La ronda anterior había gastado 35,063 s y devuelto recomendaciones ajenas. Conteos SQL y hash de la memoria original intactos durante esta comprobación.
- Última ronda posterior a las correcciones: **241 pruebas dirigidas aprobadas en 10,880 s**. La revisión amplia anterior pasó 516; no se suman como pruebas únicas. Frontend: **246 comprobaciones aprobadas**. Motor SearXNG: **7 aprobadas** dentro del contenedor.
- Una clave interna `sqlkb:` ya no oculta el `/works/OL…W` oficial al recuperar descripciones/ediciones: se consulta el identificador externo y se conserva el interno. Regresión sintética previa falló y después pasó. Los índices de capítulos de novelas no se consideran una trama suficiente.
- Repetición del proyector: **cuatro duplicados, cero inserciones/actualizaciones**, cursor final 4. No se perdió ni se retrocedió un checkpoint. El primer intento con cuota SQL de 4 MiB no admitió registros, porque la cuota incluye los ~84 MiB existentes. La proyección efectiva utilizó el auditor aditivo de expansión, sin relajar el verificador estricto de migración.
- `integridad_final_20261030.json`: memoria íntegra, cero errores FK, cero fuentes/afirmaciones/historial originales ausentes. Fuentes 13.431→13.434; dos cambios de contenido archivados exactamente y dos renovaciones de fechas. Ninguna afirmación original cambió. Memoria conserva su tamaño físico; ledger nuevo 73.728 bytes, índice existente −4.096 bytes; SQL lógico +30.254 bytes (no equivale al tamaño físico InnoDB). Disco libre >100 GiB. `.env` conserva su SHA256 original.
- Docker reiniciado sólo para aplicar su configuración; `/config` confirma Wikipedia/Open Library/Mwmbl/DuckDuckGo activos y Qwant desactivado. `healthy` y puerto exclusivo localhost comprobados. No tarea programada instalada, sin migraciones, paquetes, commits, push ni cambios de interfaz.
- Respaldo posterior `backups/contenido_20261030_03` **terminado y verificado: 41 tablas, 37.407 filas y 93 archivos**. Se conservan los anteriores y el respaldo de la migración inicial.
- `catalogo_nuevo_http_20261030.json`: una nueva sesión HTTP, sin Internet, recuperó la autoría de la colección de César Toro Montalvo en **0,355 s**, usando la ficha OL recién incorporada. Esto verifica recuperación bibliográfica, no una sinopsis del volumen.
- Después de la última revisión del cooldown de Google (incluyendo el lector inyectado por el catálogo), **105 pruebas del proveedor y las regresiones nuevas aprobadas en 3,325 s**. No hubo cambios de código posteriores.
