# Descubrimiento rápido con objetivo de 30 segundos — resultados reales

Fecha: 22-10-2026. Rama `feature/cuotas-ia-chatbot`.
Punto de partida: `253e029`, etiqueta local
`checkpoint/antes-descubrimiento-30s-20261022`.
Código de esta intervención: `45babb1`.
Sin push, sin migraciones y sin cambios en `.env`.

## Objetivo

- El navegador espera como máximo **30 s** por la petición completa; el backend
  trabaja como máximo **29 s** (`CHAT_RESPONSE_SECONDS=30`,
  `CHAT_WORK_SECONDS=29` y `chat_timeout()` con tope 29).
- La prioridad es el **descubrimiento rápido de libros y temas**, no la
  generación larga del modelo.
- Antes de generar, se consulta un **diccionario local amplio** de materias,
  lugares, alias y etiquetas.
- No se desactivan auditorías ni se inventan datos bibliográficos para cumplir
  el plazo.

## Resultado vigente

- Dos ejecuciones HTTP/SSE reales completaron **8/8 turnos antes de 30 s**;
  p95 y máximo **29,014 s**.
- La secuencia exacta de la captura responde **sin llamar al modelo**:
  Segunda Guerra Mundial **0,078 s**, seguimiento de Primera Guerra Mundial
  **0,024 s** y Antigua Grecia **0,063 s**, cada turno con tres obras y tres
  fuentes.
- La ejecución v2 publicó **6 respuestas y 2 no disponibles**; las no
  disponibles (Guerra Fría y «Guerra y Paz») agotaron el límite sin inventar
  datos.
- `source_files_changed_during_run=false` en ambas: el código no cambió
  durante la medición. `factual_review=not_independently_certified`: se midió
  estado, latencia y procedencia, no exactitud factual.

## Qué cambió

- `core/topic_reference.py` + `core/data/topic_reference.json`: diccionario
  local con **230 facetas, 252 temas y 929 alias** (~117 KB), sin límite
  artificial. Resuelve frases completas, suprime solapamientos más cortos,
  respeta exclusiones de género y restaura artículos/acentos para el texto
  visible.
- `core/books_google.py`: convierte materias y lugares del diccionario en
  consultas de catálogo; guardia de título para «Guerra y Paz» (no se
  interpreta como tema); `topic_matches()` usa `source_synopsis()`, incluida
  `description`, para no descartar fichas válidas sin `synopsis`/`categories`.
- `core/literary_search.py`: `retrieve_discovery_books()` combina catálogo
  local y Open Library/Google con búsquedas ligeras (sin resúmenes), acepta
  en cuanto hay suficientes fichas del tema y trabaja con presupuesto anidado
  de **18 s**.
- `core/literary_ai_views.py`: el descubrimiento se ejecuta antes del modelo;
  si no hay ninguna ficha de libro, responde `unavailable` en el acto
  (`provider_error: sin_fuentes_verificables`) en lugar de esperar al 9B o
  permitir una recomendación inventada.
- Fichas verificadas en vivo para Primera Guerra Mundial (David Stevenson,
  Max Hastings, Barbara W. Tuchman) y Antigua Grecia (Indro Montanelli,
  Isaac Asimov, Tucídides), además de las de Segunda Guerra Mundial.
- `core/ai_catalog_fallback.py`: etiquetas y artículos de las facetas del
  diccionario; el respaldo temático deja de exigir una lista fija de temas.
- `static/js/litmate_safe.js` y `evaluar_chat_http.py`: el cliente corta a los
  **30 s** y el benchmark mide con presupuesto de 29 s.
- Pruebas: `core/test_topic_reference.py` (integridad del diccionario) y
  `core/test_topic_discovery.py` (aceptación temprana con varias fuentes).

## Antes y después de la captura

`reportes/descubrimiento_30s_20261022/antes_captura.json` conserva la
medición con el presupuesto anterior de 9 s (archivos de fuente sin cambios
durante la ejecución):

| Turno | Antes (9 s) | Después (29 s) |
|---|---|---|
| Segunda Guerra Mundial | answered 0,056 s | answered 0,078 s |
| Seguimiento de Primera Guerra Mundial | unavailable 9,015 s | answered 0,024 s |
| Antigua Grecia | unavailable 9,012 s | answered 0,063 s |

La primera ya pasaba; las otras dos no cabían en 9 s. Con fichas verificadas
locales, las tres responden en menos de una décima de segundo.

## Ejecuciones reales de 30 s

Método: `evaluar_chat_http.py` levanta un servidor loopback con CSRF, cookies,
sesión y SSE reales, sobre una base temporal vacía creada con `schema_editor`;
Ollama y las fuentes públicas son reales, sin mocks.

| Caso | v1 `benchmark_30s_descubrimiento_20261022.json` | v2 `..._v2.json` |
|---|---|---|
| Captura, turno 1 (Segunda Guerra Mundial) | answered 0,086 s | answered 0,078 s |
| Captura, turno 2 (Primera Guerra Mundial, seguimiento) | answered 0,025 s | answered 0,024 s |
| Captura, turno 3 (Antigua Grecia) | answered 0,025 s | answered 0,063 s |
| Revolución Francesa | unavailable 29,005 s | answered 26,808 s |
| Guerra Fría | unavailable 12,279 s | unavailable 29,014 s |
| Historia de Corea del Sur | unavailable 0,778 s | answered 2,101 s |
| «Guerra y Paz» (título) | clarification 14,805 s | unavailable 29,007 s |
| Aventuras espaciales | clarification 1,098 s | answered 2,849 s |
| **Métricas** | 8/8 bajo 30 s; p50 0,938 s; p95/máx 29,005 s; 3 answered, 3 unavailable, 2 clarification | 8/8 bajo 30 s; p50 2,475 s; p95/máx 29,014 s; 6 answered, 2 unavailable |

Detalles observados en v2:

- **Revolución Francesa** (26,808 s, 2 llamadas al modelo): lista tres obras
  del catálogo (Stephens, Thompson y Taine) sin URL visible en el texto final.
- **Corea del Sur** (2,101 s, 0 llamadas al modelo) y **Aventuras espaciales**
  (2,849 s, 0 llamadas): respaldo temático con tres fichas cada uno, sin URL
  visible en el texto final; la procedencia queda en las fichas internas.
- **Guerra Fría** y **«Guerra y Paz»** agotaron el presupuesto y respondieron
  `unavailable` con el mensaje honesto de límite, sin títulos inventados.

## Fuentes externas inestables

El mismo 22-10-2026 se sondeó `retrieve_discovery_books` directamente para
cuatro temas (Guerra Fría, Corea del Sur, Revolución Francesa y aventuras
espaciales): en los cuatro el catálogo local devolvió `ok` pero vacío, Open
Library respondió `timeout` o `cooldown` y no hubo fichas de libro (0
resultados en 1,8–8,7 s). Por eso la cobertura de temas nuevos depende todavía
del estado de Open Library/Google Books. El diccionario local evita la
ambigüedad, pero no sustituye a las fuentes: cuando no hay fichas, la respuesta
es una abstención rápida, no una invención.

## Pruebas ejecutadas

```text
.\venv\Scripts\python.exe -B manage.py test core --keepdb
-> 1134 pruebas core OK en 252,578 s
   (incluye las nuevas de diccionario y descubrimiento)

.\venv\Scripts\python.exe -B manage.py test suscripciones.test_payments core.test_quotas --keepdb
-> 17 pruebas OK en 74,747 s (13 de pagos y 4 de cuotas)

node verificar_chat_seguro.js
-> 198 comprobaciones JavaScript OK
```

## Límites honestos

1. No hay revisión factual independiente; exactitud y tasa de error factual
   siguen en `null`.
2. El benchmark usa una base temporal SQLite, no la base MySQL real de la
   cuenta; no mide el guardado de sesión en producción.
3. Los turnos que agotan el presupuesto responden en ~29 s, justo por debajo
   del corte de 30 s del navegador; en una red más lenta podrían llegar al
   límite del cliente.
4. Dos temas nuevos quedaron `unavailable` por falta de fichas verificables;
   no se sustituyeron por conocimiento del modelo.
5. Las respuestas de respaldo temático muestran las obras, pero no siempre las
   URL en el texto final; la procedencia existe en las fichas, pero su
   presentación al lector es mejorable.
6. No se modificó `.env`, no se ejecutaron migraciones y no se hizo push.

## Reproducción

```powershell
.\venv\Scripts\python.exe -B manage.py test core --keepdb
.\venv\Scripts\python.exe -B manage.py test suscripciones.test_payments core.test_quotas --keepdb
node verificar_chat_seguro.js

.\venv\Scripts\python.exe -B evaluar_chat_http.py `
  --matrix C:\ruta\matrix_30s.json `
  --model qwen3.5:9b-q4_K_M `
  --output reportes\benchmark_30s_descubrimiento_20261022_v2.json
```

## Archivos de esta intervención

- Código: `core/topic_reference.py`, `core/books_google.py`,
  `core/literary_search.py`, `core/literary_ai_views.py`,
  `core/ai_quick_answers.py`, `core/ai_catalog_fallback.py`,
  `core/ai_budget.py`, `core/local_llm.py`, `litmate_project/ai_settings.py`,
  `core/management/commands/diagnosticar_ia.py`.
- Datos: `core/data/topic_reference.json`, `core/data/verified_readings.json`.
- Cliente y medición: `static/js/litmate_safe.js`, `evaluar_chat_http.py`,
  `verificar_chat_seguro.js`.
- Pruebas: `core/test_topic_reference.py`, `core/test_topic_discovery.py`,
  `core/test_chat_deadline.py`, `core/test_ai_runtime.py`,
  `core/test_ai_quality.py`, `core/test_literary_ai.py`,
  `core/test_literary_conversation.py`, `core/test_local_ai.py`,
  `core/test_google_books.py`, `core/test_free_topic_recommendations.py`,
  `core/test_space_topic_recommendations.py`.
- Reportes: este informe, `reportes/continuidad_opencode.md`,
  `reportes/benchmark_30s_descubrimiento_20261022.json` y `_v2.json`.
