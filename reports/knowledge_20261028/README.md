# Conocimiento MySQL + RAG: primer lote controlado

28 de octubre de 2026. Implementación real sobre el proyecto, sin reemplazar
Django, Ollama, los índices auxiliares ni las funciones de memoria y auditoría.

Arquitectura, políticas de fuentes, comandos y escalado en
[KNOWLEDGE_REPOSITORY.md](../../docs/architecture/KNOWLEDGE_REPOSITORY.md).

## Resultado real

- Respaldo previo `backups/conocimiento_mysql_20261028_01`: verificado, 36 tablas,
  2.945 filas, 88 archivos y SQLite portable. Se preparó antes de crear el esquema.
- Migración aditiva `core.0008_bibliographic_repository`: cinco tablas nuevas,
  cero DROP/TRUNCATE/DELETE/RENAME. Se inspeccionó el plan exacto y SQL antes de aplicarlo.
- Se comprobaron las claves y huellas de **cada una de las 2.945 filas originales**
  después del esquema, la ingesta y HTTP/SSE. Todas permanecen idénticas.
- Primer lote: **100 registros de catálogo Gutenberg**, proyectados como ediciones,
  100 nombres, 100 versiones y dos filas de control. No hay relaciones nuevas
  en este lote real porque el CSV no aporta IDs de autores u obras abstractas.
- Duplicados: repetición completa de 100 → **100 duplicados, cero inserciones**,
  sin aumentar registros, nombres ni versiones. Reanudación normal posterior:
  cursor 100 → 100, cero registros pendientes y proyector completo para ese ledger.
- Respaldo posterior `backups/conocimiento_mysql_20261028_02`: también verificado,
  **41 tablas, 3.273 filas, 89 archivos y SQLite portable con el esquema nuevo**.

El incremento total es 328 filas: 302 del repositorio y 26 de metadatos normales
Django (cinco ContentTypes, veinte permisos y una migración). Los usuarios,
mensajes, libros, pagos e IDs anteriores no se reemplazaron ni sobrescribieron.
MySQL conserva 55 libros del catálogo de la página, 50 conversaciones y 190 mensajes.

## Qué se importó y qué no

Se reutilizó `data/adquisicion/pg_catalog_20261027.csv.gz`, de 5.597.116 bytes,
SHA256 `ebf4f6e54a34dddbcd26ca8a5ef593c9cf3e0ab8b331628ea7a49170a196a07e`.
El importador existente leyó 124 filas, admitió 100 y rechazó 24 por sus reglas
de metadatos. No hubo rechazos en la proyección MySQL de las 100 admitidas.

**Cero descargas nuevas, cero textos completos y cero llamadas a APIs de pago.**
No se descargaron millones de registros ni se buscó masivamente con SearXNG.
Los importadores Open Library, Gutenberg y BNE, y las consultas acotadas Wikidata,
se reutilizan; los volcados gigantes y el enriquecimiento persistente Google
Books no se activaron. Las restricciones y enlaces oficiales están en la guía.

Los registros son nuevos en el repositorio MySQL, **no cien nuevas obras con
trama verificada**. La memoria ya conocía esos metadatos: antes y después mantiene
2.256 obras catalogadas, 842 autores normalizados y 2.388 fuentes vigentes.
No aumentaron las siete obras con descripciones admitidas, los 37 personajes ni
la cobertura narrativa. No se confundió el tamaño del catálogo con conocimiento
profundo de sus historias. No se recalcularon todos los embeddings.

## Conversación HTTP/SSE real con MySQL

Pregunta elegida dinámicamente entre registros SQL no presentes en el catálogo
de 55 libros, sin una excepción de código para ese título:

> ¿Quién escribió Thuvia, maid of Mars?

Respuesta real:

> **Thuvia, maid of Mars** es una obra de **Edgar Rice Burroughs**.
>
> Fuente de la ficha: https://www.gutenberg.org/ebooks/72

HTTP/SSE finalizado, estado `answered`, **0,3536 s en el cierre y cero llamadas
al LLM** (la ejecución anterior tardó 0,3166 s).
La tarjeta tenía identificador `sqlkb:02092dcb…`, título/autor correctos y enlaces
Amazon/Buscalibre. La portada y sinopsis quedan vacías porque no se importaron
esos contenidos; no se inventaron ni se cambiaron el diseño, voz o avatares.

La prueba usó Django, MySQL, CSRF y transporte reales, cookies de sesión firmadas
y servidor temporal sólo en loopback. No añadió conversaciones ni sesiones a
las tablas de lectores; se comprobó de nuevo la integridad original después.
Registros: `http_mysql_verified.json` y `http_mysql_closing.json`. No es una medición de generación narrativa
ni de búsquedas web complejas.

## Rendimiento y recursos observados

| Medición | Resultado |
| --- | --- |
| Importación existente: 100 metadatos al staging/memoria | 1,7192 s |
| Primera proyección a MySQL | 1,3894 s |
| Repetición inicial, 100 duplicados | 1,0687 s |
| Reanudar ledger ya procesado, cero registros | 0,0413 s |
| Autoría desde MySQL, 12 consultas | p50 10,81 ms; p95/máximo 35,71 ms |
| Primer pico de asignaciones Python del proyector | 545.536 bytes |
| Pico observado en otra ejecución del proceso | 2.964.936 bytes Python; RSS 58,13 MiB, pico RSS 59,14 MiB |
| Cuota contable de registros/versiones del piloto | 767.306 bytes |
| Estimación MySQL DATA_LENGTH + INDEX_LENGTH | 557.056 bytes para las cinco tablas |

RSS es del proceso Python del comprobador, no de todo el PC, MySQL ni Ollama.
La estimación de tablas no es el tamaño exacto de los archivos InnoDB. La cuota
contable tampoco es una cuota dura del servidor. Son mediciones de 100 registros
y 12 consultas; no certifican millones de filas ni un p95 general del asistente.

Transacciones de 25, una proyección concurrente, registros de entrada de hasta
64 KiB, tiempo acotado y almacenamiento configurable. El límite temporal se
comprueba también entre registros del lote. No se lanzó un trabajador permanente.

## Pruebas y fallos detectados

Las regresiones de `core/test_bibliographic_repository.py` cubren:

- obra/edición/autor, IDs e ISBN, alias y autores homónimos;
- ediciones e idiomas distintos; títulos literales que parecen saludos;
- fuente/política/licencia y rechazo de host suplantado;
- staging no admitido, corrupción parcial y ausencia de tramas;
- idempotencia, corte transaccional, reanudación y actualización incremental;
- preservación de versiones y cuarentena de conflictos, incluidas ediciones;
- no sustituir descripciones locales verificadas por una ficha mínima;
- límites de almacenamiento, truncamiento de candidatos ambiguos y fechas antiguas;
- exclusión de datos generados/privados y revisión explícita del operador.

Se conservan los resultados intermedios. La primera prueba real del piloto
insertó los 100 registros pero **falló la respuesta**: Gutenberg no figuraba
en la admisión bibliográfica de la ruta rápida. Se reprodujo con dos regresiones
fallidas, se añadió una rama cerrada por host/ruta/política/licencia y se verificó
que los metadatos continuaran sin autorizar sinopsis. El informe inicial
`pilot_real.json` conserva `passed=false`; los posteriores `replay_verified.json`,
`resume_final.json` y `http_mysql_verified.json` muestran la corrección verificada.

También se detectó y corrigió que repetir la versión anterior pudiera levantar
una cuarentena, que el límite ocultara homónimos y que normalizar un saludo
alterara un título. No se relajó la auditoría factual ni se añadieron respuestas
preparadas para libros concretos.

Resultados completos de cierre: **1.908 ejecutadas en 86,890 s, 1.907 aprobadas
y una integración optativa omitida**; consultar `full_closing.txt`. Las 21
regresiones nuevas pasaron también por separado (4,507 s). HTTP/SSE real se
validó aparte. JavaScript: 233 comprobaciones aprobadas.
La última ejecución dirigida de repositorio, transferencia y activación MySQL
pasó sus 39 pruebas en 13,794 s (`closing_directed.txt`).
Las pruebas generales usan SQLite aislado y proveedores simulados; las pruebas
de ingesta, consulta y HTTP descritas arriba utilizaron MySQL local real.

## Archivos principales

- Nuevos: `core/knowledge_models.py`, `core/bibliographic_repository.py`,
  `core/bibliographic_operations.py`, `core/bibliographic_http_probe.py`,
  `core/migrations/0008_bibliographic_repository.py`,
  `core/management/commands/proyectar_catalogo_mysql.py`,
  `core/test_bibliographic_repository.py`, `scripts/knowledge/mysql_control.py`.
- Integración: `core/models.py` registra sólo los modelos nuevos;
  `ai_quick_answers`, `literary_search` y `ai_answer_cache` añaden recuperación y
  revisión de cachés. `ai_catalog_fallback` admite catálogos de metadatos únicamente
  bajo sus reglas cerradas. La generación/auditoría narrativa conserva sus validadores.
- Configuración pública: `.env.example` documenta `LITMATE_STRUCTURED_KNOWLEDGE=auto`;
  `.gitignore` excluye sólo los artefactos JSON/TXT de este lote. `.env` no cambió.
- Guía, índices y continuidad actualizados. Ninguna instalación, nuevo modelo,
  API comercial, commit ni push.

## Pendientes explícitos

No se validó capacidad de millones de obras. No se importaron personajes,
relaciones narrativas ni sinopsis nuevas con este CSV. Los hechos narrativos,
conflictos y tareas de actualización existentes continúan en SQLite/RAG.
Faltan equivalencias cruzadas entre proveedores con pruebas, ingesta directa
de volcados Wikidata, interfaz de revisión, evaluación multilingüe a mayor escala
y mediciones de índices/espacio en lotes 1.000 y 10.000.

El registro de una corrección humana documenta una declaración del operador y
su fuente; no implica verificación automática universal. No se entrenaron ni
modificaron pesos de Qwen. Añadir registros persistentes, indexar y aprender de
señales agregadas no equivale a entrenar un modelo.
