# Reparación narrativa y continuidad de recomendaciones

Lote comprobado. Tras la confirmación de Google Books, la consulta de Chile ya produjo una síntesis auditada de su descripción editorial (actualización al final). Continúan pendientes comparaciones más profundas y algunas listas de personajes principales; no es una reparación universal.

- Respaldo previo verificado: `backups/narrativa_20261029_01` (41 tablas, 37.384 filas, 92 archivos).
- Causas corregidas: roles publicados en tablas, definiciones inversas, alias explícitos; confusión del nombre del autor con otro título; cierre prematuro con un solo personaje; pérdida de `scope` en la recuperación de argumento. Auditorías conservadas.
- Chile: se reprodujo la conversación completa (`chile_antes.json`). El analizador no reconocía «Dime de qué trata» ni apellidos con partículas. Corregido y probado; `chile_lote02.json` recupera autor, pero aún no sinopsis, períodos ni comparación. No se declara éxito.
- Google Books está sujeto al control existente de ausencia de facturación; no se utilizó la clave privada. La consulta pública sin clave respondió 429. No se deshabilitó el control.
- Piloto existente de cinco obras: `piloto_02.json`, 10 tareas, 4 completadas, 6 pendientes, 35,563 s, 0 llamadas LLM. `stored=13` son operaciones de almacenamiento, no trece hechos nuevos. Tres tareas de desarrollo quedaron sin evidencia; se corrigió después la pérdida del atributo de alcance, pendiente de nueva comprobación.
- Pruebas dirigidas más recientes: 58 aprobadas. La primera ronda amplia tuvo 2 errores entre 2.036 pruebas; se reprodujo y corrigió el acceso a evidencia omitida. Pendiente ronda final; no se presenta esa ejecución como aprobada.
- Sin cambios de interfaz, `.env`, credenciales, migraciones ni datos originales por las pruebas HTTP/SSE (usan copias de los almacenes auxiliares).

## Resultados reales HTTP/SSE

WSGI local en puerto temporal, peticiones TCP, sesión continua y proveedores reales; copias de memoria auxiliar. Los archivos JSON conservan salidas y diagnósticos. Cada turno comprobó conteos MySQL y hash de la memoria original sin cambios durante la prueba.

| Consulta | Antes | Después | Alcance comprobado |
|---|---:|---:|---|
| Recomendación de historia de Chile | 12,738 s | 8,016 s | Tres fichas, mismo orden |
| Contenido de Historia de Chile | 35,101 s / error | 6,237 s | **Parcial:** subtítulo oficial, 1500–2000; no sinopsis completa |
| Quién escribió ese libro | 1,870 s / aclaración | 0,225 s | Armando de Ramón, misma identidad |
| Períodos históricos | 35,057 s / error | 0,641 s | Alcance documentado del subtítulo |
| Diferencia con el segundo recomendado | 35,066 s / error | 8,502 s | **Parcial:** ambos subtítulos; no diferencias de enfoque inventadas |
| Víctor y la criatura (tras trama y personajes) | 5,676 s / unavailable | 0,478 s | Creador/vida/experimento y rechazo, dos pasajes vinculados |
| Personajes de Frankenstein | Dos nombres | Cuatro nombres / 0,258 s | Víctor, monstruo, William y Justine; no todos clasificados como principales |
| Principales de Drácula | unavailable / 6,574 s | Dos nombres / 0,415 s | Mina y Conde con clasificación explícita; no garantía de reparto completo |

Evidencias: `chile_antes.json`, `chile_lote05.json`, `conversacion_b_memoria.json`, `conversacion_c_final.json`, `personajes_antes.json`, `personajes_final.json`. Las consultas independientes no siempre usan la misma redacción; no son un benchmark estadístico. No se midió p95 ni 99 % de exactitud.

La conversación C respondió trama en 2,904 s y principales en 4,154 s, pero **sólo confirmó a Odiseo como principal**. La consulta general de personajes sí recuperó siete nombres/roles de la obra en 3,397 s. Siddhartha confirma un principal y señala lista parcial. Los argumentos siguen siendo extractos parciales, con necesidad de una síntesis más coherente/proporcionada en algunas obras.

Llamadas reales a Ollama: contenido de Chile 5→0, períodos 4→0, autor 0, relación Víctor/criatura 0. Recomendación y comparación registran dos llamadas de presentación/traducción; no se presentan como rutas totalmente libres de inferencia.

## Causas y correcciones

- `ai_narrative_answers.request_for`: prefijo «Dime de qué trata», períodos y partículas en autor; mantiene títulos originales y evita tratar un tema genérico como título sin contexto.
- `retrieve_sources` y `bound_sources`: detalle oficial de la clave Open Library, edición con vínculo `works`, descripción/subtítulo separados; prioriza la ficha descriptiva ya identificada frente a un registro vacío. Google Books existente se consulta también en esta ruta **sólo si su configuración segura lo permite**.
- `literary_ai.canonical_sources`: conserva los campos enriquecidos y su procedencia al deduplicar la misma clave de obra Open Library; conserva `scope` de los hechos literales.
- `metadata_content_answer` y `comparison_answer`: alcance bibliográfico y comparación ordinal acotados, auditados y explícitamente parciales. No reemplazan comparaciones de novelas respaldadas. Extractos editoriales cortos y literales cuando bastan; sin reconstrucción ficticia de contenido.
- `literary_ai_views.remember`: ordena primero las fuentes realmente citadas antes del recorte conversacional. La respuesta generada no se convierte en prueba. La regresión previa demostró que el octavo pasaje citado se perdía en el siguiente turno.
- `ai_character_answers`: nombres abreviados únicos, alias explícitos, clasificación verificada, prioridad de pruebas complementarias antes del límite de ocho fuentes; no fusiona homónimos. Las listas cortas muestran «Lista parcial».
- `literary_web`: columnas descriptivas, definiciones inversas y roles nominales explícitos, con y sin enlaces; no asigna rango principal por mera pertenencia.
- `literary_search`: selección de pasajes y preservación conjunta de evidencia `plot`/`events`. La ronda amplia detectó que sustituir `events` por `plot` rompía seguimientos; se conservaron ambos contratos sin relajar el evaluador.

## Fuentes, datos y persistencia

Google Books ya tenía cliente, búsqueda y detalle. Se añadió procedencia explícita de la descripción en `volume_source` y uso desde la recuperación narrativa. **Pruebas simuladas aprobadas; uso real con clave no activado:** falta confirmar `LITMATE_GOOGLE_BOOKS_CONFIRMED_NO_BILLING`. La clave no se imprimió ni utilizó. El GET sin clave devolvió 429; no se evadió. [Documentación oficial](https://developers.google.com/books/docs/v1/using).

Open Library oficial aportó subtítulos y vínculos de edición. El campo de descripción del primer libro sólo contenía medidas/páginas; el del segundo, una reseña en inglés. SearXNG respondió JSON con resultados de catálogo; DuckDuckGo no aportó resultados utilizables. El contenedor `litmate-searxng-1` estaba healthy y publicado sólo en 127.0.0.1:8080. `docker compose ps` sin el entorno del lanzador no resuelve el secreto requerido: usar el arranque existente, no reconstruir Docker ni cambiar `.env`. No se integró Crossref: la consulta de evaluación dio coincidencias incorrectas.

Volcado OL: el enlace oficial resolvió a `ol_dump_works_2026-09-30.txt.gz`; metadatos de Archive.org: **4.073.320.823 bytes**, SHA1 publicado `b5492661c5ce6d62aae87e1c14945d22826ee26b`. **No descargado ni hash local comprobado.** Había 109.572.382.720 bytes libres. No había volcado OL ya descargado en `data/adquisicion`. Se conserva el importador por streaming/checkpoint existente; su política sólo admite metadatos bibliográficos mínimos, no descripciones de derechos variables ni personajes. Los 11.100 registros SQL de obra/edición tienen autor e identificador y carecen de sinopsis en ese almacén por diseño; ninguno es registro OL de obra. La memoria auxiliar contiene más identidades OL. La muestra de dos obras no demuestra una mejora narrativa que justifique descargar/importar ahora cuatro GB. **Nuevos registros bibliográficos SQL importados: 0.** [Volcados](https://openlibrary.org/developers/dumps), [uso de API](https://openlibrary.org/developers/api), [metadatos del archivo](https://archive.org/metadata/ol_dump_2026-09-30).

Piloto de cinco identidades existentes: 10 tareas, 4 completadas/6 pendientes, 35,563 s (CPU 3,781 s, pico 108,383 MiB), +126.976 bytes, 0 llamadas LLM, 0 referencias SQL nuevas. Etiquetas con roles literales 19→27, fuentes vinculadas 25→29, obras con principal explícito 2→4. Son menciones/snapshots, no ocho personajes distintos ni corroboración independiente. No incorporó nuevos argumentos desarrollados; las seis tareas pendientes conservan backoff. No nueva cola, tabla, RAG, migración ni tarea Windows. Tipos y ejecución manual en `docs/CONOCIMIENTO_CONTINUO.md`.

## Pruebas y seguridad

- Regresiones dirigidas previas al arreglo: parser, metadatos perdidos, nombre abreviado ambiguo, evidencia desplazada y retención conversacional. Último grupo dirigido: **109 aprobadas**.
- Cierre: **2.051 ejecutadas, 2.050 aprobadas, 1 opcional omitida**, 70,928 s; `pruebas_cierre.txt`. SQLite y nueve almacenes auxiliares temporales. La primera ronda final detectó cinco regresiones; se corrigieron y se repitió por ese motivo. Sus fallos siguen en `pruebas_finales.txt`.
- **246 comprobaciones JS aprobadas**; frontend sin modificaciones en este lote. `git diff --check` sin errores (sólo avisos de finales de línea).
- Respaldo posterior `backups/narrativa_20261029_02`: verificado, 41 tablas, 37.393 filas, 92 archivos. Respecto del previo hay nueve eventos analíticos nuevos y una sesión actualizada mientras la aplicación está en uso; no se atribuyen al piloto ni a una importación. Los demás registros SQL originales se conservan, admitiendo sólo el avance derivado del checkpoint del trabajador. Inventario auxiliar: integridad SQLite OK, cero errores FK; 13.261 identidades, incluyendo dos fichas públicas OL observadas después del inventario inicial.
- `.env` y manifiesto de `mysql_preparacion_20261028_03` conservan sus SHA256 iniciales. Sin instalaciones, pagos, push, commits, borrados ni migraciones.

Archivos de este lote: `core/ai_character_answers.py`, `ai_narrative_answers.py`, `books_google.py`, `literary_ai.py`, `literary_ai_views.py`, `literary_web.py`, `literary_search.py`, `literary_enrichment.py`, `literary_learning.py`, `literary_memory.py`, `continuous_knowledge.py`; pruebas `test_narrative_coverage.py`, `test_continuous_knowledge.py`, `test_integral_retrieval.py`, `test_narrative_failure_context.py`, `test_research_integration.py`; `scripts/knowledge/audit_narrative_coverage.py`, `docs/CONOCIMIENTO_CONTINUO.md`, este informe y continuidad. Los cambios previos del repositorio se conservaron.

Pendientes al cierre anterior a la confirmación de Google: obtener una descripción más informativa de Historia de Chile mediante un proveedor habilitado y permitido; comparación temática completa; listas de principales de Frankenstein/Odisea/Siddhartha; mejor coherencia y profundidad de algunas tramas; verificar de nuevo las tareas de desarrollo tras corregir la pérdida de alcance; evaluación independiente más amplia. No declarar el objetivo completo.

## Actualización: Google Books tras confirmación del usuario

El usuario confirmó que su proyecto de Google Cloud **no tiene facturación vinculada**. No se comprobó esa condición mediante una API de facturación ni se modificó `.env`. Se reutilizó la clave existente sin imprimirla. La API devolvió el volumen `_zR9AAAAMAAJ`, título/autor/ISBN concordantes y descripción editorial en español (`google_confirmado_02.json`). Las búsquedas exactas por título/autor y por ISBN dieron vacío; una búsqueda por el autor encontró el volumen junto a otras obras. No se eligió automáticamente la primera coincidencia.

- `_google_work_sources` amplía una vez por autor si el catálogo no ofrece contenido para la identidad exacta. Vuelve a comprobar título/autor/obra con los validadores existentes. Ante error de cuota/clave/acceso no amplía; conserva los proveedores alternativos.
- `_task_content` reconoce descripciones documentales con formulaciones como «Esta obra es una historia…», además de los verbos de acción de ficción. Esto orienta recuperación; no sustituye la auditoría.
- `volume_source` incluye el subtítulo en la evidencia bibliográfica. Una pregunta de períodos utiliza ese alcance y no una cita editorial tangencial. No declara falsamente que falta descripción cuando ya se recuperó.
- Una descripción editorial extensa utiliza síntesis y auditoría existentes, con presupuesto de 18 s y extracto literal corto como respaldo si falla Ollama. No se amplían los ciclos de reparación ni se entrena con la respuesta.
- `iniciar_mysql_local.py --google-books-sin-facturacion` activa ambos indicadores únicamente durante ese proceso; pruebas verifican restauración del entorno. Sin el parámetro conserva la selección habitual. No se reinició el servidor del usuario.

Conversación real `chile_google_confirmado_02.json`: recomendación 1,222 s; contenido **answered 20,945 s, dos llamadas Ollama y auditoría approve**; autor 0,298 s; períodos 0,763 s. Esta vez el catálogo recomendó tres obras distintas de las del lote previo: se conservó correctamente esa lista y el segundo libro. La comparación con ese segundo libro quedó **unavailable 0,520 s por evidencia insuficiente**; no se cuenta como éxito. Todos los turnos conservaron conteos MySQL y hash de memoria original. La repetición final, en un proceso nuevo (`chile_google_cierre.json`), produjo síntesis en **20,929 s** y alcance de períodos en **0,664 s**, sin declarar ausencia de descripción. Dos ejecuciones no permiten afirmar un p95 ni un 99 % de exactitud.

Pruebas posteriores a esta confirmación: 159 dirigidas aprobadas; **2.057 ejecutadas, 2.056 aprobadas y una opcional omitida**, 77,196 s, en `pruebas_google_confirmado.txt`. SQLite y nueve almacenes auxiliares temporales. Nuevas regresiones reprodujeron búsqueda exacta vacía, período sustituido por descripción tangencial, descripción no ficticia ignorada y reintento indebido tras cuota. Se comprobó también que el fallback auditado sobrevive a una síntesis fallida. `.env` conserva su SHA256 original. Archivos adicionales: `iniciar_mysql_local.py`, `core/test_mysql_activation.py` y `docs/guides/MYSQL_LOCAL.md`; se ampliaron los módulos narrativos y pruebas ya citados.

Para cargarlo en la aplicación, detener el Django anterior y usar:

```powershell
.\venv\Scripts\python.exe -B iniciar_mysql_local.py --http-desarrollo --google-books-sin-facturacion
```

Pide la contraseña MySQL de forma oculta. El parámetro no activa facturación ni verifica por sí mismo la consola de Google; utiliza la confirmación del operador. Las cuotas y caídas de proveedores siguen siendo limitaciones reales. No se importó un volcado ni se guardó la respuesta generada como conocimiento verificado.
