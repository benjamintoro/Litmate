# Sinopsis y verificación de Docker — 26 de octubre de 2026

Trabajo sobre `G:\Proyecto\Litmate`, retomado desde `7810561` y conservando
los cambios pendientes. Alcance: generación de sinopsis, identidad de obras,
contexto, selección de evidencia y comprobación real de SearXNG. No se cambió
el diseño, las tarjetas, la personalidad general, la voz ni los avatares.

Checkpoints locales: Docker `0fc5990` y conjunto final
`checkpoint/sinopsis-docker-20261026`. Sin publicación ni push.

## Problemas confirmados y correcciones

1. La vista no entregaba configuración al sintetizador y descartaba sus
   contadores LLM. Ahora la síntesis funciona y registra llamadas, tokens y
   tiempos reales de generación y auditoría.
2. La investigación genérica consumía el presupuesto de páginas antes de la
   ruta narrativa. Las peticiones de contenido llegan primero a esa ruta,
   conservando el fallback general para las otras intenciones.
3. Autor explícito y subtítulos editoriales impedían vincular una fuente real.
   Se separa el autor y se comprueba el subtítulo antes de normalizarlo.
   Esa ampliación exige identidad bibliográfica y no autoriza mezclar secuelas.
4. El catálogo podía asociar el texto de Tolkien con una ficha homónima de
   Gary Russell. La evidencia de la novela se conserva sin adjuntar esa tarjeta.
   Fuentes inyectadas, contradictorias o de adaptaciones no resuelven homónimos.
5. Una plantilla histórica respondía desde materias del catálogo sin una
   descripción real. Se retiró: clasificar no ficción no prueba sus contenidos.
6. El extractor editorial recuperaba publicidad/biografía y omitía el índice
   cerrado en un acordeón. Ahora reconoce índices semánticamente identificados,
   resuelve únicamente paneles HTML del mismo documento y extrae títulos de
   capítulos limitados, sin cargar JavaScript ni descargar capítulos.
7. Las pruebas reales mostraron afirmaciones temporales inventadas y auditorías
   que aprobaban publicidad como prueba de contenidos. Para índices se entrega
   un bloque contiguo de temas publicados; la auditoría sólo puede seleccionar
   esas pruebas literales de contenido. No se concatenan capítulos distantes
   para fabricar una cita. Las materias del catálogo no sustituyen ese pasaje.
8. Se controlan siglos enumerados y rangos ES/EN, conservando siglos que forman
   parte de títulos. Una prueba debe respaldar el periodo afirmado. Este control
   acotado no constituye un verificador semántico universal.
9. Si el auditor declara `approve` pero marca frases `inference/unverified`, la
   decisión se endurece a `repair`. Se pueden retirar oraciones enteras, nunca
   promoverlas a hechos. La respuesta restante pasa nuevamente TODOS los
   validadores; una cita falsa o contradictoria no se rescata.
10. Tras una respuesta rechazada se conserva sólo la petición bibliográfica del
    lector, fuera del historial aceptado. Un seguimiento mantiene la obra sin
    convertir el borrador rechazado en conocimiento. Una nueva recomendación
    o un título explícito siguen su propia ruta.
11. Una descripción aceptada en inglés se reutiliza sin otra búsqueda externa,
    aunque necesite traducción. No se reutiliza la respuesta generada como fuente.

## Resultados reales

Línea base conservada: `reportes/arquitectura_20261023/sinopsis_antes.json`.
Medición final: `reportes/sinopsis_20261026/http_final_v4.json`.

| Consulta | Línea base | Medición final | Llamadas LLM finales |
|---|---|---|---:|
| Trama de The Unfinished Nation, Alan Brinkley | unavailable, 5,152 s | answered, 14,266 s | 2 |
| Qué temas aborda este ensayo, después de Brinkley | No estaba en esa línea base | answered, 8,211 s | 2 |
| Trama de Papelucho y el marciano | answered, 0,075 s | answered, 0,084 s | 0 |
| Cuéntame la historia de Papelucho y el marciano | No estaba en esa línea base | answered, 0,082 s | 0 |
| Trama de El Señor de los Anillos | unavailable, 6,680 s | answered, 2,567 s | 0 |
| El libro que mencionaste anteriormente, después de Tolkien | No estaba en esa línea base | answered, 0,074 s | 0 |
| Conflicto principal de esta novela, después de Tolkien | No estaba en esa línea base | answered, 0,091 s | 0 |

Las dos respuestas que fallaban ahora aportan contenido respaldado. No se
presenta el rechazo rápido de la línea base como una respuesta útil más veloz.
Brinkley explica una muestra de temas del índice, no una cronología completa:
Reconstrucción/Nuevo Sur, conquista del Oeste y supremacía industrial. Tolkien
explica el conflicto de Frodo, el Anillo Único y Sauron. Papelucho conserva su
sinopsis y la relación con Det.

- Siete turnos: media 3,625 s; p50 0,091 s; p95 muestral 14,266 s.
- 5/7 bajo 5 s; 6/7 bajo 10 s; 7/7 bajo 30 s; siete `answered`.
- Primer evento de progreso: 0,014–0,036 s. No equivale a primer texto factual.
- Brinkley inicial: recuperación 1,860 s; búsqueda web 3,136 s; extracción
  2,083 s; generación 3,398 s; auditoría 3,599 s. Algunos tiempos incluyen
  operaciones anidadas y no deben sumarse como componentes independientes.
- Su seguimiento registra `stored_content`, sin nuevas búsquedas externas.
- Endpoint real HTTP/SSE y finalización, SQLite y almacenes auxiliares temporales,
  Ollama `qwen3.5:9b-q4_K_M`, contexto 16384, fuentes externas reales.
- Precarga separada de 0,072 s: el modelo ya estaba residente tras pruebas
  previas. No son mediciones de arranque frío. No se preparan respuestas.
- Hash de código estable durante la medición. La matriz sólo contiene preguntas,
  no respuestas suministradas al modelo.
- La línea base es del 23 de octubre y las fuentes externas pueden variar;
  no es un experimento A/B simultáneo ni un certificado de precisión global.
- `answered` es un estado técnico. Se revisaron las respuestas y sus pruebas,
  pero siete turnos no acreditan una tasa de error inferior al 1 % ni el p95
  de todas las consultas habituales.

Las mediciones intermedias se conservan, incluyendo fallos. `http_final_v1.json`
detectó pérdida del contexto tras un rechazo; `http_final_v2.json` detectó la
decisión contradictoria del auditor. `http_final_v3.json` y `v4` respondieron los
siete turnos; `v4` incluye la reutilización explícita de contenido y la medición
de búsqueda web. Las trazas privadas se activan sólo en diagnósticos locales.

## Docker y SearXNG

Verificación real: `reportes/sinopsis_20261026/docker_final.json`.

- Docker Desktop activo; Engine 29.8.2 y contexto `desktop-linux`.
- `litmate-searxng-1`: running y healthy, sin OOM;
  publicado únicamente en `127.0.0.1:8080`.
- Se corrigió `display_type: [list, infobox]` para Wikipedia: antes podía emitir
  sólo infoboxes que el adaptador Django no consume. Se reinició únicamente
  ese contenedor, sin borrar volúmenes.
- Tres peticiones JSON reales HTTP 200: 0,944 / 0,894 / 1,145 s.
- Tres búsquedas desde Django: 1,060 / 0,431 / 1,380 s.
- Wikipedia responde. El motor Open Library todavía falla parcialmente con
  algunas consultas (`unexpected crash` para El nombre de la rosa). Mwmbl
  devuelve ruido: contenedor saludable y HTTP 200 no garantizan relevancia.
- La aplicación mantiene sus APIs bibliográficas y fuentes alternativas;
  ese motor parcial no implica que Docker esté detenido. No se integraron
  instancias públicas ni servicios comerciales.

## Pruebas automatizadas

Ejecutadas con Python del venv y bases aisladas:

- `core suscripciones`: **1405 pruebas OK**, 17,472 s.
  Registro: `reportes/sinopsis_20261026/pruebas_final_v2.txt`.
- JavaScript: **210 comprobaciones OK** de seguridad, formato, SSE, HTTP,
  CSRF y voz (`node verificar_chat_seguro.js`).
- `git diff --check`: sin errores de espacios; avisos normales LF/CRLF.
- Nuevas regresiones: índices ES/EN/acordeones, inyección, límites, referencias
  externas no ejecutadas, tres obras obligatorias, autores homónimos, fuentes
  contradictorias, ausencia de sinopsis, conservación del contexto tras fallos,
  recuperación en inglés, siglos/rangos, citas falsas y pool de pruebas acotado.

Estas pruebas usan proveedores simulados donde corresponde. Se distinguen de
las mediciones HTTP/Ollama/Docker reales anteriores; no se confunden sus tiempos.

## Archivos modificados

Producción:

- `core/ai_narrative_answers.py`: comprensión, vinculación de identidad,
  recuperación, selección de evidencia, síntesis, auditoría y respuestas parciales.
- `core/literary_ai_views.py`: orden del pipeline, configuración, métricas y
  conservación segura de la petición tras un fallo.
- `core/literary_web.py`: índices editoriales en HTML estático/acordeones.
- `core/literary_quality.py`: comprobación temporal reforzada.
- `core/local_llm.py`: contrato narrativo de tarjetas y pruebas acotadas.
- `searxng/settings.yml`: resultados Wikipedia compatibles con Django.

Regresiones y herramientas:

- `core/test_narrative_answers.py`, `core/test_narrative_synopsis.py`,
  `core/test_narrative_review.py`, `core/test_editorial_contents.py`,
  `core/test_scoped_narrative_evidence.py`, `core/test_narrative_failure_context.py`,
  `core/test_searx_diagnostics.py`.
- `diagnosticar_buscador.py`, `diagnosticar_sinopsis.py`, `evaluar_chat_http.py`,
  `core/data/narrative_benchmark.json` y `reportes/continuidad_opencode.md`.

## Reproducir y ejecutar

PowerShell 5.1, desde la raíz. Docker Desktop y Ollama deben estar iniciados.
Los informes rechazan sobrescrituras: escoger otra ruta en cada ejecución.

```powershell
.\venv\Scripts\python.exe -B iniciar_buscador.py
.\venv\Scripts\python.exe -B diagnosticar_buscador.py --output reportes/docker_repeticion.json
.\venv\Scripts\python.exe -B diagnosticar_sinopsis.py --synthesize --message "Dime la trama de The Unfinished Nation de Alan Brinkley" --output reportes/sinopsis_repeticion.json
.\venv\Scripts\python.exe -B evaluar_chat_http.py --matrix core/data/narrative_benchmark.json --progressive --prewarm --trace-narrative --output reportes/http_sinopsis_repeticion.json
.\venv\Scripts\python.exe -B verificar_proyecto.py core suscripciones
node verificar_chat_seguro.js
.\venv\Scripts\python.exe manage.py runserver
```

`--trace-narrative` guarda las pruebas y borradores únicamente en el informe
local del benchmark aislado. El chat público no expone las trazas de auditoría.

## Límites y continuidad

No se añadieron dependencias, modelos, APIs pagadas ni nuevas infraestructuras.
La ruta sigue usando Ollama local y fuentes públicas existentes: no agrega
facturación obligatoria por consulta. Los costos de equipo, red y electricidad
no equivalen a una factura de API. No se alteraron `.env`, secretos, settings de
producción, migraciones ni datos de usuarios; no se hizo push.

Se conservan el conocimiento persistente, RAG híbrido/semántico, caché y worker
incremental existentes. Esta unidad mejora la selección de sus fuentes y su
reutilización; no cambia embeddings ni entrena pesos ni declara evaluaciones de
modelos que no se hicieron. Las páginas sin autorización de indexación siguen
sin almacenarse como conocimiento permanente.

Queda ampliar la evaluación a más obras, idiomas, arranques fríos y concurrencia,
vigilar variaciones de búsqueda/red y resolver el defecto del motor Open Library
sin cambiar a una imagen o configuración no evaluada. La síntesis puede reconocer
insuficiencia cuando ninguna fuente respalde el dato. La precisión universal y
los objetivos globales de latencia siguen requiriendo mediciones más amplias.
