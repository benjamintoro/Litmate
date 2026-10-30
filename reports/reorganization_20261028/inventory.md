# Inventario previo al primer lote

Inventario estático completo: `inventory_before_assets.json` (generado localmente). No importa Django ni lee secretos o datos de usuarios.

## Conteos

- files: 354.
- python_modules: 261.
- imports: 2703.
- dynamic_imports: 4.
- file_anchors: 31.
- Módulos de IA candidatos: 46.
- Archivos de pruebas en core: 121.
- Archivos de migraciones registrados: 10.

## Acoplamientos de mayor alcance

| Módulo | Archivos que lo importan |
| --- | ---: |
| `core.literary_ai` | 88 |
| `core.literary_identity` | 51 |
| `core.literary_quality` | 36 |
| `core.literary_search` | 35 |
| `core.ai_budget` | 33 |
| `core.local_llm` | 27 |
| `core.literary_sources` | 25 |
| `core.literary_memory` | 25 |
| `core.literary_research` | 25 |
| `core.books_google` | 23 |
| `core.literary_web` | 23 |
| `core.literary_ai_views` | 20 |
| `core.models` | 20 |
| `core.literary_evidence` | 20 |
| `core.ai_quick_answers` | 19 |
| `core.ai_narrative_answers` | 18 |
| `core.local_rag` | 18 |
| `core.ai_character_answers` | 18 |

## Imports dinámicos encontrados

- `core/test_ai_voice.py:48`: `importlib.reload` → `<dynamic>`.
- `core/test_free_topic_recommendations.py:101`: `__import__` → `core.literary_search`.
- `core/test_protagonist_from_description.py:14`: `__import__` → `core.test_character_context_resolution`.
- `core/test_protagonist_from_description.py:14`: `__import__` → `core.test_character_context_resolution`.

## Origen, destino y riesgo

Los destinos de IA y pruebas son propuestas para lotes futuros; no se crearon ni movieron esos paquetes.

| Origen | Destino propuesto | Riesgo / decisión |
| --- | --- | --- |
| `ARQUITECTURA_IA_RENDIMIENTO.md` | `docs/architecture/ARQUITECTURA_IA_RENDIMIENTO.md` | lote 1; alias para guías principales y scripts; referencias verificadas |
| `INFORME_ARQUITECTURA_IA_21_OCTUBRE.md` | `reports/archive/INFORME_ARQUITECTURA_IA_21_OCTUBRE.md` | lote 1; alias para guías principales y scripts; referencias verificadas |
| `INFORME_BUSQUEDA_LITERARIA.md` | `reports/archive/INFORME_BUSQUEDA_LITERARIA.md` | lote 1; alias para guías principales y scripts; referencias verificadas |
| `INFORME_CONTINUACION_20_OCTUBRE.md` | `reports/archive/INFORME_CONTINUACION_20_OCTUBRE.md` | lote 1; alias para guías principales y scripts; referencias verificadas |
| `INFORME_FUENTES_MODELOS.md` | `reports/archive/INFORME_FUENTES_MODELOS.md` | lote 1; alias para guías principales y scripts; referencias verificadas |
| `INFORME_RESULTADOS_21_OCTUBRE.md` | `reports/archive/INFORME_RESULTADOS_21_OCTUBRE.md` | lote 1; alias para guías principales y scripts; referencias verificadas |
| `INFORME_SINOPSIS_DOCKER_20261026.md` | `reports/archive/INFORME_SINOPSIS_DOCKER_20261026.md` | lote 1; alias para guías principales y scripts; referencias verificadas |
| `LEEME.md` | `docs/archive/LEEME_IA_V3.md` | lote 1; alias para guías principales y scripts; referencias verificadas |
| `LitMate_IA_Gratis_Codigo_Completo.md` | `docs/archive/LitMate_IA_Gratis_Codigo_Completo.md` | lote 1; alias para guías principales y scripts; referencias verificadas |
| `MYSQL_LOCAL.md` | `docs/guides/MYSQL_LOCAL.md` | lote 1; alias para guías principales y scripts; referencias verificadas |
| `README_ASISTENTE_IA.md` | `docs/guides/README_ASISTENTE_IA.md` | lote 1; alias para guías principales y scripts; referencias verificadas |
| `activar_ollama_local.py` | `activar_ollama_local.py` | conservar en esta fase; integración Django, datos de prueba o ruta pública |
| `analizar_evaluacion_ia.py` | `scripts/analysis/analizar_evaluacion_ia.py` | lote 1; alias para guías principales y scripts; referencias verificadas |
| `auditar_conversaciones.py` | `auditar_conversaciones.py` | conservar en esta fase; integración Django, datos de prueba o ruta pública |
| `diagnosticar_buscador.py` | `diagnosticar_buscador.py` | conservar en esta fase; integración Django, datos de prueba o ruta pública |
| `diagnosticar_sinopsis.py` | `diagnosticar_sinopsis.py` | conservar en esta fase; integración Django, datos de prueba o ruta pública |
| `evaluar_cache_rag.py` | `evaluar_cache_rag.py` | conservar en esta fase; integración Django, datos de prueba o ruta pública |
| `evaluar_chat_http.py` | `evaluar_chat_http.py` | conservar en esta fase; integración Django, datos de prueba o ruta pública |
| `evaluar_inferencia_local.py` | `evaluar_inferencia_local.py` | conservar en esta fase; integración Django, datos de prueba o ruta pública |
| `evaluar_litmate.py` | `evaluar_litmate.py` | conservar en esta fase; integración Django, datos de prueba o ruta pública |
| `evaluar_rag_local.py` | `evaluar_rag_local.py` | conservar en esta fase; integración Django, datos de prueba o ruta pública |
| `fast_seed_interactions.py` | `fast_seed_interactions.py` | conservar en esta fase; integración Django, datos de prueba o ruta pública |
| `iniciar_buscador.py` | `iniciar_buscador.py` | conservar en esta fase; integración Django, datos de prueba o ruta pública |
| `iniciar_mysql_local.py` | `iniciar_mysql_local.py` | conservar en esta fase; integración Django, datos de prueba o ruta pública |
| `manage.py` | `manage.py` | conservar en esta fase; integración Django, datos de prueba o ruta pública |
| `poblar_gran_catalogo.py` | `poblar_gran_catalogo.py` | conservar en esta fase; integración Django, datos de prueba o ruta pública |
| `preparar_modelo_texto.py` | `preparar_modelo_texto.py` | conservar en esta fase; integración Django, datos de prueba o ruta pública |
| `preparar_mysql.py` | `preparar_mysql.py` | conservar en esta fase; integración Django, datos de prueba o ruta pública |
| `resumir_benchmark_ia.py` | `scripts/analysis/resumir_benchmark_ia.py` | lote 1; alias para guías principales y scripts; referencias verificadas |
| `seed_cloud_database.py` | `seed_cloud_database.py` | conservar en esta fase; integración Django, datos de prueba o ruta pública |
| `settings_ia_block.py` | `settings_ia_block.py` | conservar en esta fase; integración Django, datos de prueba o ruta pública |
| `urls.py` | `urls.py` | conservar en esta fase; integración Django, datos de prueba o ruta pública |
| `verificar_asistente.py` | `verificar_asistente.py` | conservar en esta fase; integración Django, datos de prueba o ruta pública |
| `verificar_investigacion.py` | `verificar_investigacion.py` | conservar en esta fase; integración Django, datos de prueba o ruta pública |
| `verificar_proyecto.py` | `verificar_proyecto.py` | conservar en esta fase; integración Django, datos de prueba o ruta pública |
| `core/ai_answer_cache.py` | `literary_ai/answers/ai_answer_cache.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/ai_budget.py` | `literary_ai/runtime/ai_budget.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/ai_catalog_fallback.py` | `literary_ai/runtime/ai_catalog_fallback.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/ai_character_answers.py` | `literary_ai/identity_context/ai_character_answers.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/ai_concurrency.py` | `literary_ai/runtime/ai_concurrency.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/ai_http.py` | `literary_ai/runtime/ai_http.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/ai_identification_details.py` | `literary_ai/runtime/ai_identification_details.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/ai_library_router.py` | `literary_ai/knowledge/ai_library_router.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/ai_literal_followup.py` | `literary_ai/runtime/ai_literal_followup.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/ai_narrative_answers.py` | `literary_ai/answers/ai_narrative_answers.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/ai_persistent_router.py` | `literary_ai/runtime/ai_persistent_router.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/ai_presentation.py` | `literary_ai/answers/ai_presentation.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/ai_privacy.py` | `literary_ai/runtime/ai_privacy.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/ai_progress.py` | `literary_ai/runtime/ai_progress.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/ai_public_details.py` | `literary_ai/runtime/ai_public_details.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/ai_quick_answers.py` | `literary_ai/answers/ai_quick_answers.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/ai_recommendation_candidates.py` | `literary_ai/answers/ai_recommendation_candidates.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/ai_recommendation_provenance.py` | `literary_ai/answers/ai_recommendation_provenance.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/ai_related_recommendations.py` | `literary_ai/answers/ai_related_recommendations.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/ai_stream_jobs.py` | `literary_ai/runtime/ai_stream_jobs.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/books_google.py` | `literary_ai/retrieval/books_google.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/literary_acquisition.py` | `literary_ai/knowledge/literary_acquisition.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/literary_ai.py` | `literary_ai/runtime/literary_ai.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/literary_constraints.py` | `literary_ai/verification/literary_constraints.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/literary_conversation.py` | `literary_ai/identity_context/literary_conversation.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/literary_evidence.py` | `literary_ai/verification/literary_evidence.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/literary_focus.py` | `literary_ai/identity_context/literary_focus.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/literary_gutenberg.py` | `literary_ai/knowledge/literary_gutenberg.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/literary_identity.py` | `literary_ai/identity_context/literary_identity.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/literary_knowledge.py` | `literary_ai/knowledge/literary_knowledge.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/literary_language.py` | `literary_ai/answers/literary_language.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/literary_learning.py` | `literary_ai/knowledge/literary_learning.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/literary_library.py` | `literary_ai/knowledge/literary_library.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/literary_memory.py` | `literary_ai/knowledge/literary_memory.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/literary_memory_rag.py` | `literary_ai/retrieval/literary_memory_rag.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/literary_presentation_language.py` | `literary_ai/answers/literary_presentation_language.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/literary_quality.py` | `literary_ai/verification/literary_quality.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/literary_ranking.py` | `literary_ai/runtime/literary_ranking.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/literary_research.py` | `literary_ai/retrieval/literary_research.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/literary_search.py` | `literary_ai/retrieval/literary_search.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/literary_sources.py` | `literary_ai/runtime/literary_sources.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/literary_web.py` | `literary_ai/runtime/literary_web.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/literary_wikidata.py` | `literary_ai/runtime/literary_wikidata.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/local_embeddings.py` | `literary_ai/retrieval/local_embeddings.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/local_llm.py` | `literary_ai/runtime/local_llm.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/local_rag.py` | `literary_ai/retrieval/local_rag.py` | lote futuro: imports relativos, archivos de datos y patches; requiere compatibilidad |
| `core/test_acquisition_reporting.py` | `tests/knowledge/test_acquisition_reporting.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_ai_answer_cache.py` | `tests/answers/test_ai_answer_cache.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_ai_conversation.py` | `tests/identity_context/test_ai_conversation.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_ai_diagnostics_free.py` | `tests/runtime/test_ai_diagnostics_free.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_ai_http.py` | `tests/runtime/test_ai_http.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_ai_identification_details.py` | `tests/runtime/test_ai_identification_details.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_ai_library_router.py` | `tests/knowledge/test_ai_library_router.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_ai_presentation.py` | `tests/answers/test_ai_presentation.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_ai_progress_stream.py` | `tests/runtime/test_ai_progress_stream.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_ai_public_details.py` | `tests/runtime/test_ai_public_details.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_ai_quality.py` | `tests/verification/test_ai_quality.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_ai_runtime.py` | `tests/runtime/test_ai_runtime.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_ai_voice.py` | `tests/runtime/test_ai_voice.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_benchmark_public_memory.py` | `tests/knowledge/test_benchmark_public_memory.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_benchmark_summary.py` | `tests/runtime/test_benchmark_summary.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_catalogue_narrative_proof.py` | `tests/answers/test_catalogue_narrative_proof.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_catalogue_scope_and_entry.py` | `tests/runtime/test_catalogue_scope_and_entry.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_character_alias_generalization.py` | `tests/identity_context/test_character_alias_generalization.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_character_alias_holdout.py` | `tests/identity_context/test_character_alias_holdout.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_character_context_resolution.py` | `tests/identity_context/test_character_context_resolution.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_character_depth.py` | `tests/identity_context/test_character_depth.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_character_extraction.py` | `tests/identity_context/test_character_extraction.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_character_false_premise.py` | `tests/identity_context/test_character_false_premise.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_character_memory.py` | `tests/identity_context/test_character_memory.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_character_quality_regression.py` | `tests/identity_context/test_character_quality_regression.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_chat_deadline.py` | `tests/runtime/test_chat_deadline.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_compact_audit_context.py` | `tests/verification/test_compact_audit_context.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_compact_audit_transport.py` | `tests/verification/test_compact_audit_transport.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_compact_book_transport.py` | `tests/runtime/test_compact_book_transport.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_context_reference_scope.py` | `tests/identity_context/test_context_reference_scope.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_conversation_audit.py` | `tests/identity_context/test_conversation_audit.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_database_transfer.py` | `tests/runtime/test_database_transfer.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_discovery_card_synopsis.py` | `tests/runtime/test_discovery_card_synopsis.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_editorial_contents.py` | `tests/runtime/test_editorial_contents.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_external_summary_transport.py` | `tests/runtime/test_external_summary_transport.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_fact_audit_contract.py` | `tests/verification/test_fact_audit_contract.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_factual_repair_context.py` | `tests/runtime/test_factual_repair_context.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_free_topic_recommendations.py` | `tests/answers/test_free_topic_recommendations.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_goal_evidence.py` | `tests/verification/test_goal_evidence.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_google_books.py` | `tests/retrieval/test_google_books.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_grounded_topic_fallback.py` | `tests/runtime/test_grounded_topic_fallback.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_http_work_focus.py` | `tests/identity_context/test_http_work_focus.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_hybrid_ai.py` | `tests/runtime/test_hybrid_ai.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_identity_recommendation_references.py` | `tests/identity_context/test_identity_recommendation_references.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_identity_stabilization.py` | `tests/identity_context/test_identity_stabilization.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_library_vector_cache.py` | `tests/knowledge/test_library_vector_cache.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_literal_followup.py` | `tests/runtime/test_literal_followup.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_literal_followup_integration.py` | `tests/runtime/test_literal_followup_integration.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_literary_acquisition.py` | `tests/knowledge/test_literary_acquisition.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_literary_ai.py` | `tests/runtime/test_literary_ai.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_literary_constraints.py` | `tests/verification/test_literary_constraints.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_literary_conversation.py` | `tests/identity_context/test_literary_conversation.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_literary_evaluation_tools.py` | `tests/runtime/test_literary_evaluation_tools.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_literary_gutenberg.py` | `tests/knowledge/test_literary_gutenberg.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_literary_identity.py` | `tests/identity_context/test_literary_identity.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_literary_knowledge.py` | `tests/knowledge/test_literary_knowledge.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_literary_learning.py` | `tests/knowledge/test_literary_learning.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_literary_library.py` | `tests/knowledge/test_literary_library.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_literary_memory.py` | `tests/knowledge/test_literary_memory.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_literary_ranking.py` | `tests/runtime/test_literary_ranking.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_literary_research.py` | `tests/retrieval/test_literary_research.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_literary_web.py` | `tests/runtime/test_literary_web.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_local_ai.py` | `tests/runtime/test_local_ai.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_local_audit_slots.py` | `tests/verification/test_local_audit_slots.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_local_control_schema.py` | `tests/runtime/test_local_control_schema.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_local_excerpt_basis.py` | `tests/runtime/test_local_excerpt_basis.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_local_output_budget.py` | `tests/runtime/test_local_output_budget.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_local_prewarm.py` | `tests/runtime/test_local_prewarm.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_local_recommendation_minimum.py` | `tests/answers/test_local_recommendation_minimum.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_local_stage_metrics.py` | `tests/runtime/test_local_stage_metrics.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_memory_trace.py` | `tests/knowledge/test_memory_trace.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_mysql_activation.py` | `tests/runtime/test_mysql_activation.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_narrative_answers.py` | `tests/answers/test_narrative_answers.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_narrative_failure_context.py` | `tests/answers/test_narrative_failure_context.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_narrative_review.py` | `tests/answers/test_narrative_review.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_narrative_synopsis.py` | `tests/answers/test_narrative_synopsis.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_openlibrary_editions.py` | `tests/retrieval/test_openlibrary_editions.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_persistent_depth_bridge.py` | `tests/runtime/test_persistent_depth_bridge.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_persistent_router.py` | `tests/runtime/test_persistent_router.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_prepare_text_model.py` | `tests/runtime/test_prepare_text_model.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_presentation_language.py` | `tests/answers/test_presentation_language.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_presentation_language_live.py` | `tests/answers/test_presentation_language_live.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_profile_depth.py` | `tests/runtime/test_profile_depth.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_progressive_free_sources.py` | `tests/runtime/test_progressive_free_sources.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_protagonist_from_description.py` | `tests/runtime/test_protagonist_from_description.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_published_title_alias.py` | `tests/identity_context/test_published_title_alias.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_quality_work_binding.py` | `tests/verification/test_quality_work_binding.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_question_specific_citations.py` | `tests/runtime/test_question_specific_citations.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_quotas.py` | `tests/runtime/test_quotas.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_recommendation_candidates.py` | `tests/answers/test_recommendation_candidates.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_recommendation_cards_regression.py` | `tests/answers/test_recommendation_cards_regression.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_recommendation_count.py` | `tests/answers/test_recommendation_count.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_recommendation_grounding.py` | `tests/answers/test_recommendation_grounding.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_recommendation_provenance.py` | `tests/answers/test_recommendation_provenance.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_recommendation_provenance_integration.py` | `tests/answers/test_recommendation_provenance_integration.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_recommendation_relations.py` | `tests/answers/test_recommendation_relations.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_recommendation_web_evidence.py` | `tests/verification/test_recommendation_web_evidence.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_related_recommendation_cards.py` | `tests/answers/test_related_recommendation_cards.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_research_integration.py` | `tests/retrieval/test_research_integration.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_research_limits.py` | `tests/retrieval/test_research_limits.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_research_runtime.py` | `tests/retrieval/test_research_runtime.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_response_prose.py` | `tests/answers/test_response_prose.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_retrieval_cache.py` | `tests/retrieval/test_retrieval_cache.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_retry_followup.py` | `tests/runtime/test_retry_followup.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_scoped_narrative_evidence.py` | `tests/verification/test_scoped_narrative_evidence.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_searx_diagnostics.py` | `tests/runtime/test_searx_diagnostics.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_security_hardening.py` | `tests/runtime/test_security_hardening.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_simple_factual_context.py` | `tests/runtime/test_simple_factual_context.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_source_snapshot_merge.py` | `tests/runtime/test_source_snapshot_merge.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_space_topic_recommendations.py` | `tests/answers/test_space_topic_recommendations.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_strict_research_quality.py` | `tests/retrieval/test_strict_research_quality.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_subject_attribution_audit.py` | `tests/verification/test_subject_attribution_audit.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_synopsis_pipeline.py` | `tests/runtime/test_synopsis_pipeline.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_topic_discovery.py` | `tests/runtime/test_topic_discovery.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_topic_intent.py` | `tests/runtime/test_topic_intent.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_topic_language_memory.py` | `tests/knowledge/test_topic_language_memory.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_topic_reference.py` | `tests/identity_context/test_topic_reference.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_topic_return_memory.py` | `tests/knowledge/test_topic_return_memory.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_topic_task_boundaries.py` | `tests/runtime/test_topic_task_boundaries.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_web_search.py` | `tests/retrieval/test_web_search.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
| `core/test_wikipedia_character_tables.py` | `tests/identity_context/test_wikipedia_character_tables.py` | lote futuro: imports cruzados, patch strings y descubrimiento Django |
