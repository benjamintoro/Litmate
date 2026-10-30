# Lote 2 — Evidencia, síntesis y presentación

## Pipeline real y puntos de pérdida

`/chatbot_query/` → contexto privado de sesión → `_answer_with_cache` →
`_compute_answer_impl` → rutas locales/identidad → `narrative_answer` →
`retrieve_sources` → `quick_knowledge_sources` (SQL, conocimiento, memoria,
biblioteca) → Wikipedia/Open Library/Wikidata → descubrimiento SearXNG y
lectura pública permitida → respuesta directa o síntesis/auditoría Ollama →
presentación en español → SSE `ready` → `/chatbot_finalize/` → sesión/historial
y tarjetas. Se conserva el mecanismo existente de persistencia y memoria.

Las implementaciones siguen en `core` y los lanzadores administrativos en
`scripts/knowledge`; se localizaron en el repositorio actual, no por suponer
una estructura anterior. `validate_audit` y `diagnosticar_ia` existen.

Causas reproducidas:

1. `request_for` no admitía «Hola, dime…» y rechazaba saludos con punto como si
   fueran varias tareas. La pregunta no entraba en la ruta narrativa y el
   fallback publicaba «Encontré estas referencias… / Pasaje recuperado».
2. `retrieve_sources` consideraba cualquier `_content` no vacío suficiente para
   cerrar una búsqueda. Identidades mínimas de Wikidata y pertenencia de
   personajes no aportaban una trama. Naruto se quedaba con esos datos; El
   Señor de los Anillos podía intentar sintetizar desde páginas de personajes.
3. La resolución literaria no reconocía consistentemente plurales como
   «serie de novelas» ni manga antes de una mención posterior de su anime.
4. Generación y auditoría recibían información de pertenencia/biografías como
   si fuera contexto de trama. El modelo añadió detalles no respaldados. Una
   prueba real mostró una lista de personajes aceptada con una cita sin sus
   nombres; se añadió una regresión que falló antes de fortalecer la validación.
5. Una premisa española completa de 303 caracteres no entraba en la vía
   extractiva de 300; se gastaban dos llamadas al modelo pese a existir una
   oración principal válida y reutilizable.
6. `LitMateSafe.renderMessage` construía el desplegable «Fuentes consultadas»
   a partir del pie de URLs. No provenía de SearXNG ni de MySQL. El mismo
   renderizador se utiliza al cargar historial y al redibujar SSE.

## Cambios por función

| Archivo / función | Cambio |
|---|---|
| `core/ai_narrative_answers.py::request_for` | Retira sólo el saludo inicial antes de clasificar la petición; conserva título, filtros de privacidad y guardas de preguntas compuestas. |
| `bound_sources`, `work_type` | Admite identidades literarias plurales y manga, sin aceptar anime/película como evidencia del original. |
| `_task_content` | Regla de parada dependiente de la tarea: identidad, pertenencia y biografía de personajes no bastan para trama. No es una aprobación factual. |
| `retrieve_sources` | Continúa con proveedores actuales cuando lo almacenado no responde a la tarea. No añade otro pipeline ni borra datos originales. |
| `_sentences` | Si una frase licenciada excede el límite y termina en un complemento opcional de propósito introducido por coma, puede conservar su oración principal completa. No corta por número de caracteres ni inventa texto. El pasaje y la prueba literal siguen disponibles. |
| `synthesize_answer` | Mantiene originales para auditoría, proyecta sólo evidencia adecuada a la trama para generar, conserva la identidad y explicita el formato manga cuando la introducción lo acredita. No incluye tablas de pertenencia como narración. |
| `_publish` | El pie muestra sólo las URLs utilizadas por afirmaciones respaldadas. Todas las fuentes siguen disponibles internamente; no hay referencias añadidas de páginas de personajes que no respaldaron la trama. |
| `core/literary_identity.py::same_work` | Reconoce formatos literarios antes de menciones de adaptación; no convierte una página de anime en manga. |
| `core/ai_quick_answers.py::_is_adaptation_page`, `reference_answer` | Desambigua original/adaptación por identidad; bloquea fragmentos como sustituto de una sinopsis incluso si la formulación no coincide con el parser rápido. |
| `core/literary_quality.py::unsupported_character_list_claim`, `validate_audit` | Una lista explícita de personajes debe tener sus nombres en su propia prueba citada, también cuando se inserta en una respuesta de trama. |
| `core/literary_ai_views.py::_answer_with_cache` | No inyecta estado de recomendaciones vacío en tareas sin ese contexto. Se conserva el estado existente cuando existe. |
| `core/ai_answer_cache.py` | Política `extractive-answer-v6-narrative-content`: no reutiliza respuestas anteriores a estas correcciones. No borra registros. |
| `core/literary_presentation_language.py::localize_result` | Retira encabezados solicitados del texto visible sin quitar evidencia, atribución o enlaces. |
| `static/js/litmate_safe.js::renderMessage` | No genera `details/summary` de fuentes. Usa enlaces discretos, conserva atribución y avisos; elimina encabezados históricos o incompletos sin habilitar HTML del servidor. |
| `core/test_search_narrative_repair.py` | 18 regresiones nuevas con obras sintéticas y fuentes controladas. |
| `verificar_chat_seguro.js` | 240 comprobaciones, con historial, SSE, pies vacíos/malformados, enlaces, tarjetas, seguridad y voz. |
| `scripts/knowledge/search_narrative_check.py` | Instrumentación administrativa optativa de peticiones reales, fuentes, borrador y auditoría; copia memoria/cachés y verifica conservación. |

No se aumentaron los límites de pruebas literales, se desactivaron validadores
ni se guardaron redacciones de Ollama como hechos. La retirada de afirmaciones
rechazadas reutiliza `_supported_summary` y vuelve a validar lo que se publica.
El control nuevo de listas es específico de ese patrón lingüístico, no un
reconocedor universal de entidades ni una demostración automática de verdad.

La traducción sigue utilizando la política común existente, con evidencia
original conservada y normalizaciones validadas/cacheadas; no se añade otro
servicio ni se vuelve a traducir automáticamente el contenido español.

## HTTP/SSE real antes y después

MySQL local, Docker y Ollama disponibles. Las pruebas usaron memoria copiada
del mismo origen, cachés de respuesta nuevas y cookies firmadas para no crear
lectores/historial en producción. La generación y las respuestas de los
proveedores **no se simularon**.

| Petición | Antes | Cierre | LLM antes → cierre |
|---|---|---|---:|
| Hola, dime la trama de Harry Potter | Referencias y pasaje crudo, 6,0412 s | Conflicto Harry/Voldemort, 2,8960 s | Ver diagnósticos del baseline → 0 |
| Dime la trama de El Señor de los Anillos | `unavailable`, auditoría rechazada, 34,9595 s | Trama sobre Frodo, Anillo y Sauron, 2,9631 s | 2 → 0 |
| Dime los personajes de Papelucho y el marciano | Papelucho y Det, 0,1490 s | Misma capacidad conservada, 0,1454 s | 0 → 0 |
| Dime la trama de Naruto | `unavailable`, auditoría rechazada, 21,7738 s | Premisa del manga sin mezclar anime, 1,9333 s | 2 → 0 |

Contenido de cierre revisado:

- **Harry Potter:** «El argumento se centra en la lucha entre Harry Potter y el
  malvado mago Lord Voldemort, quien asesinó a los padres de Harry en su afán de
  conquistar el mundo mágico». Procede del artículo de la saga, no de un volumen
  seleccionado arbitrariamente.
- **El Señor de los Anillos:** describe la Tierra Media y el viaje de Frodo para
  destruir el Anillo, relacionado con el poder de Sauron. Se conserva evidencia
  del artículo de la novela y se excluyen del pie las biografías no utilizadas.
- **Papelucho:** identifica a Papelucho y Det y conserva sus papeles documentados
  por la editorial. No se sustituyó por una plantilla nueva.
- **Naruto:** «Narra la historia de un ninja adolescente llamado Naruto Uzumaki,
  cuyos padres murieron en el ataque del Zorro de las Nueve Colas y quien aspira
  a convertirse en Hokage (líder de su aldea)». El pasaje proviene de la
  introducción que identifica expresamente el manga y su autor; no afirma hechos
  de su anime ni añade personajes desde pertenencia Wikidata.

Los cuatro turnos finalizaron con `answered` y `[DONE]`. La revisión del
contenido anterior, y no sólo HTTP 200, fundamenta este resultado. Son cuatro
casos y una muestra de proveedores en este PC: no acreditan una tasa global de
error del 1 % ni garantizan estos tiempos para otras obras.

Artefactos completos: `http_antes.json`, `http_despues_01.json`,
`http_despues_final.json`, `http_entrega.json` y **`http_cierre.json`**.
Los intentos intermedios se conservan: uno mezcló formatos y otros incluyeron
detalles no contenidos en la prueba a pesar de la aprobación del LLM. El cierre
de Naruto utiliza extracción literal controlada; **no demuestra que la auditoría
con modelos haya dejado de cometer todos esos errores en consultas abiertas**.

## Fallos técnicos, conocimiento insuficiente y diagnóstico

La ruta narrativa ya distingue `insufficient_content`, `model_not_configured`,
`generation_declined`, `audit_not_approved`, errores de proveedor y tiempo
agotado. La recuperación externa conserva sus estados `empty`, `partial`,
`timeout`, `unavailable`, `invalid_response` y `cooldown`.

El script administrativo registra fuentes vinculadas, identidad, etapas,
borrador/auditoría y resultado incluso cuando la publicación se rechaza. Está
desactivado en el funcionamiento habitual y sólo usa las preguntas públicas
fijas del benchmark; no crea un registro de conversaciones privadas. El frontend
sólo recibe los diagnósticos públicos ya filtrados por la aplicación.

Si hay evidencia local suficiente, no se necesita SearXNG ni Ollama. Si un motor
falla, quedan los demás y los adaptadores directos. Si no puede confirmarse la
trama o falla la síntesis/auditoría, se conserva una abstención breve: no se
sustituye por una pared de resultados del buscador.

## Conservación y funcionamiento local

`http_sin_internet.json`: proveedores externos desactivados en ese proceso.

- Ficha nueva de SQL: **Elämän polulla — Niilo Mantere**, fuente Gutenberg24905,
  tarjeta `sqlkb`, respuesta en **0,4016 s**, cero llamadas al modelo.
- Memoria narrativa: **Orgullo y prejuicio**, contenido local con fuente
  Wikipedia, **0,6038 s**, cero llamadas al modelo.

Todas las pruebas administrativas nuevas comprobaron conteos MySQL antes y
después: **41 tablas / 37.380 filas, sin cambios**. La memoria original conservó
su hash; las escrituras del pipeline de prueba se limitaron a la copia temporal.
No se modificó ni reimportó el catálogo. El mecanismo de sesiones/historial de
producción sigue siendo el mismo; la prueba administrativa no crea historial.

`rag_integridad.json`: lectura real sin embeddings nuevos de los índices
existentes. Conocimiento: cuatro documentos/cuatro fragmentos, un resultado;
biblioteca: 12 documentos/11.289 fragmentos, dos resultados. Recuperación
aproximada 1,3/1,9 ms, ambos hashes intactos. Las rutas RAG genérica y de memoria
no tienen archivo en la configuración actual; no se crearon ni reconstruyeron.
Estas lecturas prueban integridad/recuperación, no que los cuatro turnos HTTP
hayan usado búsqueda vectorial.

`.env` conserva SHA256
`1d8e35effc765d26ecb73f3e2ee26c886a1e3d98b1bc45590c356b8604008e74`.
El manifiesto del respaldo original MySQL conserva
`89e44e64babf9278643e5ef45c607a61de6e3e65973b050bccba7e1efccb1005`.
Todos los respaldos anteriores permanecen disponibles; no hubo migraciones,
dependencias nuevas, cambios de pesos, eliminación de datos ni push.

## Pruebas y fallos preservados

- Nuevas regresiones iniciales: ocho fallos de diez casos, corregidos y
  reejecutados. Las 18 regresiones finales pasan.
- Regresión de lista de personajes: falló porque el auditor aceptaba una cita
  sin los nombres; pasa tras fortalecer la validación.
- Regresión de premisa larga: falló antes del cambio y ahora comprueba el
  pasaje literal de la oración principal publicada.
- Compatibilidad inicial: se detectaron cuatro fallos y un error al restringir
  demasiado contenido editorial/en inglés. Se corrigió la distinción entre
  regla de parada de búsqueda y contenido original disponible para auditoría;
  las pruebas originales se conservaron.
- Una ejecución de 370 pruebas tuvo un `StopIteration` en el test existente
  `test_robots_and_content_share_one_budget_instead_of_renewing_it`. Esa prueba
  aislada pasó; el cierre conjunto siguiente de **371 pruebas pasó en 6,796 s**.
  No se cambió su expectativa ni se declara diagnosticada la intermitencia.
- **240 comprobaciones JavaScript** y **seis regresiones offline del motor**
  aprobadas. No se ejecutó nuevamente toda la suite del proyecto.

La batería dirigida cubre trama suficiente/parcial, saga, manga/anime,
personajes, contradicciones, ausencia de evidencia, contenido inglés,
seguimientos, idioma, tarjetas, identidad, caché, presupuestos externos,
seguridad de extracción y auditoría estricta.

## Pendientes reales

1. Medir disponibilidad y cuotas externas durante períodos más largos.
2. Mejorar la auditoría semántica de afirmaciones compuestas en redacciones
   abiertas. Los intentos con Ollama mostraron aprobaciones excesivas; las
   barreras añadidas no constituyen una solución universal a las alucinaciones.
3. Investigar el test intermitente de presupuesto/robots si vuelve a fallar.
4. Ampliar el benchmark independiente de novelas, sagas y manga. No se añadieron
   respuestas ni excepciones de procesamiento específicas para Naruto o Harry
   Potter; sus datos proceden de las fuentes recuperadas.
5. No se hizo una inspección visual en navegador de todas las conversaciones
   antiguas. La ausencia de desplegables y la conservación de enlaces/tarjetas
   se comprobaron con el renderizador compartido y sus pruebas de historial/SSE.
