# Investigación literaria gratuita de LitMate

Registro de implementación, actualizado el 19 de octubre de 2026. El asistente conserva el modelo
local, personalidad, presentación, catálogo, recomendaciones, voz y avatares.
No se crean aplicaciones paralelas ni dependencias de API facturables.
La incidencia de ejecución de pruebas se documenta al final.

## Componentes y responsabilidades

| Componente | Responsabilidad |
| --- | --- |
| core/literary_ai.py | Coordinar herramientas y redactar con el Qwen actual; conservar validadores. |
| core/literary_identity.py | Identidad estable, alias con procedencia y continuidad entre turnos. |
| core/literary_research.py | Evaluar evidencia por pregunta y ordenar candidatos mediante pistas respaldadas. |
| core/literary_search.py | Reutilizar fuentes locales, catálogo, APIs bibliográficas y descubrimiento web. |
| core/literary_sources.py | Diferenciar búsquedas vacías de errores y aplicar esperas. |
| core/literary_web.py | Descargar y extraer contenido público con límites, robots y controles HTTP. |
| core/literary_wikidata.py | Consultar metadatos y relaciones estructuradas verificables. |
| core/literary_knowledge.py | Fichas SQLite factuales, búsqueda léxica y aproximada, referencias y permisos. |
| core/local_rag.py | FTS5 y embeddings locales; actualización atómica y reutilización de vectores. |
| core/management/commands/preparar_conocimiento.py | Preparar fichas originales e índice independiente. |
| docker-compose.ia.yml, searxng/settings.yml, iniciar_buscador.py | Ejecutar la instancia local existente de SearXNG y comprobar JSON. |

## Recorrido de una pregunta

1. Resolver la obra mencionada o continuar con la obra activa. Un título nuevo
   explícito reemplaza el contexto; varias obras posibles requieren aclaración.
2. Consultar contexto, caché, fichas originales, catálogo y recuperación local.
3. Identificar lo que exige la pregunta: identidad, sinopsis, personajes,
   relaciones, acontecimientos, escenas, citas, comparación o recomendaciones.
4. Investigar únicamente datos faltantes o contradicciones verificables. Un fallo
   de formato o conexión del modelo no activa una búsqueda inútil.
5. Descubrir fuentes gratuitas, comprobar su relación con la obra y recuperar
   contenido permitido. Una película no respalda hechos de la novela.
6. Entregar evidencia y referencias al mismo asistente, separadas de sus
   instrucciones. Revisar la respuesta antes de publicarla.
7. Conservar identidad y evidencia relevante para el seguimiento; si falta
   respaldo, expresar incertidumbre concreta y solicitar pistas útiles.

Los candidatos de identificación se ordenan mediante pistas presentes en las
fuentes, con tolerancia a variaciones de nombres y recuperación híbrida local.
Se presentan hasta tres cuando hay evidencia; las puntuaciones internas no se
publican como porcentajes de certeza. Un recuerdo genérico no identifica un libro.

## Identidad, memoria y procedencia

Las obras llevan work_id, título, autor, identificadores y alias confirmados.
La semejanza de títulos no establece equivalencia. La ficha de CiNii enlazada
debajo registra explícitamente el título alternativo de Papelucho; el sistema no
elimina automáticamente palabras de todos los títulos de una colección.

Las páginas conservan su título y autor originales, URL y método de extracción.
El vínculo con la obra se añade por separado después de verificarlo. La presencia
de un nombre no demuestra una relación, acontecimiento o lista completa.

La memoria y la caché reutilizan evidencia; no prometen que todas las páginas
contengan la respuesta ni transforman el conocimiento del modelo en una fuente.
Los resúmenes factuales locales no autorizan citas textuales, páginas ni capítulos.

## Fuentes iniciales del conocimiento local

Las fichas contienen redacciones originales breves verificadas, no reproducciones
de páginas o novelas. Su licencia CC0 corresponde solo a la redacción original.
Los sitios y obras citados mantienen sus derechos y condiciones de acceso.

| Obra | Información verificada y referencia |
| --- | --- |
| Diario secreto de Papelucho y el marciano | Papelucho, Det y su convivencia según [SM](https://literaturasm.cl/diario-secreto-de-papelucho-y-el-marciano/). Alias bibliográfico explícito según [CiNii/NII](https://ci.nii.ac.jp/ncid/BA64258717). La sinopsis no prueba el desenlace ni todos los personajes. |
| El principito | Niño, planeta pequeño, rosa, zorro y aviador según el [sitio oficial de la obra](https://www.lepetitprince.com/loeuvre/). |
| Rebelión en la granja | Identidad, revolución animal y problema de igualdad según [Penguin](https://www.penguin.co.uk/books/57033/animal-farm-by-orwell-george/9780141393056). La ficha local parafrasea la idea; no atribuye una traducción o página exacta. |
| Crimen y castigo | Raskólnikov y su conflicto según la [ficha editorial de Penguin](https://www.penguinlibros.com/es/libros-clasicos/365707-libro-crimen-y-castigo-9788491057314). |

## Indexación y eliminación controlada

Las fichas y su índice se guardan en bases auxiliares SQLite independientes de la
base Django y de la colección de novelas. Prepararlas no mueve ni migra datos de
TiDB. Una reconstrucción usa un archivo temporal y reemplazo atómico; un fallo
conserva el índice anterior. Los embeddings sin cambios pueden reutilizarse.

Actualizar una ficha sustituye sus hechos obsoletos de forma transaccional. La
preparación inicial conserva fichas ajenas. El comando de preparación rechaza un
índice desconocido y rechaza usar la ruta de la colección de novelas.
Reconstruir una colección desde su carpeta elimina del índice los documentos
retirados deliberadamente de esa carpeta. No se ejecutan borrados de producción.

La indexación permanente requiere procedencia y autorización. La recuperación
temporal de una página no la convierte automáticamente en documento indexable.
Para importar una ficha original mediante indexar_libros se puede proporcionar
un manifiesto local con --metadatos; por ejemplo:

```json
{
  "Mi_resumen__Mi_autor.txt": {
    "kind": "web",
    "work_title": "Título de la obra",
    "work_author": "Autor de la obra",
    "url": "https://example.org/ficha-verificada",
    "source": "Biblioteca literaria local",
    "license": "Redacción propia autorizada para esta colección",
    "indexing_authorized": true
  }
}
```

La URL anterior es un ejemplo de formato: debe sustituirse por una referencia
real que respalde el contenido. La autorización no se deduce de un atributo de
una página web ni de que un archivo sea accesible públicamente.

## Seguridad y acceso

El lector público admite dominios revisados, protocolos y puertos permitidos.
Valida DNS e IP pública y controla conexiones y redirecciones para reducir SSRF.
Los servicios locales autorizados, Ollama y SearXNG, utilizan un camino separado;
una página o usuario no puede seleccionar un servicio interno arbitrario.

Se limitan tiempo, bytes, contenido extraído, tipos y complejidad de PDF. Los
documentos escaneados pueden no devolver texto; no se realizan descargas masivas
ni se eluden autenticación, CAPTCHA, paywalls o bloqueos. Las páginas se consultan
respetando robots.txt cuando corresponde; los endpoints oficiales se rigen por
sus políticas específicas. No se copian respuestas generadas por buscadores.

Las instrucciones externas son datos no confiables. Los registros diagnósticos
utilizan estados y clases de error, sin claves, URLs con secretos ni historial
privado. Las búsquedas se forman con identidad y hechos públicos del libro.

## Disponibilidad y límites

Configuración inicial: hasta dos búsquedas condicionadas, tres lecturas y un
presupuesto externo de quince segundos. La caché de resultados positivos dura
inicialmente veinticuatro horas; los vacíos tienen una duración breve. Los fallos
se distinguen de vacíos y activan esperas, incluyendo límites de motores.

Si SearXNG falla, siguen disponibles los datos locales y otras fuentes gratuitas.
Si un resultado corresponde a otro libro se descarta. Si hay contradicciones se
mantienen sus procedencias y el asistente no completa detalles inventados.

La cobertura de fuentes gratuitas es irregular: Mwmbl no sustituye la cobertura
de Google y los motores pueden no responder. No se garantiza encontrar cualquier
personaje, escena o cita. La velocidad del modelo depende del equipo; el streaming
existente no convierte una investigación larga en instantánea.

## Costo obligatorio y servicios existentes

El asistente usa Ollama, embeddinggemma, SQLite, FTS5 y software local; no necesita
tarjetas, cuotas promocionales, facturación por consulta ni proveedores comerciales.
La configuración deja Pinecone desactivado y el recorrido actual no usa Groq.
Books queda apagado salvo activación y confirmación expresa de ausencia de
facturación; no es necesario para las pruebas de funcionamiento gratuitas.

No se puede certificar por código la facturación de TiDB Cloud. Su riesgo económico
se mantiene separado y no se modificó ni migró su base. Tampoco se garantiza que
servicios de correo, pagos u OAuth del resto del sitio carezcan de costos.

Docker Desktop requiere revisar sus condiciones para el contexto de uso. El
buscador puede ejecutarse con Docker Engine u otro entorno compatible sin exigir
una suscripción de Desktop. No se impone VPS ni hosting pago.

Referencias: [SearXNG Docker](https://docs.searxng.org/admin/installation-docker.html),
[Wikipedia](https://www.mediawiki.org/wiki/Wikimedia_APIs/Rate_limits),
[Open Library](https://openlibrary.org/developers/api),
[Docker Desktop](https://docs.docker.com/subscription-billing/desktop-license/),
[Ollama sin nube](https://docs.ollama.com/faq),
[condiciones Google Books](https://developers.google.com/books/terms).

## Verificación reproducible

El verificador offline usa bases temporales; no migra la base del proyecto.
Las pruebas cubren casos conocidos, seguimiento, recuerdos, ambigüedad, fuentes
contradictorias, caídas, límites, caché, extracción y ataques de páginas externas.
Se conservan pruebas del catálogo y funciones existentes. Las comprobaciones
reales de Docker, fuentes y Qwen se registran aparte: un test simulado no prueba
disponibilidad externa ni exactitud universal.

Comandos e inicio están documentados en docs/guides/README_ASISTENTE_IA.md. El diagnóstico
normal no hace conexiones; --live --sin-fuentes prueba únicamente la inferencia
local sin consultar fuentes externas. Nunca imprime credenciales.

## Errores corregidos

- Alias y procedencias se conservan al normalizar la identidad y guardar historial.
- La obra nombrada ahora prevalece sobre la anterior. El prefijo Papelucho no
  identifica automáticamente otro volumen de la colección.
- La evidencia se evalúa por pregunta: sinopsis, personajes, acontecimiento,
  desenlace y cita tienen requisitos distintos.
- El clasificador recibe pistas locales documentadas para reconocer recuerdos
  sin título, incluso cuando el mensaje no contiene la palabra libro.
- Los errores de formato no activan investigaciones innecesarias.
- La auditoría no admite listas de afirmaciones vacías y comprueba todas las
  frases al responder detalles factuales. Se corrigió la confusión entre estado
  de respuesta y cobertura parcial.
- Las comillas simples también se verifican. Una ficha original no certifica
  una cita de la novela, y una variación de mayúsculas del título no es un pasaje.
- Una referencia explícita al recuerdo del lector se distingue de una cita
  certificada de la novela. Debe coincidir con sus palabras, sin ampliarlas ni
  afirmar después que se trata del texto literal de una edición.
- La reparación de una identificación no reenvía citas rechazadas que hacían
  repetir el mismo error al modelo.
- La reconstrucción semántica conserva procedencia, permisos y tipo documental:
  una variable sobrescribía el manifiesto al reconstruir por segunda vez.
- El Compose utiliza un archivo de entorno propio, una imagen fijada y un
  puerto accesible solamente desde el equipo local.

## Archivos de la entrega

Rama: feature/cuotas-ia-chatbot. Sin commits ni push. Las SQLite auxiliares y
reportes JSON permanecen locales, excluidos de Git.

| Grupo | Modificados |
| --- | --- |
| Conversación y evidencia | core/literary_ai.py, core/literary_ai_views.py, core/ai_public_details.py, core/literary_quality.py, core/literary_evidence.py, core/local_llm.py |
| Recuperación y red | core/literary_search.py, core/ai_http.py, core/local_rag.py |
| Preparación y diagnóstico | core/management/commands/indexar_libros.py, core/management/commands/diagnosticar_ia.py, verificar_proyecto.py |
| Configuración | litmate_project/ai_settings.py, .env.example, requirements-ia-pc.txt, docker-compose.ia.yml, searxng/settings.yml, iniciar_buscador.py |
| Documentación y regresiones | docs/guides/README_ASISTENTE_IA.md, core/test_local_ai.py |

| Grupo | Creados |
| --- | --- |
| Identidad e investigación | core/literary_identity.py, core/literary_research.py, core/literary_sources.py |
| Fuentes y conocimiento | core/literary_web.py, core/literary_wikidata.py, core/literary_knowledge.py, core/management/commands/preparar_conocimiento.py |
| Herramientas locales | verificar_investigacion.py, searxng/compose.env |
| Pruebas | core/test_ai_diagnostics_free.py, core/test_literary_identity.py, core/test_literary_knowledge.py, core/test_literary_research.py, core/test_literary_web.py, core/test_research_integration.py, core/test_research_limits.py, core/test_research_runtime.py, core/test_strict_research_quality.py |
| Informe | INFORME_BUSQUEDA_LITERARIA.md |

No se editaron plantillas, CSS, JavaScript, modelos Django ni migraciones. Las
pruebas automatizadas no sustituyen una comprobación manual del micrófono y
las voces en el navegador del usuario.

## Dependencias y estado local

Trafilatura 2.3.1 y Beautiful Soup 4.15.0 quedaron instalados en el entorno virtual
con sus dependencias gratuitas. pip check no detectó incompatibilidades. Continúan
qwen3.5:9b-q4_K_M y embeddinggemma locales.

Docker confirmó litmate-searxng-1 healthy y el inicio verificó su API JSON. Una
extracción real de SM utilizó Trafilatura; Wikipedia recuperó el argumento del
volumen correcto. Un contenedor sano no garantiza que todos sus motores respondan.
Dos búsquedas significa dos consultas lógicas, que pueden usar varios endpoints
gratuitos bajo el mismo plazo. El artículo completo de Wikipedia comparte las
tres lecturas con HTML.

Se prepararon cuatro obras, cinco registros factuales y cuatro fragmentos
semánticos con vectores de 768 dimensiones en las bases auxiliares. Una consulta
real «Un chico protege una flor en un asteroide diminuto» recuperó El principito
mediante embeddinggemma, conservando tipo web y procedencia. La reconstrucción
repetida conserva los metadatos y reutiliza vectores sin cambios.

La colección de novelas data/litmate_rag.sqlite3 sigue sin preparar: no se
disponía de novelas autorizadas para cargar. Las cuatro fichas originales sí
habilitan recuperación semántica real, pero son una colección inicial pequeña.
Para ampliar cobertura hay que aportar textos autorizados o fichas originales
con referencias y permisos; los comandos están en docs/guides/README_ASISTENTE_IA.md.

## Comprobación de costos y decisiones del titular

/chatbot_query/ utiliza literary_ai_views, sin llamar al controlador Groq antiguo
de views.py. Las pruebas comprueban que claves antiguas no activan un proveedor
remoto. Groq permanece instalado para importaciones antiguas; el asistente actual
no lo usa. Pinecone se fuerza desactivado y Ollama rechaza modelos cloud.

diagnosticar_ia sin --live comprueba configuración sin consultar Internet ni abrir
TiDB. Debe mostrar Ollama local y Books apagado. La confirmación administrativa
que permite activar Books no puede certificar el estado económico de una cuenta.
Books no se utilizó para validar esta entrega.

Revisar el plan, consumo y facturación de TiDB requiere acceso del titular a su
cuenta; no se resuelve modificando el código. CACHE_URL puede seleccionar Redis
externo, cuya tarifa depende del servicio; no es obligatorio. Lo mismo aplica a
correo, OAuth y pagos del resto del sitio. Equipo, electricidad e Internet siguen
siendo necesarios, aunque la funcionalidad no exija consumo de API facturable.

## Incidencia de ejecución

Una ejecución auxiliar anterior invocó las pruebas con la configuración TiDB del
proyecto. Alcanzó el intento de crear una base de pruebas y se interrumpió. No se
pudo confirmar si llegó a crearla. No hay evidencia observada de modificación de
filas de producción, pero no se certifica su estado sin revisar el servidor.
No se intentó borrar ninguna base. Las verificaciones posteriores y finales usan
verificar_proyecto.py, SQLite en memoria y almacenamiento auxiliar temporal,
sin cargar credenciales del .env ni conectar TiDB.

## Resultados finales ejecutados

Comprobaciones finales del 19 de octubre de 2026:

| Verificación | Resultado observado |
| --- | --- |
| Python, core y suscripciones | 525 pruebas aprobadas; SQLite aislado; sin incidencias del sistema Django. |
| Chat JavaScript | 194 comprobaciones aprobadas: seguridad, formato, SSE, HTTP, CSRF y voz. |
| Dependencias | pip check: sin incompatibilidades. |
| Cambios | git diff --check: sin errores de espacios. |
| Docker | litmate-searxng-1 healthy; API JSON comprobada. |
| Índice local real | Cuatro fichas indexadas; embeddinggemma recuperó El principito a partir de una descripción semántica diferente. |

Los mensajes de fallo que aparecen en el registro de pruebas son escenarios
simulados de caída, límite o rechazo de calidad. La batería terminó con OK.
Registros locales: [Python](G:/Proyecto/Litmate/reportes/pruebas_python_finales.txt)
y [chat](G:/Proyecto/Litmate/reportes/pruebas_chat_finales.txt).

| Caso | Comprobación real o simulada |
| --- | --- |
| Dime los personajes de Papelucho y el marciano | Real: identificó Diario secreto de Papelucho y el marciano, Marcela Paz, y devolvió Papelucho y Det con la referencia editorial. No afirmó una lista exhaustiva. 0,022 s, sin modelo ni web nuevos. |
| Papelucho → ¿Y sus personajes? → ¿Qué sucede con Det? | Real: mantuvo la obra, reutilizó personajes y recuperó el argumento de Wikipedia para Det. Dos consultas lógicas, unos 5,2 s externos y 32,1 s totales. |
| Niño, planeta pequeño, rosa y zorro | Real con auditoría de todas las frases: El principito, Antoine de Saint-Exupéry. Dos frases revisadas, sin búsqueda web; unos 19 s. |
| Todos los animales son iguales | Real con auditoría reforzada: Rebelión en la granja, George Orwell. La primera respuesta incluía una afirmación no respaldada; fue rechazada, reparada y aprobada después. La salida final parafraseó la idea, sin atribuir cita, página ni traducción exacta. Unos 31,8 s. |
| ¿En qué libro aparece Raskólnikov? | Real con auditoría de todas las frases: Crimen y castigo, Fiódor M. Dostoievski. Sin web, unos 19,2 s. |
| Mujer que viajaba | Real: pidió personaje, escenario o escena concreta, sin inventar una identificación; sin web ni modelo. |
| Recuerdo una escena de un libro, pero no su título | Real después de Papelucho: pidió pistas sin heredar esa obra. 0,006 s, sin web ni modelo. |
| SearXNG desconectado, incorrecto o limitado | Pruebas simuladas ejecutadas: alternativas gratuitas, límites, caché y errores diferenciados. No se detuvo el servicio real para esta simulación. |
| Fuentes contradictorias | Pruebas simuladas ejecutadas: contradicción conservada; la ruta rápida tampoco elige silenciosamente una página contradictoria. |
| Página maliciosa y SSRF | Pruebas simuladas ejecutadas de instrucciones externas, DNS, redirecciones, IP privadas, formatos, tamaños y tiempos. |

Las respuestas y diagnósticos completos están en
[conversación](G:/Proyecto/Litmate/reportes/validacion_final_litmate.json),
[identificaciones auditadas](G:/Proyecto/Litmate/reportes/identificaciones_auditadas_final.json),
[última prueba de la frase](G:/Proyecto/Litmate/reportes/frase_auditada_final.json) y
[personajes y escena](G:/Proyecto/Litmate/reportes/personajes_escena_final.json).
El informe de identificaciones auditadas conserva también el rechazo anterior
de la frase; su corrección y resultado posterior están en la última prueba de
la frase. No se borraron los fallos para presentar solamente éxitos.

Ejemplos de salidas reales finales:

> El libro que buscas es Rebelión en la granja, escrito por George Orwell.

> Basado en tu recuerdo del personaje Raskólnikov, la obra es 'Crimen y castigo'
> de Fiódor M. Dostoievski.

> ¿Recuerdas algún personaje, dónde ocurría la historia o una escena más concreta?

Estas son ejecuciones observadas, no garantías de que un modelo genere siempre
la misma respuesta. La auditoría sigue dependiendo de interpretar correctamente
el respaldo de cada pasaje. Si no consigue validar una respuesta, conserva el
rechazo y reconoce la falta de respaldo; no hay sustitución comercial.

La generación y revisión local tardaron aproximadamente 16–32 segundos en los
casos medidos, y algunas reparaciones anteriores tardaron más. Los quince
segundos son presupuesto de investigación externa, no promesa de latencia total.
El SSE existente publica la respuesta tras validarla: no se añadió transmisión
de borradores no revisados mientras el modelo los genera.

## Inicio y ampliación reproducibles

Abrir PowerShell en G:\Proyecto\Litmate, mantener Ollama y Docker disponibles y
ejecutar:

```powershell
Set-Location -LiteralPath 'G:\Proyecto\Litmate'
.\venv\Scripts\python.exe -m pip install -r requirements-ia-pc.txt
.\venv\Scripts\python.exe iniciar_buscador.py
$env:LITMATE_AI_USE_SEARXNG='True'
$env:LITMATE_USE_GOOGLE_BOOKS_API='False'
.\venv\Scripts\python.exe manage.py preparar_conocimiento --semantico
.\venv\Scripts\python.exe manage.py diagnosticar_ia
.\venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

Los modelos ya están instalados en este equipo. En otro equipo se descargan
con ollama pull qwen3.5:9b-q4_K_M y ollama pull embeddinggemma. No se ejecutan
migraciones para preparar fichas. No cambies USE_SQLITE para iniciar el sitio
habitual: la base existente debe conservar su configuración.

Para repetir las pruebas aisladas:

```powershell
.\venv\Scripts\python.exe -B verificar_proyecto.py core suscripciones
node verificar_chat_seguro.js
.\venv\Scripts\python.exe -B verificar_investigacion.py --live --web --message 'Papelucho y el marciano' --message '¿Y sus personajes cuáles son?' --message '¿Qué sucede con Det?' --output reportes/prueba_contexto.json
```

La ampliación de la colección requiere material autorizado; no requiere nuevas
claves comerciales. docs/guides/README_ASISTENTE_IA.md explica --metadatos e indexar_libros.
Queda pendiente comprobar manualmente voz, micrófono y avatares en el navegador
del usuario, revisar la cuenta de TiDB y decidir qué documentos autorizados
añadir. No se impone contratar servicios externos para continuar.
