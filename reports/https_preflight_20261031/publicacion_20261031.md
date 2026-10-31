# Funnel activado con autorización — validación móvil confirmada

**Estado final:** el usuario confirmó que todo funcionó desde datos móviles,
con Wi-Fi y VPN apagados. Evidencia: `validacion_movil_confirmada.json`.

El usuario autorizó expresamente publicar **únicamente LitMate**. Se comprobó
antes que el servidor privado respondía en 8003 y que Serve/Funnel estaban vacíos.

Se ejecutó temporalmente, sin `--bg`, sin UAC y sin cambios de firewall:

```powershell
& "$env:ProgramFiles\Tailscale\tailscale.exe" funnel --https=443 http://127.0.0.1:8003
```

El cliente informó que la función todavía no estaba habilitada en la tailnet.
El usuario abrió el enlace oficial de habilitación mostrado por el cliente y
confirmó que la habilitó. La orden que ya estaba esperando devolvió `Success`
y anunció:

**https://xato.taila70665.ts.net/chat/**

## Comprobado después de activar

- Configuración en `Foreground`: únicamente HTTPS 443 y un handler `/` con proxy
  a `http://127.0.0.1:8003`. No hay forwards TCP de MySQL, Ollama ni SearXNG.
- Certificado válido con verificación estándar, nombre correcto y TLS 1.3.
  Emisor Let's Encrypt, cadena YE1; vigencia observada 31-10-2026 a 29-01-2027
  (fechas UTC originales en el JSON).
- `/chat/` y `/static/js/chatbot.js` sin credenciales: HTTP 401 con desafío Basic.
- `/admin/`, `/.env` y `/backups/`: HTTP 404.
- MySQL, Ollama y SearXNG siguen accesibles por localhost; Docker SearXNG healthy.
- Servicios `Tailscale` y `chromoting` Running. No se aplicó la regla MySQL ni se
  solicitaron permisos administrativos.

Evidencia inicial: `https_activado_sin_credenciales.json`. Estas comprobaciones se
originaron en el propio servidor, que pertenece a la tailnet: **no demuestran
por sí solas acceso independiente desde una red móvil**. La herramienta web
externa tampoco pudo inspeccionar esta URL protegida; eso no se toma como
prueba de fallo ni de éxito de acceso exterior.

Comprobación adicional posterior: el DNS público respondió con direcciones IPv4
e IPv6 globales (`dns_publico_funnel.json`). Se estableció TLS directamente con
una de esas IP del relé público usando el SNI del dominio y la verificación
normal de certificado, sin credenciales. `/chat/` devolvió `HTTP/1.1 401
Unauthorized` con desafío Basic en 1,1945 s. Esta prueba sí recorre el relé
público y evita confundirlo con una resolución MagicDNS privada
(`relay_publico_verificado.json`), aunque se origina en el propio PC y sigue
sin reemplazar la prueba móvil autenticada desde otra conexión.

## Prueba pedida al usuario

En el teléfono: apagar Wi-Fi y desconectar la VPN Tailscale **sólo en el teléfono**;
mantener intactos Tailscale y Chrome Remote Desktop del PC. Abrir una pestaña
privada en la URL anterior e introducir usuario `demo` y la clave privada elegida
en el prompt de PowerShell. No enviarla al chat.

Comprobar carga de avatar/estilos, identificación por planeta/rosa, dos novelas
de fantasía en español con tarjetas/portadas, seguimiento del segundo libro y
progreso SSE al pedir la trama de El mundo de Sofía. Registrar cualquier error
de certificado, acceso, recursos, contexto o respuesta antes de dar por terminada
la validación. **Confirmación posterior recibida:** «Todo funcionó desde datos
móviles, con Wi-Fi y VPN apagados». Por esa respuesta se registran acceso,
interfaz, tarjetas/portadas, contexto y progreso como comprobados por el usuario.
No se midió latencia numérica desde el teléfono ni se ejecutó el comprobador
público con su contraseña; se mantienen separadas esas evidencias.

También se amplió el comprobador existente para HTTPS real desde una consola
local del operador, con clave oculta y sin guardarla en informes:

```powershell
.\venv\Scripts\python.exe -B -m scripts.demo.check_demo --publico --host xato.taila70665.ts.net --seguridad-ampliada --output reports/https_preflight_20261031/chat_https_autenticado.json --question "Recuerdo un libro donde un niño vive en un planeta pequeño y cuida una rosa" --question "Recomiéndame dos novelas de fantasía en español" --question "Cuéntame más del segundo"
```

Este comando es opcional y no sustituye la prueba móvil. Comprueba el certificado
normalmente; sólo admite HTTPS 443 en el dominio Tailscale indicado. Rechaza
redirecciones a otro origen, credenciales en URLs o degradación a HTTP para no
reenviar la contraseña. Cuatro pruebas de estas restricciones aprobadas. El
comprobador autenticado público **no se ha ejecutado**: la clave sólo la conoce
el usuario.

## Mantener y detener

Actualmente Funnel está en primer plano en la sesión de esta ejecución. Si se
cierra esa sesión, el proceso puede terminar: no es un servicio persistente ni
una tarea programada. Para la defensa, mantener una consola PowerShell propia
con el mismo comando, además de la consola del servidor; no iniciar dos Funnel
simultáneamente ni reiniciar servicios mientras se verifica el teléfono.

Para apagar únicamente la publicación propia:

```powershell
& "$env:ProgramFiles\Tailscale\tailscale.exe" funnel --https=443 off
& "$env:ProgramFiles\Tailscale\tailscale.exe" funnel status --json
```

También puede usarse Ctrl+C en la consola del Funnel. No ejecutar down, logout,
reset ni detener Tailscale/Chrome Remote Desktop. La habilitación de la función
en la cuenta no equivale a mantener una publicación activa tras apagar el proxy.

En esta versión, `tailscale funnel status` en formato de texto mostró «No serve
config» mientras el bloque `Foreground` del JSON seguía activo y HTTPS devolvía
401. Para comprobar el estado y el apagado usar **`status --json`**, además de
la comprobación del sitio; no considerar esa frase aislada una prueba de apagado.
Ctrl+C debe hacerse en la consola del proceso Funnel, no en la de Tailscale ni
en Chrome Remote Desktop. Si un comando de apagado no retira `Foreground`,
detener el proceso de Funnel que lo mantiene y verificar de nuevo.

Estado: **autorizado y activado; TLS y acceso protegido comprobados; prueba
móvil autenticada confirmada por el usuario.** El túnel permanece temporal,
ligado a su proceso en primer plano.
