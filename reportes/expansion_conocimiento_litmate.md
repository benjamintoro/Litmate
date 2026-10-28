# Expansión del conocimiento local de LitMate — 27 de octubre de 2026

Rama: `feature/cuotas-ia-chatbot`.
Estado: cambios locales sin push. No se ejecutaron migraciones ni se modificó `.env`.

Este informe separa tres cosas que no deben confundirse: **datos importados**,
**recuperación medida** y **calidad factual de una respuesta publicada**. Un
turno con estado `answered` no es una certificación de verdad.

## 1. Resultado ejecutivo

- La biblioteca autorizada pasó de 10 a **12 originales**: se añadieron
  *La Regenta* (Gutenberg 17073) y *Marianela* (Gutenberg 17340).
- El catálogo bibliográfico incorporó **300 registros en español** de Project
  Gutenberg. El ledger quedó con **2.298 registros** (2.296 Gutenberg + 2 Open
  Library), **0 relaciones** y **2.298 eventos de outbox en `done`**.
- El índice derivado se reconstruyó para los 12 libros: **11.289 fragmentos**,
  **11.289 vectores**, modelo `embeddinggemma:latest`, digest
  `85462619ee721b466c5927d109d4cb765861907d5417b9109caebc4e614679f1`,
  dimensión 768.
- Se conectó la biblioteca local con la ruta general de contenido, no sólo con
  narración y personajes. También se corrigieron dos causas de pérdida de
  evidencia: subtítulos/autores abreviados en fichas externas y alias españoles
  de obras inglesas.
- La ruta general ahora distingue material introductorio de narrativa: marca
  `front_matter` antes del recorte de la descripción, rechaza listas de materias
  del catálogo como sinopsis y, cuando hay una sinopsis web vinculada, retira
  las portadas/prefacios locales del contexto de respuesta. La web se consulta
  en varios proveedores; una página sólo se vincula si coinciden obra y autoría.
- Las pruebas dirigidas de esta fase pasaron **125/125**. La suite completa de
  `core` **no está verde**: **1.636 pruebas, 4 fallos y 2 errores en 228,839 s**.
  Los casos abiertos están en módulos no modificados en esta fase
  (`test_ai_public_details` y `test_chat_deadline`) y se detallan en §5; no se
  presentan como una suite aprobada.
- La recuperación híbrida mejora el ranking léxico en el banco real de 15
  pasajes: nDCG@10 **0,5542** frente a **0,3398**, y Recall@5 **0,6333** frente
  a **0,4333**. Sigue siendo recuperación, no exactitud factual.
- El chat HTTP/SSE con la biblioteca local fue **inestable**: la misma
  configuración léxica respondió 3/5 y luego 2/5; la semántica respondió 3/5,
  3/5 y 2/5 en ejecuciones sucesivas. Se mantiene **desactivada por defecto**
  (`LITMATE_LIBRARY_SEMANTIC_CHAT=false`).
- Se ejecutó un candidato learning-to-rank **experimental** con etiquetas
  `agent_reviewed`/`curated_test`; no se activó ni se publicó. La compuerta de
  producción sigue cerrada por falta de etiquetas `human_reviewed` y
  `label_evidence_verified` (métricas en §8.1).

## 2. Datos incorporados y procedencia

### 2.1 Biblioteca de originales

| Elemento | Estado |
|---|---:|
| Libros activos | 12 |
| Fragmentos de origen | 6.393 |
| Capítulos/secciones | 561 |
| Bytes de originales | 9.656.545 |
| Tamaño de la base de biblioteca | 31.305.728 bytes |
| Libros retirados | 0 |

Los dos libros nuevos se incorporaron con manifiesto local, SHA-256, revisión
de derechos para Chile y ausencia de traducción/introducción contemporánea
declarada:

| Obra | Gutenberg | Bytes | SHA-256 |
|---|---:|---:|---|
| *La Regenta* — Leopoldo Alas | 17073 | 1.889.429 | `29cd4c40b2a89cf643f7b3f3a53f8bbef1e67b9be204333bcb9a4dd50b61e86f` |
| *Marianela* — Benito Pérez Galdós | 17340 | 327.474 | `ec6e5dbd4260583360ab7bd29738505ad5f0dfdf58db3dcbbc401c5ce4fea03f` |

La importación local incorporó los dos originales sin errores y añadió
**1.381** fragmentos (1.186 de *La Regenta* y 195 de *Marianela*); los eventos de
importación quedaron registrados en `library_events`. Los originales,
manifiestos, bases e índices viven bajo `data/biblioteca/` y
`data/corpus_autorizado/`, rutas ignoradas por Git. El detalle de descarga está
en `reportes/expansion_20261027/descargas_es_20261027.json`.

### 2.2 Catálogo Gutenberg en español

Comando ejecutado:

```powershell
.\venv\Scripts\python.exe manage.py importar_catalogo_gutenberg `
  --catalog data\adquisicion\pg_catalog_20261027.csv.gz `
  --state-db data\adquisicion\ledger.sqlite3 `
  --database data\literary_memory.sqlite3 `
  --language es --max-records 300 --max-scanned 100000 `
  --max-seconds 300 --max-storage-mb 128
```

Resultado: **46.108** filas escaneadas, **300** aceptadas e insertadas,
**300** proyectadas en memoria, **0** errores, **109,1553 s**. El checkpoint
del conjunto español quedó en `offset=46.108`, `finished=0`. El conjunto inglés
conserva su checkpoint anterior en `offset=2.706`, `finished=0`: ambos son
reanudables y `finished=0` significa que el lote se detuvo por presupuesto, no
que la importación fallara.

El ledger final tiene **2.298** registros, **0** relaciones y **2.298** eventos
de outbox en `done`. Los 300 registros españoles son metadatos de catálogo; no
conceden por sí mismos permiso para descargar el texto de cada obra.

### 2.3 Alias españoles revisados

`core/data/library_aliases.json` contiene siete alias editoriales con evidencia
Open Library, limitados a obra y autoría exactas:

- *Pride and Prejudice* → «Orgullo y prejuicio».
- *Alice's Adventures in Wonderland* → «Alicia en el país de las maravillas».
- *The Adventures of Sherlock Holmes* → «Las aventuras de Sherlock Holmes».
- *The Adventures of Tom Sawyer, Complete* → «Las aventuras de Tom Sawyer».
- *The Picture of Dorian Gray* → «El retrato de Dorian Gray».
- *The Republic* → «La República».
- *Treasure Island* → «La isla del tesoro».

El registro se carga con `lru_cache`, falla cerrado si el archivo es inválido y
no enlaza una consulta por semejanza semántica. Una consulta con el título en
español resuelve la obra local, pero eso no garantiza que el texto léxico
recuperado sea una sinopsis completa. *Alice* abreviado no se resuelve: se exige
el título o alias completo.

## 3. Cambios de integración

| Archivo | Cambio |
|---|---|
| `core/ai_library_router.py` | Resolución de obras locales por consulta/candidatos; fragmentos con alcance de obra; puente de respuestas y personajes. |
| `core/literary_search.py` | Inyección de identidad local en la recuperación general; fallback cuando la ficha externa usa subtítulo o autor abreviado; propagación del opt-in semántico. |
| `core/literary_ai.py` | Los candidatos locales verificados entran en la ruta general para `analysis`, `summary` y `author`; ya no se pierden por una ficha externa con otro subtítulo. Conserva `front_matter`, lo retira cuando hay sinopsis web vinculada y descarta tarjetas de libro no verificadas sólo si su título/autor aparecen en la web. |
| `core/literary_library.py` | Alias editoriales, `list_library_books()` y metadatos de procedencia; marca `front_matter` sobre el fragmento completo antes del recorte canónico. |
| `core/literary_research.py` | `assess_evidence` no acepta portadas/prefacios ni listas de materias del catálogo como sinopsis, aunque superen el mínimo de caracteres. |
| `core/literary_identity.py` | Vinculación de títulos web con sufijos seguros (`- Wikipedia`, `: resumen`, nombre del sitio) y resolución de nombres por alias confirmado, siempre con obra y autoría exactas. |
| `litmate_project/ai_settings.py` | Nuevas rutas `LITMATE_LIBRARY_DB`, `LITMATE_LIBRARY_RAG_DB` y flag `LITMATE_LIBRARY_SEMANTIC_CHAT` (por defecto `False`). |
| `core/management/commands/indexar_biblioteca.py` | Reconstrucción idempotente: `CREATE TABLE IF NOT EXISTS` e `INSERT OR REPLACE` para el propietario del índice. |
| `core/data/library_aliases.json` | Registro factual de alias, con URL y evidencia; no contiene texto de las obras. |

La clave de caché de contenido incorpora ahora la revisión de la biblioteca y
el flag semántico. Sin eso, una respuesta recuperada antes de importar un libro
podía reutilizar fragmentos antiguos y perder la identidad local.

## 4. Índice reconstruido

```powershell
.\venv\Scripts\python.exe manage.py indexar_biblioteca `
  --base data\biblioteca\biblioteca.sqlite3 `
  --indice data\biblioteca\rag.sqlite3 `
  --exportar data\biblioteca\rag_export `
  --semantico --max-segundos 1800
```

Resultado: `{"books": 12, "chunks": 11289, "mode": "hybrid",
"seconds": 53.368181}`. La verificación directa del SQLite confirmó:

- 12 documentos.
- 11.289 fragmentos.
- 11.289 vectores de dimensión 768.
- Metadatos `model=embeddinggemma:latest`,
  `digest=85462619ee721b466c5927d109d4cb765861907d5417b9109caebc4e614679f1`,
  `version=hybrid-v2`.
- Propietario del índice apuntando a `data/biblioteca/biblioteca.sqlite3`.

## 5. Pruebas

| Comprobación | Resultado |
|---|---:|
| Suite completa `core` | **1.636 pruebas: 4 fallos y 2 errores**, 228,839 s; no verde |
| Pruebas dirigidas de esta fase (`research`, `hybrid_ai`, `identity`, `ranking`) | **125/125 OK**, 1,369 s |
| `core.test_ai_library_router` | **12/12 OK**, 0,385 s |
| Regresión de subtítulo/author abreviado | OK |
| Regresión de no fuga entre obras | OK |
| Alias español limitado a obra y autor | OK |
| Propagación del opt-in semántico en contenido general | OK |
| Reconstrucción del índice sobre un índice existente | OK (ejecutada; 53,368 s) |
| Exclusión de front matter y listas de materias | OK (pruebas dirigidas) |
| Vinculación de fuentes web y tarjetas inventadas | OK (pruebas dirigidas) |

Los fallos/errores abiertos de la suite completa son
`test_verified_character_details_do_not_acquire_a_model_or_consume_a_quota`,
`test_authenticated_fast_details_persist_sources_and_zero_inference_usage`,
`test_history_owned_by_a_different_user_is_not_given_to_the_fast_answer`,
`test_recollections_allow_a_semicolon_and_question_after_the_scene` (dos
subcasos) y `test_short_work_alias_keeps_documented_quixote_characters`. Están
en `core.test_ai_public_details` y `core.test_chat_deadline`, archivos que no se
modificaron en esta fase; se conservan como pendientes y no se ocultan con una
afirmación de suite verde. Las advertencias de Wikipedia, TTS, búsqueda semántica
y fallos simulados sí son pruebas de degradación controlada.

## 6. Recuperación: métricas separadas de la respuesta

### 6.1 Banco offline de fixture (48 consultas)

| Métrica | Valor |
|---|---:|
| Recall@5 / Recall@10 | 0,9167 / 0,9167 |
| Precision@5 | 0,2500 |
| MRR | 0,8594 |
| nDCG@10 | 0,8721 |
| Obra correcta en primera posición | 0,8542 |
| p50 de recuperación | 0,000154 s |

### 6.2 Biblioteca real de 12 libros (15 pasajes anotados de 5 obras)

El banco contiene 30 consultas ES/EN. Los 15 pasajes anotados son una fracción
del índice actual de 11.289 fragmentos; el resto queda como no juzgado y no se
cuenta como negativo.

| Medición | Léxico/BM25 | Híbrido (BM25 + embeddings) |
|---|---:|---:|
| Recall@5 | 0,4333 | **0,6333** |
| Recall@10 | 0,4667 | **0,7333** |
| Precision@5 | 0,0867 | **0,1267** |
| MRR | 0,2992 | **0,4981** |
| nDCG@10 | 0,3398 | **0,5542** |
| Obra correcta en primera posición | 1,0000 | 1,0000 |
| p50 | 0,2231 s | 0,2837 s |
| p95 | 0,2665 s | 0,4450 s |
| Llamadas/fallos de embedding | 0/0 | **30/0** |

Estas cifras no son latencia del chat ni exactitud factual. La precisión es baja
porque el denominador es 5 y sólo hay 1–2 pasajes pertinentes por consulta; no
se ajustó el denominador para inflar el resultado. Los informes están en
`reportes/expansion_20261027/recuperacion_biblioteca_bm25_12libros_20261027.json`
y `..._hibrida_12libros_20261027.json`.

## 7. Chat HTTP/SSE real

Condiciones: servidor loopback efímero, bases auxiliares vacías, biblioteca e
índice existentes en sólo lectura, `qwen3.5:4b`, contexto 16.384, web
deshabilitada, presupuesto de chat 75 s y de respuesta 90 s. Cada ejecución usó
la misma matriz de cinco preguntas:

1. carta de *Frankenstein* sobre William;
2. resumen de *Don Quijote*;
3. resumen de «Orgullo y prejuicio» (alias);
4. resumen de *Marianela*;
5. autor de *Drácula*.

| Ejecución | Modo | Respondidas | p50 | Máximo |
|---|---|---:|---:|---:|
| Léxica v1 | BM25/FTS | 3/5 | 9,192 s | 19,794 s |
| Léxica v2 (final) | BM25/FTS | **2/5** | **9,336 s** | **12,863 s** |
| Semántica v1 | Híbrida | 3/5 | 9,902 s | 18,762 s |
| Semántica v2 | Híbrida | 3/5 | 8,104 s | 30,857 s |
| Semántica v3 (final) | Híbrida | **2/5** | **9,782 s** | **17,219 s** |

Todas las ejecuciones terminaron dentro del presupuesto de 90 s. En la
ejecución léxica final, 5/5 quedaron por debajo de 30 s; en la semántica final,
5/5 también. La semántica v2 tuvo un turno de 30,857 s.

Las respuestas que citaron la biblioteca local incluyeron, entre otras:

- *Don Quijote*: `https://www.gutenberg.org/ebooks/2000`.
- *Drácula*: `https://www.gutenberg.org/ebooks/345`.
- *Frankenstein*: `https://www.gutenberg.org/ebooks/84`.

La variación entre repeticiones no se puede atribuir sólo a la recuperación:
intervienen el enrutador y el auditor del modelo local. Por eso no se declara
una mejora estable de la semántica ni se activa por defecto.

### 7.1 Revisión factual: `answered` no es verdad certificada

En la ejecución semántica final, *Frankenstein* quedó `answered` pero la
respuesta publicada atribuyó la carta a **Elizabeth Lavenza**. El fragmento local
y la novela atribuyen la carta con la noticia de la muerte de William al padre,
Alphonse Frankenstein. Es un error factual detectado por revisión manual; la
auditoría automática no lo bloqueó. El resultado se conserva en
`chat_biblioteca_semantico_v3_20261027.json` y **no se cuenta como acierto
factual**.

En la ejecución léxica v1 el mismo caso respondió correctamente; en la v2 quedó
`unavailable`. Esa diferencia refuerza la conclusión: el estado del endpoint es
una señal de publicación, no una garantía de calidad.

### 7.2 Investigación externa y exclusión de material introductorio

La ruta externa ya no se detiene porque la recuperación local devuelva una
portada o un prefacio. `retrieve_library` marca `front_matter` sobre el fragmento
completo antes de que `canonical_sources` recorte la descripción; `assess_evidence`
excluye esas fuentes y también las listas de materias del catálogo
(`Temas del catálogo: ...`). Cuando hay al menos una página web vinculada, la
respuesta de resumen retira los fragmentos introductorios locales y conserva las
fuentes web. Si la web no está disponible, el respaldo local se mantiene, pero el
material introductorio no se cuenta como sinopsis suficiente.

La vinculación web reconoce títulos como «Orgullo y prejuicio - Wikipedia, la
enciclopedia libre» o «: resumen» sólo si la autoría también aparece en el texto
de identidad. No recorta subtítulos de sagas ni convierte una página no vinculada
en prueba de la obra. `front_matter_excluded` deja constancia del material
descartado.

Resultados reales de «¿De qué trata Orgullo y prejuicio?»:

- `consulta_orgullo_web_20261027_run2.json`: `answered`, una búsqueda web,
  cuatro fuentes web, tres vinculadas, `front_matter_excluded=4`, evidencia
  suficiente. El texto fue una **lista de pasajes atribuidos**, no una sinopsis
  coherente. Esa ejecución es anterior al ajuste de alias: las fuentes quedaron
  ligadas a una identidad provisional (`litmate:3cff…`), no al `work_id` de la
  ficha local (`litmate:6622…`).
- `consulta_orgullo_web_20261027_final.json`: misma escalada y exclusión, pero
  `quality_rejected` por un acontecimiento concreto sin respaldo; no se publicó
  respuesta.
- `consulta_orgullo_web_20261027_resumen_breve.json`: `answered` con un pasaje
  narrativo local (capítulo XIV), no con web; demuestra el respaldo local, no la
  investigación externa.

Por tanto, la escalada y la vinculación externas están **demostradas**, pero una
sinopsis web coherente y estable **no** está demostrada. `answered` sigue sin ser
certificación factual y las páginas externas siguen siendo datos no confiables.
El agente conserva además el límite de §9.2: una obra sin candidato local puede
llegar a la web sin una identidad contra la que vincular las fuentes.

## 8. Learning-to-rank: experimental, no activo

`training_readiness.ready` sigue siendo `false`. Los conteos de producción son
cero pares, cero obras y cero consultas en entrenamiento, validación y prueba.
Faltan etiquetas `label_status=human_reviewed` y
`label_evidence_verified=true`; las anotaciones actuales son
`agent_reviewed`/`curated_test` y no son elegibles. La compuerta exige 200 pares
de entrenamiento, 20 obras y 80 consultas, además de los mínimos de validación y
prueba; la biblioteca sólo tiene 12 libros.

### 8.1 Candidato experimental y separación de datos

Se añadió `--experimental-candidate` a `evaluar_recuperacion`. El experimento
entrena una regresión logística L2 en Python puro, con particiones separadas de
entrenamiento, validación y prueba, y deja siempre:

- `experimental_readiness.ready=true` (sólo para el experimento),
- `training_readiness.ready=false` (producción),
- `activation_eligible=false`, `human_labels=false`,
- `model_activated=false`.

| Banco | Particiones train/val/test (pares) | nDCG@10 validación | nDCG@10 prueba | Decisión |
|---|---:|---:|---:|---|
| Fixture de 16 obras | 600 / 54 / 54 | 0,9529 → **0,9590** | 0,8069 → **0,8069** | Rechazado: ganancia < 0,01 |
| Biblioteca real de 5 obras | 162 / 18 / 18 | 0,8552 → **0,8552** | 0,9385 → **0,9385** | Rechazado: ganancia < 0,01 |

Los informes son
`reportes/expansion_20261027/ranking_experimental_fixture_16obras_20261027.json`
y `.../ranking_experimental_biblioteca_5obras_20261027.json`. Las métricas son
recuperación offline sobre etiquetas declaradas no humanas; no miden exactitud
factual ni calidad del chat y no autorizan producción. No se ejecutó
fine-tuning/LoRA, no se cambiaron pesos de Ollama, no se activó un modelo de
ranking y no se instalaron paquetes. La implementación es Python puro.

## 9. Límites y riesgos conocidos

1. **Sinopsis local y material introductorio.** Para *Orgullo y prejuicio*, la
   recuperación léxica devuelve principalmente portada, prefacio y listas de
   materias. Esas fuentes ya no cuentan como sinopsis (`front_matter` y
   `looks_like_catalogue_metadata`), pero el índice sigue necesitando web o una
   consulta que recupere narrativa. La respuesta aislada se abstiene; no se
   rellena con conocimiento del modelo.
2. **Cobertura de obras sin ficha local.** `simple_literary_route` puede devolver
   `candidates=[]` para un resumen. Una obra ausente de la biblioteca no tiene
   entonces una identidad local contra la que vincular páginas web; la
   investigación externa puede ejecutarse, pero no se garantiza el vínculo ni
   una respuesta final. Es una limitación conocida, no cobertura completa.
3. **Auditoría factual imperfecta.** El caso *Frankenstein*/Elizabeth demuestra
   que una respuesta `answered` puede contener una atribución errónea. La
   auditoría automática no sustituye revisión humana; una página vinculada
   acredita identidad, no verdad factual.
4. **No determinismo.** Repetir la misma matriz y el mismo modelo cambió los
   estados. En las ejecuciones reales de *Orgullo*, una respondió con una lista
   de pasajes web y otra fue rechazada por la auditoría. No se debe comparar una
   sola ejecución como si fuera un experimento controlado.
5. **Semántica opt-in.** Mejora ranking (nDCG@10 0,3398 → 0,5542), pero el chat
   no mostró una mejora estable y añadió latencia. El valor por defecto sigue
   siendo `False`.
6. **Cobertura léxica de resúmenes.** El parser de capítulos de algunas ediciones
   deja gran parte del material inicial en la sección «Inicio». Una consulta
   general puede recuperar ese material antes de la narración.
7. **Cobertura de alias.** Sólo se revisaron siete alias. Títulos abreviados,
   traducciones no registradas y ediciones con otro título no se enlazan.
8. **Catálogo ≠ permiso de texto.** Los 300 registros españoles son metadatos;
   no autorizan descargar las obras completas.
9. **Datos no versionados.** Los corpus, manifiestos locales, bases e índices no
   se añadieron a Git; el checkpoint del repositorio no reproduce los datos sin
   volver a descargarlos y verificarlos.
10. **Suite completa no verde.** Quedan 4 fallos y 2 errores en pruebas de
    detalles públicos y plazos de chat, fuera de los archivos modificados en esta
    fase. No se declara una suite aprobada ni se corrigen ocultando el fallo.

## 10. Archivos y artefactos

- Código: `core/ai_library_router.py`, `core/literary_search.py`,
  `core/literary_ai.py`, `core/literary_library.py`, `core/literary_research.py`,
  `core/literary_identity.py`, `core/literary_ranking.py`,
  `core/management/commands/indexar_biblioteca.py`,
  `core/management/commands/evaluar_recuperacion.py`,
  `litmate_project/ai_settings.py`.
- Alias: `core/data/library_aliases.json`.
- Pruebas: `core/test_ai_library_router.py`, `core/test_literary_library.py`,
  `core/test_literary_acquisition.py`, `core/test_literary_gutenberg.py`,
  `core/test_literary_research.py`, `core/test_literary_identity.py`,
  `core/test_hybrid_ai.py`, `core/test_literary_ranking.py`.
- Informes de recuperación:
  `reportes/expansion_20261027/recuperacion_biblioteca_*_12libros_20261027.json`.
- Informes HTTP:
  `reportes/expansion_20261027/chat_biblioteca_*_20261027.json` y
  `chat_orgullo_web*_20261027.json`.
- Evidencia web/fallback:
  `reportes/expansion_20261027/consulta_orgullo_web_20261027_run2.json`,
  `..._final.json` y `..._resumen_breve.json`.
- Ranking experimental:
  `reportes/expansion_20261027/ranking_experimental_*_20261027.json`.
- Log de la suite completa:
  `reportes/expansion_20261027/suite_core_20261027.txt`.
- Matriz:
  `reportes/expansion_20261027/matriz_chat_biblioteca.json`.

## 11. Decisiones

- Se conserva el pipeline Django/Ollama existente y la recuperación híbrida.
- No se reemplazaron componentes ni se creó un sistema paralelo.
- No se modificó `.env`, no se ejecutaron migraciones, no se hizo push y no se
  usaron APIs de pago ni credenciales nuevas.
- La biblioteca local es una fuente de evidencia, no una respuesta automática.
- Las páginas web sólo acreditan identidad si coinciden obra y autoría; su
  contenido sigue siendo dato externo no confiable y no se convierte en prueba
  factual por estar citado.
- El material introductorio y las listas de materias no son sinopsis. Si no hay
  evidencia narrativa, el sistema se abstiene o busca fuera; no rellena el hueco
  con el front matter.
- El candidato learning-to-rank es sólo un experimento de pipeline. Se mantiene
  inactivo hasta tener etiquetas humanas verificadas y una evaluación
  independiente; no se cambiaron pesos de producción.
- El chat semántico de biblioteca queda opt-in hasta que una evaluación estable
  y una revisión factual independiente demuestren calidad.
- El siguiente paso no es entrenar: es etiquetar humanamente, corregir la
  auditoría/atribución y cerrar la brecha de obras sin candidato local antes de
  activar ranking o semántica por defecto.

## 12. Lote posterior: generalización de alias y ampliación de catálogo (2026-10-27)

Esta sección registra una ejecución posterior; no convierte los resultados históricos anteriores en una suite aprobada ni sustituye sus capturas. Informe detallado: `generalizacion_20261027_lote01/resultados.md`.

La ingesta reutilizó el catálogo oficial ya descargado, el ledger, staging por SHA-256, outbox, proyección y FTS. Se verificaron las políticas oficiales antes de ejecutarla. **No se descargaron textos ni se otorgaron permisos de obras por disponer de metadatos.** Se respaldaron ledger y memoria pública con SQLite backup; no se tocó la base Django.

| Métrica | Antes | Después |
| --- | ---: | ---: |
| Registros de ledger | 2.298 | 2.328 |
| Obras únicas en memoria | 2.201 | 2.230 |
| Autores normalizados | 817 | 828 |
| Fuentes vigentes | 2.328 | 2.358 |
| Obras con descripción web admitida | 2 | 2 |
| Obras con evidencia de personajes | 1 | 1 |
| Etiquetas de personajes con papel literal | 12 | 12 |
| Relaciones estructuradas | 0 | 0 |
| Textos originales activos en biblioteca | 12 | 12 |

Lote español: 2.967 registros escaneados, 30 aceptados/insertados/proyectados, 0 actualizados, 1.825 filtrados, 1.112 rechazados por formato/autoría/tipo, 0 errores, **7,9391 s**. Cursor **46.108→49.075**, `complete=false`, 0 pendientes/staged. La repetición exacta devuelve 30 duplicados y la proyección repetida incorpora 0 fuentes. Treinta registros producen 29 obras nuevas y una fuente de una obra ya presente. Artefacto: `generalizacion_20261027_lote01/ingesta_real.json`.

Se corrigió la medición del importador: ahora distingue inserciones, actualizaciones, duplicados y revisiones antiguas; conserva historial y no degrada una revisión nueva. La nueva lectura `coverage_snapshot` separa metadatos de evidencia de contenido y no crea una base inexistente. Sus cifras se limitan a `literary_memory`; la biblioteca y el conocimiento curado se miden por separado.

En 29 consultas de identificación por título/autor de las obras nuevas, Recall@5 pasó de 0 a **27/29 (0,9310)** y MRR@5 de 0 a **0,8966**; recuperación local p50 **2,258 ms**, p95 **4,813 ms**. Es aumento de cobertura, no mejora demostrada de comprensión ni del ranking. Agua de Nieve (Novela) y Despertar Para Morir (Novela) siguen fuera del top 5. No se calcularon métricas de relevancia graduada sin etiquetas adecuadas.

También se unificó la extracción de alias explícitos y su uso en relaciones de una misma obra, sin nombres de libros programados en la lógica. Validación controlada independiente: 0/5→5/5 casos sobre la misma evidencia; son fixtures lingüísticos, no citas reales ni hechos verificados de sus novelas. El chat HTTP/SSE independiente respondió **7/11**, con **4 abstenciones**; p50 **2,460 s**, p95 **5,412 s**. Sam, La Maga, Sméagol y Boo siguen sin evidencia suficiente. No se presenta como solución literaria general completa ni p95 universal: esas rutas no llamaron al modelo.

**195 pruebas dirigidas y 1.742 generales aprobadas** en el lote posterior. Quedan pendientes adquisición/vinculación de perfiles y alias, identidad bibliográfica general, ranking de dos obras recién incorporadas y reducción del pipeline lento del Anillo. No se añadieron conectores, paquetes, modelos, entrenamiento, APIs de pago o tareas permanentes; se conserva la semántica de biblioteca opt-in y el ranking experimental inactivo. Continuar mediante lotes con informes y copias nuevos, respetando el checkpoint existente.

## 13. Lote 2: contenido utilizable y puente de recuperación (2026-10-27)

Informe: `generalizacion_20261027_lote02/resultados.md`; adquisición: `ingesta_real.json`; prueba de utilidad: `chat_memoria_sin_red_despues.json` dentro de ese directorio. No sustituye las mediciones históricas.

Se reutilizó el pipeline y se verificaron políticas oficiales. 8 consultas Wikipedia limitadas, 6 admitidas para 5 obras con contenido enciclopédico, sin LLM; 10 registros de catálogo francés, sin descargar textos. La ingesta duró 20,186 s, con copias previas de las dos SQLite públicas y sin tocar la base Django. Las consultas rechazadas no se asociaron a novelas por parecido: La tregua devolvió desambiguación y Narnia resultados de cine/intérpretes.

| Métrica del almacén | Lote 1 | Lote 2 |
| --- | ---: | ---: |
| Registros ledger | 2.328 | 2.343 |
| Pares título/autor representados | 2.230 | 2.245 |
| Autores normalizados | 828 | 832 |
| Fuentes vigentes | 2.358 | 2.377 |
| Obras con descripción enciclopédica | 2 | 7 |
| Obras con evidencia de personajes | 1 | 3 |
| Etiquetas canónicas con papel literal | 12 | 37 |
| Alias respaldados en pasajes vigentes | 0 | 4 |
| Relaciones estructuradas | 0 | 0 |
| Textos completos añadidos | 0 | 0 |

Estas cifras no afirman deduplicación universal de traducciones ni comprensión profunda de los 15 pares nuevos. Los pasajes de relaciones pueden responderse literalmente sin que se haya creado un grafo. Los datos enciclopédicos conservan revisión, atribución y licencia CC BY-SA; la disponibilidad en Gutenberg no se transforma en permiso para descargar novelas en Chile.

Catálogo francés: 1.318 escaneados, 10 insertados/proyectados, 1.040 filtrados y 268 rechazados por formato/autoría/tipo; 3,4423 s; cursor 0→1.318. Cursor español conservado en 49.075. Ledger final sin pendientes/staged. Repetición de los cinco registros Wikipedia finales: cinco duplicados; proyección repetida: cero. Los contadores históricos `inserted` por consulta incluyen escrituras/actualizaciones: las obras nuevas se midieron mediante estados del almacén, sin sumarlos como si fueran obras distintas.

Se corrigió una brecha compartida de recuperación: la ruta rápida descartaba las identidades de obra que el almacén devuelve aparte de sus fuentes web. Ahora se conservan sin relajar verificaciones. Se añaden definiciones de párrafos en secciones de personajes y selección antes del recorte; se guardan alias explícitos entrecomillados; los perfiles requieren obra y autor concretos. Futuras proyecciones conservan también la introducción bibliográfica, con controles de inyección. No hay excepciones de títulos en producción.

Utilidad real: mismo snapshot público/SHA y mismas 11 preguntas, HTTP/SSE con fuentes externas deshabilitadas. Antes del puente: 0 answered; después: 8 answered y 3 unavailable; LLM 16→7, p95 35,045→12,020 s. Sam y La Maga respondieron en 0,462/0,153 s desde memoria. Víctor respondió por la ruta general con evidencia local en 12,020 s. No equivale a certificación humana de cada afirmación. Jane Eyre no obtuvo personajes; Narnia no se vinculó; Boo/Sméagol siguen pendientes. El origen de las especies respondió desde un pasaje almacenado. El grupo C ya fue observado: no volver a llamarlo ciego en un lote futuro.

La sinopsis de Frankenstein se vincula mediante variante explícita publicada y tipo de obra, sin un alias manual. La pregunta del Anillo reutiliza una misión previamente aceptada, con auditoría: 35,074→0,070 s, 0 LLM/HTTP. No confunde misión con consumación. Estas mejoras no garantizan latencia o precisión universal.

247 pruebas dirigidas y 1.759 generales aprobadas. Las 10 consultas nuevas de catálogo francés tuvieron Recall@5/MRR@5 1,0; no se presenta como mejora de comprensión ni comparación equivalente con el 27/29 del lote 1. No hubo paquetes, proveedores comerciales, modelos nuevos, entrenamiento, migraciones, cambios visuales o de `.env`, commits ni push. Siguiente lote: narrativa/perfiles ausentes con grupo D, desambiguación/ediciones/traducciones, profundidad de fuentes sin secciones convencionales y relaciones estructuradas respaldadas.
