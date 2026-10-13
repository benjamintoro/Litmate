# Asistente IA de LitMate

El asistente usa Google Books para localizar obras y consultar fichas, sinopsis,
autores, ediciones, ISBN y vistas previas. Ollama genera recomendaciones y
explicaciones a partir de esas fuentes; las respuestas se revisan antes de mostrarlas.
Los dos chats utilizan el mismo servidor y conservan el contexto de la conversación.
LitMate también admite charla cotidiana y gustos del lector. Conserva ocho turnos
recientes, muestra tarjetas con portadas y enlaces a Google Books, Amazon y
Buscalibre, y distingue las sinopsis editoriales de la información pública adicional.

Las preguntas bibliográficas sencillas se responden directamente desde Google
Books, sin esperar varias generaciones del modelo. Si Ollama falla, el asistente
puede mostrar fichas relacionadas como respaldo y explica el alcance de esos datos.
Las recomendaciones e identificaciones requieren obras presentes en fuentes
recuperadas; no se publican títulos inventados por el clasificador.

Esta actualización está limitada al asistente. No cambia modelos Django ni necesita
nuevas migraciones. No modifica tus credenciales de base de datos ni las claves de .env.

## Lo que debes configurar

### Google Books

La clave de Google Books ya está configurada en este equipo. Si preparas otra
instalación, estos son los pasos para obtener tu propia clave:

1. Abre [Google Cloud Console](https://console.cloud.google.com/).
2. Selecciona o crea un proyecto. En **APIs y servicios > Biblioteca**, busca
   **Books API** y habilítala.
3. En **APIs y servicios > Credenciales**, crea una **clave de API**.
4. Restringe la clave a **Books API**. La usa el servidor Python; una restricción
   por referente HTTP del navegador no corresponde a esta integración. En un
   servidor con IP fija puedes restringirla también a esa IP.
5. Agrega estas líneas a `G:\Proyecto\Litmate\.env`. Reemplaza el valor de ejemplo
   y evita duplicar variables. No pegues la clave en los JavaScript ni en el chat.

```dotenv
LITMATE_USE_GOOGLE_BOOKS_API=True
GOOGLE_BOOKS_API_KEY=PEGA_AQUI_TU_CLAVE
GOOGLE_BOOKS_LANGUAGE=
LITMATE_AI_REQUIRE_BOOK_SOURCES=True
LITMATE_AI_BIBLIOGRAPHIC_FAST_PATH=True
LITMATE_AI_CATALOG_FALLBACK=True
LITMATE_AI_FAST_RECOMMENDATIONS=True
```

Reinicia Django después de cambiar `.env`. Una clave antigua no puede ser
sustituida por una cadena inventada. Ante errores 403/429 revisa la activación,
restricciones y cuotas del proyecto en Google Cloud.

[Documentación oficial de Books API](https://developers.google.com/books/docs/v1/using),
[búsqueda de volúmenes](https://developers.google.com/books/docs/v1/reference/volumes/list)
y [detalle de volumen](https://developers.google.com/books/docs/v1/reference/volumes/get).

### Ollama

En este equipo ya están instalados `qwen3.5:9b-q4_K_M` y `embeddinggemma:latest`.
Mantén Ollama abierto y estas variables en `.env`:

```dotenv
LITMATE_OLLAMA_URL=http://127.0.0.1:11434
LITMATE_LOCAL_MODEL=qwen3.5:9b-q4_K_M
LITMATE_LOCAL_GUARD_MODEL=qwen3.5:9b-q4_K_M
LITMATE_LOCAL_CONTEXT=16384
LITMATE_LOCAL_THINKING=False
LITMATE_LOCAL_ANSWER_TOKENS=3072
LITMATE_AI_TOTAL_TIMEOUT=360
LITMATE_AI_LOCK_BACKEND=sqlite
LITMATE_AI_USE_SEARXNG=False
```

La inferencia local no necesita claves Groq, Pinecone o Hugging Face. Google Books
es una fuente bibliográfica; no reemplaza al modelo que redacta análisis literarios.
Docker/SearXNG es opcional. No es necesario instalarlo para usar Google Books.

## Comprobar y abrir el asistente

Desde PowerShell en `G:\Proyecto\Litmate`, utiliza el intérprete del proyecto:

```powershell
.\venv\Scripts\python.exe -B manage.py diagnosticar_ia
.\venv\Scripts\python.exe -B manage.py diagnosticar_ia --books-live --message "Cien años de soledad"
.\venv\Scripts\python.exe -B manage.py diagnosticar_ia --live --message "Recomiéndame un libro sobre la historia de Chile"
.\venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

El primer diagnóstico revisa configuración sin conexiones; el segundo comprueba
Google Books sin exigir Ollama; el tercero prueba una respuesta completa con el
modelo instalado. Si falla, el comando da un motivo de configuración sin mostrar claves.

Abre [el chat](http://127.0.0.1:8000/chat/) y recarga con **Ctrl+F5** para cargar los
nuevos JavaScript. El widget flotante utiliza la misma lógica.

Prueba, por ejemplo:

- `Recomiéndame tres novelas de ciencia ficción y explica sus diferencias.`
- `Busco un libro sobre la historia de Chile.`
- `¿Quién es el autor de «1984»?`
- `¿Cuántas páginas tiene «Como agua para chocolate»?`
- `Cuéntame más del segundo libro.`
- `Analiza este fragmento: ...`

Los datos de páginas y publicación corresponden a la edición de la ficha
mostrada. Si necesitas una edición exacta, indica su ISBN. Los identificadores,
años y páginas de ediciones distintas se mantienen separados.

## Para preguntas sobre capítulos y citas

Google Books no garantiza acceso al contenido completo de cada libro. Su ficha
y sinopsis no prueban lo que ocurre en una página o capítulo. Las vistas previas
se enlazan al proveedor; el programa no descarga ni finge haber leído toda la obra.

Para consultar pasajes concretos puedes:

1. Pegar el pasaje en el chat, precedido por `fragmento:` o `pasaje del libro:`.
   Esos fragmentos se analizan localmente y no se envían a buscadores públicos.
2. Indexar archivos PDF/TXT/MD que tengas derecho a usar. Los PDF necesitan texto
   seleccionable; un escaneo requiere OCR previo.

Coloca los archivos en `data/libros` usando nombres como:

```text
Titulo_del_libro__Nombre_del_autor.pdf
Otro_titulo__Otro_autor.txt
```

```powershell
.\venv\Scripts\python.exe -B manage.py indexar_libros --semantico
```

El índice local se reemplaza de forma atómica: un fallo conserva el índice
anterior. Admite textos UTF-8 y archivos Windows de texto habituales. La colección
es compartida entre lectores del asistente; no es una biblioteca privada por usuario.
La referencia «página N del PDF» es la posición en el archivo, no la numeración impresa.

La muestra reproducible de evaluación está en `evaluacion/libros_prueba` y es
sintética, no una obra publicada. Para probarla sin mezclarla con tus libros:

```powershell
.\venv\Scripts\python.exe -B manage.py indexar_libros --carpeta evaluacion/libros_prueba --semantico
.\venv\Scripts\python.exe -B manage.py evaluar_ia --live --id rag_archivo_de_prueba
```

Ese comando reemplaza la colección del índice; vuelve a indexar `data/libros`
cuando termines. La evaluación guarda respuestas en `reportes/evaluacion_ia.json`
para revisión humana y no certifica exactitud absoluta.

## Rendimiento y coordinación

Las fichas se cachean y las preguntas bibliográficas pueden evitar el modelo.
Las preguntas sencillas por personajes también tienen una ruta rápida: verifica
la obra con Google Books y consulta las fichas de personajes publicadas en
Wikipedia. Si la identidad o los papeles no se confirman, continúa con el modelo
y la búsqueda habitual. `LITMATE_AI_PUBLIC_DETAILS_FAST_PATH=False` desactiva esa ruta.
Las recomendaciones habituales usan clasificación, respuesta y revisión, sin
planificación ni auditoría adicionales. `LITMATE_AI_FAST_RECOMMENDATIONS=False`
activa también esos pasos. Los análisis y las consultas de datos recientes
conservan la revisión completa. Cuando faltan sinopsis se busca información
adicional en fuentes públicas; se conserva su procedencia y no se inventa la trama.
Una consulta de análisis suele requerir clasificación, planificación, generación
y auditoría; una reparación añade trabajo. El modelo 9B puede tardar decenas de
segundos según el equipo. El objetivo de tres segundos del informe debe medirse;
no queda garantizado por esta implementación.

Si el 9B tarda demasiado, descarga `ollama pull qwen3.5:4b-q4_K_M`, cambia ambas
variables de modelo y compara los mismos casos. Comprueba CPU/GPU y memoria con
`ollama ps`. No reduzcas controles de evidencia para ocultar errores del modelo.

El bloqueo y contador de solicitudes se coordinan en un SQLite exclusivo de IA,
`data/litmate_ia_runtime.sqlite3`, entre los procesos del mismo equipo. Este archivo
no contiene preguntas ni claves y se crea automáticamente, sin migraciones Django.
Para varias máquinas configura un Redis compartido con `CACHE_URL` y
`LITMATE_AI_LOCK_BACKEND=redis`. El backend `cache` queda para pruebas con un proceso.

## Voz opcional

```dotenv
LITMATE_TTS_ENABLED=True
LITMATE_TTS_TIMEOUT_SECONDS=20
```

Los chats pueden leer las respuestas con la síntesis de voz del navegador, sin
necesitar una clave ni activar el servicio externo. El botón de volumen silencia
la lectura y el control deslizante ajusta su volumen. La voz disponible depende
de las voces españolas instaladas en el navegador o sistema operativo.

La voz Microsoft mediante `edge-tts` es opcional y envía el texto al proveedor.
Se limita a 3500 caracteres, cinco solicitudes por minuto y una generación
simultánea; la caché tiene límites de tamaño y tiempo. Por defecto ese servicio
externo está desactivado. Si el navegador no ofrece voces españolas, en Windows
agrega una voz desde **Configuración > Hora e idioma > Voz** y vuelve a abrirlo.

## Pruebas sin servicios externos

```powershell
.\venv\Scripts\python.exe -B verificar_asistente.py
node verificar_chat_seguro.js
```

El verificador Python utiliza únicamente una base de prueba en memoria y archivos
temporales; no aplica migraciones a tu base ni utiliza las claves de `.env`.
Las pruebas de inferencia usan un modelo simulado. Una prueba levanta un servidor
HTTP temporal en localhost para comprobar el protocolo real.

Si faltan dependencias, instálalas en tu entorno virtual:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements-ia-pc.txt
```

No sustituyas todo `settings.py` con un bloque de IA: ahora hay una sola configuración
en `litmate_project/ai_settings.py`, importada por el archivo principal.
