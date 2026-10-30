# Enriquecimiento narrativo — 28 de octubre de 2026

Trabajo realizado sobre los almacenes reales, sin importar títulos nuevos,
reimportar el catálogo, modificar `.env`, ejecutar migraciones o cambiar Qwen.
Se reutilizan memoria, cola, proveedores, extracción, índices y auditoría.

## Cobertura antes y después

Medición final con el mismo código sobre el respaldo PREVIO y la memoria actual.
`metricas_entrega.json` distingue una sinopsis parcial de una descripción,
una mención de personaje de un rol, y comprobación documental de corroboración
independiente. No se cuentan etiquetas generadas por un LLM como hechos.

| Medida | Antes | Después |
|---|---:|---:|
| Pares título/autor en memoria | 13.250 | 13.250 |
| Registros estructurados en MySQL | 11.100 | 11.100 |
| Pasajes de trama explícitos, por obra | 0 | 8 |
| Obras con descripción narrativa admitida | 6 | 13 |
| Personajes con roles literales, por obra/personaje | 25 | 49 |
| Obras con esos roles | 2 | 4 |
| Obras con protagonista explícito | 1 | 2 |
| Menciones explícitas de protagonista | 2 | 3 |
| Personajes con sólo pertenencia, sin rol útil | 12 | 11 |
| Relaciones literales respaldadas | 0 | 1 |
| Anotaciones narrativas explícitas | 0 | 11 |
| Fuentes vigentes vinculadas | 13.383 | 13.408 |
| Conflictos abiertos detectados | 0 | 0 |

Las ocho tramas son **pasajes parciales de secciones de argumento**, no sinopsis
editoriales completas ni conocimiento de todos los capítulos. Las once anotaciones
incluyen ocho de trama, dos de acontecimientos y una relación; no son once
corroboraciones independientes. Los nombres se cuentan dentro de su obra.
Las 24 vinculaciones nuevas con roles no equivalen a crear 24 entidades físicas:
algunas ya existían como menciones o registros sin evidencia literal utilizable.

Los informes antiguos contaban 7 descripciones y 37 personajes; incluían una
descripción de pertenencia Wikidata y personajes sin roles narrativos. El primer
reporte del piloto contaba roles sin revalidar sus pasajes. Se conservó ese archivo;
las cifras finales anteriores revalidan ambos lados contra evidencia literal y
separan pertenencia. No se presenta un cambio de métrica como crecimiento real.

## Almacenes y conservación

- MySQL: 55 `Libro`, 11.100 `KBRecord` y sus índices/versiones. Las 55 fichas tienen
  sinopsis no vacía, pero esa presencia no demuestra derechos, procedencia o
  verificación. El repositorio Gutenberg sigue siendo de metadatos. No se le
  añadieron columnas narrativas ni se trasladó el conocimiento SQLite a MySQL.
- Memoria SQLite: nuevas fuentes, hechos y entidades con work ID, URL, hash,
  licencia, revisión cuando existe y fechas. Es el almacén que se enriqueció.
- Conocimiento local: 4 obras y 5 hechos; índice previo con 4 documentos/vectores.
- Biblioteca autorizada: 12 originales y 561 capítulos; índice bibliotecario con
  12 documentos, 11.289 fragmentos y vectores. **No se descargaron más originales**.
- Se compararon lógicamente todas las filas de los cuatro SQLite/índices previos:
  sin cambios. No comparar sólo hashes binarios de snapshots SQLite: el backup
  online puede cambiar cabeceras. Evidencia: `indices_integridad.json`.
- MySQL conserva **las 36.275 filas originales**. Las fuentes y afirmaciones
  originales de memoria siguen intactas. Tres registros de obra actualizaron
  metadatos: un campo `year` vacío quedó omitido y dos cambiaron su referencia
  principal a una entidad Wikidata admitida; las fuentes anteriores se conservaron.
  Otros 24 registros de entidad ganaron enlaces de evidencia sin perder campos
  anteriores. El auditor permite esos enriquecimientos, rechaza pérdida de IDs,
  modificación de hechos, fuentes sin respaldo y eliminación de atributos.

Respaldos completos verificados: `backups/narrativo_20261028_01` y `_02`, ambos
con **41 tablas, 36.275 filas y 91 archivos**, incluyendo snapshots auxiliares
y SQLite portable. No se modificó el respaldo `mysql_preparacion_20261028_03`.

## Selección y resultado por obra

Piloto de **17 obras ya presentes**; **10** recibieron fuentes nuevas.

| Obra existente | Aportación o límite observado |
|---|---|
| Orgullo y prejuicio — Jane Austen | Trama, roles, protagonista y relación literal |
| Dune — Frank Herbert | Trama y evidencia de personajes reutilizable |
| Rayuela — Julio Cortázar | Trama y roles literales |
| El principito — Antoine de Saint-Exupéry | Trama; Wikidata no prueba roles |
| Frankenstein — Mary Shelley | Trama; personajes pendientes |
| Emma — Jane Austen | Trama |
| Dracula — Bram Stoker | Trama |
| Siddhartha — Hermann Hesse | Trama |
| Nana — Émile Zola | Descripción admitida; no trama explícita suficiente |
| Little Women — Louisa May Alcott | Descripción inglesa admitida; ruta extractiva española se abstiene |
| Don Quijote — Miguel de Cervantes Saavedra | Identidad no confirmada por el adaptador; no se fuerza alias |
| Diario secreto de Papelucho y el marciano — Marcela Paz | Sin resultado adecuado en este pase |
| Historia de Chile — Armando De Ramón | Rechazado contenido del tema genérico sin identidad de la obra |
| Agua de Nieve — Concha Espina | Sin resultado adecuado |
| The Time Machine — H. G. (Herbert George) Wells | No coincide la identidad/forma bibliográfica del autor |
| The Wonderful Wizard of Oz — L. Frank (Lyman Frank) Baum | No se relaja la identidad del autor |
| Moby-Dick; or, The Whale — Herman Melville | No se confirma equivalencia del título largo |

Incluye clásicos, obras del siglo XX, literatura latinoamericana y juvenil; se
intentó una obra histórica. No se localizó manga en los inventarios revisados y
no se añadió un título para completar artificialmente esa categoría. No hay
nueva cobertura tipada de antagonistas, ambientación o contexto histórico;
puede existir información en pasajes, pero no se infieren campos para rellenarlos.

## Fuentes, permisos y rechazos

Se conservaron 25 fuentes adicionales: 22 snapshots de Wikipedia por sección,
una fuente web Wikidata de pertenencia y dos fichas bibliográficas Wikidata.
Los redirects y secciones de una página **no son fuentes independientes**.
Los pasajes guardados están acotados a 1.800 caracteres; no son novelas completas.

- Wikipedia: API oficial, identidad de título **y autor**, rechazo de adaptaciones,
  revisión y atribución a colaboradores, [CC BY-SA 4.0 y condiciones de reutilización](https://www.mediawiki.org/wiki/Wikimedia_APIs/Content_reuse).
  Ejemplos: [Orgullo y prejuicio](https://es.wikipedia.org/wiki/Orgullo_y_prejuicio),
  [Dune](https://es.wikipedia.org/wiki/Dune), [Rayuela](https://es.wikipedia.org/wiki/Rayuela),
  [Emma](https://es.wikipedia.org/wiki/Emma), [Siddhartha](https://es.wikipedia.org/wiki/Siddhartha).
- Wikidata: declaraciones estructuradas [CC0](https://www.wikidata.org/wiki/Wikidata:Licensing).
  [Q25338](https://www.wikidata.org/wiki/Q25338) aportó pertenencia; no se presenta
  P674 como descripción del rol ni como corroboración independiente.
- Open Library y Gutenberg conservan sus políticas existentes de metadatos:
  no se asumió permiso general para almacenar sinopsis editoriales o generadas.
  No se importaron más catálogos ni se extrajeron comercios.

Tareas reales: 47 intentos; 10 completaron el requisito, 11 no confirmaron
identidad, 11 conservaron información parcial insuficiente, 5 no tuvieron
resultados y 10 quedaron limitados por el proveedor. Se conservaron backoff y
cooldown; no se forzaron reintentos ni se interpretó una limitación como ausencia
definitiva de información. Esos conteos son tareas, no obras distintas.

## Correcciones generalizables

1. Consultas de actualización orientadas al tipo de evidencia: trama o personajes.
   Metadatos sigue siendo la ruta predeterminada; lectura temática opt-in, una
   página por tarea, sin instalar herramientas ni ampliar dominios autorizados.
2. Snapshots de sección separados por scope, con URL/revisión/atribución originales:
   guardar personajes no reemplaza sinopsis ni snapshots anteriores. Repetir una
   sección no duplica su ID. Los cambios legítimos conservan historia.
3. Uso del presupuesto **efectivo** de páginas del contexto: si queda una lectura,
   personajes utiliza Parse en lugar de TextExtracts que omite tablas. Se reprodujo
   el fallo con una prueba antes de corregirlo; no se aumentó el presupuesto.
4. Hechos literales de secciones y relaciones con sujeto/vínculo/objeto explícitos;
   negaciones, coocurrencias y datos del modelo no se convierten en afirmaciones.
5. Separación entre trama y descripción de personaje, incluso en snapshots viejos:
   se corrigió el fallo de Elanor desplazando la trama de Tolkien.
6. Relaciones almacenadas sin ambigüedad pueden responder por ruta determinista
   con `validate_draft`, `validate_evidence` y `validate_audit(strict_facts=True)`.
   No elige entre relaciones contradictorias ni responde interpretaciones o
   preguntas adicionales. Admite títulos alternativos sólo con alias confirmado.
7. Métrica de relaciones corregida: cuenta predicados literales como «hijo» o
   «hermana», no sólo etiquetas inglesas de una enumeración cerrada.
8. Índice BM25 piloto por IDs existentes, rehidratación de fuentes y verificación
   de vigencia/hash/conflictos. Un índice parcial exige destino nuevo y no puede
   reemplazar índices previos. La recuperación del chat ya reutiliza la memoria
   FTS; no se modificaron embeddings ni se entrenaron pesos.

## Consultas y rendimiento reales

34 consultas locales iguales antes/después (trama y personajes por cada obra):
**3 → 12 respuestas extractivas auditadas**. Las otras siguen sin respuesta local
suficiente; podrían requerir investigación o síntesis del sistema completo.
Esto no mide exactitud global del LLM ni demuestra una tasa de error <1 %.

Recuperación local: p50 **7,15 → 14,92 ms**, p95 **14,37 → 23,30 ms**. Hay más
evidencia que verificar; no se declara una aceleración global de esta medición.

HTTP/SSE, Django y MySQL reales, sin fixtures de recuperación:

- Trama de Orgullo y prejuicio: **0,5144 s**, español, fuente, 0 llamadas al LLM.
- Protagonista: **Elizabeth Bennet**, **0,1781 s**, 0 llamadas al LLM.
- Relación Edward Lucas / Sir William Lucas: antes **34,9367 s y 4 llamadas Qwen**;
  otro intento **32,2518 s y 6 llamadas**, incluida reparación. Después de corregir
  la ruta y su resolución de alias: **1,0302 s, cero llamadas**, respuesta literal
  «Edward Lucas es hijo de Sir William Lucas», fuente y tarjeta conservadas.
  Se usaron preguntas equivalentes con redacción distinta, evitando reutilizar
  una respuesta exacta cacheada. No se atribuye esa mejora a todas las consultas.
- Sesiones firmadas y servidor loopback efímero; no se crearon lectores ni
  conversaciones MySQL. No se afirma que quede un servidor permanente encendido.

RAG piloto: 49 fuentes candidatas, 42 documentos, 57 fragmentos, BM25 sin
embeddings; las ocho obras con trama recuperaron evidencia vinculada (8/8),
aproximadamente 9,5–26,3 ms por consulta. Índice derivado de auditoría de 311.296
bytes; no reemplaza el índice vectorial de biblioteca.

Memoria pública: **60.592.128 → 60.923.904 bytes**, +331.776 bytes (~324 KiB).
Pico RSS del auditor: **157,41 MiB**, no incluye MySQL/Ollama. Sin saturación
observada; disco disponible superior a 100 GiB. Faltan mediciones de escala.

## Pruebas, archivos y continuidad

**206 pruebas dirigidas aprobadas** en 4,422 s; **233 comprobaciones JavaScript**
aprobadas. La suite general aislada ejecutó **1.941 pruebas** en 92,052 s:
4 fallos, 2 errores y 1 omisión, conservados en el informe. Son las incidencias
conocidas de endpoints Dune, recuerdos Platero/Metamorfosis y alias Quijote;
Tolkien ya pasa. No se declara toda la suite aprobada. Se añadieron después las
regresiones de relación literal/alias, verificadas en las 206 dirigidas finales.

Archivos principales: `core/literary_enrichment.py`, `literary_memory.py`,
`literary_learning.py`, `literary_sources.py`, `literary_search.py`,
`literary_memory_rag.py`, `literary_ai.py`, `ai_quick_answers.py`,
`ai_narrative_answers.py`, `bibliographic_http_probe.py`,
`test_narrative_enrichment.py`, `test_wikipedia_character_tables.py`;
`scripts/knowledge/enrich_narrative.py`, `audit_narrative.py`, `.gitignore`,
este informe y `reportes/continuidad_opencode.md`. Cambios previos conservados,
sin commits, push, instalación de dependencias o modificación de secretos.

Artefactos locales ignorados por Git: plan congelado, `piloto.json`,
`piloto_reanudado.json`, `wikidata.json`, logs JSONL por tarea, `auditoria.json`,
`auditoria_cierre.json`, `metricas_entrega.json`, `indices_integridad.json`, tres
pruebas HTTP de relación y salidas de tests. Los primeros intentos y mediciones
fallidas se conservaron, no se reescribieron para simular éxito.

## Reanudación y expansión futura

```powershell
.\venv\Scripts\python.exe -B -m scripts.knowledge.enrich_narrative --backup backups/narrativo_20261028_01 --plan reports/narrative_20261028/plan.json --output reports/narrative_20261028/siguiente_pase.json --execute

.\venv\Scripts\python.exe -B -m scripts.knowledge.audit_narrative --backup backups/narrativo_20261028_01 --plan reports/narrative_20261028/plan.json --output reports/narrative_20261028/nueva_auditoria.json --http
```

Contraseña oculta, MySQL local seleccionado sólo dentro del proceso. Salidas
nuevas; no es necesario repetir trabajos completos. El plan puede usar cualquier
ID existente mediante `--work-id` repetible, hasta 100. Conserva cola/checkpoints,
leases globales, 20 trabajos/120 s por lote, 12 s/tarea, pausa >=1 s (2 para
Wikidata), cuotas de página y mínimo de 10 GiB libres. Los resultados insuficientes
respetan su backoff; los ya cubiertos se omiten. No es un crawler permanente.

Antes de 1.000 obras: validar un segundo piloto independiente de hasta 100,
mejorar alias largos y nombres bibliográficos sin fusionar autores, resolver las
limitaciones de proveedores y medir por separado roles, tramas y abstenciones.
Luego procesar 1.000 como diez planes de hasta 100 con respaldo y evaluación por
lote. Para 10.000, nueva autorización/evaluación: APIs comunitarias no equivalen
a permiso para saturarlas; usar datasets con reutilización explícita o cachés
admitidas, cuotas reales, medición de CPU/disco/red y cobertura independiente.
No se ejecutaron esos lotes. El rendimiento del piloto no demuestra capacidad
ni cobertura narrativa para miles de obras.
