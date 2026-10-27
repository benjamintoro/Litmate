# Fuentes bibliográficas, permisos y costo obligatorio de API

Fecha de revisión: **27 de octubre de 2026**, America/Santiago.

Este documento registra una investigación de documentación primaria. **Revisar
una fuente no significa haber implementado o probado su conector.** Los ensayos
de importación y las cantidades realmente incorporadas se documentan por
separado en el informe principal. No se crearon cuentas, claves, suscripciones,
compras, métodos de pago ni servicios obligatorios durante esta revisión.

## Estado y clasificación

| Fuente | Acceso documentado | Uso admisible en LitMate | Estado de esta revisión |
| --- | --- | --- | --- |
| Open Library | API oficial para búsquedas humanas; volcados TSV mensuales para adquisición masiva | Metadatos mínimos, autores, obras, ediciones e identificadores; no asumir permiso general para sinopsis/biografías | Adaptador existente reutilizado; nuevo importador local streaming probado offline |
| Wikidata | API oficial y volcados; datos estructurados CC0 | Entidades y declaraciones con procedencia; pertenecer a una obra no prueba un rol narrativo | Adaptador existente reutilizado; no se descargó el volcado completo |
| Wikipedia | API oficial y exportaciones Wikimedia | Fragmentos autorizados con revisión, atribución y licencia; no son el texto original de la novela | Adaptador existente conservado |
| Project Gutenberg | Catálogo oficial y mecanismos de descarga autorizados | Metadatos del catálogo; texto completo sólo tras validar obra, edición, traducción y jurisdicción | Implementación/importación de esta etapa: consultar informe principal |
| BNE | Suministro oficial MARCXML/MARC, OAI-PMH, SRU y datos enlazados | Metadatos del catálogo CC0; no implica licencia de novelas o digitalizaciones | Nuevo lector local MARCXML probado con fixtures; no afirmar importación real BNE |
| Google Books | API oficial opcional | Consulta/visualización conforme a sus términos; no corpus permanente general ni descarga de vistas previas | Conector previo; no se habilitaron facturación ni nuevas credenciales |
| Library of Congress | API JSON/YAML y otros servicios oficiales | Metadatos; texto completo/OCR sólo para ítems con derechos compatibles | Evaluada; no se añadió conector en esta tarea documental |
| Crossref | API REST pública sin registro; servicio Plus separado y de pago | Metadatos académicos/DOI; verificar derechos de abstracts y texto enlazado | Evaluada; candidata futura opcional |
| OpenAlex | API con presupuesto gratuito y precios por uso; snapshot público gratuito | Preferir datos nativos CC0 descargados con límites; no depender de cupos API | Evaluada; no habilitada ni convertida en dependencia |
| Gutendex | API JSON de catálogo; código autohospedable | Descubrimiento de metadatos Gutenberg; no concede derechos del texto | Evaluada; no requiere desplegar otro servicio para la importación actual |
| Wikisource | API MediaWiki y exportaciones oficiales | Texto completo por edición/licencia; conservar prueba editorial, revisión y atribución | Candidata futura prioritaria; no conector nuevo en esta revisión |
| Standard Ebooks | Libros individuales y repositorios oficiales; descargas masivas con acceso específico | Ediciones seleccionadas y permisos verificados; no evadir el acceso a bulk | Evaluada; no incorporada como requisito gratuito |
| Biblioteca Virtual Miguel de Cervantes | Sitio público y condiciones específicas | Consulta/enlace; almacenamiento de corpus sólo con autorización compatible de la edición | No apta para importación automatizada masiva por defecto |
| Memoria Chilena | Fichas y documentos con situaciones de derechos diferentes | Consulta/enlace; texto completo únicamente cuando la ficha y la edición lo permitan | No se validó una API de adquisición masiva; no se habilitó crawler |
| Fandom | Licencias por comunidad y condiciones de acceso automatizado | Descubrimiento de enlaces; extracción sólo con mecanismo expresamente autorizado | No añadir scraping/API de comunidades indiscriminadamente |

## Fuentes ya utilizadas y separación de derechos

Open Library solicita no adquirir grandes colecciones mediante millones de
llamadas: las búsquedas API deben ayudar a usuarios, y el bulk debe usar sus
volcados. Documenta 1 solicitud/s sin identificación y 3/s con identificación
apropiada; no se debe inventar un correo de contacto. Su declaración general
de licencia no elimina derechos particulares. El importador conserva hechos
bibliográficos mínimos y excluye biografías y descripciones narrativas.
[API y límites](https://openlibrary.org/developers/api),
[formato de volcados](https://openlibrary.org/developers/dumps),
[licencias](https://openlibrary.org/developers/licensing).

Los datos estructurados de Wikidata son CC0. La BNE declara CC0 para su
catálogo y ofrece suministros oficiales. Ninguna de esas afirmaciones concede
por sí sola permiso para copiar la novela, las ilustraciones o una traducción.
El lector BNE no convierte el número MARC001 en una URL imaginada: exige un URI
explícito del registro para proyectar una fuente navegable a la memoria.
[Licencia Wikidata](https://www.wikidata.org/wiki/Wikidata:Licensing),
[suministro BNE](https://www.bne.es/es/perfiles/bibliotecarios/suministro-registros),
[datos enlazados BNE](https://www.bne.es/es/catalogos/datos-enlazados-bne).

## Google Books

La documentación exige identificación mediante clave API u OAuth para las
solicitudes públicas. Ofrece título, autor, ISBN, editor y enlaces; las vistas
previas dependen también de territorio y derechos. No se verificó en las páginas
consultadas una cuota numérica universal ni un compromiso de disponibilidad
ilimitada: debe comprobarse la cuota real del proyecto, sin activar facturación.
Si falta clave o cuota, la fuente debe quedar opcional y fallar de forma cerrada.
[Uso de la API](https://developers.google.com/books/docs/v1/using).

Google advierte que licencia parte de sus datos; no son una licencia abierta
general de almacenamiento. Además, los términos específicos de Books incluyen
una restricción para cobrar por la aplicación sin acuerdo o permiso de Google,
relevante si LitMate activa suscripciones. No se presume resuelta esa condición.
No se estableció aquí una supuesta regla universal de caché de 30 días.
[Descripción del servicio](https://developers.google.com/books/docs/overview),
[términos Books](https://developers.google.com/books/terms),
[términos generales de APIs](https://developers.google.com/terms).

## Library of Congress

La API JSON/YAML es pública y no exige clave. El límite documentado es **20
solicitudes/minuto**; superarlo puede bloquear durante una hora. Bajo carga puede
haber 429 o CAPTCHA incluso por debajo del límite. Un conector futuro debe usar
cola serial, caché, pausas y detención ante CAPTCHA, sin reintentos agresivos.
[API oficial](https://www.loc.gov/apis/),
[límites actuales](https://www.loc.gov/apis/json-and-yaml/working-within-limits/).

La presencia de un libro u OCR en loc.gov no autoriza toda reutilización. Hay
que conservar `Rights and Access`/`Rights Advisory` y resolver los derechos del
ítem concreto; los trabajos del gobierno y las colecciones de terceros no deben
tratarse como una sola licencia.
[Guía oficial sobre reutilización](https://www.loc.gov/legal/security-copyright-and-privacy/understanding-copyright/).

## Crossref

Su REST API pública no exige registro. Aporta DOI, autoría y metadatos útiles
para crítica, historia y teoría literarias; ciertos abstracts pueden conservar
derechos de autores/editoriales. Un DOI tampoco autoriza descargar el artículo.
El servicio Metadata Plus es separado y no es necesario para comenzar.
[REST API y derechos de metadatos](https://www.crossref.org/documentation/retrieve-metadata/rest-api/).

La actualización oficial del **21 de julio de 2026** distingue consultas de
listas y registros individuales: listas a 1/s en el pool público y 3/s en el
polite; registros individuales a 5/s y 10/s respectivamente. Deben prevalecer
las cabeceras de tasa/concurrencia y la respuesta 429. Un contacto para el pool
polite debe ser real y proporcionado por el responsable, no inferido de usuarios.
[Actualización 2026](https://community.crossref.org/t/refining-rest-api-limits-for-improved-stability-and-reliability/16137),
[acceso y autenticación](https://www.crossref.org/documentation/retrieve-metadata/rest-api/access-and-authentication/).

## OpenAlex: cambio de condiciones en 2026

**No debe describirse actualmente como API sin límites ni precios por uso.** Las
páginas vigentes distinguen uso anónimo básico de una clave gratuita con correo
verificado: la clave permite más presupuesto y paginación con cursor. La cuenta
gratuita incluye **USD 1/día de uso sin método de pago**; anónimamente son USD
0,10/día. Es presupuesto de consumo, no dinero que LitMate reciba.
[Autenticación vigente](https://help.openalex.org/api/authentication/),
[planes y prepago](https://help.openalex.org/access/pricing/).

La tabla actual indica: búsquedas USD 1/1000 llamadas, listas/filtros USD
0,10/1000, descarga PDF USD 10/1000; los registros individuales son gratuitos.
El reranking añade consumo. No se habilitan compras, planes ni prepago; la ruta
de chat no dependerá de esta cuota. Las notas antiguas sobre claves deben
contrastarse con la documentación actual.
[Ejemplos de costos, actualizados el 23-10-2026](https://help.openalex.org/access/example-costs/).

Los metadatos nativos siguen abiertos CC0. La documentación de sincronización,
actualizada el 26-10-2026, indica snapshots públicos **trimestrales** y snapshots
diarios en planes de pago. Un subconjunto local futuro es viable si se justifica
tamaño y utilidad; no se descargó el corpus completo ni se activó sincronización
pagada. La licencia de metadatos no equivale a la de PDFs enlazados.
[Snapshot](https://help.openalex.org/access/snapshot/),
[cadencia y sincronización](https://help.openalex.org/access/sync/).

## Gutendex

La API sirve catálogo Gutenberg en JSON y permite filtros por idioma, autor y
materia. Su autor pide **autohospedar para uso a largo plazo**; la instancia
pública no debe ser una dependencia permanente. El software tiene licencia MIT,
distinta de los derechos de obras o traducciones. `copyright=false` describe
dominio público en Estados Unidos, no una verificación de Chile. El catálogo
local Gutenberg evita hoy mantener otro Django/servicio sólo para estos datos.
[Documentación oficial](https://gutendex.com/),
[repositorio y licencia](https://github.com/garethbjohnson/gutendex).

## Wikisource y exportaciones Wikimedia

Ofrece API MediaWiki y textos con licencia o dominio público especificados por
obra. Deben verificarse también traducción, edición, autoría de aportes y
atribución; la política inglesa explica su referencia territorial estadounidense.
Es una fuente de textos primarios, distinta de la explicación enciclopédica de
Wikipedia.
[Política española](https://es.wikisource.org/wiki/Wikisource:Derechos_de_autor),
[política inglesa](https://en.wikisource.org/wiki/Wikisource:Copyright_policy).

El acceso debe identificar el cliente, agrupar lecturas, respetar límites/backoff
y utilizar `maxlag` en tareas diferidas. **La página oficial de descargas avisa
que los volcados XML heredados serán retirados en enero de 2027 y recomienda
MediaWiki Content File Exports**. Un nuevo importador no debe quedar atado sólo
a XML mensual. Las descargas exigen User-Agent y se limitan a tres conexiones/IP.
[Etiqueta API](https://www.mediawiki.org/wiki/API:Etiquette),
[aviso y exportaciones oficiales](https://dumps.wikimedia.org/backup-index.html).

## Standard Ebooks

La política del proyecto dedica sus aportes a los ebooks mediante CC0; se debe
comprobar además el texto original/traducción y la jurisdicción aplicable. Los
repositorios individuales oficiales permiten identificar edición y cambios.
No se interpreta la licencia de un repositorio de herramientas como licencia
de todos los contenidos.
[Política de dominio público](https://standardebooks.org/about/standard-ebooks-and-the-public-domain),
[ejemplo de repositorio oficial de edición](https://github.com/standardebooks/jane-austen_pride-and-prejudice).

La página oficial de acceso identifica las descargas masivas y feeds como
beneficios del Patrons Circle. No son un requisito compatible con la decisión
de no pagar. Las consultas directas del sitio fallaron por timeout o formato
XHTML en esta revisión; las afirmaciones anteriores se contrastaron con páginas
oficiales indexadas y el repositorio, no con una descarga masiva exitosa.
[Acceso oficial a bulk](https://standardebooks.org/sessions/new?redirect=%2Fbulk-downloads%2Fcollections).

## Cervantes Virtual y Memoria Chilena

El marco legal de Cervantes Virtual distingue obras en dominio público,
aportaciones/ediciones digitales y obras cuyo permiso fue concedido al portal.
Su autorización de copia personal no equivale a publicar un corpus de LitMate.
Sin permiso compatible por edición, limitarse a enlaces/consulta; no crear un
crawler masivo suponiendo una licencia global.
[Marco legal del portal](https://www.cervantesvirtual.com/marco-legal/).

Memoria Chilena diferencia patrimonio cultural común de materiales protegidos
cuya difusión se autorizó al portal. La ficha puede indicar propiedad intelectual
en sus clasificaciones; la ausencia de ese campo no constituye permiso. No se
validó aquí una API de adquisición masiva. Es valiosa para literatura chilena,
pero exige revisar derechos de cada documento y sus traducciones/ediciones.
[Preguntas frecuentes y derechos](https://www.memoriachilena.gob.cl/602/w3-article-123838.html).

## Fandom

La página de licencias señala CC BY-SA 3.0 para muchos textos, con excepciones
por comunidad; imágenes, discusiones y chats no comparten necesariamente esa
licencia. También deben conservarse atribución, versión y alcance de la obra
para no confundir adaptaciones o universos.
[Licencias oficiales](https://www.fandom.com/licensing).

La versión de términos publicada como **2025-10-13**, consultada mediante su
índice, restringe robots/scraping sin permiso escrito. El endpoint directo actual
de términos/licencias devolvió 403 en la comprobación HTTP; no se afirma haber
verificado una excepción API vigente que autorice el uso propuesto. Por tanto,
no automatizar extracción ni asumir que tener una API MediaWiki resuelve las
condiciones de acceso. Se pueden descubrir enlaces para el lector sin evadir
bloqueos ni copiar contenido.
[Versión identificada de términos](https://www.fandom.com/terms-of-use-2025-10-13).

## Próximos conectores con valor real

Estas prioridades son una decisión de ingeniería derivada de la revisión,
todavía no mejoras medidas:

1. **Wikisource por ediciones seleccionadas en español:** añade textos primarios
   y traducciones identificadas, complementando catálogo y Wikipedia. Reutilizar
   el manifiesto de derechos, almacenamiento local y trazabilidad existentes;
   probar capítulos, OCR y atribución antes de ampliar.
2. **BNE real mediante una muestra oficial MARCXML:** el lector ya está probado
   offline. Aporta autoridades y ediciones españolas; verificar formato actual
   y URI explícitos antes de considerar la importación validada con servicio real.
3. **Crossref opcional para consultas académicas:** amplía crítica/historia con
   DOI sin exigir tarjeta. Aporta más que otra copia del catálogo de novelas,
   pero no debe presentarse como fuente de escenas o personajes.
4. **LOC para colecciones concretas:** útil para historia y documentación; su
   límite de 20/min aconseja adquisición diferida y selección de colecciones,
   no incorporarlo al camino crítico de cada mensaje.

Gutendex autohospedado duplicaría inicialmente datos que ya se adquieren del
catálogo Gutenberg. OpenAlex añade costos por uso si se excede presupuesto y
una gran infraestructura si se replica todo; no es prioridad. Fandom, Cervantes
Virtual y Memoria Chilena necesitan condiciones/ediciones específicas antes
de una importación automatizada. Ninguna fuente evaluada se vuelve obligatoria.

## Comprobación operativa de costo obligatorio cero

- Ejecutar importaciones de volcados/locales con las herramientas gratuitas
  existentes; no activar cuentas de cobro ni solicitudes de aumento pagado.
- Mantener Google Books opcional; no introducir la cuota gratuita de OpenAlex
  como requisito de funcionamiento normal.
- Conservar Ollama/modelos locales y los índices locales; documentar electricidad,
  disco y hardware como recursos propios, separados de facturación de API.
- Frente a 429, falta de clave o fuente caída, usar evidencia local o reconocer
  el límite. No cambiar automáticamente a un proveedor de pago.
- Las páginas oficiales se revisaron como documentación. No se efectuaron
  pruebas de extremo a extremo de los conectores todavía no implementados,
  ni se considera autorización una página pública o un `robots.txt` permisivo.
