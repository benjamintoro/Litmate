# Publicación de LitMate: revisión final pendiente de autorización

> Actualización posterior: **autorización recibida y Funnel activo**.
> [Publicación y verificaciones actuales](publicacion_20261031.md).
> La validación móvil autenticada ya fue confirmada por el usuario; este archivo
> conserva la revisión anterior a la autorización.

Fecha de revisión: 31-10-2026. **Funnel no ejecutado. Firewall sin cambios. Sin UAC.**
La regla `AislarMySqlDemo.ps1` permanece sólo preparada por decisión del usuario.

## Resultado de las comprobaciones previas

| Elemento | Estado comprobado |
|---|---|
| Puerto de destino | `127.0.0.1:8003` |
| Escucha real | Comprobada mediante `server.socket.getsockname()`, además de la configuración. El lanzador rechaza un enlace distinto. |
| Servidor | Waitress existente; WhiteNoise para estáticos. Sin runserver público. |
| Perfil | `DEBUG=False`, host único `xato.taila70665.ts.net`, origen CSRF `https://xato.taila70665.ts.net`. |
| Proxy | Backend HTTP sólo loopback, esquema HTTPS lógico para terminación TLS futura; no confía en encabezados reenviados del solicitante. |
| Sesión | Archivos aislados; cookie Secure/HttpOnly/SameSite Lax; CSRF Secure/SameSite Lax. |
| Acceso | Gateway existente con usuario `demo`, clave privada de al menos 16 caracteres; no es una cuenta administradora de Django. |
| Rutas sensibles | Admin, cuentas, pagos, `.env`, respaldos y media privado bloqueados incluso con credenciales. Sin clave, chat y estáticos responden 401. |
| MySQL | `litmate_db`, 55 libros; conexiones de demo read-only. No es un destino del futuro Funnel. |
| Ollama/SearXNG | Servicios locales disponibles; tampoco son destinos del futuro Funnel. |
| Tailscale | 1.104.4, Running, MagicDNS activo; DNS `xato.taila70665.ts.net`. |
| Servicios Serve/Funnel previos | Ambos estados `{}`; nada que sobrescribir en la revisión. Se comprobarán otra vez justo antes de activar. |
| Certificado y permisos públicos | No activados ni dados por confirmados; su configuración se completará sólo tras autorización. |

`check --deploy` señaló únicamente W005 (HSTS en subdominios) y W021 (preload).
Se mantienen desactivados conscientemente para esta demo, sin silenciar los
controles. HTTPS real, el certificado público y la cadena SSE externa sólo
podrán verificarse después de activar el túnel con permiso.

Evidencia actual: `verificacion_final_funnel.json`, todos sus controles correctos.
Cinco turnos respondidos: identificación 1,0681 s; recomendaciones 0,1416 s;
ordinal 0,1184 s; enlaces 0,0994 s; consulta narrativa con dos llamadas al modelo
20,5913 s. En esta última, primer progreso SSE a 0,0553 s y resultado verificado
a 20,5257 s. Hay progreso real antes de terminar; el texto factual se publica
después de la auditoría. No se presenta como streaming de un borrador sin verificar.

Se ejecutaron nuevamente 11 pruebas focalizadas Django y cuatro casos JS de
finalización, todos aprobados. No se repitieron las baterías literarias extensas.
No hubo cambios en UI, memoria, RAG ni funciones del asistente. El único cambio
del lanzador añade la comprobación del socket real usando la misma fábrica
de servidor que emplea Waitress internamente.

## Contraseña privada y servidor del usuario

La comprobación se hizo con una clave efímera que no se publicará. Se detuvo
exclusivamente ese servidor para liberar 8003; MySQL, Ollama, Docker, Tailscale
y Chrome Remote Desktop permanecen en ejecución.

Se solicitó al usuario iniciar su consola con una nueva clave privada:

```powershell
cd G:\Proyecto\Litmate
.\venv\Scripts\python.exe -B iniciar_demo.py --modo https --host xato.taila70665.ts.net --puerto 8003 --carpeta .testtmp/demo-https-20261103 --comprobar-despliegue --google-books-sin-facturacion
```

Primer prompt: contraseña MySQL. Segundo: elegir contraseña nueva para el acceso
`demo` y conservarla privadamente para el teléfono. Ninguna clave se envía al chat
ni se escribe en `.env`, argumentos de proceso, Git o informes. Mantener esa
consola abierta. El arranque debe imprimir `actual_listener: 127.0.0.1:8003`.
Los procesos de ensayo detenidos no deben confundirse con este arranque privado.

**Confirmación posterior:** el usuario ya inició el servidor con su clave privada
y dejó la consola abierta. `servidor_privado_confirmado.json` registra acceso
local en 8003, 401 para chat/estáticos sin clave, 404 para admin/respaldos/`.env`
y 400 para un host ajeno. Los procesos de `iniciar_demo.py` tienen modo HTTPS,
host y puerto previstos. No se leyó ni registró la contraseña del usuario.
**Conservar este servidor del usuario: no detenerlo como si fuera el ensayo.**
Serve y Funnel siguen vacíos; falta exclusivamente autorización final de
publicación y la validación posterior de HTTPS público/teléfono.

Si MySQL/Ollama/Docker ya están activos, no reiniciarlos. El estado se consulta
con `scripts/demo/EstadoDemo.ps1`; el buscador se verifica con
`venv\Scripts\python.exe -B iniciar_buscador.py` cuando haga falta. No ejecutar
ingestas, migraciones o benchmarks en paralelo con la prueba móvil.

## Comando exacto propuesto — todavía NO ejecutado

Después de confirmar el arranque privado y recibir autorización final, comprobar
nuevamente que Serve/Funnel no hayan cambiado y ejecutar en primer plano:

```powershell
& "$env:ProgramFiles\Tailscale\tailscale.exe" funnel --https=443 http://127.0.0.1:8003
```

Se publica exclusivamente el proxy HTTP al chat protegido; no se usan opciones
`--tcp`, otros destinos, puertos del router ni `--bg`. El comando es compatible
con la ayuda de la versión instalada y la
[CLI oficial de Tailscale](https://tailscale.com/docs/reference/tailscale-cli/funnel).
Si aparece un Serve/Funnel nuevo antes de activarlo, detener el procedimiento;
no reemplazarlo, borrarlo ni ejecutar reset.

La primera activación puede pedir aprobación de HTTPS/Funnel en la cuenta de
Tailscale. No confundir esa aprobación de cuenta con UAC de Windows. Si requiere
elevación de Windows o cambios de firewall, detenerse sin solicitarlos.

Dirección **prevista**, todavía no una URL públicamente verificada:
`https://xato.taila70665.ts.net/chat/`.

## Apagar solamente esta publicación

Ctrl+C en la consola que ejecuta el comando Funnel. Si fuera necesario:

```powershell
& "$env:ProgramFiles\Tailscale\tailscale.exe" funnel --https=443 off
& "$env:ProgramFiles\Tailscale\tailscale.exe" funnel status --json
```

Se retirará únicamente la publicación propia en HTTPS 443. No usar `tailscale
down`, logout, reset ni detener su servicio o Chrome Remote Desktop. Después,
Ctrl+C en la consola de LitMate sólo si se quiere detener también la demo.

## Validación posterior desde el teléfono

Sólo después de autorizar y activar:

1. Comprobar desde el servidor HTTPS/certificado, acceso sin clave, clave
   incorrecta y rutas sensibles. No declarar publicación exitosa sólo por obtener
   un HTTP 200.
2. En el teléfono desactivar Wi-Fi y la VPN Tailscale; usar datos móviles y
   navegador privado, sin aceptar excepciones de certificado.
3. Entrar en la URL real que devuelva Funnel. Usuario `demo`, clave elegida en la
   consola. Esto es el diálogo de autenticación del navegador, no `/login/`.
4. Identificar el libro por planeta/rosa; pedir dos novelas de fantasía en español;
   comprobar portadas, tarjetas y botones; preguntar «Cuéntame más del segundo».
5. Pedir una trama que necesite generar/verificar, observar progreso antes de la
   respuesta y conservar el contexto en un seguimiento. Contrastar con los
   eventos/timing registrados desde el servidor.
6. Confirmar que MySQL, Ollama y SearXNG no aparecen como rutas o destinos del
   Funnel. Esto no cambia ni certifica su acceso privado previo por Tailscale.
7. Registrar errores reales de TLS, autenticación, SSE, imágenes o contexto;
   corregirlos y repetir antes de considerar completada la publicación.

La publicación permanecerá **pendiente** hasta la autorización explícita y la
comprobación desde esa otra conexión. El control remoto del PC se conserva.
