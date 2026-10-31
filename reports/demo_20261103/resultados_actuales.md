# Cierre incremental — 31 de octubre de 2026

Se continuó desde los cambios locales existentes; no se reconstruyó el proyecto.
La configuración remota está preparada, **no publicada**. El recorrido local
comprobado funciona; no se declara completada la validación desde el instituto.

## Causas demostradas y correcciones

| Fallo | Causa y cambio general |
|---|---|
| Explicar las pistas tardaba 32,64 s y añadía una afirmación de unicidad no respaldada. | `sanitized_history` descartaba el propósito `identify`. Se conserva y `identification_explanation_answer` reutiliza pasajes recibidos con al menos dos pistas documentadas. Sin nuevas inferencias. |
| Relación entre dos personajes no recuperada. | `_relationship_fact` no reconocía «Amiga que Ana conoce…». Se admite la cláusula relativa literal sobre las dos entidades; se rechaza la que relaciona a una tercera persona. |
| Interpretaciones de objetos presentadas como roles. | `_facts` mezclaba simbolismo puro con papel narrativo. Se filtran en recuperación expresiones abstractas inequívocas, sin borrar evidencia persistente ni excluir objetos personificados que actúan en la historia. Es una mejora parcial, no una revisión completa de todos los perfiles existentes. |
| Una ficha local verificada dejaba de servir de referencia tras combinar proveedores. | La etiqueta dejaba de ser literalmente un proveedor. Se recupera la ficha original incluida en el programa por identidad **y URL**; no se aceptan como propios sus campos combinados. Las páginas narrativas ya ligadas a la obra aportan temas sin convertirse en tarjetas. |
| «Dame otras dos opciones» terminaba buscando esas palabras y recomendando un manual de prompts. | La elipsis perdía la relación con la obra inicial al caer al flujo genérico. Se conserva `related_reference`, restricciones y lecturas previas en la sesión. Una búsqueda relacionada sin opciones válidas no pasa a recomendaciones genéricas. |
| «Ya leí el primero…» podía almacenarse como un título literal. | El extractor anterior de títulos se aplicaba además del análisis ordinal. Ahora son rutas excluyentes; un ordinal inexistente se aclara sin inventar un título. |
| «Cuéntame más del segundo» tardaba 35,11 s; «dónde encontrarlo» podía volver al principito. | Faltaba esa construcción en `request_for`; por tanto no actualizaba el foco. Se reconoce como consulta narrativa, resuelve la tarjeta y `quick_answer` aprovecha su sinopsis literal auditada cuando basta. No reduce la evidencia ni recorta una petición compleja a una frase. |
| Se buscaban existencias al pedir dónde encontrar un libro ya identificado. | `book_links_answer` reutiliza la identidad y las tarjetas con destinos reales de búsqueda; no asegura precio o disponibilidad. |
| Aparecía un encabezado de fuentes vacío para fichas internas. | `_validated_result` sólo añade el pie cuando existen URLs. No se elimina procedencia interna ni atribuciones exigibles. |
| El navegador recibía 429 al cargar recursos protegidos de la demo. | El gateway contaba desafíos Basic sin credenciales como contraseñas incorrectas. Ahora limita credenciales enviadas e inválidas; los recursos iniciales pueden solicitar autenticación. Prueba fallida antes y aprobada después; no se deshabilitó el límite de consultas del chat. |
| Dos clientes simultáneos provocaron un 409 de finalización. | Existe un bloqueo de cuota compartida por usuario/IP. El cliente hace como máximo dos reintentos del mismo token, sólo con `409` y `Retry-After` acotado, dentro del deadline original. No repite búsqueda/generación ni reintenta revisiones caducadas. `chat-v9` invalida la caché del helper, sin cambio visual. |

Los filtros de público adulto y obra autoconclusiva exigen metadatos/evidencia
explícita y se conservan en seguimientos. La falta de esa información no se
resuelve suponiendo que toda novela cumple ambos filtros. No se añadieron
excepciones para títulos ni se entrenaron modelos.

## Conversaciones reales y límites de la comparación

| Consulta o recorrido | Resultado medido |
|---|---|
| Explicación de pistas | 32,6427 s antes; 0,1283 s en el cierre. Sin llamada al modelo en el cierre. |
| Relación principito/zorro | Abstención en 6,1667 s antes; relación literal en 0,7863 s al cierre. |
| «Cuéntame más del segundo», misma lista de fantasía | Abstención en 35,1067 s en el ensayo intermedio; sinopsis de El Hobbit en 0,3467 s al cierre. |
| «¿Dónde puedo encontrarlo?» tras esa selección | El Hobbit y sus tarjetas, 0,2804 s, sin asegurar existencias. |
| Recorrido final HTTP/SSE de 10 turnos | 9 `answered` + 1 acuse `social`; todos útiles. Media 0,7465 s, mediana 0,3319 s, máximo/p95 muestral 3,1537 s; 0 llamadas al modelo; 10/10 bajo 5 s. |
| El mundo de Sofía → otro similar | 16,2833 s y 7,7688 s. Afinidad filosófica de catálogo con Thus Spoke Zarathustra; no se afirma semejanza de trama. |
| Obra ausente: La mala costumbre, de Alana S. Portero | Consulta externa 4,4338 s. Nueva sesión/proceso con proveedores deshabilitados y sockets públicos bloqueados: 0,6212 s, misma premisa, 0 LLM. |

Evidencias: `recorrido_cierre.json`, `filosofia_cierre.json`,
`obra_externa_primera.json`, `obra_externa_reutilizacion_sin_red.json`,
`metricas_cierre.json`. La sesión sin red usa el arnés existente
`scripts.knowledge.search_narrative_check --local-only --memory-snapshot ...`.

**No son un benchmark de carga ni prueba de exactitud del 99 %.** La muestra es
pequeña; parte de los ensayos compartió recursos con una captura de navegador.
El punto inicial usaba wsgiref aislado y el cierre Waitress. El recorrido final
incluye género e idioma, en lugar de afirmar que se resolvió una similitud profunda
con todos los filtros originales. No calcular una mejora global de cobertura
a partir de esas preguntas distintas.

La petición «dos libros similares en español» devolvió una sola opción en una
ronda y `unavailable` en otra (12,4221 s). Su seguimiento corregido se abstuvo en
0,2514 s sin recomendar títulos ajenos. Sigue pendiente mejorar cobertura de
afinidades, descripciones y filtros; una respuesta rápida incierta no es un acierto.
No se repitió toda la matriz histórica de microbiología ni se afirma resuelta.

## Persistencia e integridad

- Ausencia inicial verificada de La mala costumbre en las 14.467 obras de memoria,
  4 fichas del almacén auxiliar y 12 elementos de biblioteca; tampoco está en
  `core_libro`, `core_kbrecord` ni sus nombres normalizados. Se conservan las
  consultas de inventario en `ausencia_inicial.json` e `integridad_final_verificada.json`.
  Se obtuvieron identidad de Open Library y evidencia narrativa de Wikipedia.
  La copia de demo contiene una obra nueva con dos fuentes. La respuesta es una
  premisa documentada, no una trama exhaustiva.
- Esta incorporación sólo afecta a `.testtmp/demo-control-20261030`, no a los
  almacenes originales ni al MySQL original. El perfil conserva conocimiento entre
  arranques con esa misma carpeta; no se promete que otra carpeta ya lo contenga.
- MySQL local autenticado y utilizado realmente: `litmate_db`, 41 tablas,
  46.822 filas observadas, 55 libros del modelo `Libro`. La demo usa conexiones de
  sólo lectura y sesiones de archivo. No se importaron datos ni hubo migraciones.
- El arnés de reutilización comparó todos los conteos MySQL antes/después de su
  consulta: iguales. Esa comprobación no equivale a demostrar inmutabilidad de
  cada fila durante todo el día; se conservó el servidor habitual del usuario.
  No se borran filas para hacer coincidir un conteo histórico distinto.
- `.env`, memoria original y RAG original: SHA-256 iguales a la línea base.
  `quick_check=ok`, cero incidencias FK en ambos SQLite. Los cinco auxiliares del
  ensayo sin red también conservaron sus hashes. `integridad_cierre.json` recoge
  el inventario; `integridad_final_verificada.json` repite los conteos y verifica
  también los nombres de conocimiento SQL. `integridad_hashes_actual.json`
  conserva la comparación inicial.
- Respaldos existentes conservados. Sin Git destructivo, commits, push, modelos
  nuevos, importaciones masivas ni APIs de pago.

## Pruebas y grabación

- `tests_release.json`: **210 pruebas Django aprobadas**, SQLite y almacenes
  temporales; 3,348 s de suite, 4,589 s de proceso. Incluye que una categoría
  `Fiction` sola no confirma público adulto. No sumar rondas.
- `node verificar_chat_seguro.js`: 246 comprobaciones aprobadas.
- `node scripts/demo/test_finalize_retry.cjs`: cuatro casos adicionales aprobados
  (éxito tras bloqueo, conflicto definitivo, límite de reintentos, deadline).
- `pip check`: sin dependencias rotas. `git diff --check`: sin errores de formato.
- `https_cierre.json`: backend con host HTTPS exacto, 401 sin clave, admin 404,
  host desconocido 400, CSRF exigido, cookies Secure, HSTS, estáticos y saludo SSE.
  No es una prueba de TLS público ni de conectividad desde otra red.
- Grabación recomendada: `grabacion_defensa/funcionamiento_real.webp`, 27 capturas
  reales, ocho turnos, 16 respuestas de chat HTTP 200 y ninguna excepción JS en
  ese ensayo. Sin audio. Se inspeccionaron las capturas de identificación y
  seguimiento. No se fabricaron conversaciones ni se reemplazó el DOM por textos.

Se conservaron fallos intermedios: las dos primeras carpetas de capturas muestran
el límite de autenticación defectuoso; `captura_final` documenta el ordinal lento;
`captura_entrega` el conflicto de finalización entre clientes. No utilizarlas
como grabación de defensa. La última grabación no reprodujo el conflicto y fue
anterior al reintento adicional del cliente, que tiene sus pruebas independientes.

## Preparación remota y pendientes

Ver `servidor_remoto.md` para comandos, requisitos, prueba móvil y apagado.
Tailscale está instalado y autenticado; Funnel permanece `{}`. Waitress y
WhiteNoise se instalaron con aprobación. El gateway sólo permite chat, estáticos
y audio propio. El perfil HTTPS no confía en cabeceras reenviadas del solicitante.

El usuario pidió **sólo preparar** el firewall: no se aplicó. MySQL mantiene su
escucha previa en todas las interfaces. No se puede dar por resuelto su
aislamiento LAN/tailnet. Hace falta revisar/aprobar ese punto antes de publicar,
autorizar Funnel y probar desde datos móviles/instituto. No se abrieron puertos
de router ni se publicaron MySQL, Ollama o SearXNG mediante túnel.

La voz externa devolvió 503 durante el ensayo; se preservan su botón, ruta y
fallback del navegador. Las pruebas JS validan ese fallback, pero no se comprobó
audio audible ni micrófono real. No se declara que la voz remota funcione.

Persisten listas parciales, perfiles interpretativos y falta de sinopsis/portadas
en algunas fichas. La identificación por pistas no prueba una coincidencia única
entre todos los libros existentes. No se elimina incertidumbre para mejorar métricas.

## Archivos de esta revisión

- Lógica reutilizada: `core/ai_character_answers.py`, `ai_identification_details.py`,
  `ai_quick_answers.py`, `ai_related_recommendations.py`, `ai_narrative_answers.py`,
  `genre_recommendations.py`, `literary_ai.py`, `literary_ai_views.py`,
  `literary_constraints.py`, `bibliographic_http_probe.py`.
- Perfil aislado: `iniciar_demo.py`, `litmate_project/demo_settings.py`,
  `litmate_project/demo_urls.py`, `core/demo_gateway.py`, `requirements-demo.txt`.
- Cliente: `static/js/litmate_safe.js` (reintento de finalización) y
  `templates/base.html` (únicamente versión del asset; sin cambio visual).
- Regresiones: `core/test_detective_demo.py`, `core/test_demo_gateway.py`,
  `core/test_genre_recommendations.py`.
- Herramientas: `scripts/demo/check_demo.py`, `test_demo.py`,
  `test_finalize_retry.cjs`, `capturar_demo.py`, `capturar_demo.mjs`,
  `verificar_integridad.py`, `EstadoDemo.ps1`, `ProtegerServicios.ps1`.
- Informes de esta carpeta y continuidad en `reportes/continuidad_opencode.md`.

Se conservan las modificaciones anteriores del resto del repositorio; el listado
de `git diff` completo contiene también trabajo previo y no debe atribuirse
íntegramente a esta revisión.

## Estado al finalizar

`estado_cierre.json`: Waitress de prueba 8002/8003 detenido y navegadores propios
cerrados; MySQL, Ollama y SearXNG responden en localhost. Funnel sigue `{}` y no
se aplicó el firewall. En esa comprobación el puerto 8000 tampoco tenía escucha;
no se terminó ningún proceso ajeno. Para abrir la aplicación hay que usar los
comandos del procedimiento. Los hashes originales siguen iguales al cierre.
