# Resumen del benchmark literario

- Fuente: `reportes\arquitectura_20261023\cache_entrega_despues_v5.json`
- Generado: `2026-10-23T19:36:45.403493+00:00`
- Certificación factual: `not_independently_certified`

## Global

| Métrica | Valor |
|---|---:|
| Turnos | 6 |
| Estados | {'answered': 6} |
| p50 | 0.042 s |
| Media | 0.234 s |
| p95 | 1.183 s |
| Máximo | 1.183 s |
| Bajo 5 s | 6 |
| Bajo 10 s | 6 |
| Bajo 30 s | 6 |
| Publicadas bajo 30 s (no certifica cobertura ni exactitud) | 6 |
| Primer progreso (p50) | 0.04 s |
| Primer texto (p50) | 0.042 s |
| Sobrecarga de entrega (p50) | 38.637 ms |
| Llamadas al modelo conocidas | 0 |
| Turnos con llamadas desconocidas | 0 |
| Aciertos de caché exacta | 5 |
| RSS máximo del servidor Python | 62.742 MB |
| CPU del servidor Python | 0.375 s |

## Por categoría

| Categoría | Turnos | Estados | p50 | p95 | Bajo 5 s | Bajo 30 s | Llamadas |
|---|---:|---|---:|---:|---:|---:|---:|
| cache_exacta | 6 | {'answered': 6} | 0.042 s | 1.183 s | 6 | 6 | 0 |

## Etapas instrumentadas

Los tiempos inclusivos pueden solaparse o ejecutarse en paralelo; no deben sumarse como latencia total.

| Etapa | Turnos | Total | Media por turno |
|---|---:|---:|---:|
| cache_lookup | 6 | 20.16 ms | 3.36 ms |
| knowledge_lookup | 1 | 62.197 ms | 62.197 ms |
| retrieval | 1 | 1023.054 ms | 1023.054 ms |
