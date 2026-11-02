# Resumen del benchmark literario

- Fuente: `reportes\arquitectura_20261023\integral_progressive_v3_4b_warm.json`
- Generado: `2026-10-23T19:33:28.346693+00:00`
- Certificación factual: `not_independently_certified`

## Global

| Métrica | Valor |
|---|---:|
| Turnos | 16 |
| Estados | {'answered': 9, 'unavailable': 5, 'clarification': 2} |
| p50 | 2.341 s |
| Media | 7.664 s |
| p95 | 24.647 s |
| Máximo | 24.647 s |
| Bajo 5 s | 10 |
| Bajo 10 s | 10 |
| Bajo 30 s | 16 |
| Publicadas bajo 30 s (no certifica cobertura ni exactitud) | 9 |
| Primer progreso (p50) | 0.017 s |
| Primer texto (p50) | 2.341 s |
| Sobrecarga de entrega (p50) | 128.689 ms |
| Llamadas al modelo conocidas | 27 |
| Turnos con llamadas desconocidas | 0 |
| Aciertos de caché exacta | 0 |
| RSS máximo del servidor Python | 73.754 MB |
| CPU del servidor Python | 3.25 s |

## Por categoría

| Categoría | Turnos | Estados | p50 | p95 | Bajo 5 s | Bajo 30 s | Llamadas |
|---|---:|---|---:|---:|---:|---:|---:|
| cache_exacta | 2 | {'answered': 2} | 8.159 s | 15.297 s | 1 | 2 | 3 |
| cita_exacta | 1 | {'unavailable': 1} | 13.267 s | 13.267 s | 0 | 1 | 4 |
| conocimiento_indexado | 1 | {'answered': 1} | 0.177 s | 0.177 s | 1 | 1 | 0 |
| fuentes_contradictorias | 1 | {'unavailable': 1} | 18.212 s | 18.212 s | 0 | 1 | 4 |
| identificacion_por_escena | 1 | {'clarification': 1} | 4.472 s | 4.472 s | 1 | 1 | 2 |
| materia_general | 1 | {'unavailable': 1} | 24.647 s | 24.647 s | 0 | 1 | 5 |
| multiturno_memoria | 2 | {'answered': 2} | 1.58 s | 2.033 s | 2 | 2 | 0 |
| multiturno_recomendacion | 2 | {'unavailable': 1, 'clarification': 1} | 12.031 s | 22.38 s | 1 | 2 | 4 |
| relacion_personajes | 1 | {'unavailable': 1} | 11.689 s | 11.689 s | 0 | 1 | 5 |
| simple_autoria | 1 | {'answered': 1} | 2.65 s | 2.65 s | 1 | 1 | 0 |
| simple_personajes | 1 | {'answered': 1} | 1.259 s | 1.259 s | 1 | 1 | 0 |
| simple_protagonista | 1 | {'answered': 1} | 1.183 s | 1.183 s | 1 | 1 | 0 |
| simple_sinopsis | 1 | {'answered': 1} | 1.528 s | 1.528 s | 1 | 1 | 0 |

## Etapas instrumentadas

Los tiempos inclusivos pueden solaparse o ejecutarse en paralelo; no deben sumarse como latencia total.

| Etapa | Turnos | Total | Media por turno |
|---|---:|---:|---:|
| audit | 9 | 24863.255 ms | 2762.584 ms |
| cache_lookup | 16 | 64.583 ms | 4.036 ms |
| extraction | 1 | 329.554 ms | 329.554 ms |
| generation | 6 | 27198.292 ms | 4533.049 ms |
| intent | 7 | 29.222 ms | 4.175 ms |
| knowledge_lookup | 16 | 758.762 ms | 47.423 ms |
| local_search | 7 | 78.701 ms | 11.243 ms |
| model_inspection | 7 | 194.846 ms | 27.835 ms |
| repair | 5 | 22460.281 ms | 4492.056 ms |
| retrieval | 14 | 17025.1 ms | 1216.079 ms |
| routing | 6 | 17215.379 ms | 2869.23 ms |
| web_search | 6 | 15068.899 ms | 2511.483 ms |

## Etapas del modelo

| Etapa | Llamadas registradas | Total |
|---|---:|---:|
| answer | 6 | 27198.0 ms |
| audit | 5 | 24850.0 ms |
| plan | 5 | 8635.0 ms |
| repair | 5 | 22460.0 ms |
| route | 6 | 8581.0 ms |

## Revisión interna de cobertura

No es una certificación factual independiente.

| Clasificación | Turnos |
|---|---:|
| adequate_basic_answer | 4 |
| partial_missing_requested_detail | 4 |
| contains_unverified_extra_claims | 1 |
| unavailable | 5 |
| clarification_without_context | 1 |
| clarification_missing_evidence | 1 |

Turnos sin revisión: 0.
