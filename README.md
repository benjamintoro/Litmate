# LitMate

### Plataforma Web Inteligente de Descubrimiento Literario

**Proyecto de Título — Ingeniería en Informática | INACAP**

LitMate es una plataforma web de descubrimiento y recomendación literaria que integra inteligencia artificial, recuperación de información bibliográfica y procesamiento de lenguaje natural para ayudar a los lectores a encontrar libros de una manera más intuitiva.

Su principal característica es la capacidad de **identificar obras literarias a partir de recuerdos incompletos, descripciones imprecisas de argumentos, personajes o situaciones narrativas**, sin exigir que el usuario conozca el título, el autor o el ISBN.

A diferencia de un buscador tradicional, LitMate permite mantener una conversación contextual, explorar obras relacionadas, consultar información bibliográfica y recibir recomendaciones adaptadas a las preferencias expresadas.

El proyecto utiliza Django, MySQL, Ollama, modelos de lenguaje locales, un sistema de recuperación aumentada por generación (RAG) y múltiples fuentes bibliográficas.

---

## 1. Objetivo del proyecto

Desarrollar una plataforma web inteligente que facilite el descubrimiento de libros mediante consultas en lenguaje natural, recuperación semántica y recomendaciones literarias contextualizadas.

LitMate busca resolver tres problemas principales:

- **Búsqueda por recuerdos imprecisos:** permitir encontrar una obra aunque el lector solo recuerde fragmentos de su historia.
- **Descubrimiento y recomendación:** ofrecer alternativas literarias relacionadas con las preferencias y consultas del usuario.
- **Exploración bibliográfica:** reunir información sobre libros, autores, personajes y opciones de adquisición en una interfaz accesible.

La plataforma se desarrolla como proyecto académico y prototipo funcional. Algunas funcionalidades comerciales y de suscripción permanecen en etapas de integración o validación.

---

## 2. Funcionalidades principales

### Identificación de libros mediante inteligencia artificial

LitMate interpreta descripciones de obras escritas en lenguaje natural.

Por ejemplo:

> «Recuerdo un libro donde un niño vive en un planeta pequeño y cuida una rosa».

El sistema analiza las pistas proporcionadas e intenta recuperar la obra correspondiente utilizando los datos bibliográficos disponibles.

La identificación no depende exclusivamente de coincidencias exactas con el título o el autor.

### Asistente literario conversacional

El usuario puede conversar con LitMate para:

- Identificar libros.
- Consultar argumentos y sinopsis.
- Obtener información sobre autores y personajes.
- Explorar géneros literarios.
- Solicitar recomendaciones.
- Investigar obras relacionadas.
- Formular preguntas de seguimiento.

El asistente está diseñado para comunicar incertidumbre cuando la información disponible no permite confirmar una respuesta.

### Memoria y continuidad conversacional

LitMate conserva el contexto necesario para interpretar referencias a elementos mencionados anteriormente.

Por ejemplo:

1. El usuario solicita dos recomendaciones de fantasía.
2. LitMate presenta las obras.
3. El usuario pregunta: «Cuéntame más del segundo».
4. El asistente interpreta la referencia a la segunda recomendación.

Esta capacidad permite interacciones más naturales que una búsqueda independiente por cada mensaje.

### Recuperación bibliográfica y RAG

La plataforma combina información estructurada y recuperación semántica para respaldar las respuestas.

Integra mecanismos de:

- Consulta de registros bibliográficos locales.
- Recuperación de información relacionada.
- Enriquecimiento de metadatos.
- Investigación en fuentes externas cuando corresponde.
- Reutilización de información previamente recuperada.
- Generación contextual mediante modelos de lenguaje.

Las respuestas pueden variar según la disponibilidad y calidad de las fuentes.

### Recomendaciones literarias

El asistente puede sugerir obras relacionadas con determinados géneros, argumentos, autores y preferencias.

Las recomendaciones se presentan mediante componentes visuales que pueden incluir:

- Título y autor.
- Portada.
- Descripción bibliográfica.
- Información contextual.
- Enlaces externos disponibles.

La pertinencia de las recomendaciones depende de la cobertura del catálogo y de la información recuperada.

### Interfaz web

LitMate dispone de una interfaz web con navegación entre las secciones implementadas y un chat interactivo.

Incluye una identidad visual propia, avatar, tarjetas bibliográficas y estados de progreso durante determinadas consultas.

El sitio completo ha sido probado desde un navegador móvil mediante acceso HTTPS externo.

---

## 3. Estado del proyecto

**Fecha de referencia: 31 de octubre de 2026.**

| Funcionalidad | Estado |
|---|---|
| Sitio web y navegación | Publicado y probado externamente |
| Asistente literario | Funcional y probado |
| Consultas mediante HTTP/SSE | Funcionales y probadas |
| Identificación por recuerdos difusos | Funcional, con mejoras adicionales evaluadas por separado |
| Continuidad conversacional | Funcional en los escenarios verificados |
| Recomendaciones literarias | Implementadas |
| Tarjetas y portadas bibliográficas | Funcionales |
| Recuperación bibliográfica local | Implementada |
| Integración con fuentes externas | Implementada parcialmente según el proveedor |
| Publicación HTTPS mediante Tailscale Funnel | Probada desde datos móviles |
| Últimas 99 pruebas focalizadas | Aprobadas en una versión de trabajo separada |
| Sistema de cuentas y cuotas | Integrado, publicado y aceptado desde teléfono con datos móviles el8/11/2026 |
| Mejoras adicionales del chat móvil | Desarrolladas en versión separada |
| Cobros reales de suscripciones | No habilitados |

**Importante:** los resultados de las pruebas aisladas no implican automáticamente que todos los cambios estén incorporados a la instancia pública.

---

## 4. Tecnologías utilizadas

### Backend

- **Python:** lenguaje principal de desarrollo.
- **Django:** framework web y lógica de aplicación.
- **MySQL:** persistencia relacional y catálogo bibliográfico.
- **SQLite:** almacenamiento auxiliar o entornos de pruebas, según la configuración.

### Inteligencia artificial

- **Ollama:** ejecución local de modelos de lenguaje.
- **Qwen:** familia de modelos utilizada para tareas de generación.
- **RAG:** recuperación de información para contextualizar respuestas.
- **Recuperación híbrida:** combinación de búsqueda estructurada, fuentes bibliográficas y mecanismos semánticos.

### Fuentes bibliográficas e investigación

- Google Books.
- Open Library.
- Wikidata.
- Project Gutenberg.
- SearXNG.

La utilización de cada proveedor depende del tipo de consulta, la conectividad y las restricciones de sus servicios.

### Frontend

- HTML.
- CSS.
- JavaScript.
- Plantillas Django.
- Fetch API y mecanismos HTTP/SSE para la comunicación del chat.

### Infraestructura y herramientas

- **Waitress:** servidor WSGI para el entorno Windows de demostración.
- **WhiteNoise:** servicio de archivos estáticos.
- **Docker:** ejecución de servicios auxiliares.
- **Tailscale Funnel:** publicación HTTPS de la aplicación web.
- **Git y GitHub:** control de versiones y colaboración.
- **Visual Studio Code:** entorno de desarrollo.

---

## 5. Arquitectura general

LitMate utiliza una arquitectura web organizada en componentes.

**Capa de presentación:** interfaz del navegador, navegación, chat, tarjetas y recursos visuales.

**Capa de aplicación:** Django administra solicitudes HTTP, sesiones, reglas de negocio y coordinación de servicios.

**Capa de inteligencia literaria:** interpreta consultas, identifica pistas, recupera información y construye respuestas contextualizadas.

**Capa de persistencia:** conserva información bibliográfica y otros datos de aplicación mediante los almacenes configurados.

**Capa de integración:** conecta los servicios locales con proveedores bibliográficos externos.

**Capa de despliegue:** Waitress ejecuta Django y Tailscale Funnel proporciona acceso HTTPS a la instancia de demostración.

### Flujo simplificado de una consulta

1. El lector envía una pregunta desde el navegador.
2. Django recibe y procesa la solicitud.
3. El sistema identifica la intención y el contexto conversacional.
4. Se consultan los recursos bibliográficos pertinentes.
5. Cuando corresponde, Ollama genera una respuesta utilizando el contexto recuperado.
6. La respuesta y sus elementos complementarios se presentan al usuario.

No todas las consultas necesitan ejecutar el modelo generativo: algunas pueden resolverse con información estructurada ya disponible.

---

## 6. Requisitos para ejecución local

El entorno principal de desarrollo utiliza Windows.

Componentes necesarios, según las funciones que se deseen ejecutar:

- Python y dependencias del proyecto.
- Entorno virtual de Python.
- MySQL local.
- Ollama y el modelo configurado.
- Docker Desktop para los servicios que lo requieran.
- Node.js para determinadas pruebas del frontend.
- Conexión a Internet para las integraciones externas.

El funcionamiento y el rendimiento dependen de los recursos de hardware disponibles.

La aplicación puede responder a determinadas consultas utilizando información local, pero las investigaciones externas requieren conectividad.

---

## 7. Ejecutar LitMate en Windows

### 7.1. Preparar el entorno

Desde la raíz del repositorio:

```powershell
cd G:\Proyecto\Litmate
```

La ruta anterior corresponde al entorno de desarrollo original. Debe adaptarse si el repositorio se encuentra en otro directorio.

Activar el entorno virtual existente:

```powershell
.\venv\Scripts\Activate.ps1
```

Las dependencias Python se mantienen en `requirements.txt` y en los archivos de compatibilidad correspondientes.

Si se prepara una instalación nueva, debe seguirse la documentación técnica del repositorio antes de configurar MySQL, Ollama y los demás servicios.

### 7.2. Iniciar el entorno local de desarrollo

Con MySQL configurado:

```powershell
.\venv\Scripts\python.exe -B iniciar_mysql_local.py --http-desarrollo
```

Para ejecutar con la opción bibliográfica utilizada en determinadas pruebas:

```powershell
.\venv\Scripts\python.exe -B iniciar_mysql_local.py --http-desarrollo --google-books-sin-facturacion
```

El lanzador solicita la contraseña local de MySQL de forma oculta.

Este procedimiento selecciona la configuración local correspondiente al proceso iniciado. No implica una sincronización automática entre motores de bases de datos ni una migración de datos.

La aplicación puede abrirse desde el navegador en la dirección local indicada por el servidor, normalmente:

`http://127.0.0.1:8000/chat/`

**Nota:** para que todas las funciones estén disponibles deben estar activos los servicios de los que dependen, como MySQL, Ollama y los componentes auxiliares correspondientes.

---

## 8. Servidor de demostración HTTPS

LitMate dispone de un perfil específico para su demostración mediante HTTPS.

La arquitectura utilizada para las pruebas externas comprende:

- Django con `DEBUG=False`.
- Waitress ejecutándose en una interfaz local.
- WhiteNoise para archivos estáticos.
- Autenticación de demostración.
- Tailscale Funnel como punto de acceso HTTPS público.

El proceso web escucha localmente, mientras que el túnel publica únicamente el servicio autorizado.

### Inicio del servidor de demostración

El proyecto dispone del lanzador:

```powershell
.\venv\Scripts\python.exe -B iniciar_demo.py
```

Las opciones de despliegue se encuentran documentadas en los procedimientos técnicos correspondientes.

Para el perfil HTTPS verificado se utilizó el puerto local `8003`, con una configuración específica de seguridad, almacenamiento y autenticación.

La publicación no se activa automáticamente por iniciar Waitress. Se requiere configurar y autorizar Tailscale Funnel por separado.

### Condiciones de funcionamiento

La demostración remota depende de:

- Un equipo anfitrión encendido.
- Conectividad a Internet.
- Servidor de aplicación activo.
- Servicios locales necesarios disponibles.
- Túnel HTTPS operativo.

La URL pública de demostración puede ser temporal y no constituye un servicio de alojamiento permanente ni una garantía de disponibilidad continua.

Por seguridad, las contraseñas, configuraciones privadas y credenciales de acceso no se incluyen en este README.

---

## 9. Pruebas y aseguramiento de calidad

El proyecto dispone de pruebas automatizadas y comprobaciones de integración para diferentes componentes.

### Verificación general de Python

```powershell
.\venv\Scripts\python.exe -B verificar_proyecto.py
```

### Verificación del chat

```powershell
node verificar_chat_seguro.js
```

Las pruebas aisladas pueden utilizar SQLite temporal y proveedores simulados o deshabilitados, según el escenario.

MySQL, Ollama, Docker/SearXNG y los servicios externos requieren verificaciones adicionales cuando intervienen en un caso de prueba.

### Resultados registrados durante octubre de 2026

Se informaron, entre otras, las siguientes comprobaciones:

| Evaluación | Resultado |
|---|---|
| Pruebas Django de estabilización | 210 aprobadas |
| Comprobaciones del chat | 246 aprobadas |
| Casos de reintento | 4 aprobados |
| Conversación HTTP/SSE de diez turnos | Respuestas entre 0,13 y 3,15 segundos |
| Seguimiento «Cuéntame más del segundo» | Respuesta correcta en 0,35 segundos en el caso evaluado |
| Recuperación de una obra previamente investigada sin Internet | 0,62 segundos en el caso evaluado |
| Batería focalizada de identificación literaria | 99 pruebas aprobadas en versión separada |

Estos resultados corresponden a conjuntos y entornos de prueba específicos.

No deben interpretarse como garantías universales de precisión, disponibilidad, tiempo de respuesta o ausencia de errores.

Los informes técnicos y registros de evaluación se conservan en la documentación interna del proyecto.

---

## 10. Cuentas, planes y suscripciones

LitMate contempla un modelo de acceso basado en usuarios y planes de utilización.

El desarrollo incluye funciones para:

- Registro y autenticación.
- Administración de sesiones.
- Selección de planes.
- Acceso gratuito.
- Límites de consultas.
- Control de consumo diario.
- Restricciones de uso según el plan.

El perfil de aplicación `litmate_project.reader_settings` integra cuentas,
sesiones persistentes, cuotas atómicas y control de solicitudes concurrentes.
Se selecciona con `iniciar_demo.py --cuentas-db`; el lanzamiento sin esa opción
conserva la demostración anterior de sólo lectura.

**Estado actual (8 de noviembre de 2026):** registro, login → Planes, Gratuito sin
tarjeta, invitado una consulta y cuotas 15/100/ilimitadas están integrados y
validados localmente. Favoritos, listas privadas y edición del perfil están
integrados. El almacén definitivo `data/accounts/users.sqlite3` ya fue creado
con autorización: conserva 179 usuarios, 231 favoritos, listas e historiales,
con respaldo/restauración y reapertura verificados. MySQL permanece de sólo lectura.
Este perfil está publicado y fue aceptado desde datos móviles el8/11/2026.
No se han habilitado pagos ni entregas de correo.
No ejecutar migraciones sobre el catálogo para activar este perfil.

Procedimiento, respaldo/restauración y verificaciones actuales:
[Avance funcional y estado de despliegue](reports/avance_20261108/README.md).
Los datos de prueba nunca deben promoverse al almacén definitivo.

### Pagos

La plataforma contempla planes de suscripción pagados, pero **los cobros reales no se encuentran habilitados**.

No se debe considerar operativa una contratación hasta contar con integración segura, confirmación del proveedor de pagos y validación de sus estados.

El plan gratuito está diseñado para no requerir información bancaria.

---

## 11. Diseño y compatibilidad móvil

LitMate utiliza una interfaz web adaptable que permite navegar por sus secciones desde dispositivos de escritorio y móviles.

La navegación y el chat de la versión publicada fueron probados desde un teléfono mediante una conexión de datos móviles externa.

Adicionalmente, se desarrollaron mejoras específicas para adaptar la experiencia del chat a pantallas pequeñas, incluyendo la distribución de mensajes, controles y elementos bibliográficos.

La publicación de estas mejoras adicionales debe verificarse por separado.

---

## 12. Seguridad

El proyecto incorpora medidas de protección en el entorno de demostración:

- Ejecución de Django con depuración desactivada.
- Autenticación de acceso a la demostración.
- HTTPS mediante Tailscale Funnel.
- Restricción del servidor web a la interfaz local.
- Separación entre el servicio público y las dependencias internas.
- Configuración específica para proteger los datos bibliográficos originales.
- Manejo privado de credenciales.

Los puertos internos de MySQL, Ollama y SearXNG no forman parte de la publicación HTTPS de LitMate.

Estas medidas reducen la superficie de exposición, pero no equivalen a una auditoría integral de seguridad ni a una certificación de producción.

### Buenas prácticas

- No publicar archivos `.env`.
- No subir contraseñas ni tokens al repositorio.
- No incluir bases de datos privadas en commits.
- No compartir credenciales de administración.
- Mantener separados desarrollo, pruebas y demostración.
- Verificar los cambios antes de desplegarlos.
- Conservar respaldos de información importante.

---

## 13. Estructura del repositorio

El proyecto se organiza en directorios y archivos destinados a diferentes responsabilidades.

| Elemento | Descripción |
|---|---|
| `core/` | Lógica principal y servicios de la aplicación |
| `litmate_project/` | Configuración del proyecto Django |
| `templates/` | Plantillas de la interfaz web |
| `static/` | Recursos estáticos |
| `searxng/` | Configuración de servicios de búsqueda relacionados |
| `scripts/` | Herramientas de ejecución, mantenimiento y demostración |
| `docs/` | Documentación técnica |
| `reports/` | Resultados de pruebas e informes técnicos |
| `backups/` | Respaldos locales |
| `requirements.txt` | Dependencias principales de Python |
| `iniciar_mysql_local.py` | Lanzador del entorno local |
| `iniciar_demo.py` | Lanzador del entorno de demostración |
| `verificar_proyecto.py` | Comprobaciones automatizadas del proyecto |

La estructura puede evolucionar durante el desarrollo. Algunos directorios locales contienen datos o artefactos que no deben incorporarse al repositorio público.

---

## 14. Limitaciones conocidas

LitMate es un proyecto académico con una implementación funcional y mejoras continuas.

Entre sus limitaciones actuales se encuentran:

- Cobertura bibliográfica desigual según la obra, el autor y la fuente.
- Posibles errores en la identificación de libros a partir de pistas ambiguas.
- Información incompleta sobre determinados personajes o argumentos.
- Variaciones en el tiempo de respuesta de las consultas complejas.
- Dependencia de Ollama y del hardware anfitrión para ciertas operaciones.
- Dependencia de Internet para investigaciones externas.
- Disponibilidad limitada por la infraestructura utilizada en la demostración.
- Integraciones comerciales y cobros reales todavía no habilitados.
- Cobros y correo reales pendientes de proveedores autorizados; cuentas y cuotas ya validadas públicamente.

Las respuestas generadas mediante inteligencia artificial deben interpretarse como asistencia informativa y no como una fuente infalible.

---

## 15. Próximas etapas

Las siguientes actividades forman parte de la evolución del proyecto:

1. Integración final de las mejoras de cuentas y cuotas en la aplicación pública.
2. Validación adicional del diseño móvil.
3. Ampliación de la cobertura de obras, autores y personajes.
4. Mejora de la precisión de búsqueda mediante recuerdos ambiguos.
5. Optimización de consultas con mayor costo de inferencia.
6. Evaluación sistemática de precisión, latencia y disponibilidad.
7. Integración de pagos mediante proveedores autorizados, si se decide habilitar la comercialización.
8. Evaluación de infraestructura de despliegue con mayor disponibilidad.
9. Ampliación de documentación técnica y manuales de usuario.

---

## 16. Documentación

La documentación del proyecto incluye:

- Manual de usuario.
- Guías de configuración y ejecución.
- Documentación de MySQL y persistencia bibliográfica.
- Arquitectura y servicios de inteligencia artificial.
- Informes de pruebas.
- Registros de evolución y continuidad del desarrollo.
- Procedimientos de publicación HTTPS.
- Evidencias de funcionamiento del prototipo.

Los directorios `docs/` y `reports/` contienen documentación y registros técnicos, cuando se encuentran incluidos en la copia del repositorio.

Las guías históricas deben interpretarse de acuerdo con su fecha y versión. No se recomienda reutilizar instrucciones antiguas sin comprobar su compatibilidad con el código actual.

---

## 17. Contexto académico

**LitMate: Plataforma Web Inteligente de Descubrimiento Literario** se desarrolla como Proyecto de Título en INACAP, en el área de Informática y Telecomunicaciones.

El proyecto aplica conocimientos de:

- Ingeniería de software.
- Desarrollo web.
- Diseño de bases de datos.
- Inteligencia artificial generativa.
- Recuperación de información.
- Integración de sistemas.
- Ciberseguridad.
- Aseguramiento de calidad.
- Gestión de proyectos de software.

El propósito académico es demostrar la integración de tecnologías actuales para resolver un problema real de descubrimiento y exploración literaria.

---

**LitMate — Descubre historias, incluso cuando no recuerdas sus nombres.**
