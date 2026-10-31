# Conocimiento literario, investigación y rendimiento — 30/10/2026

> Actualizaci?n de continuidad: las correcciones posteriores de identidad, parentescos, recuperaci?n de La Odisea y evaluaci?n biling?e est?n en [continuacion_estabilizacion.md](continuacion_estabilizacion.md). Incluye la bater?a completa de 2.157 pruebas y las conversaciones actuales; las cifras de las rondas anteriores que siguen abajo se conservan como hist?rico.


Estado: correcciones implementadas y verificadas; **la misión completa de cobertura y calidad sigue parcialmente pendiente**. El chat conserva diseño, tarjetas, avatares, voz y sus servicios. No se reconstruyó el proyecto ni se descargaron otra vez los volcados.

## A. Conocimiento incorporado

Se procesaron 120 obras existentes: piloto de 20, ampliación hasta 100 y un segundo corpus revisado de 20. Los 120 checkpoints individuales se conservan; las ejecuciones posteriores omiten sus salidas existentes. Hubo 118 trabajos reclamados, 18 completados y 25 fuentes admitidas en estos lotes. Otros trabajos quedaron diferidos o no eran elegibles por su backoff previo. **Examinar 120 obras no equivale a enriquecerlas todas.**

Un lote adicional de cuatro requisitos temáticos admitió una fuente introductoria, pero ninguno alcanzó evidencia temática suficiente. Una incorporación pública explícita de Dandadan admitió su artículo oficial de Wikipedia, tras contrastar autor y premisa con VIZ. No se promovió la redacción del modelo ni se convirtió un resultado comercial en contenido con licencia libre.

Cobertura global, recalculada sobre ambos snapshots con la misma política de lectura V3:

| Dimensión | Inicial | Final | Cambio |
|---|---:|---:|---:|
| Identidades en memoria | 14.466 | 14.467 | +1 |
| Obras con descripción web admitida | 17 | 41 | +24 |
| Obras con evidencia etiquetada y admitida de argumento | 13 | 26 | +13 |
| Obras con extracto distribuido de desarrollo | 10 | 18 | +8 |
| Personajes con roles literales, distintos por obra/nombre normalizado | 81 | 94 | +13 |
| Obras con roles literales | 9 | 11 | +2 |
| Relaciones explícitas | 2 | 2 | 0 |
| Hechos narrativos admitidos por la política | 30 | 61 | +31 |

Fuente: `quality_policy_v3.json`. Estas dimensiones no son etapas excluyentes. Un extracto distribuido no garantiza un argumento completo, ni una atribución/licencia prueba cada afirmación de forma independiente. No hay nuevos hechos temáticos de no ficción suficientemente respaldados en el lote específico; la introducción admitida no se cuenta como una tarea temática resuelta.

La clasificación anterior contaba 35 obras con etiquetas de argumento y 70 hechos. La revisión V3 excluye de la recuperación premisas cortadas o meramente bibliográficas: quedan 26 y 61. Se conserva cada registro original y su hash; es una proyección de lectura, no un borrado para mejorar indicadores.

El primer selector experimental favorecía títulos cortos y concentró demasiadas candidatas CJK, con escasa cobertura en los lectores actuales es/en. Se conservó ese resultado negativo y se ejecutó un corpus adicional, sin reintentar artificialmente las tareas fallidas. El selector para planes nuevos usa demanda, idiomas disponibles y una reserva para otros idiomas; el trabajador continuo conserva su cursor rotativo y sus límites por autor.

No se crearon tablas: se reutilizaron `memory_works`, aliases, fuentes, aserciones, entidades, historial, cola y uso; MySQL conserva sus registros bibliográficos y ahora 23 referencias adicionales `KBRelation.memory_evidence`. Una edición sigue siendo una edición. Las referencias se enlazan por URL de catálogo exacta y única; no por parecido de título.

## B. Investigación de obras inicialmente desconocidas

`frozen.json` fijó 22 casos antes del enriquecimiento. La revisión conservadora de variantes, almacenes públicos y copia previa del RAG dejó **12 ausencias iniciales**, no las 13 del primer recuento. Se documentó la omisión inicial del índice cuyo path se obtiene por defecto, sin sobrescribir el inventario. Véase `absence_review.json` y [referencias independientes](referencias.md).

Se ejecutaron 22 primeras consultas HTTP/SSE, repeticiones en sesiones nuevas y 12 pruebas offline finales con caché exacta vacía. Las respuestas se generaron con Ollama real y consultas bibliográficas reales. Los dobles de red/modelo pertenecen sólo a las pruebas automáticas, separadas de estos archivos.

La investigación del benchmark usa una copia pública persistente en `research/`; no se presenta como ingesta global. Varias búsquedas persistieron identidad de Open Library, pero **no su sinopsis protegida**. Eso explica que algunas repeticiones tengan una ficha y sigan sin poder explicar su contenido sin Internet. Sólo dos obras inicialmente desconocidas —Dandadan y El invencible verano de Liliana— respondieron en la prueba offline final de ese perfil. The Jade Cabinet también respondió, pero ya existía inicialmente. Dandadan se incorporó además a la memoria global por la ruta de fuentes admitidas y volvió a responder allí.

La primera implementación del control offline bloqueaba sockets públicos pero dejaba accesible el contenedor SearXNG de localhost. Se corrigió el experimento: **sólo los registros con `offline_guard_version=2`** acreditan el modo offline de campaña; desactivan los proveedores y bloquean sockets públicos. El instrumento `search_narrative_check --local-only` ya mantenía ambos controles. No se detuvo Docker ni se alteró su conectividad.

Google Books se probó en un perfil adicional con las banderas de confirmación sin facturación, usando la autorización previa del usuario y sin editar `.env`. Respondió una de seis consultas con contenido (Mugre rosa); hubo errores de proveedor y rechazos de auditoría. No constituye disponibilidad garantizada. La búsqueda convencional de Google no se automatizó ni se extrajo su HTML: **no hay una comparación cronometrada válida contra Google ni una superioridad demostrada**. Las referencias editoriales, de autores y bibliotecas sirven de contraste manual de identidad/premisa, no de veredicto automático para toda la respuesta.

## C. Rendimiento medido

Datos reproducibles en `metricas.json` y `case_*.json`; p95 por rango más próximo:

| Muestra | n | Estado answered | Media | p50 | p95 | Bajo 30 s |
|---|---:|---:|---:|---:|---:|---:|
| Primera ronda fría | 22 | 13 | 13,44 s | 10,56 s | 35,06 s | 19 |
| Perfil frío posterior, mismo snapshot inicial | 22 | 12 | 5,39 s | 5,16 s | 9,36 s | 22 |
| Offline estricto, sesión/caché de respuesta nueva | 12 | 3 | 1,80 s | 0,60 s | 14,54 s | 12 |

**No se obtuvo una mejora global de cobertura: 13→12 respuestas `answered` en las rondas frías.** Parte de la reducción de tiempo corresponde a abstenciones más rápidas y a disponibilidad variable de los proveedores. No se afirma una ganancia de exactitud ni un SLA p95 de producción. Los dos barridos fríos se hicieron en momentos distintos; el segundo precede a los últimos filtros de secciones/premisas. Las pruebas HTTP finales locales sí usan el código final. No se suman estos indicadores como muestras independientes de calidad.

Correcciones con evidencia concreta:

- «Explica el contenido…» no entraba en la ruta narrativa. Los tres casos de no ficción agotaban aproximadamente 35 s; tras reconocer esa forma, tardaron 9,27 / 1,66 / 9,08 s. El primero sólo obtuvo un fragmento y Sapiens sólo alcance del subtítulo: **rapidez con contenido parcial**, no tres explicaciones completas.
- Jade Cabinet: el registro previo de 19,31 s se descompone en 12,77 s de generación y 5,43 s de auditoría, con cuatro inferencias, incluidas traducción de tarjeta y su verificación. El control repetido midió 18,80→13,96 s al pasar de cuatro a dos inferencias. Otra ejecución fría tardó 20,84 s con dos llamadas; la variabilidad no desapareció. No se redujo la auditoría factual de la respuesta.
- Dandadan en memoria global, proceso nuevo sin red: 0,76 s y cero inferencias. Personajes de Little Women: 0,46 s y cero inferencias; antes no respondía con el snapshot inicial.
- The Secret Garden: antes sin contenido local; después ofreció una premisa en español en 14,50 s. Sigue siendo una premisa, no un argumento desarrollado.

`read_sse` mide el primer evento recibido, el token de resultado aprobado y la entrega factual tras finalizar. El primer progreso suele llegar en decenas de milisegundos; **no es el primer texto factual**. No se muestran borradores sin auditar ni se simuló escritura.

Los 120 trabajos midieron 243,00 s de ejecución interna, 15,15 s de CPU acumulada y pico de 123,59 MB RSS, cero llamadas al LLM. Excluye inventarios/verificación de respaldos, Ollama, Docker y MySQL; no es consumo total del PC. La máquina mostró 31,92 GiB RAM y 11,44 GiB libres en la comprobación. La memoria literaria creció 389.120 bytes. El índice derivado tiene 499 fuentes/498 documentos/526 fragmentos, BM25 sin embeddings; el FTS de memoria mantiene el catálogo completo. No se añadieron modelos, entrenamiento, paquetes ni servicios pagados.

## D. Calidad, causas y pendientes

Las correcciones generales, con regresiones que fallaron antes y pasaron después:

1. **Cobertura temática:** materias de catálogo ya no completan un requisito de contenido temático; un pasaje temático literal sí puede hacerlo. Las secciones de temas/contexto/adaptaciones ya no se etiquetan todas como argumento.
2. **Identidad persistente:** reconocimiento de artículos literarios en inglés y autoría de manga «escrita e ilustrada por». Permite recordar evidencia licenciada aunque no exista una tarjeta de catálogo; no inventa ISBN o edición.
3. **Títulos publicados:** una introducción puede acreditar el título completo que el encabezado abrevia. Se mantienen autoría, revisión, licencia y pruebas negativas de secuelas. Una coincidencia parcial de palabras ya no bloquea innecesariamente el segundo idioma; se conserva la equivalencia sólo de espacios en descubrimiento.
4. **Autores y personajes:** preguntas de personajes reutilizan el analizador de autor explícito; un nombre de personaje añadido a una búsqueda de acontecimientos no se convierte automáticamente en apellido del autor durante descubrimiento. La vinculación final sigue comprobando el autor completo.
5. **Secciones:** la extracción de resumen respeta encabezados aunque los espacios se hayan compactado. No anexa automáticamente título/epígrafe/recepción de otra obra. La repetición real de Liliana eliminó la frase de otra sección.
6. **No ficción:** materias bibliográficas se consideran antes de menciones incidentales a ficción en la prosa; se reconocen filosofía, ensayo, economía y ciencias políticas.
7. **Presentación:** la tarjeta de una única respuesta narrativa aprobada puede usar su resumen, evitando traducir otra vez una sinopsis extranjera. Mantiene fuentes originales, títulos, autores, botones, portada y texto plano de tarjeta. No aplica a recomendaciones, comparaciones o borradores rechazados.
8. **Lectura V3:** los fragmentos cortados y los datos de publicación dejan de ser premisas de trama utilizables; los snapshots originales siguen disponibles.
9. **Aclaraciones:** si se conoce el libro pero falta el personaje, la aclaración conserva el título. No supone quién es un protagonista no verificado.
10. **MySQL:** admite referencias a ediciones verificadas por URL sin promoverlas a obras; inserción idempotente y rechazo de coincidencias sólo por título.

No existe aún una evaluación factual exhaustiva ni una tasa de error ≤1 %. Un veredicto del auditor o `answered` no sustituye al cotejo independiente. Se observó una mala traducción «corteza» por *courtship* en una ejecución de Jade; la auditoría la había aprobado. No se convirtió esa respuesta en conocimiento. La corrección semántica general de traducciones complejas sigue pendiente.

`fantasia_conversacion.json` conserva el escenario de siete turnos. Recomendó cinco títulos/tarjetas, pero la explicación del tercero, protagonista, relaciones, final y recomendaciones con protagonista femenina **no superaron conjuntamente la prueba**. El título editorial incluye la colección entre paréntesis y faltan enlaces bibliográficos fiables para reconciliarlo; no se recortó a ciegas ni se inventó la respuesta. La aclaración de libro conocido se corrigió después; no se afirma que la conversación completa ya funcione.

`recuerdos_y_generalizacion.json`: identificó Papelucho por la pista del niño/extraterrestre (23,43 s) y propuso Rebelión en la granja con incertidumbre (0,78 s). Falló la búsqueda por la escritora/hermana (23,39 s) y la errata «Mugre roza» (6,32 s). Moby-Dick obtuvo respuesta (33,83 s), pero la puntuación del título desvió el pipeline y añadió el desenlace sin petición expresa: pendiente, no un éxito completo.

Prioridad siguiente: reconciliar obra/edición/colección con identificadores y variantes publicadas, recuperación por recuerdos/erratas sin mezclar obras, foco conversacional tras abstenciones y validación bilingüe de atribuciones. Ampliar relaciones y contenidos de no ficción a partir de secciones/índices verificables. No volver a procesar indiscriminadamente las candidatas diferidas.

## E. Integridad, archivos y continuidad

- Respaldo nuevo **`backups/conocimiento_20261030_01`** completo y verificado: 41 tablas, 46.821 filas; se conservan `_03` y todos los anteriores. Quedaron unos 81 GiB libres. El mayor crecimiento de disco es el respaldo, no los textos literarios.
- Las 14.466 identidades originales permanecen. Los 14.645 registros de fuente del snapshot inicial siguen exactamente activos, cero faltantes. MySQL conserva las filas originales; sólo 23 referencias nuevas y avance del checkpoint derivado. Usuarios, autenticación, catálogo e historial SQL sin cambios.
- `quick_check=ok` y cero errores FK en memoria/RAG. `.env` conserva SHA256 `1d8e35effc765d26ecb73f3e2ee26c886a1e3d98b1bc45590c356b8604008e74`.
- `final_integrity.json` registra el punto antes de activar la lectura V3. `quality_policy_v3.json` lo complementa con la política e índice actuales: los datos fuente no cambiaron; el índice del respaldo puede reconstruirse tras restaurar. No sobrescribir el informe anterior.
- SearXNG permanece healthy y publicado sólo en `127.0.0.1:8080`. No se cambió su imagen, configuración, puertos o motores ni se hicieron reinicios.
- No se crearon tareas permanentes de Windows ni procesos de enriquecimiento infinitos. Los trabajadores finitos terminaron y conservan estados/reintentos. Sin migraciones de producción, commits, push, paquetes, `.env` o cambios visuales.

Archivos de código de este lote:

- `core/ai_character_answers.py`, `core/ai_narrative_answers.py`.
- `core/literary_identity.py`, `core/literary_search.py`, `core/literary_learning.py`, `core/literary_enrichment.py`, `core/literary_memory.py`.
- `core/continuous_knowledge.py`, `core/literary_presentation_language.py`, `core/bibliographic_http_probe.py`.
- Nuevos `core/test_knowledge_campaign.py`, `core/test_knowledge_sql_projection.py`; ampliado `core/test_presentation_language.py`; aislamiento de cooldowns en `core/test_recommended_content.py` y `core/test_local_ai.py`.
- Nuevos `scripts/knowledge/knowledge_campaign.py`, `scripts/knowledge/summarize_campaign.py`, este directorio de evidencias y `reportes/continuidad_opencode.md`.

Los cambios anteriores del repositorio se conservaron. Las primeras baterías completas detectaron regresiones y contaminación de cooldowns entre pruebas; se corrigieron y sus JSON se conservaron. El resultado definitivo está en `tests_core_accepted.json`: 2.140 pruebas ejecutadas, **2.139 aprobadas y una omitida**, con SQLite y los almacenes auxiliares temporales. Los fallos de red/voz/OAuth que aparecen como warnings en esa batería son escenarios simulados. No se cuentan los planes `dry_run` como conversaciones reales.

### Comandos desde PowerShell 5.1

```powershell
# Arranque existente con MySQL local y confirmación previamente autorizada de Google sin facturación.
# Solicita la contraseña oculta; no escribirla en parámetros ni en el chat.
.\venv\Scripts\python.exe -B iniciar_mysql_local.py --http-desarrollo --google-books-sin-facturacion

# Siguiente lote conservador del trabajador existente; usar siempre una salida nueva.
.\venv\Scripts\python.exe -B -m scripts.knowledge.continuous_worker --max-works 5 --max-jobs 2 --max-seconds 30 --job-seconds 8 --pause 2 --output reports/continuous_runs/continuacion_manual_01.json

# Comprobación real local, con red pública bloqueada y proveedores desactivados.
.\venv\Scripts\python.exe -B -m scripts.knowledge.search_narrative_check --local-only --output reports/conocimiento_20261030/comprobacion_manual_nueva.json --question 'Dime la trama de Dandadan de Yukinobu Tatsu'

# Agregación reproducible de los resultados existentes, sin conexión a MySQL ni secretos.
.\venv\Scripts\python.exe -B -m scripts.knowledge.summarize_campaign --folder reports/conocimiento_20261030 --output reports/conocimiento_20261030/metricas_manual_nuevas.json
```

El trabajador admite marcador de parada `data/enrichment.stop` y `--stop-file`;
Ctrl+C deja las tareas recuperables tras expirar su lease. Para reanudar se
retira únicamente el marcador creado para esa pausa y se ejecuta de nuevo con
salida nueva. Los checkpoints no se reinician ni se fuerza el backoff.
No se instaló una tarea del Programador de Windows: cualquier programación
permanente sigue necesitando aprobación explícita y provisión local segura de
credenciales, nunca contraseña en argumentos o Git.
