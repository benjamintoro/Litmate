# Resumen del benchmark literario

- Fuente: `reportes\arquitectura_20261023\integral_progressive_v2_9b_warm.json`
- Generado: `2026-10-23T19:33:28.307900+00:00`
- Certificación factual: `not_independently_certified`

## Global

| Métrica | Valor |
|---|---:|
| Turnos | 16 |
| Estados | {'answered': 9, 'unavailable': 5, 'clarification': 2} |
| p50 | 2.425 s |
| Media | 11.103 s |
| p95 | 35.114 s |
| Máximo | 35.114 s |
| Bajo 5 s | 10 |
| Bajo 10 s | 10 |
| Bajo 30 s | 13 |
| Publicadas bajo 30 s (no certifica cobertura ni exactitud) | 9 |
| Primer progreso (p50) | 0.017 s |
| Primer texto (p50) | 2.425 s |
| Sobrecarga de entrega (p50) | 130.796 ms |
| Llamadas al modelo conocidas | 25 |
| Turnos con llamadas desconocidas | 0 |
| Aciertos de caché exacta | 1 |
| RSS máximo del servidor Python | 71.875 MB |
| CPU del servidor Python | 2.875 s |

## Por categoría

| Categoría | Turnos | Estados | p50 | p95 | Bajo 5 s | Bajo 30 s | Llamadas |
|---|---:|---|---:|---:|---:|---:|---:|
| cache_exacta | 2 | {'answered': 2} | 0.747 s | 1.348 s | 2 | 2 | 0 |
| cita_exacta | 1 | {'unavailable': 1} | 21.189 s | 21.189 s | 0 | 1 | 4 |
| conocimiento_indexado | 1 | {'answered': 1} | 0.167 s | 0.167 s | 1 | 1 | 0 |
| fuentes_contradictorias | 1 | {'unavailable': 1} | 31.129 s | 31.129 s | 0 | 0 | 4 |
| identificacion_por_escena | 1 | {'clarification': 1} | 11.991 s | 11.991 s | 0 | 1 | 2 |
| materia_general | 1 | {'unavailable': 1} | 35.114 s | 35.114 s | 0 | 0 | 4 |
| multiturno_memoria | 2 | {'answered': 2} | 1.746 s | 2.169 s | 2 | 2 | 0 |
| multiturno_recomendacion | 2 | {'unavailable': 1, 'clarification': 1} | 18.266 s | 35.07 s | 1 | 1 | 6 |
| relacion_personajes | 1 | {'unavailable': 1} | 27.514 s | 27.514 s | 0 | 1 | 5 |
| simple_autoria | 1 | {'answered': 1} | 2.681 s | 2.681 s | 1 | 1 | 0 |
| simple_personajes | 1 | {'answered': 1} | 3.247 s | 3.247 s | 1 | 1 | 0 |
| simple_protagonista | 1 | {'answered': 1} | 1.511 s | 1.511 s | 1 | 1 | 0 |
| simple_sinopsis | 1 | {'answered': 1} | 1.581 s | 1.581 s | 1 | 1 | 0 |

## Etapas instrumentadas

Los tiempos inclusivos pueden solaparse o ejecutarse en paralelo; no deben sumarse como latencia total.

| Etapa | Turnos | Total | Media por turno |
|---|---:|---:|---:|
| audit | 8 | 35500.043 ms | 4437.505 ms |
| cache_lookup | 16 | 63.386 ms | 3.962 ms |
| generation | 5 | 48138.38 ms | 9627.676 ms |
| intent | 6 | 12.078 ms | 2.013 ms |
| knowledge_lookup | 15 | 772.205 ms | 51.48 ms |
| local_search | 6 | 62.522 ms | 10.42 ms |
| model_inspection | 6 | 194.564 ms | 32.427 ms |
| repair | 4 | 26551.851 ms | 6637.963 ms |
| retrieval | 13 | 22321.299 ms | 1717.023 ms |
| routing | 5 | 32299.957 ms | 6459.991 ms |
| web_search | 5 | 11380.408 ms | 2276.082 ms |

## Etapas del modelo

| Etapa | Llamadas registradas | Total |
|---|---:|---:|
| answer | 5 | 48138.0 ms |
| audit | 5 | 35494.0 ms |
| plan | 5 | 19692.0 ms |
| repair | 5 | 26552.0 ms |
| route | 5 | 12607.0 ms |

## Revisión interna de cobertura

No es una certificación factual independiente.

| Clasificación | Turnos |
|---|---:|
| adequate_basic_answer | 5 |
| partial_missing_requested_detail | 4 |
| unavailable | 5 |
| clarification_without_context | 1 |
| clarification_missing_evidence | 1 |

Turnos sin revisión: 0.
