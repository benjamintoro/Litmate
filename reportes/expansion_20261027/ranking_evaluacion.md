# Recuperación y aprendizaje de ranking — 27 de octubre de 2026

Se reutiliza SQLite FTS5/BM25. `core/local_rag.py` ya combina BM25 y embeddings
locales mediante Reciprocal Rank Fusion (RRF); esta tarea no sustituye ese
componente ni añade dependencias. `literary_learning.provider_order` conserva su
heurística de utilidad agregada: no es un modelo entrenado ni mide verdad factual.

## Implementación

- `core/literary_ranking.py`: validación de corpus/juicios graduados, separación
  reproducible por obra, Recall@5/10, Precision@k, MRR, nDCG@10, identificación
  de obra en primera posición y latencia p50/p95. RRF reutilizable, características
  sin IDs/etiquetas y regresión logística L2 ligera, únicamente con opt-in.
- `evaluar_recuperacion`: SQLite en memoria por defecto; lectura de un índice
  local real mediante `--index`. Embeddings existentes sólo con `--semantic`.
  Registra llamadas/fallos de embeddings; no afirma que hubo búsqueda semántica
  si el índice o proveedor cayó silenciosamente a BM25.
- `core/data/retrieval_benchmark.json`: 32 anotaciones originales de LitMate,
  16 obras y 48 consultas (16 por autor, 16 descripciones ES, 16 descripciones EN),
  con procedencia y licencia de la redacción propia. Reutiliza
  `verified_readings.json`, **no representa conocimiento nuevo importado**.
- Entrenamiento y evaluación se agrupan por `work_id`: 10 obras/30 consultas
  para entrenamiento, 3/9 para validación y 3/9 para prueba. Todas las variantes
  de una obra permanecen juntas. El corpus de consulta puede contener obras
  desconocidas; sus etiquetas nunca entran al ajuste de pesos.

Los juicios iniciales son `curated_test`, pendientes de revisión humana
independiente; no se aceptan como etiquetas de entrenamiento. Los identificadores
estables deben agrupar traducciones/ediciones de la misma obra al ampliar el
dataset. De lo contrario no puede garantizarse ausencia de contaminación semántica.

## Medición ejecutada

Comando real, sin red ni generación LLM:

```powershell
.\venv\Scripts\python.exe -B manage.py evaluar_recuperacion --train-candidate --output reportes/expansion_20261027/recuperacion_fixture_v2.json
.\venv\Scripts\python.exe -B verificar_proyecto.py core.test_literary_ranking
```

Resultados FTS5/BM25 sobre las anotaciones pequeñas:

| Métrica | Resultado |
|---|---:|
| Recall@5 | 0,91667 |
| Recall@10 | 0,91667 |
| Precision@5 | 0,25000 |
| MRR | 0,85938 |
| nDCG@10 | 0,87215 |
| Obra correcta en primera posición | 0,85417 |
| Latencia p50 de recuperación | 0,154 ms |
| Latencia p95 de recuperación | 0,438 ms |

Pruebas propias: **23 aprobadas**, última ejecución 0,403 s. Incluyen fórmulas
conocidas, duplicados, resultados vacíos, particiones por obra, documentos ajenos,
etiquetas inexistentes, negativos de obras reservadas, repetición artificial de
muestras, opt-in semántico, errores del embedder, presupuestos de entrenamiento
y protección contra sobrescritura de informes.
La optimización logística se ejercitó exclusivamente con datos sintéticos dentro
de una prueba; **no se entrenó ni activó un modelo útil para producción**.

Estas cifras son recuperación offline, no latencia del chat ni calidad factual.
La precisión máxima práctica es baja cuando sólo existe uno/dos documentos
pertinentes y se divide por cinco; no se ajustó el denominador para inflarla.
La muestra pequeña y las anotaciones breves no permiten extrapolar a una
biblioteca grande. Tampoco se ha demostrado una mejora respecto al chat anterior.
El primer informe `recuperacion_fixture.json` es exploratorio y contenía consultas
mal codificadas por stdin de PowerShell; **usar v2**, con UTF-8 corregido.

## Entrenamiento y activación

Para una futura versión del dataset se necesitan ejemplos humanos con
`label_status=human_reviewed` y `label_evidence_verified=true`, fuentes permitidas
y respaldo comprobado. Relevancia: 0 irrelevante, 1 parcial, 2 directa. Los
documentos no juzgados no son negativos de entrenamiento.

Puertas mínimas, explícitas y conservadoras:

| Partición | Pares distintos | Obras | Consultas distintas |
|---|---:|---:|---:|
| Entrenamiento | 200 | 20 | 80 |
| Validación | 60 | 8 | 20 |
| Prueba | 60 | 8 | 20 |

Repetir un ID o la misma consulta no aumenta el volumen de muestras. Una misma
consulta/documento con etiquetas contradictorias bloquea el ajuste. Los
hiperparámetros quedan fijados antes de medir el holdout de prueba. El candidato
debe mejorar nDCG@10 al menos 0,01 en validación y prueba, sin empeorar Recall,
MRR ni identificación; el p95 tampoco debe crecer más del umbral documentado en
el código. El artefacto **siempre permanece inactivo**: medir recuperación no
demuestra exactitud factual, memoria total ni ausencia de regresiones del chat.
La activación exige revisión independiente de esos componentes.
El ajuste tiene un presupuesto predeterminado de 30 segundos y 50.000 pares;
un presupuesto agotado devuelve un intento incompleto sin activar ni publicar
pesos como modelo entrenado útil.

```powershell
# Preparación/evaluación; rechaza entrenamiento mientras falten etiquetas válidas.
.\venv\Scripts\python.exe -B manage.py evaluar_recuperacion --dataset RUTA_DATASET.json --train-candidate --output reportes/ranking_candidato_nuevo.json

# Índice ya construido: requiere que las qrels nombren fragmentos reales del índice.
.\venv\Scripts\python.exe -B manage.py evaluar_recuperacion --dataset RUTA_QRELS_REALES.json --index RUTA_INDICE.sqlite3 --output reportes/recuperacion_real_bm25.json
.\venv\Scripts\python.exe -B manage.py evaluar_recuperacion --dataset RUTA_QRELS_REALES.json --index RUTA_INDICE.sqlite3 --semantic --output reportes/recuperacion_real_semantica.json
```

La API actual de `local_rag` retorna como máximo ocho fragmentos: el informe lo
expone; Recall@10 no implica que se hayan obtenido diez. Los documentos sólo se
asocian a juicios cuando coinciden identidad y fragmento literal/ID, nunca sólo
porque aparece el título correcto. Los informes no sobrescriben resultados previos.

## Decisiones tecnológicas y fuentes oficiales consultadas

- Se conserva [SQLite FTS5/BM25](https://www.sqlite.org/fts5.html#the_bm25_function):
  ya instalado, índice ligero y sin servicio nuevo. PostgreSQL/pgvector, FAISS y
  BM25S no se incorporan sin demostrar un cuello de botella de escala.
- Se mantiene RRF y el embedder local actual. Los
  [cross-encoders](https://sbert.net/docs/cross_encoder/usage/usage.html) evalúan
  cada pareja consulta/documento y suelen costar más que un bi-encoder. No se
  añade un modelo a la GPU sin datos y medición que justifiquen su latencia.
- No se usan resúmenes generados automáticamente de catálogos como verdad de
  entrenamiento. Las páginas actuales de Gutenberg declaran expresamente ese
  origen para sus resúmenes; sólo los campos bibliográficos estructurados y
  evidencia textual autorizada pueden servir para verificación posterior.
- [Metamorphosis #5200](https://www.gutenberg.org/ebooks/5200) declara derechos
  reservados para esa traducción: no se deduce permiso para descargarla del
  dominio público de Kafka ni del acceso gratuito al catálogo.

No se ejecutó fine-tuning/LoRA, no se instalaron paquetes, no se cambiaron pesos
de Ollama y no hay APIs de pago. Sigue pendiente un conjunto humano independiente
de relaciones, entidades y respuestas factuales para evaluar esas métricas;
el comando las informa como `not_measured` en lugar de inventar valores.
