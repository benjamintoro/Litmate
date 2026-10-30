# LitMate: asistente local para tu PC — versión 3

> La guía vigente de este proyecto es [README_ASISTENTE_IA.md](../guides/README_ASISTENTE_IA.md).
> Esta versión 3 se conserva como referencia histórica: ahora Google Books API
> se activa con tu clave, la configuración es centralizada y no se deben pegar
> nuevamente sus bloques de código sobre el proyecto.

El código completo está en este paquete. Copia los archivos manteniendo sus rutas dentro de tu proyecto, donde está `manage.py`. Para copiar y pegar por archivo, usa `docs/archive/LitMate_IA_Gratis_Codigo_Completo.md`.

## Qué incorpora

- Ollama local con `qwen3.5:9b-q4_K_M`: sin clave ni créditos de una API de IA.
- Clasificación del ámbito, planificación de la pregunta y auditoría antes de publicar. Admite recomendaciones de libros de cualquier tema; rechaza recetas, código y tareas prácticas, aunque mencionen un libro.
- RAG híbrido: recupera fragmentos de tus PDF/TXT/MD por palabras y por significado, con `embeddinggemma` local. Filtra por título y autor.
- Catálogo de LitMate, Open Library y búsqueda de Google/DuckDuckGo mediante SearXNG local. Wikipedia queda como respaldo. Puede hacer una búsqueda dirigida adicional si falta un dato.
- Seguimiento de la obra elegida, revisión de preguntas múltiples, fuentes identificadas y comprobación literal de citas. No presenta una ficha como si fuera el libro completo.
- Límites de solicitudes, una inferencia a la vez, tiempos acotados, validación de JSON y corrección del formateador de los dos chats. Los errores de ocupación o espera se muestran sin confundirlos con límites de un plan de pago.
- 175 pruebas del backend y 20 casos para evaluar tu modelo real, con respuestas guardadas para revisión humana.

No existe garantía de cero errores ni de una nota 7. La auditoría usa un modelo y puede equivocarse. El sistema distingue respuestas conocidas, evidencia recuperada y datos que no pudo confirmar. No cobra créditos de IA; sí utiliza tu computador, electricidad e Internet.

## 1. Copiar los archivos

Haz una copia de tu proyecto o trabaja en una rama propia. Este paquete se preparó sobre el ZIP de LitMate aportado al chat; no contiene una nueva consulta a la rama privada de GitHub. Revisa diferencias si después cambiaste tu proyecto.

Copia los archivos del paquete sobre los correspondientes del proyecto. Combina las carpetas: conserva los demás archivos de `core`, `static` y `litmate_project`.

| Archivo o carpeta | Qué hacer |
| --- | --- |
| `core/literary_ai.py`, `literary_quality.py`, `literary_evidence.py` | Copiar: motor, plan, auditoría y comprobaciones de evidencia. |
| `core/local_llm.py`, `local_embeddings.py`, `local_rag.py` | Copiar: modelo local y recuperación de textos. |
| `core/literary_search.py`, `ai_http.py`, `ai_budget.py` | Copiar: búsquedas, HTTP y presupuesto compartido. |
| `core/literary_ai_views.py`, `core/urls.py` | Copiar: conecta ambos chats al asistente nuevo y conserva las otras rutas de la versión analizada. |
| `core/management/commands/` | Copiar los tres comandos. Los `__init__.py` incluidos están vacíos; créalos solo si faltan. |
| `static/js/chatbot.js`, `static/js/floating_chat.js` | Reemplazar los archivos completos. Mantienen voz y envío de mensajes; escapan el texto y muestran referencias como enlaces seguros. |
| `settings_ia_block.py` | **Excepción:** copia SU CONTENIDO al final de `litmate_project/settings.py`, reemplazando tu bloque anterior de IA. No reemplaces todo `settings.py` con este archivo. |
| Los demás archivos | Copiar manteniendo sus rutas. Incluyen Docker, pruebas, requisitos y evaluación. |

Después de copiar los JavaScript, recarga el navegador con **Ctrl + F5**. El asistente entrega títulos y referencias, sin inventar tarjetas con precios.

## 2. Instalar en Windows desde VS Code

Instala [Python 3.12](https://www.python.org/downloads/), [Ollama](https://ollama.com/download) y [Docker Desktop](https://www.docker.com/products/docker-desktop/). Abre Ollama y Docker Desktop.

En PowerShell, ubicado en la carpeta de `manage.py`:

```powershell
py -3.12 -m venv .venv-ia-pc
.\.venv-ia-pc\Scripts\python.exe -m pip install -r requirements-ia-pc.txt
ollama pull qwen3.5:9b-q4_K_M
ollama pull embeddinggemma
.\.venv-ia-pc\Scripts\python.exe activar_ollama_local.py
```

Cierra Ollama completamente desde su icono y ábrelo otra vez para aplicar el modo local. Selecciona `.venv-ia-pc` como intérprete de Python en VS Code. Los comandos de esta guía usan el ejecutable directo y no requieren activar PowerShell.

`requirements.txt` reúne las dependencias de la aplicación y del asistente local; `requirements-ia-pc.txt` lo incluye para conservar los comandos existentes. `groq` sigue instalado porque `core/views.py` lo importa al cargar las URLs; las rutas nuevas no invocan su API. La integración antigua con Pinecone/SentenceTransformer está separada en `requirements-legacy-ai.txt`. Las versiones se comprobaron en el `venv` existente con Python 3.14.7; para otras versiones de Python hay que comprobar también sus dependencias transitivas. Ollama, sus modelos y Docker/SearXNG se instalan por separado, no mediante pip.

Para seleccionar MySQL local o SQLite, respaldar y comprobar los datos, consulta [MYSQL_LOCAL.md](../guides/MYSQL_LOCAL.md). La selección existente se conserva hasta que configures explícitamente el corte; el soporte de MySQL incluye `mysqlclient` y conserva PyMySQL para el remoto anterior.

Arranque explícito con MySQL local, sin editar `.env`: `.\venv\Scripts\python.exe -B iniciar_mysql_local.py --http-desarrollo`. Introduce la contraseña en el prompt oculto. El lanzador comprueba la conexión y arranca Django en `http://127.0.0.1:8000/`; no importa datos ni aplica migraciones. La configuración guardada de TiDB permanece disponible al detenerlo.

En tu `.env`, agrega o reemplaza estas variables. No dupliques una misma variable con valores diferentes ni borres tus credenciales de base de datos:

```dotenv
LITMATE_OLLAMA_URL=http://127.0.0.1:11434
LITMATE_LOCAL_MODEL=qwen3.5:9b-q4_K_M
LITMATE_LOCAL_GUARD_MODEL=qwen3.5:9b-q4_K_M
LITMATE_LOCAL_CONTEXT=16384
LITMATE_LOCAL_ANSWER_TOKENS=3072
LITMATE_LOCAL_THINKING=false
LITMATE_AI_TOTAL_TIMEOUT=360
LITMATE_AI_USE_SEARXNG=true
LITMATE_SEARXNG_URL=http://127.0.0.1:8080
LITMATE_RAG_SEMANTIC=true
LITMATE_EMBED_MODEL=embeddinggemma:latest
```

Tu proyecto también carga un archivo llamado `env`; comprueba que no conserve valores contradictorios. No necesitas añadir ninguna API key para esta IA.

## 3. Iniciar el buscador y Django

```powershell
$env:DJANGO_SETTINGS_MODULE="litmate_project.settings"
.\.venv-ia-pc\Scripts\python.exe iniciar_buscador.py
.\.venv-ia-pc\Scripts\python.exe manage.py check
.\.venv-ia-pc\Scripts\python.exe manage.py migrate
.\.venv-ia-pc\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Entra a **http://127.0.0.1:8000/chat/**. `migrate` aplica las migraciones existentes; esta mejora no añade modelos Django ni requiere crear nuevas migraciones. Mantén tu configuración actual de SQLite o MySQL/TiDB.

SearXNG consulta motores públicos; Google puede bloquear consultas o no encontrar información. El asistente intenta sus otras fuentes y declara lo que falta confirmar. Google Books se consulta como sitio web, sin activar su API con clave. Eso no concede acceso al contenido completo de sus libros.

## 4. Darle contenido real de libros

Crea `data/libros` y agrega archivos con esta convención:

```text
Titulo del libro__Nombre del autor.pdf
Otro titulo__Otro autor.txt
```

Usa títulos y autores correctos. Los guiones bajos simples se interpretan como espacios; el doble `__` separa título y autor. La colección es compartida por los lectores del asistente, no una biblioteca privada separada por usuario.

En otra terminal:

```powershell
$env:DJANGO_SETTINGS_MODULE="litmate_project.settings"
.\.venv-ia-pc\Scripts\python.exe manage.py indexar_libros --semantico
.\.venv-ia-pc\Scripts\python.exe manage.py diagnosticar_ia --live
```

El índice se guarda en `data/litmate_rag.sqlite3`. Si cambias el modelo de embeddings o su versión descargada, vuelve a indexar. El reemplazo es atómico: un fallo al importar conserva el índice anterior.

Los PDF deben tener texto seleccionable; un escaneo necesita OCR previo. Recuperar fragmentos ayuda a responder con evidencia, pero no significa haber leído toda la obra. Para una cita o capítulo que no esté disponible, el asistente pide el pasaje en lugar de inventarlo. La «página del PDF» indica la posición del archivo, no la numeración impresa.

## 5. Probarlo y reunir evidencia para tu presentación

Pruebas automáticas, sin Ollama ni APIs reales:

```powershell
.\.venv-ia-pc\Scripts\python.exe verificar_asistente.py
```

Opcional, si ya tienes Node.js: `node verificar_chat_seguro.js` comprueba el formateador de los dos chats sin instalar paquetes npm.

Evaluación con el modelo **real de tu PC**, primero seis casos:

```powershell
.\.venv-ia-pc\Scripts\python.exe manage.py evaluar_ia --live --limit 6
```

Para los veinte casos, agrega a `data/libros` una copia del archivo incluido en `evaluacion/libros_prueba`. Es un texto sintético para probar el RAG, no una obra publicada. Vuelve a indexar tu colección y ejecuta:

```powershell
.\.venv-ia-pc\Scripts\python.exe manage.py indexar_libros --semantico
.\.venv-ia-pc\Scripts\python.exe manage.py evaluar_ia --live
```

El resultado se guarda en `reportes/evaluacion_ia.json`. Guarda ese archivo como evidencia: contiene preguntas, respuestas, fuentes, llamadas al modelo, tiempos y casos que requieren revisión. Compara también las respuestas con los libros. Un caso «OK» significa que pasó los criterios observables del archivo, no que un profesor le asignaría puntaje perfecto.

Prueba una consulta concreta con `evaluar_ia --live --id comparacion_multiple`. Puedes ampliar `evaluacion_ia.json` con preguntas de tu profesor y datos comprobados de los libros elegidos.

## 6. Ajustar el modelo cuando ya lo probaste

El archivo de Qwen 9B publicado en Ollama ronda 6,6 GB; necesitas memoria adicional para contexto y ejecución. Comprueba el uso con `ollama ps`. No conozco las especificaciones exactas de tu PC.

Si tarda demasiado o no cabe, descarga `ollama pull qwen3.5:4b-q4_K_M`, cambia **ambas** variables de modelo en `.env` y reinicia Django. Ejecuta los mismos casos para comparar respuestas y tiempos. No actives un modelo con `cloud` en su nombre: el backend exige modelos descargados localmente.

Deja `LITMATE_LOCAL_THINKING=false` al principio. Plan y auditoría ya separan tareas; activar razonamiento del modelo aumenta el tiempo y requiere volver a medir. Una pregunta sencilla suele requerir cuatro generaciones locales: clasificación, plan, respuesta y auditoría. Solo se transmite el texto final aprobado; el indicador del chat puede esperar durante esos pasos.

## Si algo falla

| Situación | Revisión concreta |
| --- | --- |
| Ollama no responde o falta el modelo | Abre Ollama, revisa `ollama list` y ejecuta `manage.py diagnosticar_ia --live`. |
| Búsqueda no disponible | Repite `iniciar_buscador.py`. Consulta los logs con `docker compose -f docker-compose.ia.yml logs --tail 30`. El secreto requerido se genera dentro del iniciador. |
| No encuentra un pasaje | Revisa texto seleccionable, título/autor del archivo e indexa otra vez. Una pregunta sobre un capítulo completo necesita ese capítulo. |
| La IA está ocupada | Se admite una generación a la vez para proteger el PC. Espera y reintenta; la API devuelve `Retry-After`. |
| Error de CSRF tras copiar archivos | Reinicia Django, recarga `/chat/` con Ctrl + F5 y vuelve a iniciar sesión. El chat envía el token de la cookie. |
| Respuesta incompleta o rechazada por el auditor | Consulta `reportes/evaluacion_ia.json` y el diagnóstico. No se publica el borrador inválido; mejora el caso o aporta el texto faltante. |
| Error al cargar `settings.py` | El archivo `settings_ia_block.py` es un bloque para pegar, no un reemplazo de todo tu archivo de configuración. |

## Alcance verificado

Se verificaron Python 3.12, Django 5.2.18, NumPy 2.3.5 y pypdf 6.10.0; 175 pruebas del backend pasaron. También pasaron la sintaxis JavaScript, ocho entradas de seguridad por chat y una integración HTTP con Django, CSRF, sesiones, SSE y RAG SQLite reales. Se comprobó la carga del driver PyMySQL 1.2.3 con Django, sin conectar a tu base remota. En esa integración Ollama fue simulado; no se midió aquí la calidad de Qwen ni se levantó Docker/SearXNG. La evaluación `--live` sirve para comprobar esas partes en tu PC.

Este paquete prepara la ejecución local. Un sitio SaaS público necesita un despliegue separado con servidor de producción, HTTPS y caché compartida para coordinar procesos; `runserver` y la caché en memoria corresponden a esta prueba local. Ollama y SearXNG permanecen en puertos locales.

## Documentación consultada

- [Ollama: chat y parámetros](https://docs.ollama.com/api/chat).
- [Ollama: salida con esquema JSON](https://docs.ollama.com/capabilities/structured-outputs).
- [Ollama: modo local y GPU](https://docs.ollama.com/faq).
- [Qwen 3.5 9B cuantizado](https://ollama.com/library/qwen3.5:9b-q4_K_M).
- [EmbeddingGemma](https://ollama.com/library/embeddinggemma) y [API de embeddings](https://docs.ollama.com/api/embed).
- [API de SearXNG](https://docs.searxng.org/dev/search_api.html) y [configuración del contenedor](https://docs.searxng.org/admin/installation-docker.html).
- [Open Library: búsqueda](https://openlibrary.org/dev/docs/api/search).
- [Google Books: alcance de su API](https://developers.google.com/books/docs/v1/using).
- [Django: despliegue](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/).

No se modificó el proyecto original ni se hicieron commits o pull requests.
