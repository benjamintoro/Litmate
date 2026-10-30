# Continuación de LitMate — 20 de octubre de 2026

Actualización posterior: [correcciones, modelos, límites y resultados del 21 de octubre](INFORME_RESULTADOS_21_OCTUBRE.md). Este documento conserva el diagnóstico y las mediciones del trabajo anterior.

Trabajo sobre `G:\Proyecto\Litmate`, conservando los cambios existentes del 19 de octubre. No se han hecho commits, migraciones ni pruebas contra la base de producción. La interfaz, tarjetas, organización de mensajes, voz y avatares permanecen sin cambios.

## Problemas reproducidos y correcciones

1. **Recomendaciones clasificadas como recuerdos de una novela.** «Busco un libro sobre arte japonés» se confundía con identificar una historia olvidada. Se comparte un detector de intención temática entre clasificación, memoria y requisitos de evidencia. «Sobre un tema» se distingue de «donde sucede una escena»; el veto de seguridad no se convierte en autorización mediante este detector.
2. **Tema perdido tras un fallo o una continuación.** La petición del lector se conserva aparte de las respuestas aceptadas. «Cualquiera» mantiene arte japonés; un cambio explícito reemplaza el tema. Hasta cuatro temas saneados pueden retomarse durante una hora; una referencia ambigua pide aclaración. No se convierten respuestas rechazadas en hechos.
3. **Consultas de catálogo demasiado literales y novelas de otro tema.** Open Library recibe materias bibliográficas y filtros de autor/idioma; cada materia y lugar pedidos requieren respaldo en los metadatos recuperados. Se conservan los filtros anteriores de ficción. Las conjeturas de títulos/autores del clasificador no bastan para recomendar una obra.
4. **Texto, cantidad y tarjetas incoherentes.** Se acotan las fichas antes de redactar; se comprueban títulos y autores enumerados, cantidad, identidad, duplicados y presencia de los títulos en la respuesta. Las nuevas opciones excluyen obras previas y las referencias «del mismo autor», «otro parecido» y «al segundo» usan identidades del historial aceptado.
5. **Materias y fragmentos de buscador tratados como sinopsis.** Un fragmento de resultados sirve para localizar una página. El enriquecimiento requiere una página o API realmente consultada y una identidad de obra compatible; no usa snippets, instrucciones externas, menciones incidentales ni otro volumen de una saga como descripción del libro.
6. **Auditorías incompletas o formalmente válidas pero sin respaldo.** Cada frase factual estricta tiene un campo obligatorio de comprobación. El transporte no permite repetir una frase para omitir otra. Se preservan iniciales y abreviaturas al segmentar, y se rechazan pruebas de otra obra, títulos usados como prueba de argumento y detalles de estilo/época ausentes de un catálogo. El esquema local comparte esas restricciones con el validador, sin relajarlo.
7. **Un fallo al redactar inutilizaba fichas correctas.** Si se agota la reparación de una recomendación temática, un respaldo bibliográfico construye una respuesta nueva limitada al alcance documentado. Aplica los cuatro validadores existentes, conserva el rechazo previo y no inventa una sinopsis. No sustituye preguntas sobre personajes, recuerdos, citas o filtros que no puede verificar.
8. **Diagnósticos que no distinguían intento y éxito de búsqueda.** Ahora se separan solicitudes reales, resultados de caché, lecturas reservadas y páginas extraídas. No se registra el texto privado del lector en estas trazas. `web_searches=0` por sí solo no significa que el enriquecimiento no haya consultado fuentes: la traza compartida incluye esas operaciones.

## Archivos principales

| Área | Archivos |
| --- | --- |
| Flujo y recomendaciones | `core/literary_ai.py`, `core/ai_catalog_fallback.py`, `core/literary_ai_views.py`, `core/literary_constraints.py` |
| Contexto e identidad | `core/literary_conversation.py`, `core/literary_identity.py` |
| Recuperación y procedencia | `core/literary_search.py`, `core/books_google.py`, `core/literary_research.py`, `core/literary_sources.py`, `core/literary_web.py`, `core/literary_wikidata.py` |
| Validación y modelo | `core/literary_quality.py`, `core/literary_evidence.py`, `core/local_llm.py` |
| RAG y conocimiento autorizado | `core/local_rag.py`, `core/literary_knowledge.py`, `core/management/commands/preparar_conocimiento.py`, `core/management/commands/indexar_libros.py` |
| Configuración local | `litmate_project/ai_settings.py`, `.env.example`, `docker-compose.ia.yml`, `searxng/settings.yml`, `iniciar_buscador.py` |
| Reproducción y medición | `verificar_proyecto.py`, `verificar_investigacion.py`, `evaluar_litmate.py`, `evaluar_rag_local.py`, `datos_evaluacion_ia.json` |

Las pruebas nuevas se encuentran en `core/test_*`: contexto, retorno de temas, identidad, recomendaciones, restricciones, auditoría, seguridad de fuentes y herramientas de evaluación. `git status --short` muestra el conjunto completo, incluidos los cambios conservados del trabajo anterior.

## Fuentes y costo obligatorio

El detalle de servicios y pruebas HTTP está en [INFORME_FUENTES_MODELOS.md](INFORME_FUENTES_MODELOS.md). Se reutilizan Open Library, Wikipedia/Wikidata, SearXNG autohospedado y lectores de fuentes autorizadas. Google Books permanece opcional y requiere configuración expresamente confirmada sin facturación; una clave antigua no lo activa automáticamente.

Amazon, Buscalibre, Casa del Libro, Goodreads, Barnes & Noble, Gandhi y WorldCat pueden aportar enlaces descubiertos por SearXNG. Eso **no autoriza** extraer sus páginas, ni prueba que el buscador encuentre resultados para cada consulta. WorldCat no se integra mediante una API que exige suscripción institucional. La API oficial de Library of Congress respondió 403 en tres consultas reales: no se eludió. No se inventó una API de la Biblioteca Nacional de Chile.

La generación, embeddings y búsquedas implementadas no requieren una API de pago. No hay sustitución automática por Groq, Pinecone, Gemini, Brave o Tavily. Se mantienen los límites de dos búsquedas lógicas, tres lecturas y un presupuesto compartido de investigación externa; los servicios pueden fallar o limitarse. El equipo, electricidad, conexión y almacenamiento son recursos necesarios. La facturación de la cuenta TiDB existente, o de un Redis remoto configurado por el usuario, no se puede certificar desde el código y queda fuera de esta garantía de costo de API del asistente.

## Medición real y límites

Los archivos de `reportes/` conservan también los fallos. Una respuesta marcada `answered` por el sistema no equivale a una respuesta factualmente correcta. La matriz y el ejecutor separan publicación, indisponibilidad y revisión factual; no cuentan los fallos simulados como búsquedas reales exitosas.

**RAG real:** `reportes/rag_hibrido_20_oct.json` compara ocho consultas positivas y un control negativo contra las cuatro fichas originales autorizadas del índice auxiliar. BM25 obtuvo 7/8 primeros resultados correctos; la recuperación híbrida con `embeddinggemma` obtuvo 8/8. Ningún método devolvió candidatos en el control negativo. El hash del índice no cambió. Esto mide recuperación en esa colección pequeña, no exactitud general del chatbot; no justifica agregar un reranker adicional ni más modelos de embeddings.

**Fuentes HTTP reales:** `reportes/fuentes_publicas_20261020.json` registra Open Library, Wikipedia bilingüe, SearXNG y una extracción permitida de Tuttle mediante Trafilatura. Una extracción probada por separado no se atribuye a una respuesta del chat que no la utilizó.

**Reproducciones anteriores conservadas:** `reproduccion_temas_usuario.json`, `recomendaciones_temas_corregidas.json`, `temas_con_auditoria_factual.json`, `validacion_temas_final.json`, `validacion_temas_20_oct_9b.json` y `validacion_temas_20_oct_4b.json`. Exponen fallos de redacción, cobertura, sinopsis o validación; no deben presentarse como una batería plenamente aprobada.

La comparación de modelos y las verificaciones posteriores se registran en [los resultados del 21 de octubre](INFORME_RESULTADOS_21_OCTUBRE.md). No se ha demostrado una tasa de errores del 1 % o menos. Una batería pequeña seleccionada para regresiones no permite certificar ese objetivo.

## Ejecución y pruebas seguras

```powershell
Set-Location -LiteralPath 'G:\Proyecto\Litmate'
.\venv\Scripts\python.exe iniciar_buscador.py
$env:LITMATE_AI_USE_SEARXNG='True'
$env:LITMATE_USE_GOOGLE_BOOKS_API='False'
.\venv\Scripts\python.exe manage.py diagnosticar_ia
.\venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Mantener abiertos Ollama y Docker Desktop. No ejecutar migraciones para estas mejoras. La preparación de las fichas autorizadas se describe en `docs/guides/README_ASISTENTE_IA.md`; no añade novelas completas sin permiso.

```powershell
.\venv\Scripts\python.exe -B verificar_proyecto.py core suscripciones
.\venv\Scripts\python.exe -B verificar_investigacion.py --live --web --public-catalog --trace --message 'recomiendame libros sobre la historia de corea' --message 'estoy buscando un libro sobre arte japones' --message 'obras de distintos artistas recomiendame cualquiera' --output reportes/mi_prueba.json
.\venv\Scripts\python.exe -B evaluar_rag_local.py --output reportes/mi_rag.json
.\venv\Scripts\python.exe -B evaluar_litmate.py --dry-run
```

Usar el verificador aislado, **no** `manage.py test` con el entorno habitual de producción. El ejecutor de casos conserva conversaciones, resultados y logs; permite seleccionar casos con `--case` y comparar resúmenes con `--before`. Las respuestas generadas necesitan revisión contra sus fuentes antes de registrar exactitud factual.
