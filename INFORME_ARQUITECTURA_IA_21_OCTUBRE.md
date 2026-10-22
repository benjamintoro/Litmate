# Arquitectura del asistente LitMate: herramientas, RAG y modelos locales

Fecha de revisión: 21 de octubre de 2026. Proyecto: `G:\Proyecto\Litmate`.

## Decisión

Conservar Django, Ollama y la recuperación existente. No añadir ahora LangGraph, LlamaIndex ni un segundo modelo conversacional obligatorio. La aplicación ya consulta herramientas bibliográficas y web mediante un recorrido controlado, con límites y comprobaciones propias. Los fallos recientes proceden de clasificación, contexto, cobertura bibliográfica, tamaño de los mensajes al modelo y validación de evidencias; cambiar el nombre de la biblioteca de orquestación no los resuelve por sí mismo.

Esto no descarta una migración futura. Tendría que demostrar una ventaja en una comparación reproducible conservando los mismos modelos, preguntas, fuentes, límites y validadores. Esta revisión no instaló paquetes, no descargó modelos, no ejecutó inferencias y no modificó archivos de `core`. Únicamente produjo este informe.

## Qué existe realmente

El recorrido actual puede describirse así:

1. `core/literary_ai_views.py` aplica privacidad, límites y memoria de conversación. Las consultas sencillas pueden resolverse mediante `core/ai_public_details.py` y `core/ai_catalog_fallback.py` sin inferencia.
2. `core/literary_conversation.py` conserva temas y preferencias; `core/literary_identity.py` resuelve obras, alias confirmados, referencias ordinales y continuaciones.
3. `core/literary_ai.py` clasifica la petición, decide recuperación y solicita un plan cuando la tarea lo necesita. Las peticiones sencillas ya cuentan con planes literales limitados, sin inventar preguntas adicionales.
4. `core/literary_search.py` coordina conocimiento local, documentos autorizados, catálogo Django, Open Library y Google Books opcional. `core/literary_research.py` comprueba qué evidencia necesita la pregunta concreta.
5. Si falta evidencia, el servidor permite búsqueda mediante SearXNG local y fuentes gratuitas. `core/literary_web.py` controla acceso HTTP, redes privadas, redirecciones, robots y extracción de pasajes. El modelo no recibe un navegador ni ejecuta direcciones arbitrarias.
6. La respuesta pasa por validación de esquema, identidad de fichas, cantidad y correspondencia entre texto y tarjetas, comprobación de citas y auditoría factual antes de publicarse.

Por tanto, existe **selección y ejecución de herramientas controlada por el servidor**. No se utiliza actualmente el protocolo nativo `tools`/`tool_calls` de Ollama: se obtienen decisiones estructuradas y el código decide qué funciones autorizadas ejecutar. Esta distinción evita afirmar que se añadió una herramienta nativa que todavía no se implementó.

La recuperación tampoco es exclusivamente vectorial. `core/local_rag.py` combina SQLite FTS5 con BM25 y similitud de embeddings locales, fusiona posiciones mediante Reciprocal Rank Fusion y filtra por identidad de obra. Conserva procedencia, localizador y distinción entre texto original y fichas redactadas. La colección auxiliar evaluada contiene cuatro fichas autorizadas; no equivale a una biblioteca de novelas completas.

## Evaluación de las alternativas

| Alternativa | Aporte posible | Decisión para este proyecto |
|---|---|---|
| LangGraph | Grafo explícito, estado durable, reanudación e intervención humana en procesos prolongados. | Posponer: el asistente mantiene un recorrido corto y acotado. Sería útil si aparecen investigaciones largas que deban reanudarse tras reiniciar el proceso. |
| LlamaIndex | Componentes de carga, indexación, recuperación, procesamiento de resultados y síntesis. | Posponer: ya existen estos componentes y filtros bibliográficos. Considerarlo si crece mucho la colección autorizada o se necesita un conector concreto. |
| Ollama con herramientas nativas | El modelo propone llamadas estructuradas, el servidor ejecuta funciones y devuelve sus resultados. | Experimento opcional y limitado; no reemplazar las protecciones existentes ni abrir ejecución libre. |
| Ollama con salidas estructuradas | Restringe la forma de la salida con un esquema JSON. | Conservar: ya se usa `format` y después se valida el contenido. Un JSON correcto no demuestra que un dato literario sea verdadero. |

LangGraph permite combinar decisiones deterministas y del modelo y no exige utilizar LangChain. Su documentación describe persistencia y reanudación; esas capacidades no constituyen una promesa de exactitud bibliográfica. [Documentación oficial](https://docs.langchain.com/oss/python/langgraph/overview).

LlamaIndex describe un recorrido RAG de preparación, indexación, recuperación, generación y evaluación, con componentes para selección y reordenamiento. En LitMate, la comparación debe medir recuperación real, no la cantidad de componentes instalados. [Introducción oficial a RAG](https://developers.llamaindex.ai/python/framework/understanding/rag/).

Los repositorios principales de ambos frameworks publican licencia MIT. Su ejecución local con proveedores locales puede mantener un costo obligatorio de API de $0; no se habilitarían servicios alojados, trazas remotas ni integraciones comerciales. Los servicios externos opcionales del ecosistema quedan fuera de esta decisión. [Licencia LangGraph](https://raw.githubusercontent.com/langchain-ai/langgraph/main/LICENSE), [licencia LlamaIndex](https://raw.githubusercontent.com/run-llama/llama_index/main/LICENSE).

Ollama documenta llamadas de herramientas, incluida la devolución de resultados para que el modelo continúe. Incorporar ese mecanismo podría ayudar a formular una consulta adicional específica; también puede añadir vueltas de generación. No proporciona automáticamente mejor selección de fuentes ni protección contra instrucciones maliciosas. [Herramientas de Ollama](https://docs.ollama.com/capabilities/tool-calling).

El esquema JSON se envía mediante `format` a `/api/chat`. LitMate además comprueba IDs, pruebas literales y coherencia entre obras. Estas comprobaciones deben conservarse aunque se cambie la forma de solicitar herramientas. [Salidas estructuradas de Ollama](https://docs.ollama.com/capabilities/structured-outputs).

## Modelos y hardware observados

Se consultó únicamente `/api/tags` del servidor Ollama local durante esta revisión. Modelos instalados:

| Modelo | Tamaño de archivos observado | Papel |
|---|---:|---|
| `qwen3:8b` | 5.225.388.164 bytes | Candidato conversacional de texto ya evaluado en informes existentes. |
| `qwen3.5:4b` | 3.324.173.934 bytes | Candidato menor; no se selecciona por ser más pequeño. |
| `qwen3.5:9b-q4_K_M` | 6.550.825.550 bytes | Modelo original, con pruebas previas de presión de recursos. |
| `embeddinggemma:latest` | 621.875.917 bytes | Embeddings locales existentes. |

El hardware registrado el 20 de octubre en `reportes/modelos_hardware_20261020.json` es Ryzen 5 5500X3D, 31,9 GiB de RAM física y RTX 4060 con 8.188 MiB de VRAM. No se vuelve a presentar esa memoria disponible como una medición de disponibilidad actual. El tamaño de los pesos no incluye memoria de contexto ni otros procesos.

Los informes previos documentan capacidades y licencias de los candidatos en `INFORME_FUENTES_MODELOS.md`. Esta revisión no repitió la comparación de inferencia y no elige un ganador nuevo. Es preferible un modelo conversacional activo y el embedder existente antes que cargar modelos adicionales sin beneficio medido. Un reranker solo estaría justificado con una colección y una evaluación más amplias.

El ensayo pequeño de recuperación en `reportes/rag_hibrido_20_oct.json` registró 7/8 primeros resultados correctos con BM25 y 8/8 con recuperación híbrida, además de un control negativo sin resultados. Mide recuperación en cuatro fichas, no una tasa de alucinación del chatbot.

## Latencia: observaciones y problemas aún medibles

Los siguientes puntos complementan las correcciones de preguntas sencillas, mensajes compactos y auditoría realizadas durante esta continuación. No se han aplicado como cambios adicionales en este informe.

**Generación secuencial.** Una respuesta puede requerir clasificación, rescate de clasificación, planificación, redacción, auditoría, reparación y nueva auditoría. Las consultas locales no cuestan dinero por llamada, pero consumen GPU y tiempo. Los diagnósticos ya registran etapas; conviene medir su contribución antes de añadir un bucle de herramientas o un framework.

**No existe transmisión de tokens del modelo al usuario.** `core/local_llm.py` solicita `stream=false`; `stream_result` en `core/literary_ai_views.py` divide la respuesta final en bloques de 160 caracteres después de validarla. Conserva la seguridad de publicación, pero no reduce el tiempo hasta el primer texto. Emitir borradores sin validar reduciría esa protección. Una mejora de progreso debe describir operaciones realmente ejecutadas y conservar la publicación de respuestas verificadas.

**Embeddings y metadatos repetidos.** `configured_embedder` en `core/local_embeddings.py` crea una instancia nueva. Su primera identificación consulta `/api/show` y `/api/tags`; generar un vector utiliza `/api/embed`. El catálogo principal y la colección auxiliar pueden recuperar la misma consulta durante una petición. No hay una memoria compartida por petición para reutilizar ese vector exacto. Esto es una oportunidad concreta de instrumentación y caché, no una latencia que este informe haya medido.

**Caché de matrices con una sola entrada.** `_vector_matrix` en `core/local_rag.py` usa `lru_cache(maxsize=1)`. Alternar el índice principal y el auxiliar puede expulsar la matriz previa y volver a leerla. Con cuatro fichas el efecto será pequeño; con miles de fragmentos debe medirse. Aumentar el límite requiere presupuestar RAM y mantener las comprobaciones de revisión del archivo.

**Búsqueda de sinopsis posterior a encontrar fichas suficientes.** `enrich_book_sources` puede realizar consultas web para dos libros sin descripción. Es útil cuando se solicitó una trama, pero no todas las recomendaciones necesitan el mismo nivel de enriquecimiento. Registrar si esa descripción cambió la respuesta permitiría evitar consultas que no aportan evidencia nueva, sin desactivar la investigación cuando sí es necesaria.

**Dos límites temporales distintos.** La investigación externa comparte un presupuesto habitual de 15 segundos; la petición completa admite hasta 360 segundos por defecto en `litmate_project/ai_settings.py`. El primero no limita el tiempo de inferencia. No se debe anunciar que el asistente responderá en 15 segundos.

**Recursos compartidos.** El embedder y el modelo conversacional comparten el equipo. Antes de modificar contextos o mantener varios modelos cargados, comparar tiempos de carga, evaluación del prompt y generación. Ollama documenta cómo observar si el modelo reside en CPU o GPU; esta revisión no cargó modelos para medirlo. [FAQ oficial](https://docs.ollama.com/faq).

Como referencia histórica, `reportes/validacion_final_qwen3_8b_8192.json` muestra 120,440 / 77,912 / 59,013 segundos en tres consultas temáticas, con fallback conservador en las dos primeras. `reportes/validacion_recomendaciones_compactas_21_oct.json` registra 22,266 / 14,302 / 6,924 segundos con tres llamadas locales por consulta. Son ejecuciones concretas de revisiones distintas, no un ensayo controlado de frameworks ni una garantía para otras preguntas. Los fallos de contexto de `reportes/validacion_contexto_21_oct.json` motivaron cambios posteriores; no se presentan como éxitos del código final.

## Experimentos opcionales concretos, sin nuevas APIs de pago

1. **Reutilización por petición del vector de consulta.** Instrumentar las llamadas al embedder y reutilizar un vector únicamente si coinciden texto exacto y digest del modelo dentro de la misma petición. La memoria no debe persistir el texto privado ni reutilizar vectores entre modelos. Comparar número de `/api/embed`, tiempo total y resultados de recuperación; aprobar únicamente si se conservan los resultados y mejora el tiempo medido.
2. **Prueba pequeña de herramientas nativas.** Exponer solo `buscar_catalogos(consulta)` y `buscar_fuentes_publicas(consulta)` con argumentos limitados; sin navegador genérico, shell ni descarga de URLs propuestas por el modelo. Ejecutar mediante las funciones actuales y su presupuesto compartido. Mantener validadores, memoria y auditoría. Comparar con el routing actual usando las mismas fuentes simuladas primero y servicios reales después. No adoptar si incrementa errores, vueltas de generación o latencia sin mejorar cobertura.
3. **Caché de dos matrices.** Ensayar alternancia de dos índices representativos; medir RAM, lecturas y latencia antes/después. No merece instalar un framework para sustituir una política pequeña de caché.

No se realizaron estos experimentos ni se declara una mejora anticipada. LangGraph solo pasaría a una prueba si hiciera falta reanudación durable; LlamaIndex si un componente de recuperación concreto mostrase una mejora frente al actual. Cualquier prueba mantendría los servicios locales y la interfaz existente.

## Cómo comprobar costo obligatorio de API de $0

`build_assistant` utiliza `OllamaJSON`; la configuración fija el proveedor local y deshabilita Pinecone. El cliente exige modelos GGUF locales descargados y rechaza metadatos de modelos remotos. Google Books requiere habilitación y confirmación explícita de modalidad sin facturación. Ninguna propuesta de este informe añade un proveedor comercial.

Para una eventual integración, las pruebas deben comprobar que no salen solicitudes hacia proveedores comerciales ni servicios de trazas, que los clientes solo apuntan al servidor local y a las fuentes públicas autorizadas, y que no se activa ninguna alternativa remota cuando falla Ollama. Los frameworks no deberían obtener credenciales de proveedores antiguos ni elegir clientes por defecto.

Costo obligatorio de API de la arquitectura propuesta: **$0**. Permanecen consumo eléctrico, equipo, almacenamiento y conexión. Esta afirmación no certifica el plan de la base TiDB existente ni un Redis remoto opcional, ni convierte servicios alojados del ecosistema en gratuitos.

## Criterio de aceptación

Toda alternativa deberá mejorar una medición concreta: cobertura de evidencia, identidad correcta de la obra, cumplimiento de filtros, continuidad de conversación o latencia. Se deben separar falta de evidencia reconocida, fallo de servicio, rechazo de un borrador inventado y error factual publicado. Los resultados con fuentes simuladas no sustituyen pruebas reales.

No hay evidencia suficiente para afirmar que el error global sea inferior al 1 %. Ni añadir un framework ni verificar el formato JSON proporciona esa garantía. La decisión actual es ampliar y medir el sistema que ya funciona, conservando las protecciones y la personalidad del asistente.
