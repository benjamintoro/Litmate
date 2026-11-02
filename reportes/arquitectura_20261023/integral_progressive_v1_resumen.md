# Resumen del benchmark literario

- Fuente: `reportes\arquitectura_20261023\integral_progressive_v1.json`
- Generado: `2026-10-23T19:29:35.367589+00:00`
- Certificación factual: `not_independently_certified`

## Global

| Métrica | Valor |
|---|---:|
| Turnos | 16 |
| Estados | {'answered': 11, 'unavailable': 4, 'clarification': 1} |
| p50 | 2.415 s |
| Media | 12.313 s |
| p95 | 35.169 s |
| Máximo | 35.169 s |
| Bajo 5 s | 10 |
| Bajo 10 s | 10 |
| Bajo 30 s | 13 |
| Publicadas bajo 30 s (no certifica cobertura ni exactitud) | 10 |
| Primer progreso (p50) | 0.017 s |
| Primer texto (p50) | 2.415 s |
| Sobrecarga de entrega (p50) | 123.305 ms |
| Llamadas al modelo conocidas | 25 |
| Turnos con llamadas desconocidas | 0 |
| Aciertos de caché exacta | 0 |
| RSS máximo del servidor Python | 84.906 MB |
| CPU del servidor Python | 3.109 s |

## Por categoría

| Categoría | Turnos | Estados | p50 | p95 | Bajo 5 s | Bajo 30 s | Llamadas |
|---|---:|---|---:|---:|---:|---:|---:|
| cache_exacta | 2 | {'answered': 2} | 0.591 s | 1.03 s | 2 | 2 | 0 |
| cita_exacta | 1 | {'unavailable': 1} | 27.412 s | 27.412 s | 0 | 1 | 4 |
| conocimiento_indexado | 1 | {'answered': 1} | 0.161 s | 0.161 s | 1 | 1 | 0 |
| fuentes_contradictorias | 1 | {'answered': 1} | 28.181 s | 28.181 s | 0 | 1 | 4 |
| identificacion_por_escena | 1 | {'unavailable': 1} | 18.942 s | 18.942 s | 0 | 1 | 4 |
| materia_general | 1 | {'unavailable': 1} | 35.138 s | 35.138 s | 0 | 0 | 4 |
| multiturno_memoria | 2 | {'answered': 2} | 1.528 s | 1.919 s | 2 | 2 | 0 |
| multiturno_recomendacion | 2 | {'unavailable': 1, 'clarification': 1} | 18.534 s | 35.169 s | 1 | 1 | 4 |
| relacion_personajes | 1 | {'answered': 1} | 35.099 s | 35.099 s | 0 | 0 | 5 |
| simple_autoria | 1 | {'answered': 1} | 2.91 s | 2.91 s | 1 | 1 | 0 |
| simple_personajes | 1 | {'answered': 1} | 1.445 s | 1.445 s | 1 | 1 | 0 |
| simple_protagonista | 1 | {'answered': 1} | 4.848 s | 4.848 s | 1 | 1 | 0 |
| simple_sinopsis | 1 | {'answered': 1} | 1.567 s | 1.567 s | 1 | 1 | 0 |

## Etapas instrumentadas

Los tiempos inclusivos pueden solaparse o ejecutarse en paralelo; no deben sumarse como latencia total.

| Etapa | Turnos | Total | Media por turno |
|---|---:|---:|---:|
| audit | 9 | 32715.191 ms | 3635.021 ms |
| cache_lookup | 16 | 62.586 ms | 3.912 ms |
| extraction | 1 | 1196.061 ms | 1196.061 ms |
| generation | 6 | 68355.39 ms | 11392.565 ms |
| intent | 6 | 3.048 ms | 0.508 ms |
| knowledge_lookup | 16 | 780.642 ms | 48.79 ms |
| local_search | 6 | 65.548 ms | 10.925 ms |
| model_inspection | 6 | 186.046 ms | 31.008 ms |
| repair | 5 | 32732.966 ms | 6546.593 ms |
| retrieval | 13 | 16616.101 ms | 1278.162 ms |
| routing | 5 | 33096.395 ms | 6619.279 ms |
| web_search | 6 | 11756.298 ms | 1959.383 ms |

## Etapas del modelo

| Etapa | Llamadas registradas | Total |
|---|---:|---:|
| answer | 6 | 68355.0 ms |
| audit | 4 | 32706.0 ms |
| plan | 5 | 19924.0 ms |
| repair | 5 | 32733.0 ms |
| route | 5 | 13171.0 ms |

## Revisión interna de cobertura

No es una certificación factual independiente.

| Clasificación | Turnos |
|---|---:|
| adequate_basic_answer | 5 |
| partial_missing_requested_detail | 3 |
| wrong_entity | 1 |
| unavailable | 4 |
| clarification_without_context | 1 |
| irrelevant_reference | 2 |

Turnos sin revisión: 0.
