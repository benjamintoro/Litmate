# Preparación HTTPS y verificación de acceso — 31-10-2026

> **Estado posterior actualizado:** el usuario autorizó y habilitó Funnel;
> está activo hacia LitMate y se verificó TLS/acceso sin clave por el relé público.
> El usuario confirmó la prueba móvil autenticada con Wi-Fi/VPN apagados.
> Ver [publicación actual](publicacion_20261031.md).
> El resto de este documento conserva las comprobaciones anteriores a la activación.

**Preparado y probado localmente. No autorizado para publicar. No publicado.
Sin prueba desde Internet. No se modificó el firewall ni se solicitó UAC.**

| Estado | Resultado |
|---|---|
| Preparación y pruebas locales autorizadas | Sí |
| Servidor probado localmente | Sí, luego detenido |
| Regla adicional aplicada | No; aplazada por el usuario |
| Publicación autorizada | No |
| Funnel publicado | No |
| Prueba desde Internet | Pendiente |

El usuario decidió conservar su acceso remoto hasta poder estar físicamente
frente al PC. La aplicación de reglas queda aplazada; esta decisión prevalece
sobre cualquier procedimiento de activación anterior.

## MySQL: escucha y exposición son comprobaciones distintas

Se verificó por conexión real con MySQL, no sólo mirando una captura de netstat:

- `bind_address=*`, puerto 3306.
- `mysqlx_bind_address=*` para el protocolo X, normalmente 33060.
- `litmate_db`, 55 registros `Libro`; sesión de pruebas de sólo lectura.

Que el servidor escuche en todas sus interfaces **no demuestra** que un equipo
de Internet pueda conectarse. La accesibilidad depende también del firewall,
las rutas y el router. No se hizo una prueba desde otra red ni se inspeccionó
la configuración del router; no se puede certificar un puerto público cerrado
o abierto a partir de una conexión originada en el mismo PC.

Auditoría de firewall exclusivamente de lectura:

- Dominio, Privado y Público habilitados; entrada predeterminada `Block`.
- Perfil Público en la interfaz física observada; Privado en Tailscale.
- 204 reglas activas de entrada examinadas. Se distinguieron las condiciones
  de aplicación, servicio, protocolo, puerto, dirección y familia de paquete
  (PFN), para no interpretar permisos de Microsoft Store como permisos de MySQL.
- No se encontró una regla de permiso aplicable a MySQL que abra sus puertos
  por la interfaz pública/LAN. Las reglas inspeccionadas mantienen el bloqueo
  por defecto en ese acceso.
- **Sí hay dos excepciones `Tailscale-In`**: permiten todos los puertos hacia
  las IP privadas IPv4/IPv6 del dispositivo en perfiles Dominio/Privado.
  `ShieldsUp=False`. Por ello, MySQL podría ser accesible para otros dispositivos
  autorizados de la tailnet, sujeto a la política de acceso de Tailscale y a la
  autenticación de MySQL. No se probó desde otro dispositivo de esa red.
- No hay Serve ni Funnel configurados (`{}`). La tabla de `netsh interface
  portproxy show all` estaba vacía. Esto no inspecciona los reenvíos del router.

Conclusión acotada: **no hay evidencia de publicación de MySQL a Internet y no
hay un permiso directo encontrado que lo abra por la interfaz pública. Sí existe
una excepción de red privada Tailscale que impide afirmar que MySQL esté bloqueado
para todos los demás dispositivos.** La prueba externa sigue pendiente.

Las excepciones explícitas pueden prevalecer sobre el bloqueo predeterminado;
véase la [documentación de reglas de Windows Firewall](https://learn.microsoft.com/en-us/windows/security/operating-system-security/network-security/windows-firewall/rules).
La auditoría no usa como protección global una regla condicionada a otro usuario.
No se modificaron reglas del sistema ni del entorno de ejecución.

Evidencia: `mysql_firewall_actual.json`, `red_reglas_revisadas.json`,
`servicios.json`. Las muestras de netstat no mostraron consistentemente todos los
listeners; se contrastaron con la configuración real de MySQL, el mapeo Docker,
el código de enlace de Waitress y sondas locales. No afirmar que una ausencia
momentánea de netstat demuestra que un servicio está cerrado.

## Control remoto, Docker y los dos scripts de firewall

Chrome Remote Desktop (`chromoting`) y Tailscale están `Running`, con inicio
automático. El host de Chrome funciona como `LocalSystem`. Sus reglas existentes
permanecen intactas. No se desconectó Tailscale, cerró sesión, reinició Windows,
cambió adaptadores ni detuvo servicios de control remoto.

1. **`ProtegerServicios.ps1`, anterior:** abarca TCP 3306/33060/11434/8080 en
   interfaces no loopback, incluida WSL. Es más amplio de lo necesario para el
   estado observado. No se aplicó y no se certifica que su aplicación conserve
   toda comunicación Docker. No utilizarlo para esta revisión remota.
2. **`AislarMySqlDemo.ps1`, alternativa preparada:** selecciona únicamente
   `C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqld.exe`, entrada TCP
   3306/33060, interfaces no loopback. No cambia reglas de Chrome, Tailscale,
   Docker, ni sus puertos de comunicación. No se aplicó.

Por su alcance, la alternativa no selecciona el proceso `remoting_host.exe`,
`tailscaled.exe` ni el backend de Docker. Chrome utiliza comunicaciones HTTPS,
STUN y UDP; no se modifican esos puertos ni el tráfico saliente. Véase
[Google: acceso y conectividad de Chrome Remote Desktop](https://support.google.com/chrome/answer/1649523).
Esto es una comprobación de configuración, no una garantía absoluta sin ensayo
de aplicación/reversión.

Docker sólo contiene el SearXNG observado en esta revisión: `healthy`, publicado
en `127.0.0.1:8080`, sin variables de dependencia MySQL. El Compose existente
confirma que SearXNG no usa la base MySQL de Django. Su consulta real devolvió
59 resultados en 1,0859 s con Open Library/Mwmbl, sin motores marcados como
no disponibles en esa prueba. Hay resultados ajenos al tema: se comprueba
conectividad, no una precisión del 100 % de los resultados.

## Reversión preparada, no ejecutada

La nueva regla tendría el nombre único `LitMateDemo-MySQL-Only-20261103`.
La reversión comprueba su descripción de propiedad, programa, dirección,
protocolo y puertos antes de deshabilitar **sólo esa regla**. No elimina reglas
previas, cambia perfiles ni reinicia servicios.

Sólo tras una autorización futura y con las condiciones de acceso verificadas:

```powershell
# Preparación de lectura: no requiere elevación ni cambia el firewall.
.\scripts\demo\AislarMySqlDemo.ps1

# NO ejecutados: ambas operaciones necesitan permiso y PowerShell elevado.
.\scripts\demo\AislarMySqlDemo.ps1 -Aplicar
.\scripts\demo\AislarMySqlDemo.ps1 -Revertir
```

El análisis de sintaxis pasó; el plan de lectura confirmó el ejecutable y los
puertos; no contiene comandos para detener servicios, adaptadores, Windows,
Tailscale o Docker. La reversión real no se ha probado porque la regla no existe.
Tampoco hay una tarea automática de recuperación instalada. Una reversión que
requiere administrador no sustituye un acceso alternativo comprobado.

## ¿Se podrá responder UAC por la sesión remota?

Lecturas realizadas: `EnableLUA=1`, `PromptOnSecureDesktop=1`,
`ConsentPromptBehaviorAdmin=5`, `ConsentPromptBehaviorUser=3`. El servicio de
Chrome está instalado como `LocalSystem`, no es sólo una pestaña de soporte.
Chromium contempla los cambios al escritorio de inicio/UAC en su
[implementación del host Windows](https://chromium.googlesource.com/chromium/src/+/b3d3200e934ff2463f36c573a1d33592cdeb89dc/remoting/host/win/desktop_event_handler.h).

Es consistente con que el host pueda gestionar ese escritorio, **pero no prueba
que la sesión remota actual vaya a mostrar y aceptar la solicitud**. No se abrió
ningún aviso UAC ni se alteró el escritorio seguro para probarlo. No se puede
garantizar este punto con operaciones de sólo lectura; se deja pendiente hasta
un momento con recuperación segura/acceso físico, como pidió el usuario.

## Servidor y aplicación comprobados

Se reutilizaron Waitress, WhiteNoise y el perfil existente, con copias auxiliares
aisladas en `.testtmp/https-preflight-20261031`. No se tocaron las funciones
literarias, `.env`, datos MySQL, voz, avatares, tarjetas o diseño.

- Waitress únicamente en `127.0.0.1:8003`; modo HTTPS lógico para terminación TLS
  futura, host `xato.taila70665.ts.net` y origen CSRF exactos.
- `DEBUG=False`; sesiones de archivo, cookie de sesión Secure/HttpOnly/SameSite
  Lax y cookie CSRF Secure/SameSite Lax. CSRF permanece legible por el cliente
  para enviar el encabezado del POST; no se confundió con la cookie de sesión.
- No se confía en `X-Forwarded-Host` ni en el esquema enviado por un solicitante.
- Usuario exclusivo `demo` en el gateway existente, sin sesión Django privilegiada;
  contraseña efímera de ensayo sólo en memoria. No sirve como clave pública.
- Root dirige al chat; CSS, JavaScript actual, avatar y dos portadas reales
  respondieron correctamente. Las portadas se solicitaron sin credenciales.
- Admin, cuentas, pagos, respaldos, `.env` y media ajeno bloqueados incluso con
  autenticación. Credenciales incorrectas rechazadas; límite de intentos y
  validaciones de entrada conservados.
- `check --deploy` con el perfil real: sólo `security.W005` (subdominios HSTS)
  y `security.W021` (preload HSTS). Se mantienen conscientemente desactivados
  para un dominio de demostración; no se silenciaron comprobaciones ni se
  solicitó preload permanente. Sin otras advertencias en esa ejecución.
- MySQL local en modo de sesión read-only, 55 libros. RAG: 498 documentos,
  526 fragmentos, nueve coincidencias FTS en la consulta de control y
  `quick_check=ok`.
- Modelo configurado `qwen3.5:9b-q4_K_M` instalado y ejecución real confirmada:
  respondió `listo` en 9,0119 s; no se cambió el modelo ni su configuración.

### HTTP/SSE real

`conversacion.json`: seis turnos correctos (recuerdo, trama, protagonistas
parciales, dos novelas de fantasía, segundo libro y dónde encontrarlo), entre
0,1995 y 2,3329 s. Se conservan las limitaciones narrativas del informe anterior.

`seguridad_sse.json`: controles ampliados de seguridad correctos y consulta
narrativa con modelo: primer progreso a los **0,0499 s**, fases búsqueda,
redacción y revisión, resultado verificado a los 20,8309 s y respuesta completa
a los **20,8886 s**. El seguimiento tardó 0,1011 s y conservó el libro.

El progreso viaja antes de completar el trabajo, sin buffering de toda la
respuesta por Waitress. **No se transmite como definitiva la generación factual
sin auditar**: la respuesta literaria final llega al finalizar la verificación.
No se cambió ese contrato para aparentar más velocidad.

Pruebas nuevas/dirigidas: 11 Django aprobadas (incluido error 500 genérico con
DEBUG desactivado), 246 comprobaciones JS existentes y cuatro casos de reintento
idempotente. No se repitieron las 210 pruebas literarias de la fase anterior.
La primera prueba de error 500 necesitó incluir las rutas reales del sitio para
que su plantilla pudiera resolver enlaces; no fue un defecto del servidor vivo.

## Tailscale y lo que sigue pendiente

Versión 1.104.4, estado Running, MagicDNS habilitado, DNS
`xato.taila70665.ts.net`. CertDomains no anunciado y atributo Funnel no anunciado
en el estado local: no se dieron por habilitados los certificados/permisos.
La [documentación oficial](https://tailscale.com/docs/features/tailscale-funnel)
requiere MagicDNS, HTTPS/certificados y autorización de Funnel; admite HTTPS
443, 8443 y 10000 y tiene límites de ancho de banda no configurables.

No se activó Serve, Funnel, certificado ni política de la cuenta. El transporte
HTTP proxy hace razonable evaluar SSE, pero sólo una prueba de la cadena pública
podrá confirmarlo en este entorno. No se declara compatible de extremo a extremo
basándose únicamente en esta prueba local.

URL **prevista**, no publicada ni validada externamente:
`https://xato.taila70665.ts.net/chat/`.

Comando futuro, exclusivamente después de autorización explícita y revisión
de pendientes:

```powershell
& "$env:ProgramFiles\Tailscale\tailscale.exe" funnel --https=443 http://127.0.0.1:8003
```

Sin `--bg`, sin reenvíos TCP de servicios internos ni puertos del router.
La primera activación puede pedir aprobar HTTPS/permisos en la cuenta. Para
detener sólo la publicación propia: Ctrl+C en esa terminal y comprobar el estado;
si fuese necesario, `tailscale funnel --https=443 off`. No ejecutar `tailscale
down`, cerrar sesión ni reiniciar su servicio. Sintaxis de
[la CLI oficial](https://tailscale.com/docs/reference/tailscale-cli/funnel).

No se pide de nuevo aprobación para el firewall mientras el usuario mantenga
su decisión de aplazarlo. La autorización de publicación tampoco se da por
concedida. Después de autorizar, probar desde datos móviles con Wi-Fi y cliente
Tailscale del teléfono desactivados; revisar HTTPS real, contraseña, SSE, sesión,
tarjetas y que los puertos internos no tengan ruta en Funnel.

## Día de la defensa

1. PC encendido, despierto y conectado; control remoto disponible. No cambiar
   políticas de suspensión o instalar tareas automáticamente durante esta revisión.
2. Comprobar MySQL, Ollama y Docker: `scripts/demo/EstadoDemo.ps1`.
3. En PowerShell de usuario iniciar el perfil HTTPS; introducir claves ocultas
   y elegir una nueva contraseña de demo de al menos 16 caracteres:

```powershell
.\venv\Scripts\python.exe -B iniciar_demo.py --modo https --host xato.taila70665.ts.net --puerto 8003 --carpeta .testtmp/demo-https-20261103 --comprobar-despliegue --google-books-sin-facturacion
```

4. Sólo cuando se autorice publicar, ejecutar el comando Funnel y completar
   la comprobación móvil. Seguir `reports/demo_20261103/guion_8_minutos.md`.
5. Durante la exposición, evitar importaciones, migraciones y pruebas paralelas.
6. Al terminar, apagar sólo Funnel y el proceso de demo; mantener Chrome Remote
   Desktop y Tailscale. No aplicar/deshacer reglas que no se hayan autorizado.
7. Contingencia: grabación auténtica existente
   `reports/demo_20261103/grabacion_defensa/funcionamiento_real.webp`, claramente
   presentada como grabación, no sesión en vivo.

Si no se activa el túnel, sigue disponible el modo `--modo local --puerto 8002`
del procedimiento anterior. Los procesos de ensayo pueden detenerse sin tocar
los servicios del usuario. Las claves de ensayo no se escribieron en el repositorio.

## Cierre comprobado

`cierre.json`: servidor Waitress de prueba detenido (8003 sin escucha), reglas
relevantes y perfiles de firewall iguales al inicio, mismos procesos de control
remoto, Tailscale Running y Serve/Funnel vacíos. MySQL, Ollama y SearXNG siguen
respondiendo por localhost. `.env`, memoria y RAG originales conservan SHA-256.
No hubo elevación, UAC, migraciones, instalación de paquetes ni cambios de datos.

Archivos añadidos/modificados en este lote: argumento de comprobación de despliegue
en `iniciar_demo.py`; herramientas de lectura `AuditarAcceso.ps1`,
`RevisarProteccionMySql.ps1`, `preflight_services.py`; ampliación opcional de
`check_demo.py`; alternativa **sólo preparada** `AislarMySqlDemo.ps1`; pruebas
`core/test_demo_preflight.py`; este informe y continuidad. No se modificaron
los servicios literarios ni el diseño de la aplicación.
