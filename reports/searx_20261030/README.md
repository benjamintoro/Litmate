# SearXNG — revisión acotada del 30/10/2026

Se revisaron el informe de volcados, el adjunto, los cambios pendientes, la configuración **efectivamente montada**, el código de la imagen instalada, los logs con fecha y las rutas reales de LitMate. Este lote se limitó a proveedores, pausas y recuperación; no hubo nuevas descargas masivas ni cambios en la IA generadora.

## Estado observado

| Problema | Evidencia actual | Acción |
|---|---|---|
| DuckDuckGo CAPTCHA, `suspended_time=0` | Los últimos eventos anteriores al lote llegaban hasta 06:34 UTC. La consulta actual produjo 10 resultados, sin CAPTCHA. El código de esta imagen impone explícitamente plazo 0; el valor general 3.600 s no lo sustituye. | No se deshabilitó un motor que ahora responde ni se evadieron bloqueos. Se corrigió la pausa de **LitMate**, que antes sólo duraba en LocMemCache y se perdía entre procesos. |
| Open Library timeout / curl_cffi | Eventos anteriores hasta 06:19 UTC. Cuatro consultas actuales al motor personalizado terminaron sin error en **0,372–2,308 s**, dentro de sus 3 s configurados. | No se aumentaron timeouts ni se modificó el motor para ocultar un fallo que no se reproduce. |
| `add_unresponsive_engine after ResultContainer.close` | En los logs anteriores aparece inmediatamente después del timeout de Open Library. El procesador instalado intenta registrar el fallo en un contenedor ya cerrado. No reapareció en el lote. | Se identifica como efecto secundario del cierre por plazo; no se parcheó el núcleo de SearXNG. |
| Qwant Access denied | Último evento observado 03:35 UTC, anterior al último arranque, 04:01 UTC. Sigue `disabled: true`; no figura en las listas efectivas de Django. | Sin cambios y sin consultas nuevas a Qwant. `disabled` evita su uso normal; no debe solicitarse explícitamente para intentar eludir su denegación. |
| Cabeceras IP ausentes | Advertencia una vez al arrancar, 04:01 UTC. El código instalado usa `log_error_only_once` y conserva `REMOTE_ADDR` en conexión directa. `trusted_proxies=[]`. | No se inventaron cabeceras ni proxies. No se cambió `server.limiter`, que ya era false. |

`logs_cierre.json` contiene **cero errores/advertencias nuevos** desde el comienzo de esta ventana de pruebas. Esto no garantiza disponibilidad futura de proveedores externos.

Docker siguió `running/healthy`, con la misma imagen fijada por digest y el mismo volumen. La publicación real verificada es exclusivamente **`127.0.0.1:8080 → 8080/tcp`**. No hay publicación en `0.0.0.0` ni en IPv6 del host. La escucha interna del contenedor no cambia esa restricción. No se reinició, reconstruyó ni eliminó ningún contenedor o volumen.

## Correcciones demostradas

1. **Pausa compartida y duradera:** `core/ai_concurrency.py` reutiliza la tabla `leases` del runtime existente. Un CAPTCHA observado pausa DuckDuckGo por una hora; otras denegaciones/límites mantienen pausas acotadas. No se almacenan consultas ni datos personales. La pausa se consulta desde la ruta SearXNG y desde la ruta directa, continúa en un proceso nuevo y no acorta una suspensión más larga ni modifica leases de trabajo.
2. **Continuidad de otros motores:** al estar pausado DuckDuckGo, la búsqueda web puede utilizar Wikipedia/Open Library/Mwmbl ya habilitados. No se agregó ningún proveedor. Un resultado parcial se conserva; la pausa de un motor no suspende a todos.
3. **Contenido que se perdía:** se conserva `search_engines` durante la normalización. Las páginas descubiertas por motores válidos de SearXNG pasan al lector público existente; antes sólo DuckDuckGo podía entrar por esa rama. La búsqueda web admite los mismos enlaces HTTPS públicos que DuckDuckGo; el descubrimiento bibliográfico mantiene su lista de dominios.
4. **Recorte y lecturas desperdiciadas:** el adaptador clasifica los candidatos antes del corte de cinco, conserva diversidad de páginas frente a catálogos repetidos y deduplica destinos. `_retrieve_web` dejó de descartar páginas distintas con fragmentos vacíos o idénticos. Los enlaces de Open Library/Google Books, que se consultan por API, ya no consumen el cupo de lecturas HTML e impiden leer una fuente posterior.

**No se amplió el permiso de red del lector:** se mantienen verificación DNS e IP pública, rechazo de direcciones privadas y credenciales, bloqueo de redirecciones, robots, tiempo/tamaño y detección de inyección. Una URL descubierta no se convierte en hecho ni adquiere permiso de almacenamiento permanente.

La protección nueva contra CAPTCHA corresponde al **cliente LitMate**. La interfaz directa de SearXNG conserva el `suspended_time=0` upstream; no se afirma haber corregido ese código interno. Cambiar solamente `search.suspended_times` en YAML no resolvería su anulación explícita. La documentación de [suspensiones](https://docs.searxng.org/admin/settings/settings_search.html) se contrastó con el código de la imagen instalada, no se asumió que la documentación de la versión más nueva fuese idéntica.

## Pruebas reales de motores

Se probaron novela, manga, historia y ensayo en español. `motores_reales.json`: cuatro consultas por motor, **12/12 sin errores de proveedor**.

| Motor | Consultas con resultados | Latencia por consulta | Pertinencia y contenido |
|---|---:|---:|---|
| Wikipedia | 2/4 | 0,216–0,419 s | Dos títulos correctos. El motor instalado consulta un título exacto por REST; no es un buscador de texto libre. Sus resultados de lista son etiquetas breves, no argumentos completos. Las APIs oficiales de Wikipedia usadas directamente por LitMate siguen disponibles. |
| Open Library | 4/4 | 0,372–2,308 s | 20 fichas, 15 con coincidencia literal normalizada de título. La mayoría carece de descripción; una frase inicial tampoco equivale a sinopsis. |
| Mwmbl | 4/4 | 0,258–0,743 s | 253 resultados brutos, 61 con coincidencia de título. Incluye ruido, páginas de autor, adaptaciones y opiniones: no se consideran 253 fuentes útiles ni verdaderas. |

`baseline.json`: una consulta acotada adicional a DuckDuckGo produjo diez resultados en **1,045 s**, incluyendo una página pertinente de la novela. No se hicieron reintentos de CAPTCHA ni cambios de región/IP para esquivar restricciones.

`fallback_cierre.json`: con la pausa de DuckDuckGo **simulada sólo en runtime temporal**, las consultas a los demás motores y las lecturas sí fueron reales. Las cuatro búsquedas devolvieron cinco candidatos cada una; búsquedas en **0,379–1,448 s**. Hubo contenido explicativo vinculado automáticamente para manga, pero **no se acreditó suficiente contenido narrativo en las otras tres búsquedas SearXNG aisladas**. Se rechazaron, entre otros, un prólogo no equivalente al argumento, fichas sin descripción y opiniones no vinculadas suficientemente. Esto sigue pendiente y no se disimula contando HTTP 200.

No se añadieron motores alternativos: los existentes respondieron y el problema demostrado estaba también en cómo LitMate conservaba y leía sus resultados. Añadir otro motor no solucionaría por sí mismo esas pérdidas.

## Backend HTTP/SSE real

`chat_actual.json` y `chat_ddg_pausado.json` utilizan el backend existente y MySQL local, con memoria/runtime de prueba aislados. La segunda ejecución simula una pausa previa de DuckDuckGo, **no un bloqueo real actual del proveedor**.

| Consulta | Normal | Con DuckDuckGo pausado | Resultado |
|---|---:|---:|---|
| Trama de El nombre de la rosa | 5,678 s | 2,151 s | Respuesta en español desde Wikipedia; una consulta al adaptador oficial. |
| Trama del manga Naruto | 2,271 s | 5,800 s | Respuesta en español desde Wikipedia; una consulta al adaptador oficial. |
| Tres libros de historia del Perú | 1,299 s | 16,085 s | Tres fichas bibliográficas. En la segunda ronda falló Google Books y hubo dos llamadas al modelo; no se acredita que todas las fichas tengan sinopsis. |
| El infinito en un junco | 1,598 s | 1,550 s | Contenido documental en español desde evidencia disponible. |
| Emma | 0,667 s | 0,684 s | Evidencia local, **cero consultas a Wikipedia/SearXNG y cero llamadas al modelo**. |

Las diez peticiones finalizaron `answered` y SSE correctamente. Los ejemplos de novela/manga/ensayo conservan títulos, autores y fuente relacionada; la lista de historia es bibliográfica, no una explicación narrativa. No se demuestra precisión universal por diez respuestas.

En esas consultas no hizo falta activar SearXNG: bastaron las rutas locales y Wikipedia directa. **No se atribuyen estos éxitos narrativos a la metabúsqueda.** Las consultas SearXNG reales están en la matriz y en el piloto de fallback separado. Esta distinción demuestra además que SearXNG sigue siendo complemento y no una dependencia obligatoria de cada turno.

Primer evento de progreso en la ronda con pausa: **12–38 ms**; no es tiempo hasta una respuesta factual completa. Las diferencias entre rondas incluyen variación de proveedores y contenido, por lo que no se presentan como una aceleración causal ni como un p95 de producción.

## Archivos, seguridad y continuidad

- `core/ai_concurrency.py`: pausas técnicas sobre el runtime actual, sin tablas ni migraciones nuevas.
- `core/literary_search.py`: pausa compartida, fallback de motores existentes, selección de candidatos y uso del lector seguro.
- `core/literary_ai.py`: conserva procedencia de motores reconocidos durante `canonical_sources`.
- `core/test_searx_resilience.py`: regresiones nuevas, incluidas las que fallaron antes del cambio, proceso independiente, caducidad, leases, destinos privados y conservación del presupuesto de páginas.
- `core/test_web_search.py`, `core/test_search_narrative_repair.py`, `core/test_progressive_free_sources.py`: aíslan la coordinación de las simulaciones en caché de pruebas.
- `scripts/knowledge/searx_quality_check.py`: matriz y lecturas reales reproducibles, consultas públicas fijas y almacenamiento temporal.
- `scripts/knowledge/search_narrative_check.py`: opción de pausa simulada sobre runtime temporal para pruebas HTTP/SSE.
- `searxng/README.md`, `reportes/continuidad_opencode.md`: estado y límites actualizados. **No se modificó `searxng/settings.yml`, el motor montado ni Compose.**

Última ronda: **204 pruebas aprobadas en 1,584 s**, con SQLite y almacenes auxiliares temporales. Incluye límites de red, redirecciones privadas, robots e inyección. Dentro de la imagen fijada: **7 regresiones offline de Open Library aprobadas**. No se repitió una auditoría de miles de pruebas.

Integridad: todas las peticiones comprobaron conteos MySQL intactos y hash de la memoria original sin cambios. Comparación lógica adicional con el respaldo `_03`: **16 tablas de memoria y 10 del índice RAG sin diferencias**, `quick_check=ok`. Los hashes físicos de archivos SQLite de respaldo pueden diferir del archivo vivo pese a tener contenido lógico idéntico; no se interpretó eso como pérdida de datos. `.env` conserva su hash original. El respaldo existente se conserva, sin nueva importación ni migración.

No se instalaron paquetes, APIs pagadas, tareas permanentes ni modelos. No hubo push, commits, cambios visuales ni modificaciones de claves. No se eliminaron logs, índices, volúmenes o datos.

## Reproducir

Desde la raíz, usando rutas de salida nuevas:

```powershell
.\venv\Scripts\python.exe -B -m scripts.knowledge.searx_quality_check --mode engines --output reports/searx_20261030/motores_nuevos.json
.\venv\Scripts\python.exe -B -m scripts.knowledge.searx_quality_check --mode fallback --output reports/searx_20261030/fallback_nuevo.json
.\venv\Scripts\python.exe -B -m scripts.knowledge.search_narrative_check --pause-duckduckgo --trace-search --output reports/searx_20261030/chat_nuevo.json --question 'Dime la trama de Emma'
```

La última orden pide la contraseña de MySQL en forma oculta. Si Django ya estaba abierto sin recarga automática, cargar el código nuevo reiniciándolo con su lanzador habitual: `.\venv\Scripts\python.exe -B iniciar_mysql_local.py`. No requiere tocar `.env` ni reiniciar Docker.
