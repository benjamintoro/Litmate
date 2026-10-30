# LitMate: correcciones y comprobaciones del 21 de octubre de 2026

Trabajo directo en `G:\Proyecto\Litmate`. Se conservaron los cambios previos y el diseño del chat. No se modificaron plantillas, estilos, tarjetas, voz ni avatares. No se hicieron commits, migraciones ni pruebas contra la base principal.

**Estado del alcance solicitado: no está completado al 100 %.** Hay implementación real de búsqueda, contexto y validación, pero no se ha demostrado precisión general ni respuesta rápida en todas las consultas. Algunas fuentes permiten únicamente descubrir enlaces. La revisión posterior de latencia añade correcciones de citas web y clasificación de seguimientos; sus resultados se distinguen del ensayo anterior.

## Qué se corrigió

1. **Recomendaciones espaciales.** «Si busco recomendaciones de otros libros con temática espacial» ahora conserva la petición como un tema nuevo, busca espacio **y** ciencia ficción y comprueba ambas materias en cada ficha. No recomienda simplemente cualquier distopía. Las exclusiones expresas, como «sin ciencia ficción», prevalecen; una petición de divulgación no se convierte en una novela. Los títulos citados no se reinterpretan como instrucciones de búsqueda.
2. **«Dime» frente a «busca».** Las peticiones sencillas de personajes utilizan el mismo recorrido. Al localizar una ficha se tolera la omisión de un artículo inicial; esto no crea un alias ni relaja `same_work`. La consulta pública conserva la variante bibliográfica completa, incluso ante homónimos de autores distintos. La autoría se verifica después.
3. **Traducciones y volúmenes.** Se utilizan ediciones vinculadas por Open Library a la obra. Un título de colección no identifica automáticamente un volumen. Para confirmar un título corto de edición recopilatoria se comprueban el rango explícito de la obra, la clave del autor, la relación de edición, el subtítulo y su tabla de contenidos. Enumerar dos o tres partes por sí solo no demuestra que sea la obra completa.
4. **Personajes en tablas.** Wikipedia TextExtracts omitía la tabla de *El Señor de los Anillos*. Se consulta su API oficial `action=parse` para recuperar filas publicadas bajo una sección explícita de personajes. Para esta pregunta se prioriza esa lectura, evitando gastar otra antes. Se excluyen secciones y subsecciones de adaptaciones, películas, videojuegos y reparto, incluidas `Cast` y reparto de voz. Los nombres y papeles no se generan con un modelo.
5. **Contradicciones.** La ruta sin modelo deja pasar al flujo de evaluación dos descripciones distintas del mismo personaje. Las relaciones de parentesco incompatibles con respaldo literal se detectan como evidencia que necesita contraste. Una lista más corta o una ocupación complementaria no constituye una contradicción por sí sola.
6. **Pruebas que no respaldaban la respuesta.** Las materias del catálogo no pueden demostrar acontecimientos de una trama aunque la ficha tenga además otra sinopsis. Las preguntas sobre sucesos, escenas o desenlaces deben citar el pasaje específico recuperado: citar una página general sobre la amistad entre dos personajes no demuestra cómo llegó uno de ellos ni qué intentó hacer después. Se conserva la validación de todas las frases y de la obra a la que pertenece cada prueba.
7. **Reparaciones que repetían el mismo error.** La reparación recibe las frases rechazadas como advertencias separadas de la evidencia. Se conservan también las que el auditor llamó `supported` pero cuyo apoyo rechazó el validador. Los borradores factuales rechazados no se incorporan al historial como hechos. Ninguna advertencia se convierte automáticamente en una fuente.
8. **Respuesta con solo un saludo.** Se conserva la comprobación entre texto y tarjetas y se añade una cota de longitud al transporte de recomendaciones. Si el modelo devuelve únicamente un saludo y existen fichas temáticas suficientes, se construye inmediatamente el respaldo bibliográfico ya validado, evitando repetir una inferencia que en las pruebas volvía a saludar. Este respaldo ofrece títulos, autores y alcance; no inventa sinopsis ni responde preguntas de contenido.
9. **Contexto y consumo.** Se elimina la duplicación exacta de descripciones en el transporte de auditoría únicamente cuando sus pasajes íntegros ya están presentes, asociados al mismo ID. No se retiran pruebas, fuentes contrarias ni controles. Sin fragmento del lector o recuperado, el esquema ya no ofrece `basis=excerpt`.
10. **Recuerdos sencillos ya documentados.** Un identificador local consulta únicamente las fichas factuales originales CC0. Exige un candidato único, suficiencia sin contradicción y dos pistas narrativas documentadas fuera del título y autor. Solo propone la identidad y pregunta «¿Te suena?»: no añade trama. Aplica los validadores de respuesta, evidencia y auditoría estricta. Si no se cumplen esas condiciones, continúa el asistente normal. No convierte la puntuación de similitud en una probabilidad ni una certeza.

La conversación breve reserva hasta 1.024 tokens de salida y la auditoría compacta hasta 1.536, manteniendo los mensajes, las instrucciones y los controles. Una respuesta truncada sigue siendo rechazada. No se cambió la ventana de contexto ni el modelo configurado en producción.

## Archivos modificados en esta continuación

| Responsabilidad | Archivos |
|---|---|
| Intención, contexto y catálogo temático | `core/books_google.py`, `core/literary_conversation.py` |
| Respuesta de personajes, identificación local y respaldo bibliográfico | `core/ai_public_details.py`, `core/ai_identification_details.py`, `core/ai_catalog_fallback.py`, `core/literary_ai_views.py` |
| Fuentes, ediciones y Wikipedia | `core/literary_search.py`, `core/literary_web.py` |
| Evidencia, generación y reparación | `core/literary_research.py`, `core/literary_ai.py`, `core/literary_quality.py`, `core/local_llm.py` |
| Ejecución de pruebas reales | `verificar_investigacion.py` |
| Clasificación literal de seguimientos documentados y medición por etapa | `core/ai_literal_followup.py`, `core/local_llm.py` |
| Preparación opcional de perfil textual, sin descarga de pesos | `preparar_modelo_texto.py`, `core/test_prepare_text_model.py` |
| Regresiones nuevas | `core/test_space_topic_recommendations.py`, `core/test_wikipedia_character_tables.py`, `core/test_catalogue_narrative_proof.py`, `core/test_compact_audit_context.py`, `core/test_factual_repair_context.py`, `core/test_local_excerpt_basis.py`, `core/test_local_recommendation_minimum.py`, `core/test_local_output_budget.py`, `core/test_question_specific_citations.py`, `core/test_ai_identification_details.py` |
| Regresiones ampliadas | `core/test_ai_public_details.py`, `core/test_openlibrary_editions.py`, `core/test_catalogue_scope_and_entry.py`, `core/test_grounded_topic_fallback.py`, `core/test_literary_research.py`, `core/test_simple_factual_context.py` |
| Regresiones de la continuación de latencia | `core/test_literal_followup.py`, `core/test_literal_followup_integration.py`, `core/test_recommendation_web_evidence.py`, `core/test_local_stage_metrics.py` |

El historial del trabajo anterior, incluido el RAG híbrido, se conserva en [INFORME_CONTINUACION_20_OCTUBRE.md](INFORME_CONTINUACION_20_OCTUBRE.md). `git status --short` muestra el conjunto real sin hacer un commit.

## Fuentes y arquitectura elegidas

Se mantienen Open Library, Wikipedia y Wikidata oficiales, SearXNG local y la extracción autorizada de páginas públicas mediante Trafilatura. Google Books continúa opcional, con confirmación expresa de configuración sin facturación; permanece desactivado en los ensayos. Los fragmentos de resultados sirven para descubrir páginas, no como prueba de haberlas leído.

Amazon, Buscalibre, Casa del Libro, Goodreads, Barnes & Noble, Gandhi y WorldCat permanecen como descubrimiento de enlaces cuando el buscador los encuentra. No se inventó una API gratuita para esas tiendas ni se extrajo contenido prohibido. Fandom se limita al descubrimiento del host exacto `lotr.fandom.com`: no se habilitó `*.fandom.com`, su API ni su lectura automatizada. Library of Congress devolvió 403 en los ensayos conservados; no se evadió. Los detalles y condiciones están en [INFORME_FUENTES_MODELOS.md](INFORME_FUENTES_MODELOS.md).

Se evaluaron LangGraph, LlamaIndex y las herramientas nativas de Ollama. Se conserva Django y la orquestación existente: ya decide qué recuperadores autorizados utilizar, aplica presupuestos y verifica evidencia antes de publicar. No se encontró una mejora medida que justificara añadir otro framework o reescribir la aplicación. El análisis, sus fuentes oficiales y las alternativas están en [INFORME_ARQUITECTURA_IA_21_OCTUBRE.md](INFORME_ARQUITECTURA_IA_21_OCTUBRE.md).

## Modelos y RAG

El equipo tiene Ryzen 5 5500X3D, 31,9 GiB de RAM y RTX 4060 de 8 GiB. Se evaluaron los modelos locales gratuitos instalados `qwen3.5:9b-q4_K_M`, `qwen3.5:4b` y `qwen3:8b`; se conserva `embeddinggemma:latest` para recuperación. Los ensayos no demostraron un reemplazo conversacional con mejor calidad y latencia en todas las tareas. **No se cambió `.env`: continúa el 9B con contexto de 16.384.**

- 4B: una aparente respuesta era solo un saludo y las otras dos fueron rechazadas. No se seleccionó.
- 8B con 8.192: algunas recomendaciones fueron rápidas, pero hubo errores de contexto y respuestas rechazadas sobre recuerdos conocidos. No basta para sustituir el modelo de producción.
- 8B con 12.288: el caso espacial respondió mediante respaldo bibliográfico en 58,703 s. El seguimiento sobre Det respondió en 54,232 s, pero identificar *El principito* volvió a fallar tras 125,415 s. Ese ensayo se interrumpió y quedó registrado; no se cuentan sus casos pendientes como ejecutados.
- 9B: conservado por continuidad y porque no se demostró una alternativa superior de forma general. También tiene fallos y latencia alta; conservarlo no equivale a certificar su precisión. Los informes conservan tanto respuestas como rechazos y borradores para revisión local.

La última comprobación de 8B/8.192 conservó una conversación cálida y revisada en 36,181 s, pero volvió a rechazar el seguimiento sobre Det por referencias incorrectas en 54,423 s. No se eligió únicamente por conversar más rápido. Evidencia: `reportes/latencia_8b8k_ultima_21_oct.json`.

Se investigó también la memoria del paquete 9B. Su manifest contiene un GGUF de lenguaje de 5.629.109.120 bytes y un proyector visual separado de 921.704.832 bytes. Se creó localmente `litmate-qwen35-text:9b-q4_K_M`, reutilizando exactamente el mismo GGUF, renderer, parser, plantilla, parámetros y licencia, sin descargar ni recuantizar pesos. La API confirma `completion`, `tools` y `thinking`, sin `vision`. Se conserva el tag original.

La variante textual ocupó 5.761.421.803 bytes según `/api/ps`, todos en GPU, con contexto de 16.384. Esto mide residencia agregada; **no demuestra que el proyector visual fuera la causa de toda la lentitud** ni que antes se ejecutaran capas de lenguaje en CPU. El seguimiento sobre Det tardó 77,484 s y necesitó reparación, frente a 73,795 s del ensayo integrado original. La recomendación espacial tardó 143,893 s, frente a 115,131 s del original, y volvió a utilizar el respaldo bibliográfico validado. La conversación informal terminó en 42,193 s; las conversaciones de los otros ensayos no tenían un historial idéntico, por lo que no constituyen una comparación controlada de ese caso. No se anuncia una aceleración general ni se cambia `.env` por ese único ahorro de memoria. Evidencia: `reportes/modelo_textual_creado_21_oct.json`, `reportes/residencia_texto_9b_21_oct.json` y `reportes/modelo_texto_prueba_real_21_oct.json`.

El helper verifica hashes y perfil. Sin argumentos de creación solo inspecciona; `--create` permite crear el alias fijo si no existe y nunca reemplaza uno diferente. La comprobación real de solo lectura terminó con `existing_profile_verified`, sin inferencia ni cambios en el manifest original (`reportes/perfil_alias_texto_21_oct.json`). La importación conserva los pesos, como permite la [API oficial de creación](https://docs.ollama.com/api/create) y la [importación GGUF](https://docs.ollama.com/import). Flash Attention y caché KV Q8 se evaluaron documentalmente, sin modificar el servidor: pueden reducir la caché de atención, pero no todos los estados recurrentes de Qwen3.5. No se ejecutó un segundo servicio ni se atribuye un beneficio medido a opciones que no se probaron.

El RAG existente combina BM25, embeddings locales y fusión RRF con filtro de obra, procedencia y localizador. La prueba real anterior de ocho consultas positivas y un control negativo dio 7/8 primeros resultados correctos con BM25 y 8/8 con recuperación híbrida, sobre **cuatro fichas factuales originales autorizadas**, no sobre novelas completas. No se añadieron modelos de reranking ni otra base vectorial sin demostrar beneficio. Se mantuvo la auditoría completa mientras se redujo texto duplicado en su transporte.

## Comprobaciones automáticas y límites de las mediciones

**972 pruebas Django aprobadas** en el verificador aislado (`reportes/pruebas_continuacion_latencia_21_oct.txt`), frente a las 947 de la entrega anterior (`reportes/pruebas_finales_21_oct.txt`). **194 comprobaciones del chat aprobadas**, incluidas seguridad, formato, SSE, CSRF y voz. `pip check` no detectó incompatibilidades; `git diff --check` no detectó errores de espacios. No hay cambios en `static/` ni `templates/`.

El verificador utiliza SQLite en memoria, desactiva migraciones y aísla archivos auxiliares. Las pruebas de fallos de API, resultados incorrectos, contradicciones, límites y seguridad son controladas; no se presentan como solicitudes reales exitosas. El resultado final y los ensayos HTTP se registran en la sección siguiente.

`answered` significa que el sistema publicó una respuesta; no demuestra por sí mismo que cada frase sea correcta. Durante la revisión se detectaron aprobaciones con respaldo inadecuado y se añadieron regresiones. Los informes con `source_files_changed_during_run=true` documentan ejecuciones durante las que cambió código: sirven para diagnosticar, no como comparación controlada entre modelos.

### Ensayo integrado de la entrega anterior

El informe `reportes/comprobacion_final_estable_21_oct.json` usa el 9B configurado, APIs reales, el mismo presupuesto compartido de dos búsquedas y tres lecturas que el endpoint, y SQLite aislado. Las fichas CC0 son datos reales de la colección local. Se excluye únicamente la consulta a la base principal, no se simulan respuestas HTTP ni el modelo. El hash de código permite comprobar que no cambió durante esa ejecución. Es una medición anterior a las nuevas correcciones de citas y clasificación literal.

| Consulta | Antes observado | Resultado final medido |
|---|---|---|
| Niño, planeta pequeño y rosa | 74,283 s; identificaba la obra pero añadía un detalle no respaldado | Propone *El principito*, 0,046 s, sin inferencia ni HTTP; no añade argumento |
| Todos los animales son iguales | Rechazo tras 111,927 s al ampliar el argumento | Propone *Rebelión en la granja*, 0,009 s, sin inferencia ni HTTP; no inventa una cita |
| Escena sin ninguna pista | Pedía información adicional | Pide una pista concreta, 0,009 s, sin modelo ni búsqueda |
| «Dime los personajes del señor de los anillos» | Reproducción fallida de 44,961 s | Cinco papeles publicados vinculados a Tolkien, 6,989 s; seis solicitudes HTTP y tres lecturas, sin modelo |
| «Busca los personajes…» a continuación | Podía seguir otra ruta y devolver películas | Misma obra y respuesta, 0,022 s, reutilizando historial y caché |
| Personajes de *Papelucho y el marciano* | La ruta local ya respondía | Se conserva: dos personajes documentados, 0,019 s |
| «¿Y qué sucede con Det?» | Rechazo o referencias generales que no respaldaban los hechos concretos | Mantiene la obra, consulta fuentes y cita el pasaje de Wikipedia sobre Det, 73,795 s; sigue lento |
| Aceptar recomendaciones con temática espacial | La captura no obtenía recomendaciones fiables | Tres obras pertinentes con texto y tarjetas coherentes, 115,131 s; utiliza el respaldo bibliográfico validado después de rechazar el borrador, sin publicar su sinopsis insegura |

Las diferencias incluyen cambios de estrategia y de cantidad de texto: la identificación rápida devuelve solo identidad y confirmación, no intenta redactar una sinopsis. La repetición de personajes mide reutilización de caché e historial, no una segunda búsqueda fría. Las ocho consultas terminaron con el resultado previsto (siete respuestas y una solicitud de pistas), sin cambios de código durante el ensayo. **No equivale a un 100 % de exactitud del asistente.** El resumen está en `reportes/resumen_final_21_oct.json`; el informe completo conserva respuestas, fuentes, rechazos y tiempos de cada etapa.

La velocidad general sigue pendiente: los 73,795 s de Det y 115,131 s de la recomendación espacial son demasiado altos. No se atribuye a las respuestas rápidas de identificación una reducción general de todos los tiempos. La matriz de quince casos está disponible, pero no se ejecutó toda con servicios reales en esta continuación.

Evidencia complementaria conservada: `reportes/personajes_wikipedia_antes_20261021.json`, `reportes/anillos_alcance_verificado_20261021.json`, `reportes/consulta_espacial_openlibrary_21_octubre.json`, `reportes/ediciones_openlibrary_20261021.json` y `reportes/fuentes_publicas_20261020.json`. Este último incluye una extracción real permitida de Tuttle con Trafilatura; no se atribuye a una respuesta que no la haya usado. Los fallos y los ensayos de modelos descartados no se borraron.

## Costo obligatorio de API

Los cambios no requieren una tarjeta, cuenta de pago ni cobro por solicitud. La generación y los embeddings son locales; SearXNG se autohospeda; las fuentes implementadas no incorporan una API comercial obligatoria. No hay fallback automático a Groq, Gemini, Brave o Tavily ni dependencia vectorial de Pinecone. El costo obligatorio de API de este asistente sigue siendo **$0**. Electricidad, equipo, disco e Internet son recursos necesarios.

La base TiDB existente y un Redis remoto que el usuario configure son servicios ajenos a esta garantía: no se inspeccionó ni modificó su facturación. Google Books no se activa por tener una clave antigua. No se pueden garantizar disponibilidad perpetua, cobertura completa ni ausencia de límites de las fuentes gratuitas.

## Qué sigue pendiente

| Requisito de la mejora profunda | Estado comprobado |
|---|---|
| Evaluar tecnologías y modelos | Se evaluaron tres modelos locales, RAG, LangGraph, LlamaIndex y herramientas de Ollama. No se demostró que una reescritura mejorara el sistema. No se implementaron `tool_calls` nativos: el servidor controla las herramientas. |
| Integrar múltiples fuentes | Open Library, Wikipedia, Wikidata y SearXNG están integrados. Google Books sigue opcional y no se usó en los ensayos citados. Tiendas y Fandom tienen alcance de descubrimiento de enlaces; no equivalen a APIs de lectura. |
| Búsqueda y extracción pública | Implementadas con SearXNG y Trafilatura, condicionadas a permisos, robots, seguridad y disponibilidad. No dan acceso indiscriminado a Internet. |
| Investigar automáticamente | Implementado con evaluación de suficiencia, identidad de obra y presupuestos de investigación. No garantiza resolver cualquier pregunta. |
| Contexto y razonamiento | Mejoras comprobadas en casos concretos; falta demostrar fiabilidad en una muestra amplia de conversaciones complejas. |
| Precisión y rendimiento | Optimización y medición en curso. No está demostrado error menor al 1 % ni respuesta rápida general. |
| Implementación y diseño | Cambios reales y pruebas aisladas; se conservan diseño, tarjetas, personalidad, voz y avatares. |

La latencia de preguntas que requieren varias inferencias sigue siendo alta en esta GPU. Las respuestas bibliográficas de respaldo son menos detalladas que una sinopsis bien fundamentada. La lista rápida de personajes es parcial, no un reparto exhaustivo. El catálogo puede no tener traducciones, portadas o información suficiente de una obra. Los modelos y sus auditores pueden equivocarse aun con JSON válido; los controles añadidos son barreras concretas, no una demostración matemática de verdad.

No se ha demostrado una tasa de errores del 1 % o menos. La evaluación actual es una batería de regresiones seleccionadas. Queda ampliar un conjunto independiente y revisado, medir rechazo incorrecto además de alucinaciones y comparar modelos con código y fuentes congelados. No se publicó texto sin validar para simular rapidez: el SSE sigue entregando la respuesta después de las comprobaciones.

## Ejecutar el proyecto y repetir las comprobaciones

Mantener abiertos Ollama y Docker Desktop. No hacen falta migraciones para estas mejoras.

```powershell
Set-Location -LiteralPath 'G:\Proyecto\Litmate'
.\venv\Scripts\python.exe iniciar_buscador.py
$env:LITMATE_AI_USE_SEARXNG='True'
$env:LITMATE_USE_GOOGLE_BOOKS_API='False'
.\venv\Scripts\python.exe manage.py diagnosticar_ia
.\venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

```powershell
.\venv\Scripts\python.exe -B verificar_proyecto.py core suscripciones
.\venv\Scripts\python.exe -B verificar_investigacion.py --live --web --public-catalog --trace --message 'Dime los personajes del señor de los anillos' --message 'Busca los personajes del señor de los anillos' --output reportes/mi_prueba_anillos.json
.\venv\Scripts\python.exe -B verificar_investigacion.py --live --web --public-catalog --trace --message 'Dime los personajes de Papelucho y el marciano' --message '¿Y qué sucede con Det?' --message 'Si busco recomendaciones de otros libros con tematica espacial' --output reportes/mi_prueba_contexto.json
```

El ejecutor no carga `.env` ni la base principal; elige explícitamente el modelo indicado o el 9B predeterminado. `--public-catalog` consulta APIs reales y sustituye únicamente la consulta SQL por una lista vacía. El presupuesto de investigación se comparte entre la ruta de personajes y el modelo, como en el endpoint real. Los informes `--trace` son locales y las consultas de ejemplo no contienen datos personales. No usar `manage.py test` con el entorno habitual de producción.
