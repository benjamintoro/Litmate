# LitMate: conocimiento persistente y rendimiento

Revisión: 23 de octubre de 2026. Punto de partida: commit `9d59c69`.

## Decisiones

Se mantienen Django, Ollama, la personalidad, los validadores y la interfaz.
No se instalaron dependencias ni se habilitaron proveedores comerciales.
LangGraph aporta ejecución durable y orquestación, pero incorporarlo aquí no
elimina las llamadas secuenciales del modelo. Se reutilizan el enrutamiento
existente, SQLite, el pool acotado y los contratos de evidencia.
LlamaIndex ofrece recuperación híbrida; LitMate ya dispone de FTS5/BM25,
embeddings locales y fusión RRF. No se añade otro framework sin demostrar
una mejora frente a esos componentes.

Referencias técnicas consultadas:

- [SQLite FTS5 y BM25](https://www.sqlite.org/fts5.html).
- [Ollama: generación, métricas y keep_alive](https://docs.ollama.com/api/generate).
- [Ollama: contexto y uso de memoria](https://docs.ollama.com/context-length).
- [LangGraph](https://reference.langchain.com/python/langgraph/overview).
- [LlamaIndex: fusión de recuperadores](https://developers.llamaindex.ai/python/framework/integrations/retrievers/reciprocal_rerank_fusion/).
- [SearXNG: formatos permitidos](https://docs.searxng.org/admin/settings/settings_search.html).

## Flujo de una consulta

1. Las respuestas sociales y rechazos claros conservan sus rutas inmediatas.
2. La caché exacta privada comprueba propietario, contexto, revisión y vigencia.
3. El índice persistente y las fichas existentes recuperan evidencia. Las rutas
   extractivas comprueban identidad y requisitos de la pregunta sin llamar al LLM.
4. Para autoría, personajes y sinopsis simples, una ronda concurrente de fuentes
   estructuradas intenta recuperar las pruebas que faltan.
5. Las recomendaciones mantienen su descubrimiento por tema y sus filtros.
6. Cuando la evidencia no basta, continúa la investigación y generación existentes
   bajo un único presupuesto. Una sinopsis no acredita personajes ni escenas.
7. El resultado factual sólo se publica después de las validaciones aplicables.

No se reutiliza una respuesta final por parecido semántico. Las paráfrasis pueden
recuperar las mismas fuentes, pero deben volver a demostrar identidad y cobertura.

## Almacenes separados

- `literary_memory.sqlite3`: datos públicos admitidos, entidades, fuentes,
  afirmaciones, alias, relaciones, conflictos, historial, FTS5 y cola durable.
  Cada snapshot conserva procedencia, hash, recuperación, verificación y expiración.
- `litmate_answers.sqlite3`: respuestas extractivas privadas, TTL de una hora,
  claves HMAC ligadas al lector y contexto, máximo de mil entradas. No es una
  base de hechos ni entrenamiento. Una avería invalida el hit y permite investigar.
- `litmate_ia_stream.sqlite3`: resultados privados pendientes, TTL de dos minutos,
  tokens opacos, finalización idempotente y protección contra respuestas obsoletas.
- Se conservan los índices RAG y el corpus original anteriores.

Los almacenes auxiliares tienen marcadores de propiedad y rechazan bases ajenas.
No requieren modelos ni migraciones Django. Las pruebas les asignan rutas
temporales independientes; no usan los datos del lector.

## Fuentes y derechos

La autorización para leer una página no autoriza almacenarla permanentemente.
El nuevo almacén sólo acepta políticas explícitas:

- Open Library: metadatos bibliográficos mínimos, sin sinopsis editoriales,
  portadas ni textos anidados. Su documentación no concede CC0 general a cada
  contribución: [condiciones](https://openlibrary.org/developers/licensing).
- Wikidata: declaraciones estructuradas CC0, sin presentar una declaración como
  corroboración independiente: [licencia](https://www.wikidata.org/wiki/Wikidata:Licensing).
- Wikipedia: pasajes limitados con revisión real, licencia CC BY-SA 4.0 y
  atribución a sus contribuyentes. No se relabelan como CC0:
  [reutilización](https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use#7._Licensing_of_Content).
- Corpus factual original: sólo los textos exactos autorizados ya revisados.
- Google Books, Amazon, Buscalibre, Fandom, editoriales y páginas generales
  conservan sus mecanismos actuales de consulta y enlaces. No se les atribuye
  permiso de almacenamiento permanente por ser páginas públicas.

Se mantienen HTTPS, DNS público fijado, robots, límites de páginas y tamaño,
rechazo de redirecciones privadas y de instrucciones externas. No hay extracción
de respuestas generadas por Google ni descarga indiscriminada de novelas.

## Actualización y aprendizaje

`actualizar_conocimiento` es un trabajador opcional separado. No inicia un
proceso permanente al arrancar Django. Usa un lease global, tareas durables,
reintentos con backoff, pausas y límites de trabajos/tiempo. Puede detenerse y
continuar sin perder la cola. Actualiza el inventario conocido; no rastrea
indiscriminadamente nuevos sitios.

Las señales adaptativas guardan únicamente IDs de obras, categorías controladas,
aciertos/fallos verificados y tiempos. Sin mensajes, IP ni identidad del lector.
La selección de proveedores sólo cambia tras un mínimo de observaciones y con
efecto acotado. Popularidad y aciertos de caché no prueban verdad factual.
`--delete-usage` elimina esas señales sin borrar las obras ni sus fuentes.
No se entrenan pesos ni se ingieren respuestas del LLM como conocimiento.

## Progreso y medidas

El navegador solicita `progress:true`. El servidor emite fases desde operaciones
reales y entrega un token `ready`; un POST con CSRF a `/chatbot_finalize/` guarda
la conversación y devuelve texto y tarjetas validados. Funciona también con
cookies firmadas. Las respuestas rápidas y el protocolo SSE anterior se conservan.

La instrumentación distingue recuperación, lectura de conocimiento, HTTP,
generación, auditoría, reparación e inspección del modelo. Los tiempos anidados
y concurrentes no deben sumarse como si fueran tiempo total exclusivo.
El benchmark mide en el cliente el primer progreso y la respuesta completa.
La memoria RSS corresponde al proceso Django, no a Ollama ni a la GPU.

Hay una ventana de caída entre consumir cuota y guardar el recibo de finalización:
falla cerrada hasta expirar, sin volver a consumir. La carrera histórica de cuotas
entre clientes del endpoint legado no se declara resuelta.

## Comprobación reproducible

Desde PowerShell, con Ollama disponible:

```powershell
.\venv\Scripts\python.exe -B verificar_proyecto.py core suscripciones
node verificar_chat_seguro.js
.\venv\Scripts\python.exe -B evaluar_chat_http.py --progressive --message '¿Quién escribió Orgullo y prejuicio?' --repeat 3 --output reportes/prueba_http_nueva.json
.\venv\Scripts\python.exe -B evaluar_chat_http.py --progressive --empty-answer-cache-each-turn --empty-retrieval-cache-each-turn --message '¿Quién escribió Orgullo y prejuicio?' --output reportes/prueba_sin_cache_nueva.json
.\venv\Scripts\python.exe -B evaluar_cache_rag.py --help
.\venv\Scripts\python.exe -B evaluar_inferencia_local.py --output reportes/comparacion_modelos_nueva.json
```

Los informes no se sobrescriben: usa rutas nuevas. El benchmark HTTP crea una
base Django vacía temporal y usa fuentes/Ollama reales. Las pruebas unitarias
simulan proveedores explícitamente. El microbenchmark RAG usa BM25 real y
vectores controlados: no mide inferencia neuronal ni demuestra rendimiento del chat.

Para ejecutar la aplicación y el trabajador opcional:

```powershell
.\venv\Scripts\python.exe manage.py runserver
.\venv\Scripts\python.exe manage.py actualizar_conocimiento --stats
.\venv\Scripts\python.exe manage.py actualizar_conocimiento --once --enqueue-known --max-jobs 2 --max-seconds 30
.\venv\Scripts\python.exe manage.py actualizar_conocimiento --watch --enqueue-known --interval 60
```

No se modificó `.env`. Las nuevas rutas son configurables en `ai_settings.py`;
se justifican para separar conocimiento público y resultados privados de Django.
El coste obligatorio de API añadido es $0. Electricidad, disco, Internet y
cualquier servicio de hosting/base de datos ajeno mantienen sus costes propios.

## Alcance que debe medirse sin promesas

Los objetivos de 5/10/30 segundos y 1% de errores no están garantizados por
timeouts, tests simulados ni cuatro preguntas. Deben revisarse respuestas
completas, parciales, abstenciones, ambigüedades, arranque frío y fallos de red.
Los resultados reales de esta intervención se registran en
`reportes/arquitectura_20261023/` y `reportes/continuidad_opencode.md`.
