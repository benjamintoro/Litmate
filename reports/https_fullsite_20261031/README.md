# Recorrido completo de la web en la demo — 2026-10-31

Actualización posterior: el usuario **reinició Waitress y confirmó una prueba
real satisfactoria de la web ampliada desde su celular mediante la URL HTTPS
pública, incluida la navegación entre secciones**. Confirmó también que Funnel
y su acceso remoto siguen funcionando. Se registra como validación real del
usuario en `validacion_web_publica_confirmada.json`; no es una prueba pública
autenticada automatizada realizada por el agente. No se infieren latencias,
tipo de red ni pruebas individuales de voz/SSE que no se hayan especificado.

## Estado de aplicación

**Web ampliada activada y validada desde el teléfono por el usuario.** Conservar
esta versión estable para la defensa del 3 de noviembre: no reiniciar servicios
ni introducir cambios importantes. La guía final de verificación y recuperación
está en `DEFENSA_20261103.md`. En esta actualización sólo se modifica documentación.

Funnel ya publica `/` hacia `http://127.0.0.1:8003`. Se conservó exactamente su
configuración Foreground en 443, sin --bg, otro proxy, UAC ni firewall.
Tailscale, Chrome Remote Desktop y MySQL80 continúan Running.
`publicacion_preservada.json` conserva el estado anterior al reinicio. La lectura
actual confirma que las secciones ampliadas, incluida `/about/`, ahora exigen
Basic Auth (401 sin credenciales); admin, .env y backups siguen 404. Esta lectura
no sustituye la prueba de navegación autenticada confirmada por el usuario.

## Causa y alcance de los cambios

Había dos restricciones intencionadas: DemoGateway admitía casi exclusivamente
el chat y demo_urls redirigía la raíz a `/chat/`. El proxy HTTPS no era la causa.
La raíz ahora resuelve la portada auténtica de core.views.index. Se amplió una
lista cerrada de rutas y métodos; no se publica indiscriminadamente el URLconf.

Además se detectaron escrituras indirectas incompatibles con la demo:

- El carrusel de inicio intentaba recuperar y guardar precios ausentes.
- El catálogo intentaba registrar EventoAnalitica en cada búsqueda.
- El comparador podía forzar scraping, persistencia de precios e historial.
- El login normal actualiza last_login; registro, contacto, recuperación,
  favoritos, listas, perfiles y contratación requieren escrituras o datos privados.

En el perfil read-only se omiten las dos primeras escrituras y el comparador
utiliza únicamente registros frescos existentes. Ignora force=true, no scrapea
ni crea precios/historial. No presenta series sintéticas de precios en la demo.
El funcionamiento normal, fuera del perfil demo, conserva su comportamiento.
MySQL mantiene SET SESSION TRANSACTION READ ONLY en cada conexión.

## Inventario y disponibilidad preparada

Todas las rutas siguientes exigen primero la autenticación Basic existente,
usuario `demo`. Esta autenticación no convierte al visitante en un usuario
personal de Django ni le concede privilegios.

| Rutas reales | Antes en la demo | Versión preparada y probada |
| --- | --- | --- |
| `/` | Redirección al chat | Portada original, carrusel y navegación |
| `/about/` | 404 | Sobre nosotros, equipo e imágenes |
| `/post/` | 404 | Publicaciones y enlaces externos originales |
| `/libros/` | 404 | Catálogo, filtros, búsqueda y comparador en lectura |
| `/suscripciones/planes/` | 404 | Consulta de planes, sin contratación |
| `/contact/` | 404 | Formulario original con aviso permanente de vista previa |
| `/login/`, `/registro/`, `/password-reset/` | 404 | Formularios originales en vista previa, sin cuentas/correos |
| `/terminos-y-condiciones/` | 404 | Página original |
| `/politica-de-privacidad/` | 404 | Página original |
| `/politica-de-cookies/` | 404 | Página original |
| `/chat/`, `/chatbot/` | Disponible | Sin cambios de comportamiento o diseño |
| `/api/quick-search/` | 404 | Búsqueda global y atajos |
| `/api/libro/precios/` | 404 | Precios almacenados; sin actualización externa |
| Checkout de planes | 404 | Redirección a planes con aviso de pagos desactivados |
| Botones Google/GitHub | 404 | Vuelven al login con aviso; no inicia OAuth |
| `/logout/` POST | 404 | Explica cierre de Basic Auth sin borrar el contexto |
| `/api/track-conversion/` POST | 404 | Responde tracked=false, sin analítica persistente |
| Chat query/finalize, cuota, voz, estáticos y audio opaco | Disponible | Conservados con métodos explícitos |

Se mantienen 404 para admin, herramientas de error/debug, archivos privados,
backups, .env, perfiles personales, favoritos, listas, lectura, limpieza de
historial, callbacks OAuth, confirmaciones de contraseña, pasarelas/callbacks de
pago y demás rutas no autorizadas. Sólo se sirven estáticos públicos y los MP3
opacos del directorio aislado de voz. No se publican MySQL, Ollama o SearXNG.

## Pruebas ejecutadas

- Cuatro regresiones iniciales reprodujeron la restricción de rutas, redirección
  de portada y actualización de precios en read-only; fallaban antes del cambio.
- **25 pruebas Django dirigidas aprobadas**, sin bases productivas: gateway,
  errores con DEBUG=False, formularios sin escrituras/credenciales reflejadas,
  CSRF, pagos y OAuth inactivos, analítica, métodos HTTP, conservación de sesión,
  errores de precios sin detalles internos y rutas normales sin alteraciones.
  Ver `regresiones_frontend.json`.
- **210 regresiones existentes de demo/IA aprobadas**, SQLite temporal aislado.
  Ver `regresiones_210.json`. Los fallos de proveedores registrados allí son
  simulaciones intencionadas de las pruebas.
- **246 comprobaciones JS del chat**, **4 de reintentos de finalización** y
  **4 de transporte/redirecciones** aprobadas. git diff --check sin errores.
- Perfil HTTPS ensayado en **127.0.0.1:8004**, Host del dispositivo público,
  DEBUG=False, cookies Secure, HSTS, origen/CSRF y MySQL read-only.
  **14 páginas HTTP 200, 23 recursos estáticos locales correctos**, cuatro
  destinos extra de navegación, búsqueda de Dune, quick-search y comparador.
  POST a los cuatro formularios devolvió la vista previa sin conservar el
  contenido enviado. Ver `recorrido_formularios_sse.json`.
- Navegación real con Edge en **127.0.0.1:8005**, perfil local aislado y proceso
  propio, sin instalar paquetes. En `navegador_enlaces/captura.json` constan los
  clics en enlaces reales, páginas cargadas, ninguna imagen con src no vacío
  fallida y ninguna excepción JavaScript. En el catálogo cargaron 41 imágenes.
  Las capturas de inicio y catálogo se inspeccionaron visualmente. Las imágenes
  vacías de modales cerrados no se cuentan como portadas fallidas.
- Conversación real desde la interfaz: dos novelas de fantasía; navegación a
  Sobre nosotros y al catálogo; regreso al chat; «Cuéntame más del segundo».
  Resolvió correctamente la segunda recomendación, **Choque de Reyes**, con
  tarjetas y enlaces. **Misma cookie de sesión antes/después** (se registra sólo
  el booleano, nunca su valor). Dos turnos completos, 0,5213 y 0,5114 segundos,
  medidos desde la interfaz. Son rutas rápidas existentes, no un benchmark de
  inferencia completa de Qwen. También se verificaron query/finalize HTTP 200.

## Límites y fallos observados

- Un ensayo HTTP identificó El principito en 1,0474 s, pero «¿Quién lo escribió?»
  pidió más pistas en 15,8063 s. Se conserva el resultado real en
  `navegacion_sse.json`; no se declara corregido ese caso de IA. No se alteraron
  el RAG, la clasificación o la memoria para ocultarlo.
- La voz externa opcional está desactivada en la configuración actual
  (LITMATE_TTS_ENABLED=False). El navegador recibió 503 en ese endpoint; conserva
  el fallback speechSynthesis existente. No se modificó voz ni .env y no se
  comprobó reproducción audible en Edge headless. Hay que comprobar el botón de
  volumen en el teléfono si forma parte de la exposición.
- Los formularios públicos no son cuentas operativas en esta demo. Para mostrar
  altas, perfiles, favoritos, listas, estados de lectura y suscripciones se
  necesitaría un conjunto de usuarios/datos y una base de escritura aislados.
  No se preparó ni publicó esa copia, ni se deshabilitó read-only.
- Contacto no guarda ni envía; recuperación no manda correo; no hay pagos reales
  ni simulador de pasarelas. Las publicaciones conservan enlaces externos, cuyas
  condiciones/disponibilidad no dependen de LitMate.

## Integridad

`integridad_lectura.json`: MySQL `litmate_db`, sesión read-only, **41 tablas y
46.822 filas**, mismos conteos observados anteriormente; 55 libros del catálogo
de presentación. Las pruebas usan copias propias de los almacenes auxiliares y
sesiones de archivos separadas. SHA-256 de .env, literary_memory.sqlite3 y
literary_memory_rag.sqlite3 sin cambios; quick_check OK y cero problemas de claves
foráneas en ambos SQLite. No hubo migraciones, importaciones, instalaciones,
commits, push ni cambios de servicios/red. No se copió ningún secreto a informes.

## Referencia de reinicio — ya realizado por el usuario

El usuario autorizó y realizó el reinicio en su consola. No repetirlo ahora.
Los pasos siguientes quedan como referencia histórica; ante una caída utilizar
`DEFENSA_20261103.md`. Sólo se actúa **en la consola de Waitress**, no en la de
Funnel/Tailscale ni en Chrome Remote Desktop:

1. Terminar o guardar visualmente la conversación que se quiera conservar.
2. Ctrl+C para detener únicamente iniciar_demo.py de 8003. Funnel permanece.
3. Volver a ejecutar, desde G:\Proyecto\Litmate:

```powershell
.\venv\Scripts\python.exe -B iniciar_demo.py --modo https --host xato.taila70665.ts.net --puerto 8003 --carpeta .testtmp/demo-https-20261103 --comprobar-despliegue --google-books-sin-facturacion
```

4. Introducir MySQL y **la misma contraseña privada de demo** en los prompts
   ocultos, sin compartirlas en el chat. Esperar actual_listener: 127.0.0.1:8003.
   No se ha cambiado la contraseña existente. El operador debe volver a
   introducirla; no se extrajo del proceso activo ni se conoce su valor.
5. Mantener abiertas las consolas de servidor y Funnel. Comprobar las URL raíz
   y chat. No volver a ejecutar Funnel ni cambiar su configuración.

**Sesión:** el lanzador actual genera SECRET_KEY aleatoria en cada arranque.
Aunque se mantienen los archivos de sesión y las copias de conocimiento, sus
firmas antiguas pueden dejar de ser válidas. No prometer continuidad del hilo
a través del reinicio. La navegación dentro de la misma ejecución sí se
comprobó. No se extrajo la clave del proceso ni se desactivó la verificación de
firmas. Durante el reinicio HTTPS podría mostrar un fallo de proxy temporal;
el escritorio remoto no depende de Waitress ni se detiene.

Al cerrar los ensayos se detuvieron únicamente los servidores propios 8004 y
8005; `cierre_ensayos.json` confirma ambos sin escucha y 8003 todavía activo.
`integridad_final.json` conserva exactamente los conteos MySQL del inicio del
ensayo y los hashes originales. No se detuvo el servidor público ni Funnel.

Si el arranque falla, mantener Funnel/Tailscale/Chrome Remote Desktop abiertos,
conservar el mensaje de error sin claves y relanzar el mismo comando en la
consola. No cambiar puertos, MySQL, firewall o .env como intento de reparación.
La web ampliada ya está activa; mantenerla sin cambios mientras funcione.

## Comprobación posterior desde el teléfono

Con Wi-Fi y VPN del teléfono apagados, conservando Tailscale del PC conectado:

1. Abrir https://xato.taila70665.ts.net/ en pestaña privada con demo y la misma
   contraseña. Debe aparecer la portada original, no redirigir al chat.
2. Recorrer Sobre nosotros, Post, Explorar, Planes y Contacto desde el menú.
3. En Explorar buscar Dune, abrir su ficha y comprobar portada/enlaces. Los
   precios ausentes no se actualizarán en este perfil.
4. Comprobar avisos de vista previa en login, registro, recuperación y contacto;
   no introducir credenciales de cuentas reales ni esperar envíos/pagos.
5. Entrar al Asistente IA desde el menú, pedir dos novelas de fantasía, visitar
   otra sección, volver y pedir más del segundo. Revisar progreso SSE, tarjetas,
   portadas y, manualmente, voz.
6. /admin/, /.env y /backups/ deben seguir sin acceso.

Comprobador opcional posterior (pide la clave de demo oculta y valida TLS):

```powershell
.\venv\Scripts\python.exe -B -m scripts.demo.check_demo --publico --host xato.taila70665.ts.net --seguridad-ampliada --web-completa --output reports/https_fullsite_20261031/publico_despues.json --question "Recomiéndame dos novelas de fantasía en español" --question "Cuéntame más del segundo"
```

Ese comprobador autenticado no se ha ejecutado sobre el servidor público
modificado: la contraseña la introduce únicamente el operador. La web ampliada
sí cuenta ahora con una prueba real satisfactoria desde el celular confirmada
por el usuario. El tipo de red de esta última prueba no se especificó; el ensayo
anterior de chat mediante datos móviles se mantiene como evidencia separada.

## Archivos de esta unidad

- core/demo_gateway.py: rutas y métodos públicos explícitos, misma autenticación.
- core/demo_frontend.py: vistas previas y apoyos sin escrituras ni cuentas reales.
- litmate_project/demo_urls.py: portada auténtica y overrides sólo del perfil demo.
- core/views.py: guardas de precios/analítica y mensaje de error público acotado.
- core/scraper.py: comparador de lectura, sin scraping/persistencia/gráfico sintético.
- templates/base.html: aviso de vista previa cuando la vista lo suministra;
  sin cambiar colores, distribución, avatar, tarjetas o controles.
- core/test_demo_frontend.py, test_demo_gateway.py, test_demo_preflight.py.
- scripts/demo/check_demo.py y frontend_checks.py: recorrido HTTP reproducible.
- scripts/demo/capturar_demo.py/.mjs: puerto local configurable, clics y sesión.
- Este informe, evidencias adjuntas y reportes/continuidad_opencode.md.

Se conservaron los demás cambios preexistentes del repositorio.
