# Asistente literario de LitMate

LitMate conserva su personalidad, Qwen local, interfaz, recomendaciones, catálogo,
tarjetas, voz y avatares. La investigación aporta evidencia al asistente actual.
No requiere Groq, Pinecone, Tavily, Brave ni Gemini ni activa sustituciones de pago.
El costo obligatorio de API del asistente es $0.

La base Django existente no se modifica ni migra. Una cuenta TiDB Cloud puede tener
facturación propia: el código no permite certificar su plan ni consumo. Equipo,
electricidad, almacenamiento e Internet siguen siendo recursos necesarios.

## Inicio local en Windows

Desde PowerShell en la carpeta del proyecto, con el entorno virtual instalado:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements-ia-pc.txt
ollama pull qwen3.5:9b-q4_K_M
ollama pull embeddinggemma
```

Los comandos pull descargan modelos sin API de inferencia paga; no es necesario
repetirlos si ya están instalados. Mantén Ollama abierto. Para desactivar su nube,
configura OLLAMA_NO_CLOUD=1 en el entorno del proceso que inicia Ollama y reinícialo.
LitMate también rechaza modelos cloud.

Abre Docker Desktop y ejecuta:

```powershell
.\venv\Scripts\python.exe iniciar_buscador.py
```

El script reutiliza el Compose existente, genera un secreto interno y comprueba
salud y JSON. Invoca Docker con
`docker compose --env-file searxng/compose.env -f docker-compose.ia.yml up -d`.
El archivo de entorno específico evita cargar credenciales del .env de Django.
Usa el script para proporcionar el secreto; no hace falta una clave comercial.

SearXNG se publica solo en 127.0.0.1:8080. Sus motores son Wikipedia, Open Library
y Mwmbl; Google HTML y DuckDuckGo HTML están excluidos. Mwmbl tiene cobertura
limitada. No se eluden bloqueos, CAPTCHA ni límites y no se depende de instancias
públicas de SearXNG.

En la misma consola puedes activar el buscador sin editar tu .env:

```powershell
$env:LITMATE_AI_USE_SEARXNG='True'
$env:LITMATE_USE_GOOGLE_BOOKS_API='False'
.\venv\Scripts\python.exe manage.py preparar_conocimiento --semantico
.\venv\Scripts\python.exe manage.py diagnosticar_ia
.\venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Para conservar la configuración entre reinicios, copia las variables pertinentes
de .env.example a tu .env sin borrar datos de otros servicios. Abre
[el chat](http://127.0.0.1:8000/chat/). Ambos chats usan el mismo asistente.
No se requieren migraciones para preparar fichas o índices de IA.

## Fuentes e investigación

La recuperación utiliza contexto, caché, fichas locales, catálogo y colección
local antes de investigar detalles faltantes en fuentes gratuitas. Evalúa qué
necesita la pregunta: una sinopsis no prueba personajes secundarios, escenas,
citas ni páginas. Un fallo de formato del modelo no justifica buscar más.

Wikipedia y Wikidata usan interfaces oficiales. Open Library identifica obras y
ediciones. SearXNG descubre fuentes y el lector controlado recupera páginas y PDF
públicos admitidos. Las fuentes mantienen sus URLs y su vínculo con la obra; se
evitan películas y otros volúmenes. Las instrucciones de páginas externas no
pueden modificar el comportamiento del asistente.

Las consultas se construyen desde título, autor y detalle literario. Los pasajes
privados, claves, correos y la conversación completa no se envían a buscadores.
Se aplican controles contra SSRF, redirecciones privadas, contenido excesivo y
tipos no admitidos, y se revisa robots.txt cuando corresponde. No se eluden
autenticaciones ni se descargan novelas completas protegidas.

```dotenv
LITMATE_OLLAMA_URL=http://127.0.0.1:11434
LITMATE_LOCAL_MODEL=qwen3.5:9b-q4_K_M
LITMATE_LOCAL_GUARD_MODEL=qwen3.5:9b-q4_K_M
LITMATE_LOCAL_CONTEXT=16384
LITMATE_AI_QUALITY_CHECKS=True
LITMATE_AI_USE_WEB=True
LITMATE_AI_USE_SEARXNG=True
LITMATE_SEARXNG_URL=http://127.0.0.1:8080
LITMATE_SEARXNG_ENGINES=wikipedia,openlibrary,mwmbl
LITMATE_AI_USE_OPENLIBRARY=True
LITMATE_AI_USE_WIKIDATA=True
LITMATE_RESEARCH_ENABLED=True
LITMATE_RESEARCH_TIMEOUT=15
LITMATE_RESEARCH_MAX_SEARCHES=2
LITMATE_RESEARCH_MAX_PAGES=3
LITMATE_RESEARCH_CACHE_SECONDS=86400
LITMATE_RAG_SEMANTIC=True
LITMATE_EMBED_MODEL=embeddinggemma:latest
```

El presupuesto externo no promete una latencia total: generar y revisar respuestas
también depende del equipo. No reduzcas validadores para ocultar respuestas
incorrectas. El historial conserva obra activa, alias confirmados y evidencia.

## Conocimiento y búsqueda semántica

`preparar_conocimiento --semantico` crea dos SQLite auxiliares separados:

- data/litmate_knowledge.sqlite3: fichas y hechos con referencias.
- data/litmate_knowledge_rag.sqlite3: FTS5 y vectores locales de esas fichas.

Las cuatro fichas iniciales son redacciones factuales originales breves de
Papelucho y el marciano, El principito, Rebelión en la granja y Crimen y castigo.
No son novelas, listas completas de personajes ni citas. CC0 se aplica solo a esta
redacción original, nunca al contenido de las fuentes o a las obras.

El comando no reemplaza data/litmate_rag.sqlite3 ni elimina fichas ajenas. Rechaza
sobrescribir índices desconocidos. Reutiliza embeddings sin cambios y conserva
el índice anterior si falla una reconstrucción. Sin Ollama puedes preparar FTS:

```powershell
.\venv\Scripts\python.exe manage.py preparar_conocimiento
```

Para añadir documentos que tengas derecho a usar, coloca PDF/TXT/MD en data/libros
con nombres Titulo__Autor.pdf:

```powershell
.\venv\Scripts\python.exe manage.py indexar_libros --semantico
```

Este comando reconstruye la colección compartida del asistente desde esa carpeta.
Los archivos retirados dejan de figurar tras una reconstrucción correcta; un fallo
conserva el índice anterior. Los escaneos necesitan OCR. Página N del PDF significa
posición del archivo, no numeración impresa de cualquier edición.

Un manifiesto opcional `--metadatos ruta.json` identifica resúmenes autorizados
como kind=web o kind=book, con URL, licencia y autorización de indexación. No se
convierten en kind=excerpt. Las páginas consultadas durante una conversación no
se indexan permanentemente.

## Diagnóstico y pruebas

```powershell
.\venv\Scripts\python.exe manage.py diagnosticar_ia
.\venv\Scripts\python.exe manage.py diagnosticar_ia --live --sin-fuentes --message 'Hola, ¿cómo estás?'
.\venv\Scripts\python.exe manage.py diagnosticar_ia --live --message 'Dime los personajes de Papelucho y el marciano'
.\venv\Scripts\python.exe -B verificar_asistente.py
.\venv\Scripts\python.exe -B verificar_proyecto.py core suscripciones
node verificar_chat_seguro.js
```

Sin --live, el diagnóstico no hace conexiones: muestra configuración y cuenta
registros locales sin consultar TiDB. --live --sin-fuentes prueba Ollama sin
fuentes externas. El verificador offline usa tablas temporales y no migra la base
del proyecto. Las pruebas en vivo se ejecutan aparte y exigen revisar resultados.

Para una integración real aislada de usuarios, .env y TiDB, usa este verificador:

```powershell
.\venv\Scripts\python.exe -B verificar_investigacion.py --live --web --message 'Papelucho y el marciano' --message '¿Y sus personajes cuáles son?' --message '¿Qué sucede con Det?' --output reportes/prueba_contexto.json
```

Sin --live solo recupera fuentes; --web permite las fuentes públicas gratuitas.
Los informes quedan en reportes/, excluido de Git. --trace guarda borradores
solo en ese informe local: úsalo con preguntas de prueba, sin datos personales.
El verificador aislado comprueba las herramientas y el modelo, no sustituye una
prueba manual de la sesión web. Para probar con datos propios usa el diagnóstico
habitual y el navegador, conservando la configuración de tu base.

Casos que debe cubrir la conversación:

1. Papelucho y el marciano → ¿Y sus personajes? → ¿Qué sucede con Det?
2. Recuerdo un niño en un planeta pequeño, una rosa y un zorro.
3. Un libro donde todos los animales son iguales.
4. ¿En qué libro aparece Raskólnikov?
5. Era un libro sobre una mujer que viajaba.

La última consulta no identifica una obra de forma definitiva. LitMate debe pedir
pistas: similitud semántica no prueba identidad. La sinopsis de Det tampoco prueba
su desenlace. SearXNG caído permite continuar con fuentes locales y otras APIs
gratuitas. Errores, cuotas y tiempos agotados se distinguen de búsquedas vacías,
con esperas para no insistir. Sin evidencia fiable se reconoce la incertidumbre.

## Google Books opcional y costo

Books queda desactivado por defecto. Una clave antigua no basta: también exige
LITMATE_GOOGLE_BOOKS_CONFIRMED_NO_BILLING=True. Solo actívalo tras comprobar que
tu cuenta no exige facturación y sus términos permiten el uso previsto, sobre
todo si LitMate cobra suscripciones. El asistente funciona sin Books y no requiere
registrar una tarjeta para estas funciones.

La variable es una confirmación administrativa, no una verificación del estado
económico de la cuenta. Tampoco se certifican planes de TiDB, OAuth, correo o
pagos de otras partes del proyecto. No se trasladó la base existente.

## Voz y despliegue

La voz del navegador sigue funcionando sin claves. edge-tts es opcional, queda
desactivado por defecto y envía texto a Microsoft si se activa. Las voces dependen
del navegador y del sistema operativo.

Mantén SearXNG privado. Si Django pasa a otro contenedor, se necesita configurar
esa conexión privada concreta y separarla de las URLs públicas de lectores o
páginas. Redis es opcional y puede autohospedarse. No se exige VPS, hosting de pago
ni suscripción para iniciar este buscador.

Consulta INFORME_BUSQUEDA_LITERARIA.md para componentes, fuentes y límites.
