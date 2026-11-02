# Reorganización segura — primer lote, 28 de octubre de 2026

Objetivo: separar documentación, informes históricos y herramientas offline
sin cambiar el comportamiento externo ni mover los módulos de IA en este lote.

- [Inventario de dependencias, origen, destino y riesgos](inventory.md).
- [Estructura actual y siguiente lote](../../docs/architecture/REPOSITORY_LAYOUT.md).
- [Índice de documentación](../../docs/README.md).

Se respaldaron y comprobaron 13 archivos antes de preparar sus sustitutos en
`backups/reorganizacion_20261028_01`. Se conservaron las huellas de 282 archivos
de integración, pruebas, modelos, migraciones, configuración y presentación.
`.env` sólo se identificó por hash; no se copiaron ni imprimieron credenciales.

## Movimientos realizados

| Origen | Destino canónico |
| --- | --- |
| `README_ASISTENTE_IA.md` | `docs/guides/README_ASISTENTE_IA.md` |
| `MYSQL_LOCAL.md` | `docs/guides/MYSQL_LOCAL.md` |
| `ARQUITECTURA_IA_RENDIMIENTO.md` | `docs/architecture/ARQUITECTURA_IA_RENDIMIENTO.md` |
| `LEEME.md` | `docs/archive/LEEME_IA_V3.md` |
| `LitMate_IA_Gratis_Codigo_Completo.md` | `docs/archive/LitMate_IA_Gratis_Codigo_Completo.md` |
| `INFORME_ARQUITECTURA_IA_21_OCTUBRE.md` | `reports/archive/INFORME_ARQUITECTURA_IA_21_OCTUBRE.md` |
| `INFORME_BUSQUEDA_LITERARIA.md` | `reports/archive/INFORME_BUSQUEDA_LITERARIA.md` |
| `INFORME_CONTINUACION_20_OCTUBRE.md` | `reports/archive/INFORME_CONTINUACION_20_OCTUBRE.md` |
| `INFORME_FUENTES_MODELOS.md` | `reports/archive/INFORME_FUENTES_MODELOS.md` |
| `INFORME_RESULTADOS_21_OCTUBRE.md` | `reports/archive/INFORME_RESULTADOS_21_OCTUBRE.md` |
| `INFORME_SINOPSIS_DOCKER_20261026.md` | `reports/archive/INFORME_SINOPSIS_DOCKER_20261026.md` |
| `analizar_evaluacion_ia.py` | `scripts/analysis/analizar_evaluacion_ia.py` |
| `resumir_benchmark_ia.py` | `scripts/analysis/resumir_benchmark_ia.py` |

Antes, todos estaban en la raíz. Ahora hay índices `README.md`, `docs/README.md`,
`reports/README.md` y `scripts/README.md`. Los tres documentos principales
mantienen entradas compatibles en la raíz; los dos scripts antiguos delegan
en un único objeto de módulo canónico. Esto preserva imports, parches y estado.

Los originales se conservaron hasta comprobar las copias, 21 pruebas dirigidas,
43 enlaces y las huellas protegidas. Después se sustituyeron las cinco entradas
compatibles y se retiraron ocho archivos documentales de la raíz. Todos los
originales completos siguen en el respaldo verificado; el paquete histórico de
código y las implementaciones trasladadas conservan exactamente sus bytes.

## Referencias y rutas

- Rebasados los enlaces entre guías, índices e informes y las menciones de sus
  nombres antiguos. Ningún enlace local faltaba en el lote original.
- Los comandos de guías trasladadas siguen ejecutándose desde la raíz. Los
  analizadores conservan el significado de argumentos relativos al CWD del usuario.
- No se reescribieron los informes antiguos de `reportes/` ni datos relacionados
  por SHA256. Ese almacén operativo y continuidad mantienen sus rutas.
- `config/`, `requirements/`, `tests/` y `literary_ai/` no se crearon vacíos.
  Docker, requisitos y ejecutores conservan sus ubicaciones por sus dependencias.
- `.gitignore` conserva sus reglas previas y añade únicamente exclusiones para
  JSON/TXT derivados de estos lotes. Los informes Markdown sí son versionables.

## Pruebas y resultados

| Grupo | Resultado |
| --- | --- |
| Línea base de herramientas antiguas | 18 pruebas aprobadas, 0,232 s |
| Implementaciones copiadas, originales aún presentes | 21 aprobadas, 1,381 s |
| Corte y compatibilidad | 25 aprobadas, 1,426 s |
| Suite completa después del movimiento | 1.887 ejecutadas en 82,377 s; 1.886 aprobadas, una integración real optativa omitida por defecto |
| JavaScript, tarjetas, voz y transporte | 233 comprobaciones aprobadas |
| Archivos iniciales fuera del lote | 341 huellas iguales, cero cambios inesperados |
| `manage.py check --database default` | Aprobado con MySQL local real |
| Migraciones | 26 aplicadas, cero pendientes; sólo lectura, ninguna ejecutada |
| Imports y URL de chat | `core.*` y `core.literary_ai_views` correctos |
| MySQL local | 8.0.46, mysqlclient, `litmate_db`, 36 tablas y 2.945 filas |
| ORM real | 55 libros, 50 conversaciones, 190 mensajes |
| Ollama real | API local disponible, modelos locales reconocidos |
| SearXNG real | API JSON disponible, 20 resultados y cero motores fallidos en la consulta de prueba |
| Integración HTTP/SSE real optativa | Aprobada aparte en 9,108 s; cuatro turnos finalizados, tarjetas y enlaces conservados |

El descubrimiento pasó de 1.880 a 1.887 casos: siete comprobaciones nuevas de
reorganización, sin perder casos anteriores. Incluye regresiones de memoria,
sesiones, RAG, conocimiento, HTTP/SSE, fuentes, tarjetas, estáticos y plantillas.
Las pruebas generales utilizan proveedores simulados y SQLite aislado; la
comprobación MySQL y la disponibilidad de servicios se ejecutaron por separado
con servicios reales, sin reutilizar la importación ni editar credenciales.

La integración adicional usó Ollama y una ficha de Open Library reales en el
límite de presentación, HTTP/SSE y CSRF reales, sesiones firmadas y almacenes
temporales. Los cuatro turnos respondieron: 7,768 s la primera traducción,
0,032 s la repetición, 0,042 s la sinopsis y 0,040 s el inglés explícito. No es
un benchmark de ranking ni de toda una investigación web. Se redirigió su informe
a `http_sse_verified.json` dentro de este lote para no sobrescribir la evidencia
de la fase anterior en `reportes/idioma_20261028`.

La nueva prueba de identidad de migraciones falló inicialmente porque el
ejecutor aislado tiene `MIGRATION_MODULES=None` por aplicación. Se corrigió la
prueba para inspeccionar las migraciones en disco con `MigrationLoader(None)`
y override temporal sólo de pruebas, sin ejecutarlas ni tocar configuración real.

Artefactos locales: `inventory_before_assets.json`, `inventory_after.json`,
`staged_documents_verified.json`, `layout_verified.json`,
`unchanged_source_verified.json`, `runtime_verified.json`, `full_tests.txt`.
Inventarios JSON y registros TXT son artefactos locales ignorados; este informe
y el inventario Markdown permanecen versionables.

## Riesgos, límites y siguiente lote

No se trasladaron módulos de IA: se identificó una red amplia de imports
relativos, fixtures cruzados, patch strings, rutas `__file__` y nombres Django
persistidos. Permanecen en `core` modelos, migraciones, vistas, motor, RAG,
auditoría, proveedores y memoria. No se cambiaron app labels ni tablas.

No hubo migraciones, importaciones, instalaciones, commits ni push. `.env`,
configuración MySQL, arranque y todos los cambios previos se conservaron.
Los recuentos de MySQL incluyen las sesiones de actividad anteriores al lote;
no se volvió a importar ni se compararon como si debieran regresar al respaldo.

Siguiente lote: un grupo pequeño de pruebas de herramientas en `tests/tools`,
con control de descubrimiento y fixtures. Después, un módulo hoja de IA con
alias de módulo probado; no empezar por el motor, identidad, calidad ni RAG.
El plan detallado y los destinos propuestos están en el inventario y en
`docs/architecture/REPOSITORY_LAYOUT.md`.

Para revisar o revertir selectivamente este lote, usar el manifiesto y los
originales en `backups/reorganizacion_20261028_01`. Comparar primero las huellas
actuales para conservar ediciones posteriores; no se requiere resetear Git ni
restaurar bases. No se automatizó una reversión que pudiera sobrescribir trabajo.
