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
- La suite completa de `core` pasó: **1.626 pruebas OK en 25,938 s**. Las
  pruebas dirigidas de la integración pasaron **12/12**.
- La recuperación híbrida mejora el ranking léxico en el banco real de 15
  pasajes: nDCG@10 **0,5542** frente a **0,3398**, y Recall@5 **0,6333** frente
  a **0,4333**. Sigue siendo recuperación, no exactitud factual.
- El chat HTTP/SSE con la biblioteca local fue **inestable**: la misma
  configuración léxica respondió 3/5 y luego 2/5; la semántica respondió 3/5,
  3/5 y 2/5 en ejecuciones sucesivas. Se mantiene **desactivada por defecto**
  (`LITMATE_LIBRARY_SEMANTIC_CHAT=false`).
- No se entrenó ni activó learning-to-rank. La compuerta sigue cerrada por falta
  de etiquetas `human_reviewed` y `label_evidence_verified`.

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
| `core/literary_ai.py` | Los candidatos locales verificados entran en la ruta general para `analysis`, `summary` y `author`; ya no se pierden por una ficha externa con otro subtítulo. |
| `core/literary_library.py` | Alias editoriales, `list_library_books()` y metadatos de procedencia; el índice derivado conserva la identidad del original. |
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
| Suite completa `core` | **1.626 pruebas OK**, 25,938 s |
| `core.test_ai_library_router` | **12/12 OK**, 0,385 s |
| Regresión de subtítulo/author abreviado | OK |
| Regresión de no fuga entre obras | OK |
| Alias español limitado a obra y autor | OK |
| Propagación del opt-in semántico en contenido general | OK |
| Reconstrucción del índice sobre un índice existente | OK (ejecutada; 53,368 s) |

Las advertencias de la suite sobre Wikipedia, TTS, búsqueda semántica y fallos
simulados son parte de pruebas de degradación controlada; no hubo fallos de la
suite.

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

### 7.2 Fallback externo

Se probó «¿De qué trata Orgullo y prejuicio?» con web habilitada, en modo léxico
y semántico. Ambas ejecuciones aisladas quedaron `unavailable` y no produjeron
fuentes web vinculables; los informes son `chat_orgullo_web_20261027.json` y
`chat_orgullo_web_semantico_20261027.json`. El pipeline externo existente se
conserva, pero **no se demostró** que rescate este caso cuando la evidencia local
es sólo material introductorio. Queda como limitación pendiente, no como éxito.

## 8. Learning-to-rank: no entrenado ni activo

`training_readiness.ready` es `false`. Los conteos son cero pares, cero obras y
cero consultas en entrenamiento, validación y prueba. Faltan etiquetas
`label_status=human_reviewed` y `label_evidence_verified=true`; las anotaciones
actuales son `curated_test`/revisadas por agente y no son elegibles.

No se ejecutó fine-tuning/LoRA, no se cambiaron pesos de Ollama, no se activó un
modelo de ranking y no se instalaron paquetes. `scikit-learn 1.9.1` está
instalado en el entorno, pero la implementación de ranking inspeccionada es
Python puro y no se usó para producción.

## 9. Límites y riesgos conocidos

1. **Sinopsis con evidencia parcial.** Para *Orgullo y prejuicio*, la
   recuperación léxica devuelve principalmente material editorial inicial; el
   índice no basta para una sinopsis completa sin web o sin semántica. La
   respuesta aislada se abstiene, lo cual es preferible a inventar.
2. **Auditoría factual imperfecta.** El caso *Frankenstein*/Elizabeth demuestra
   que una respuesta `answered` puede contener una atribución errónea. La
   auditoría automática no sustituye revisión humana.
3. **No determinismo.** Repetir la misma matriz y el mismo modelo cambió los
   estados. No se debe comparar una sola ejecución como si fuera un experimento
   controlado.
4. **Semántica opt-in.** Mejora ranking (nDCG@10 0,3398 → 0,5542), pero el chat
   no mostró una mejora estable y añadió latencia. El valor por defecto sigue
   siendo `False`.
5. **Cobertura léxica de resúmenes.** El parser de capítulos de algunas ediciones
   deja gran parte del material inicial en la sección «Inicio». Una consulta
   general puede recuperar ese material antes de la narración.
6. **Cobertura de alias.** Sólo se revisaron siete alias. Títulos abreviados,
   traducciones no registradas y ediciones con otro título no se enlazan.
7. **Catálogo ≠ permiso de texto.** Los 300 registros españoles son metadatos;
   no autorizan descargar las obras completas.
8. **Datos no versionados.** Los corpus, manifiestos locales, bases e índices no
   se añadieron a Git; el checkpoint del repositorio no reproduce los datos sin
   volver a descargarlos y verificarlos.

## 10. Archivos y artefactos

- Código: `core/ai_library_router.py`, `core/literary_search.py`,
  `core/literary_ai.py`, `core/literary_library.py`,
  `core/management/commands/indexar_biblioteca.py`,
  `litmate_project/ai_settings.py`.
- Alias: `core/data/library_aliases.json`.
- Pruebas: `core/test_ai_library_router.py`, `core/test_literary_library.py`,
  `core/test_literary_acquisition.py`, `core/test_literary_gutenberg.py`,
  `core/test_literary_ranking.py`.
- Informes de recuperación:
  `reportes/expansion_20261027/recuperacion_biblioteca_*_12libros_20261027.json`.
- Informes HTTP:
  `reportes/expansion_20261027/chat_biblioteca_*_20261027.json` y
  `chat_orgullo_web*_20261027.json`.
- Matriz:
  `reportes/expansion_20261027/matriz_chat_biblioteca.json`.

## 11. Decisiones

- Se conserva el pipeline Django/Ollama existente y la recuperación híbrida.
- No se reemplazaron componentes ni se creó un sistema paralelo.
- No se modificó `.env`, no se ejecutaron migraciones, no se hizo push y no se
  usaron APIs de pago ni credenciales nuevas.
- La biblioteca local es una fuente de evidencia, no una respuesta automática.
- El chat semántico de biblioteca queda opt-in hasta que una evaluación estable
  y una revisión factual independiente demuestren calidad.
- El siguiente paso no es entrenar: es etiquetar humanamente y corregir la
  auditoría/atribución antes de activar ranking o semántica por defecto.
