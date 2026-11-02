# Continuación: recuperación y fidelidad narrativa — 2026-10-30

Este documento complementa [el informe A–E](README.md). Conserva los resultados
fallidos y los checkpoints anteriores. No se volvió a importar el catálogo,
descargar volcados ni modificar datos originales durante esta continuación.

## Causas demostradas y correcciones

1. **Artículos del título.** La búsqueda interna encontraba `Odisea`, pero el
   filtro exterior de `search_wikipedia` no consideraba utilizable esa página
   para `La Odisea` y continuaba hacia películas y resultados tangenciales.
   Ahora admite esa diferencia para una página literaria identificada y
   atribuida. No fusiona registros bibliográficos ni infiere alias de sagas.
2. **Referencias a un personaje por su papel.** Existía una relación literal
   creador–ser vivo, pero `la criatura` no coincidía con el nombre del perfil.
   `profile_relationship_answer` resuelve esa referencia únicamente si el
   creador tiene una sola creación viva documentada dentro de la obra vinculada.
   Dos creaciones o un nombre desconocido no se resuelven por conjetura. No se
   guarda `criatura` como alias global ni se programó una respuesta por título.
3. **Autor frente a revista/editorial.** `_identity_author` podía seleccionar el
   último nombre propio de una introducción, incluyendo la revista de
   publicación. Acota primero la atribución antes de las cláusulas de
   publicación, ilustración o traducción y exige un candidato inequívoco.
   Cuando aparecen varios candidatos sin poder resolverlos, conserva el vacío.
4. **Títulos alternativos y declaraciones bibliográficas.** El punto y coma
   `; or,` y las iniciales de autores se interpretaban como preguntas múltiples.
   `sentence_check_text` sólo normaliza el texto de comprobación; el título y
   mensaje originales permanecen intactos. La declaración literaria admite año
   y género antes de `novel`, manteniendo el rechazo de películas/personajes.
5. **Pasajes omitidos.** Se reconoce `Plot summary` en todos los controles de
   resumen. Una premisa inglesa explícita en la introducción llega al auditor
   junto al pasaje argumental; no se confunde con datos editoriales.
6. **Auditoría demasiado permisiva.** Se distinguen falta de respaldo y
   contradicción. Las comprobaciones deterministas rechazan la muerte propia
   de un menor como causa de su orfandad cuando la evidencia dice que mueren sus
   padres. También exigen prueba del parentesco tío/tía concreto y rechazan
   inversiones de género. Se conservan la auditoría estricta y los controles de
   filas, evidencia, identidad, licencia e instrucciones externas.
7. **Desenlace no solicitado.** Una sinopsis rápida retira oraciones que anuncian
   inequívocamente un cierre. Una pregunta explícita por el final utiliza la
   ruta existente para spoilers. No es un detector universal de revelaciones.

## Español sin inventar equivalencias

La API oficial entrega enlaces entre idiomas y el identificador Wikidata.
`_wikipedia_spanish_counterpart` aprovecha una página española sólo cuando ambas
páginas tienen revisión/atribución, comparten identificador y autor, y la página
española aporta contenido para la pregunta. Una lista de personajes no sustituye
una trama. Las lecturas consumen el presupuesto existente; fallar conserva la
fuente inglesa. Se usan endpoints fijos, nunca URLs indicadas dentro del texto.

El último ajuste conserva además un título completo con subtítulo que esté
literalmente publicado en la introducción original. El enlace entre idiomas
aportaba sólo el título corto del artículo, por lo que se perdía esa equivalencia
ya verificable. La prueba conserva introducción, títulos, Wikidata y revisiones;
no acepta una continuación inventada con el mismo prefijo.

Referencias técnicas: [MediaWiki Langlinks](https://www.mediawiki.org/wiki/API:Langlinks)
y [Pageprops](https://www.mediawiki.org/wiki/API:Pageprops).

Se evaluó además extraer oraciones inglesas literalmente y después usar el
traductor y verificador existentes. **Este prototipo permanece desactivado por
defecto**: una ronda inventó una especie de ballena y otra tradujo mal un giro
temporal. La ronda siguiente aún produjo `mano verde` para un modismo inglés.
No se activó una ruta por el mero hecho de que fuese más rápida.

El glosario existente incorpora la equivalencia general `sperm whale → cachalote`,
con [procedencia lexicográfica](https://dictionary.cambridge.org/dictionary/english-spanish/sperm-whale).
No son hechos programados sobre una novela. La versión de caché de traducción
pasa a V5. Sólo pasajes públicos literalmente auditados pueden compartir una
traducción validada; las respuestas privadas o con añadidos no entran allí.
Una traducción narrativa totalmente rechazada ahora informa `unavailable` y no
se recuerda como respuesta aceptada.

La evaluación opcional se ejecuta exclusivamente con `--foreign-literal` en
`search_narrative_check`; no se añadió una bandera a `.env` o a los settings de
producción. Evidencias: `moby_garden_literal_prototipo.json` y
`moby_garden_literal_revision.json`, incluidos sus fallos.

## Conversación real antes y después

MySQL local, HTTP/SSE y contexto compartido entre los seis turnos. Fuentes
actuales copiadas para la evaluación; sin respuestas preparadas ni escrituras
de usuarios. `continuacion_actual_06.json` conserva el resultado previo y
`continuacion_actual_06_corregida.json` la repetición después del arreglo.

| Consulta | Antes | Después | Alcance comprobado |
|---|---:|---:|---|
| Trama de Frankenstein | 0,829 s | 0,824 s | Planteamiento; no argumento completo |
| Sus personajes | 3,948 s | 3,530 s | Un perfil, lista parcial |
| Víctor y la criatura | Abstención, 4,186 s | 0,497 s | Creación y rechazo, con pasajes literales |
| Trama de La Odisea | Abstención, 7,700 s | 3,302 s | Retorno y episodios; cohesión mejorable |
| Sus personajes | 4,493 s | 4,506 s | Un perfil, lista parcial |
| Trama del manga Naruto | 1,019 s | 1,126 s | Premisa y arcos seleccionados |

Estado `answered`: **4/6 → 6/6**; media **3,696 → 2,297 s**, cero llamadas al
modelo en ambas rondas. Ese estado no certifica una explicación completa ni
una exactitud del 100 %. Las listas parciales siguen siendo una limitación.

La última repetición, `continuacion_actual_06_aislada.json`, copia también todos
los almacenes públicos auxiliares e índices: **6/6 answered**, media **2,631 s**,
p50 **2,058 s**, máximo/p95 por rango más próximo **5,683 s**, cero llamadas al
modelo y todos los turnos bajo 30 s. Sólo seis observaciones: no demuestra el
p95 general del sistema. Los proveedores y su latencia varían entre rondas.
Métricas reproducibles en `continuacion_comparacion.json`.

Comprobaciones adicionales independientes:

- *The Wonderful Wizard of Oz*: respuesta española con fuente española,
  **1,789 s**, título de la tarjeta conservado.
- *The Portrait of a Lady*: respuesta española desde la página relacionada,
  **2,653 s**; explicación breve, no argumento desarrollado.
- *The Secret Garden*: las rondas iniciales mostraron atribuciones falsas de
  parentesco pese a auditoría aprobada. La última conversación con snapshot
  inicial (`continuacion_conversacion_07.json`) dio una premisa correcta sobre
  Mary y la muerte de sus padres, **16,139 s / dos inferencias**, sin ese
  parentesco. No se declara resuelta toda posible traducción o síntesis.
- *Moby-Dick; or, The Whale*: el título ya no cae en la ruta de preguntas
  múltiples. Antes de conservar el subtítulo entre idiomas, una ronda tardó
  **26,434 s / dos inferencias** y otra fría fue rechazada en 36,070 s. Después,
  `moby_titulo_publicado_final.json` respondió desde la página española en
  **2,926 s / cero inferencias**, con los originales intactos. La respuesta
  sigue siendo extractiva y contiene redacción histórica de la fuente; no se
  declara resuelta la profundidad o el estilo de todas las tramas.

El snapshot inicial y la memoria actual se probaron por separado. No se cuentan
los nuevos conocimientos de una copia privada como ingesta global. Tampoco se
atribuyen a estas correcciones los resultados históricos de las 22 consultas.

## Pruebas, integridad y archivos

- Aplicación: **2.157 pruebas ejecutadas, 2.156 aprobadas, una omitida**, cero
  errores/fallos; 73,523 s de suite / 75,083 s del proceso medido.
  `tests_core_continuacion_cierre.json`, SQLite y almacenes temporales.
- Después se amplió únicamente el instrumento de pruebas y se añadió su
  regresión de aislamiento: **174 pruebas dirigidas aprobadas / 3,614 s**.
  Finalmente se corrigió la transferencia del subtítulo publicado y se ejecutó
  una batería ampliada de **351 pruebas aprobadas / 8,077 s de suite** sobre los
  componentes afectados (`tests_affected_ultimo_alias.json`). No se suman las
  rondas ni se presenta la batería completa anterior como posterior al último
  ajuste de alias.
- Las regresiones nuevas se ejecutaron antes de sus correcciones y reprodujeron
  los fallos. Incluyen una creación ambigua, nombre no documentado, revista como
  autor, artículos del título, película, Wikidata distinto, parentesco sin
  prueba, encabezados ingleses, traducción rechazada y ausencia de caché privada.
- `continuacion_integridad_final.json`: conteos MySQL iguales en cada turno,
  memoria original sin cambios, SQLite `quick_check=ok`, cero errores FK,
  hashes de todos los almacenes públicos copiados iguales antes/después.
- El RAG vigente tiene **498 documentos, 526 fragmentos, cero vectores**, política
  V3 y revisión 14841 coincidente con la memoria original. Sus **1.658.880 bytes**
  corresponden al punto posterior a la reindexación V3, mientras el antiguo
  `final_integrity.json` registró el punto anterior. Esa diferencia física no
  constituye evidencia de contaminación de fuentes por estas pruebas.
- Se conserva `backups/conocimiento_20261030_01`, completo/verificado, y todos
  los anteriores. No hubo ingesta global adicional en esta continuación.
- `.env` conserva su SHA256 previo; SearXNG sigue healthy, exclusivamente en
  `127.0.0.1:8080`. Sin cambios de Docker, credenciales, dependencias,
  migraciones, tareas automáticas, diseño, voz, avatares, tarjetas, commits o push.

Archivos de aplicación de esta continuación: `core/ai_character_answers.py`,
`core/ai_narrative_answers.py`, `core/literary_ai.py`,
`core/literary_identity.py`, `core/literary_search.py`,
`core/literary_quality.py`, `core/literary_presentation_language.py`,
`core/data/presentation_terminology.json`.
Pruebas/instrumento: `core/test_knowledge_campaign.py`,
`core/test_presentation_language.py`, `scripts/knowledge/search_narrative_check.py`.
Se añaden informes de esta carpeta y continuidad; los demás cambios anteriores
se conservan y no se atribuyen todos a esta continuación.

## Pendiente y siguiente lote

Ampliar listas de personajes con roles respaldados, mejorar cohesión de tramas
extractivas, resolver ediciones/colecciones con identificadores publicados,
evaluar comparaciones y contexto complejo de fantasía y reforzar fidelidad
bilingüe. No se activa la extracción extranjera experimental. No se alcanzaron
ni se demostraron 99 % de precisión, cobertura completa de 100 obras o
superioridad sobre Google.

Los resultados de enriquecimiento (120 candidatas examinadas, 26 identidades
tocadas, 18 tareas completadas, 31 hechos narrativos nuevos bajo política V3 y
13 roles nuevos) permanecen en el informe A–E. No equivalen a 120 obras con
tramas completas. Las relaciones nuevas del lote de datos siguen siendo cero;
el arreglo de recuperación reutiliza una relación existente.

Para reproducir la conversación actual, usar una salida nueva:

```powershell
.\venv\Scripts\python.exe -B -m scripts.knowledge.search_narrative_check --conversation --trace-search --output reports/conocimiento_20261030/comprobacion_posterior_nueva.json
```

Pide la contraseña oculta y no modifica el motor de arranque. Los procesos de
prueba y enriquecimiento de este lote son finitos; no se instaló un trabajador
permanente. El comando de arranque MySQL y los límites/reanudación del trabajador
existente están documentados en el informe principal.
