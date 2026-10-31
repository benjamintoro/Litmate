# Demo desde el instituto — preparación del 31 de octubre de 2026

> Revisión posterior y decisión vigente: [preflight de seguridad](../https_preflight_20261031/README.md).
> El usuario aplazó cualquier aplicación de firewall mientras está remoto.
> Se revisaron 204 reglas: bloqueo predeterminado y excepciones privadas de
> Tailscale; exposición pública no probada. No usar el script amplio anterior.
> La alternativa limitada a mysqld.exe queda sólo preparada. Funnel sigue apagado.

**Estado: preparado y probado por localhost; Funnel no activado. El acceso desde
otra red y el certificado HTTPS público siguen pendientes de autorización y prueba.**
No se ha publicado el proyecto, abierto el router ni modificado `.env`.

## Qué se utiliza

- Django existente con `litmate_project.demo_settings`, `DEBUG=False`.
- Waitress 3.0.2 y WhiteNoise 6.12.0, instalados en `venv` con autorización.
  Las dependencias opcionales están en `requirements-demo.txt`.
- MySQL local `litmate_db`, con **todas las conexiones de este perfil en modo de
  sesión de sólo lectura**. No permite registrar usuarios, escribir historiales
  personales ni modificar el catálogo original durante la exposición.
- Copias persistentes de los almacenes auxiliares públicos en `.testtmp`.
  La investigación de la demo puede enriquecer esas copias; no importa datos al
  MySQL original ni sustituye su RAG. No eliminar la carpeta si se quiere conservar
  ese conocimiento. Las conversaciones quedan en sesiones locales separadas.
- Gateway con usuario `demo`, contraseña elegida por el operador de al menos
  16 caracteres, introducida en prompt oculto. No se guarda en archivos.
  Bloquea administración, registro, cuentas, pagos y archivos ajenos al chat.
  Elige una contraseña nueva para exponer; las pruebas usaron una de fixture.
- Tailscale 1.104.4 instalado con autorización, sesión iniciada por el usuario.
  DNS observado: `xato.taila70665.ts.net`. `funnel status --json`: `{}`.

Se recomienda [Tailscale Funnel](https://tailscale.com/docs/features/tailscale-funnel):
ofrece HTTPS para un servicio local y admite el plan Personal gratuito. Requiere
MagicDNS, HTTPS y permiso de Funnel en la cuenta. El instituto sólo necesita un
navegador. Funnel publica el sitio en Internet; la contraseña del gateway sigue
siendo necesaria. No se ha activado ninguna de esas opciones automáticamente.
No se recomienda Quick Tunnels para este chat porque su documentación indica que
[no admite SSE](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).
La continuidad de SSE a través de Funnel debe medirse al autorizar la publicación.

## Comprobar e iniciar, sin publicar

En PowerShell 5.1 dentro de `G:\Proyecto\Litmate`:

```powershell
.\scripts\demo\EstadoDemo.ps1
ollama list
.\venv\Scripts\python.exe -B iniciar_buscador.py
```

MySQL80 debe estar Running. Si está detenido, iniciarlo desde Servicios de Windows
con los permisos habituales. Abrir Docker Desktop y Ollama si no están abiertos.
No reiniciar, recrear ni borrar servicios que ya estén funcionando.

Prueba local independiente del túnel:

```powershell
.\venv\Scripts\python.exe -B iniciar_demo.py --modo local --puerto 8002 --carpeta .testtmp/demo-20261103 --google-books-sin-facturacion
```

Introduce la clave MySQL en el primer prompt y la de acceso demo en el segundo.
Abrir `http://127.0.0.1:8002/chat/`, usuario `demo`. El acceso HTTP se limita a
loopback; **no usar la IP LAN**. `--google-books-sin-facturacion` es opcional y se
basa en la confirmación previa del usuario de que su proyecto no tiene facturación.
Sin ese argumento se mantienen los proveedores gratuitos ya habilitados.

`--comprobar` hace las comprobaciones sin dejar un servidor abierto. Debe mostrar
`debug: false`, `database: litmate_db`, `mysql_read_only: true`, 55 libros del modelo
`Libro` y `public_access_activated: false`. El catálogo de conocimiento adicional
no está incluido en esos 55 registros.

Perfil de destino para un futuro túnel HTTPS (tampoco publica):

```powershell
.\venv\Scripts\python.exe -B iniciar_demo.py --modo https --host xato.taila70665.ts.net --puerto 8003 --carpeta .testtmp/demo-https-20261103 --google-books-sin-facturacion
```

Waitress escucha sólo en `127.0.0.1:8003`. El perfil presupone terminación TLS en
el túnel, fija el esquema HTTPS y descarta cabeceras proxy no confiables. Tiene
host y origen CSRF exactos, cookies Secure/HttpOnly/SameSite, HSTS limitado y
sesiones de archivo para no truncar evidencias grandes en una cookie de 4 KB.
No se puede validar ese perfil abriendo directamente `http://127.0.0.1:8003`
en un navegador: requiere el host HTTPS o el comprobador de backend de abajo.

La clave de sesión es nueva en cada arranque. Reiniciar cierra las sesiones de
los lectores; no elimina las copias públicas de conocimiento ni las fuentes.
No hay que arrancar `runserver` para la demo remota.

## Activación futura — ejecutar sólo después de autorización explícita

Primero verificar que no exista una publicación ajena y resolver el aislamiento
de servicios internos indicado más abajo. Con el perfil HTTPS abierto:

```powershell
& "$env:ProgramFiles\Tailscale\tailscale.exe" funnel status --json
& "$env:ProgramFiles\Tailscale\tailscale.exe" funnel --https=443 http://127.0.0.1:8003
```

No usar `--bg`: se quiere una sesión visible y finita. La primera activación puede
solicitar habilitar HTTPS/Funnel en la cuenta; es un paso del operador, no una
operación realizada en este lote. No usar `--tcp`, puertos internos, `0.0.0.0`
ni otro backend. Sintaxis de [la CLI oficial](https://tailscale.com/docs/reference/tailscale-cli/funnel).
URL esperada, **todavía no validada públicamente**:
`https://xato.taila70665.ts.net/chat/`.

## Prueba externa necesaria

Con autorización y túnel activo, usar móvil con Wi-Fi apagado o un navegador del
instituto. Verificar en ventana privada:

1. HTTPS y certificado válido, sin aceptar excepciones.
2. Sin credenciales pide acceso; contraseña incorrecta no entrega el chat.
3. Usuario `demo` y contraseña nueva permiten entrar; `/admin/` sigue en 404.
4. Avatar, estilos, portadas y botones cargan. No requieren servicios internos
   accesibles directamente desde Internet.
5. Una pregunta sencilla y otra con fuentes reciben progreso SSE antes de la
   respuesta. Revisar `text/event-stream` en Network y medir tiempos reales.
6. Un seguimiento conserva la obra y un ordinal selecciona la tarjeta correcta.
7. Voz: comprobar botón y permiso de audio. El micrófono requiere permiso del
   navegador y HTTPS; no está validado con esta prueba local automatizada.
8. El PC sigue encendido y despierto, con conexión y alimentación estables.

No declarar acceso remoto completado hasta registrar esta prueba. Las cookies
Secure, CSRF y HSTS se comprobaron en el backend simulando terminación TLS;
eso **no demuestra** certificado público ni conectividad desde el instituto.

## Aislamiento pendiente por decisión del usuario

Se detectó una escucha previa de MySQL en `0.0.0.0:3306`. El usuario pidió
**sólo dejar preparada** `scripts/demo/ProtegerServicios.ps1`; no se aplicó ninguna
regla ni se cambiaron interfaces MySQL. Tampoco se deshabilitó ninguna protección.
La publicación de Docker SearXNG observada sigue siendo `127.0.0.1:8080`.

El script preparado bloquea entradas TCP a 3306, 33060, 11434 y 8080 por interfaces
no loopback; requiere aprobación y administrador para aplicarse. No se ha probado
su aplicación ni su efecto sobre WSL/Docker. Antes de autorizar publicación hay
que revisar/aprobar ese aislamiento o una configuración equivalente. El túnel
preparado sólo apunta al chat, pero no corrige por sí solo una escucha LAN/tailnet
preexistente. No se puede afirmar que todos los servicios internos estén aislados.

## Detener y volver al funcionamiento habitual

- Ctrl+C en la terminal de Funnel. Verificar `funnel status --json` sin publicación.
- Si sigue activa la configuración creada para HTTPS 443, apagar sólo ese servicio:

```powershell
& "$env:ProgramFiles\Tailscale\tailscale.exe" funnel --https=443 off
& "$env:ProgramFiles\Tailscale\tailscale.exe" funnel status --json
```

- Ctrl+C en `iniciar_demo.py`. No usar `funnel reset`, borrar volúmenes, terminar
  otros servidores ni detener MySQL/Ollama/Docker sin necesidad.
- El arranque de desarrollo anterior con `iniciar_mysql_local.py` sigue intacto.
  Ninguna variable de `.env` necesita revertirse.
- Si falla la conexión externa, usar el perfil local o las capturas/grabación
  auténticas del informe. Una grabación no se presenta como una sesión en vivo.

## Comprobadores reproducibles

```powershell
.\venv\Scripts\python.exe -B -m scripts.demo.test_demo --output reports/demo_20261103/pruebas_nueva_ronda.json
.\venv\Scripts\python.exe -B -m scripts.demo.check_demo --output reports/demo_20261103/control_local_nuevo.json --question Hola
.\venv\Scripts\python.exe -B -m scripts.demo.check_demo --puerto 8003 --host xato.taila70665.ts.net --perfil-https --output reports/demo_20261103/control_backend_nuevo.json --question Hola
.\venv\Scripts\python.exe -B -m scripts.demo.capturar_demo --carpeta reports/demo_20261103/captura_nueva
node scripts/demo/test_finalize_retry.cjs
.\venv\Scripts\python.exe -B -m scripts.demo.verificar_integridad --output reports/demo_20261103/integridad_nueva.json
```

Usar salidas nuevas; los programas rechazan sobrescribir informes. Las claves
se solicitan ocultas. No elevar límites de consultas para ejecutar pruebas:
respetar el enfriamiento si aparece HTTP 429. El capturador usa Edge aislado,
sin perfil personal, datos de pruebas públicos y CDP sólo en localhost; cierra
su navegador al terminar. Los PNG y WebP son capturas reales, sin audio y sin
fabricar texto o tarjetas. La carpeta temporal del navegador queda conservada.
