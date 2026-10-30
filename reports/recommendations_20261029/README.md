# Recomendaciones por género y continuidad — 29/10/2026

Se reprodujeron los cuatro errores originales mediante HTTP/SSE y MySQL local y se corrigieron recuperación, clasificación, identidad y seguimiento. No se reimportó el catálogo ni se cambiaron el modelo, el diseño o el arranque.

## Causas demostradas

1. La ruta anterior buscaba títulos/palabras y podía elegir un único libro por la presencia de «crimen». No aprovechaba la relación `Libro.generos` ni las materias de las 11.100 fichas SQL.
2. Las materias del proveedor no tenían una representación consultable por género. Una palabra en una sinopsis podía llevar a mezclar realismo mágico y fantasía.
3. Las variantes ortográficas de autores impedían reconocer la misma obra aun cuando compartían una referencia bibliográfica primaria. No existía una lista de obras recomendadas que sobreviviera correctamente a todos los seguimientos.
4. «Otro que no sea ese» perdía intención y tema antes de recuperar candidatos.
5. El limpiador de presentación no quitaba un encabezado vacío «Fuentes de las fichas». Algunos enlaces antiguos de Google Books se construían con identificadores locales no verificados.
6. Durante la validación apareció otro defecto general: un punto dentro de un título, por ejemplo «No. 138», dividía la identidad bibliográfica en aparentes afirmaciones narrativas. Se añadió una regresión y se corrigió la segmentación sin quitar afirmaciones de la auditoría.

## Implementación y archivos

| Archivo | Responsabilidad del cambio |
|---|---|
| `core/literary_genres.py` | Taxonomía versionada, equivalencias multilingües, jerarquías y ejes separados de género, formato y público. Sólo clasifica categorías explícitas; conserva los temas originales. |
| `core/bibliographic_repository.py` | `classification_edges`, `index_classifications` y `genre_sources`: proyección aditiva a relaciones existentes, consulta indexada y exclusiones antes del límite. `_sync_indexes` mantiene las categorías al actualizar una ficha. |
| `core/genre_recommendations.py` | Recuperación del M2M local, ranking, diversidad, restricciones, exclusiones y memoria privada acotada. `genre_answer` usa los validadores existentes. |
| `core/literary_identity.py` | `same_work` reconoce variantes con título/alias y referencia primaria compartida, sin fusionar homónimos por similitud textual. |
| `core/literary_conversation.py` | `resolve_topic_context` conserva el género en seguimientos y reconoce cambios explícitos. |
| `core/literary_ai_views.py` | Integra la ruta de catálogo antes de las operaciones costosas y conserva recomendaciones en el mecanismo existente de sesión/historial. |
| `core/literary_quality.py` | `factual_statements` conserva la unidad de un título bibliográfico con puntos; mantiene la auditoría estricta. |
| `core/ai_answer_cache.py` | Nueva versión de política para no reutilizar respuestas anteriores a la corrección. |
| `core/ai_presentation.py` | Tarjetas con enlaces bibliográficos válidos; no fabrica enlaces de volumen a partir de IDs antiguos. Añade enlace de fuente Gutenberg. |
| `core/literary_presentation_language.py`, `static/js/litmate_safe.js` | Retiran el encabezado vacío/histórico solicitado; conservan referencias narrativas y botones. |
| `core/bibliographic_http_probe.py` | Conversación HTTP/SSE reproducible con una misma sesión. |
| `scripts/knowledge/index_genres.py` | Indexación reanudable, respaldo previo, verificación de originales y respaldo posterior. |
| `scripts/knowledge/recommendation_check.py` | Prueba real de conversación y medición SQL con `EXPLAIN`; contraseña oculta. |
| `core/test_genre_recommendations.py`, `verificar_chat_seguro.js` | Regresiones de clasificación, identidad, seguimiento, auditoría, tarjetas, sesiones independientes y SQL. |
| `.gitignore` | Excluye artefactos locales JSON/TXT del benchmark. |

Las preferencias y obras vistas pertenecen a la conversación; no se publican como conocimiento ni se comparten entre usuarios. El registro está acotado a 200 identidades y 20 exclusiones explícitas por tipo. Las consultas con calificadores no soportados conservan la ruta anterior: la ruta rápida no elimina restricciones para obtener resultados.

## MySQL y conservación

- Respaldo previo verificado: `backups/recomendaciones_20261029_01`, 41 tablas, 36.275 filas, 91 archivos.
- Respaldo posterior verificado: `backups/recomendaciones_20261029_02`, 41 tablas, 37.380 filas, 91 archivos.
- Cambio aditivo: **1.104 relaciones derivadas de clasificación y un control de proyección**. Se reutilizan `KBRelation`, su índice B-tree de `target_id` y `KBProjection`. No hay migración de esquema.
- Se comprobaron las claves y huellas de las 36.275 filas originales: no se borraron ni modificaron. Continúan 55 `Libro` y 11.100 fichas `KBRecord`; no se incorporaron títulos nuevos.
- Las categorías originales, proveedor, URL y fechas permanecen en `KBRecord`. La taxonomía es `literary-taxonomy-v1`; el control de proyección registra versión y fecha de indexación. Las respuestas conservan categorías originales y diagnóstico de clasificación para auditoría.
- La clasificación representa **metadatos declarados por la fuente**, no una corroboración independiente del argumento o la portada. No se deduce desde una sinopsis ni se guarda texto generado como evidencia.
- `.env` y el manifiesto de `backups/mysql_preparacion_20261028_03` conservan sus hashes anteriores. SQLite, RAG y copias previas permanecen disponibles. No se instalaron paquetes ni se utilizaron APIs pagadas.

## Cobertura de candidatos

Consulta real de fichas SQL con autor utilizable, sin sumar el catálogo local ni afirmar unicidad canónica entre todos los proveedores:

| Categoría | Candidatos SQL recuperables en la muestra |
|---|---:|
| Crimen | 35 |
| Misterio | 35 |
| Fantasía | 59 |
| Romance | 55 |
| Ciencia ficción | 120 |
| Terror | 23 |
| Ficción histórica | 160, límite de muestra |
| Aventura | 104 |
| Drama | 70 |
| Poesía | 160, límite de muestra |
| Ensayo | 63 |
| Biografía | 11 |
| No ficción | 74 |
| Infantil | 8 |
| Juvenil | 2 |

El M2M local aporta, entre otros, 24 candidatos de fantasía y siete de ciencia ficción; puede haber solapamientos, por lo que no deben sumarse como obras únicas. Fantasía épica/urbana/oscura, thriller, novela negra, crimen psicológico, romance histórico, realismo mágico, manga y novela gráfica tienen representación en la taxonomía pero **ningún candidato verificado en esta muestra SQL/local específica**. No se inventa cobertura para esas etiquetas.

## Conversación real: antes y después

Artefactos completos locales: `antes.json` y `despues_entrega.json`. Se preservan también los intentos intermedios fallidos y sus diagnósticos.

Antes:

| Petición | Resultado | Tiempo |
|---|---|---:|
| Recomiéndame libros de crimen | Sólo Crimen y castigo | 0,3033 s |
| Más libros de crimen | Misma obra con variante de autor | 3,5691 s |
| Otro que no sea ese | Aclaración que pierde el tema | 9,8025 s |
| Libros de fantasía | Cien años de soledad | 0,1536 s |

Después, misma sesión durante diez turnos HTTP/SSE reales contra MySQL:

| Petición | Tarjetas | Tiempo |
|---|---:|---:|
| Recomiéndame libros de crimen | 3 | 0,2950 s |
| Más libros de crimen | 3 nuevas | 0,1701 s |
| Otro que no sea ese | 1 nueva | 0,1477 s |
| Dame diferentes | 3 nuevas | 0,1558 s |
| Ahora de fantasía | 3 | 0,4302 s |
| Más libros de fantasía | 3 nuevas | 0,6326 s |
| Ahora de romance | 3 | 0,2376 s |
| Que no sea de Stephen King | 3 nuevas | 0,4256 s |
| Ya leí ese | 3 nuevas | 0,4420 s |
| No me gustó ninguno | 3 nuevas | 0,4381 s |

Las 28 tarjetas tienen IDs distintos; todos los turnos terminaron en `answered` y evento final SSE. No apareció «Fuentes de las fichas» ni se hicieron llamadas al LLM en esta ruta. Ejemplos iniciales: El código Da Vinci, La sombra del viento y El clavo; el cambio a fantasía recuperó Choque de reyes, El camino de los reyes y El Hobbit. No se utiliza el realismo mágico como sustituto automático.

Mediana de esta muestra: **0,3603 s**; p95 por rango más próximo y máximo: **0,6326 s**. Es un benchmark pequeño de recomendaciones locales, no una promesa para todo el chat ni una medición de error factual inferior al 1 %.

Las pruebas HTTP administrativas usan cookies firmadas y no crean lectores ni historial de producción. La persistencia del backend normal de sesiones Django se probó separadamente con dos clientes, base de pruebas aislada y estado independiente; no se cambió el mecanismo de MySQL de la aplicación.

## Rendimiento SQL

Artefacto: `consultas_mysql.json`, 20 consultas reales por categoría.

| Categoría | SQL por llamada | p50 | p95 |
|---|---:|---:|---:|
| Crimen | 1 | 4,54 ms | 5,22 ms |
| Fantasía | 1 | 6,69 ms | 6,92 ms |
| Romance | 1 | 7,25 ms | 7,59 ms |
| Ciencia ficción | 1 | 11,86 ms | 18,50 ms |

`EXPLAIN`: `KBRelation` usa `ref` sobre `core_kbrelation_target_id_4031cf38`; para crimen examina 35 relaciones. `KBRecord` enlaza por `eq_ref PRIMARY`. No hay recorrido de las 11.100 fichas JSON por mensaje. El catálogo local usa tres consultas con `select_related`/`prefetch_related`; las futuras comprobaciones de padres se agrupan, sin N+1. La recuperación tiene límites de candidatos y exclusiones.

## Pruebas ejecutadas

- **268 pruebas dirigidas aprobadas en 5,835 s**, cierre posterior a los últimos cambios (`pruebas_finales.txt`). Incluyen presentación/idioma, repositorio, identidad, restricciones, contexto, conteo, procedencia, tarjetas y auditoría estricta.
- **234 comprobaciones JavaScript aprobadas** de seguridad, formato, HTTP/SSE, CSRF y voz.
- Regresiones controladas: varios candidatos; 3+3+1 sin repetir; alias de autoridad y homónimos; fantasía/realismo mágico e híbridos; manga/formato/público; exclusiones; ausencia de resultados; metadatos de tarjetas; títulos con puntos; rechazo de auditoría; sesiones independientes; idempotencia y número acotado de consultas SQL.
- No se ejecutó nuevamente la suite completa de todas las funciones del proyecto. Sus incidencias previas ajenas a esta tarea no se declaran resueltas.

Comando reproducible de las pruebas nuevas, sobre SQLite de pruebas:

```powershell
$env:DB_ENGINE='sqlite'
.\venv\Scripts\python.exe -B manage.py test core.test_genre_recommendations core.test_bibliographic_repository --noinput
```

Arranque habitual, sin tocar `.env`:

```powershell
.\venv\Scripts\python.exe -B iniciar_mysql_local.py --http-desarrollo
```

Nueva conversación de comprobación real (introducir contraseña sólo en el prompt oculto; utilizar salida nueva):

```powershell
.\venv\Scripts\python.exe -B -m scripts.knowledge.recommendation_check --after --output reports/recommendations_20261029/nueva_conversacion.json
.\venv\Scripts\python.exe -B -m scripts.knowledge.recommendation_check --sql-only --output reports/recommendations_20261029/nueva_medicion_sql.json
```

El índice de géneros ya está construido; no es necesario repetir la expansión de 11.000 registros ni aplicar migraciones.

## Limitaciones y siguientes tareas

- Falta enriquecer categorías de algunos subgéneros y formatos con fuentes autorizadas. La taxonomía no crea datos inexistentes.
- No hay una autoridad canónica universal entre todas las traducciones, volúmenes y proveedores. Se eliminan variantes con evidencia compartida; las ediciones sin esa vinculación pueden seguir requiriendo reconciliación. No se fusionan por parecido.
- Los metadatos locales heredados no equivalen a verificación independiente. Se conserva el vínculo exacto de portada/ficha y el marcador existente cuando falta imagen; no se inspeccionaron visualmente todas las portadas antiguas contra cada edición.
- Las fichas Gutenberg mayoritariamente carecen de sinopsis/portada; se muestran sin inventar contenido. Continúa la política española de presentación existente para descripciones disponibles.
- Preguntas compuestas, calificadores desconocidos y peticiones interpretativas conservan el pipeline de investigación anterior; no quedan cubiertas por las latencias de este benchmark.
- No se alteraron personalidad, voz, avatares, distribución visual, RAG, credenciales ni configuración de arranque. No se hicieron commits ni push.
