# Recuperación y respuestas narrativas — 29/10/2026

Trabajo realizado en dos lotes sobre el estado real del proyecto. Se conservaron
todos los cambios anteriores y no se reconstruyeron MySQL, memoria o RAG.

- [Lote 1: SearXNG y recuperación](LOTE_1.md).
- [Lote 2: evidencia, narración y presentación](LOTE_2.md).
- [Configuración y mantenimiento del buscador](../../searxng/README.md).

Resultado de cierre: **371 pruebas dirigidas aprobadas en 6,796 s**, seis
regresiones offline del motor en el contenedor y **240 comprobaciones JavaScript**.
Las cuatro consultas HTTP/SSE reales obtuvieron respuestas revisadas contra su
evidencia: 2,8960 / 2,9631 / 0,1454 / 1,9333 s, sin llamadas al LLM en ese cierre.
No son una medición general de precisión ni de p95 de todo el asistente.

Los artefactos JSON/TXT/LOG completos son locales e ignorados por Git. Se
preservan intentos fallidos: no deben confundirse con el cierre verificado.
La suite completa del proyecto no se ejecutó en esta tarea.

Arranque de Django conservado:

```powershell
.\venv\Scripts\python.exe -B iniciar_mysql_local.py --http-desarrollo
```

Reproducción de las consultas reales, con contraseña oculta y salida nueva:

```powershell
.\venv\Scripts\python.exe -B -m scripts.knowledge.search_narrative_check --output reports/search_narrative_20261029/nueva_conversacion.json
.\venv\Scripts\python.exe -B -m scripts.knowledge.search_narrative_check --local-only --output reports/search_narrative_20261029/nueva_prueba_local.json
```

Estas pruebas leen MySQL real, utilizan HTTP/SSE, CSRF, una copia consistente
temporal de la memoria y cachés SQLite temporales. No crean lectores ni historial
de producción. Sus envoltorios de diagnóstico ejecutan las funciones originales:
no reemplazan respuestas de buscadores ni del modelo con datos preparados.

Regresiones sintéticas dirigidas:

```powershell
$env:DB_ENGINE='sqlite'
.\venv\Scripts\python.exe -B manage.py test core.test_search_narrative_repair core.test_narrative_answers core.test_response_prose core.test_narrative_synopsis core.test_narrative_failure_context core.test_web_search core.test_searx_diagnostics --noinput
node verificar_chat_seguro.js
```

No se modificaron `.env`, pesos de Qwen, credenciales, migraciones o el arranque.
No se importaron libros, instalaron dependencias ni contrataron APIs. No se
realizaron commits, push, eliminación de volúmenes o operaciones destructivas.
