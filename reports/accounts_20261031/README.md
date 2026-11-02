# Cuentas persistentes, cuotas y chat móvil — versión preparada, no publicada

## Alcance y protección de la versión actual

Base inicial de Git: `f38650a`. La publicación HTTPS existente conserva su
perfil de demostración. No se reinició Waitress 8003, Funnel, Windows, Docker,
Ollama, MySQL ni el escritorio remoto. Los reinicios del ensayo afectan sólo
al servidor propio 8006. No se modificó .env, no hubo instalaciones, cobros,
push, commits ni eliminación/movimiento de archivos existentes.

La implementación es un **perfil optativo**. El comando anterior, sin
`--cuentas-db`, conserva la demo de sólo lectura. La preparación del almacén
persistente real y el cambio del servidor público requieren autorización.

## Diagnóstico real

- `auth.User` ya existe, con formularios y autenticación Django; no se cambia
  AUTH_USER_MODEL ni se reemplazan sus migraciones.
- Hay 179 usuarios, 158 perfiles y 157 suscripciones en MySQL local. Se
  conservaron mediante una copia de ensayo, sin editar el origen.
- La demo HTTPS utiliza sesiones de archivos y genera una clave de firma
  aleatoria por arranque; registro/login/contacto son vistas previas.
- `core/quotas.py` usa caché temporal y una clave diaria por IP para invitados.
  No ofrece consumo durable ni la consulta única total solicitada.
- El control de cuotas está desactivado en la configuración auditada. Si se
  habilitara el control antiguo, su diccionario y el fallback de nombre de campo
  podían aplicar límites diferentes de los de PlanSuscripcion.
- El asistente tenía rutas de saludos y rechazos anteriores al control antiguo;
  la comprobación antes de generar y el incremento posterior no constituían una
  reserva atómica. Finalizar el transporte tampoco aseguraba una transacción
  conjunta de historial y consumo.
- El historial literario actual utiliza ConversacionIA/MensajeIA; también existe
  HistorialChatbot legado. No son el índice RAG ni conocimiento literario global.
- Transbank, Mercado Pago y PayPal tienen servicios/callbacks y pruebas de
  seguridad existentes. Esto no acredita configuración operativa, cobros reales
  o confirmación externa de los registros históricos.

## Planes comprobados, no inventados

`auditoria_solo_lectura.json` procede de SELECT sobre litmate_db, sesión read-only.

| Nombre / slug | Precio | Moneda | Periodo | Consultas diarias | Beneficios configurados | Pago | Estado de este perfil |
| --- | ---: | --- | --- | ---: | --- | --- | --- |
| Gratuito / gratis | 0 | CLP | Mensual sin cobro | 15 | IA estándar; 20 favoritos configurados | No requiere tarjeta | Cuenta, activación y cuota funcionales en ensayo |
| Lector Pro / lector-pro | 4990 | CLP | Mensual | 100 | Flag IA avanzada; 100 favoritos | Confirmación verificable del proveedor | Contratación desactivada |
| Lector VIP / lector-vip | 9990 | CLP | Mensual | 0 = ilimitadas | Flag IA avanzada; favoritos 0 = sin límite | Confirmación verificable del proveedor | Contratación desactivada |

En el perfil nuevo, pantalla y cálculo de cuota leen **la misma tabla
PlanSuscripcion y el campo limite_consultas_ia_diarias**. No hay un segundo
diccionario comercial. La tabla privada se inicializa con el catálogo real
auditado. Los beneficios avanzados/favoritos son configuración histórica, no
funcionalidades nuevas que se hayan implementado en este lote.

## Arquitectura implementada

- `litmate_project/reader_settings.py` hereda las protecciones del perfil HTTPS,
  mantiene MySQL protegido y añade un alias SQLite privado `accounts`.
- `reader_accounts/router.py` dirige User/auth, contenttypes, sesiones,
  suscripciones, PerfilUsuario, AsistenteIA y los historiales compatibles al
  almacén privado. El catálogo y KB/RAG conservan su conexión existente. El
  perfil instala también la protección read-only de las conexiones MySQL.
- `reader_accounts/models.py` añade sólo AccountEmail, UsageBucket y
  QueryOperation. Migración nueva `reader_accounts/migrations/0001_initial.py`.
  No se aplicó al almacenamiento real.
- En funcionamiento autorizado, cuentas, sesiones, ledger y clave protegida
  quedan bajo `data/accounts`, fuera de directorios de prueba. El runtime
  persistente reutiliza prepare_workspace, con copias aisladas de los almacenes
  existentes. El arranque nunca ejecuta migraciones ni importa usuarios.
- La clave de firma se protege con DPAPI del usuario Windows, se reutiliza al
  reiniciar y no se imprime. Su respaldo debe acompañar a la base privada y
  restaurarse bajo el mismo usuario Windows. Si falta una clave de una base ya
  utilizada, el lanzador se detiene en vez de regenerarla silenciosamente.
- La cookie de visitante es aleatoria, firmada, HttpOnly y Secure en HTTPS;
  independiente de la sesión Django. No se utiliza IP como identidad de cuota
  ni una huella del dispositivo. Los límites de recursos también separan
  visitantes identificados detrás de la misma IP de Funnel.
- User sigue usando el hasher oficial de Django y sus validadores. AccountEmail
  agrega unicidad transaccional sin alterar el modelo de usuario existente.
- Registro e inicio de sesión redirigen a Planes. El gratuito se selecciona
  mediante POST con CSRF y se activa sin proveedor, tarjeta o pago. Repetir la
  selección no reinicia consumo. Un contrato pagado activo no se reemplaza
  silenciosamente mediante el botón gratuito.
- No se migran ni se exponen las relaciones de favoritos/listas/lectura con el
  catálogo protegido: esas acciones se ocultan sólo en el perfil nuevo. Los
  datos originales permanecen intactos. No se copian fotos personales.

## Política de cuota, concurrencia y errores

1. Invitado: una consulta **total por identidad reconocida**, periodo lifetime.
   Cuenta: periodo diario America/Santiago y límite del modelo del plan.
2. Validación de JSON/identidad y reserva persistente antes de llamar al motor.
   SQLite BEGIN IMMEDIATE, incremento condicional y claves únicas actor/periodo
   y actor/request_id impiden exceder el límite por concurrencia.
3. Cada envío aceptado cuenta, incluidos saludos y aclaraciones. No se excluyen
   rutas rápidas del control. Cambiar fecha, cuota o plan desde el navegador no
   modifica el derecho calculado en servidor.
4. Mismo request_id y misma pregunta: replay o respuesta «en curso»; no una nueva
   inferencia ni otro consumo. Otro texto con el mismo ID se rechaza.
5. Finalización factual obligatoria en este perfil, aunque el cliente envíe
   progress=false. El motor y su auditoría se reutilizan, sin adelantar hechos.
6. Historial privado y confirmación de cuota comparten una transacción. Un fallo
   de almacenamiento revierte los mensajes; el reintento recupera el resultado
   ya auditado mediante el transporte existente y un marcador por operación.
   No duplica turnos ni cobra dos veces. No se repite generación/auditoría.
7. Un fallo técnico antes de entregar respuesta libera la reserva; si una
   operación queda sin finalizar, caduca a los 120 segundos y se reconcilia al
   consultar el consumo o reservar de nuevo. Una respuesta parcial entregada
   puede contar. Una regeneración manual es una operación nueva.
8. No se permite consultar si el ledger no está disponible: falla cerrado, con
   mensaje seguro. No se concede una cuota inventada desde una caché de respaldo.
9. Cookie eliminada/navegador/dispositivo distintos pueden generar otro invitado;
   no se promete identificar infaliblemente a una persona anónima. La cuota de
   una cuenta sí se comparte entre sus dispositivos autenticados.

## Pagos: bloqueo efectivo

El perfil no publica iniciar-pago, callbacks, simulador ni acciones de cobro.
Las tarjetas de planes pagados indican contratación no disponible.

`reader_accounts/payments.py` no confía en los estados históricos activa/completado
por sí solos. El acceso pagado exige recibo firmado de confirmación del proveedor,
coincidente con usuario, plan, referencia, importe, moneda e historial de pago.
Actualmente **ninguna ruta emite ese recibo**: falta habilitar y probar la
integración con un proveedor autorizado. No se activaron pagos reales ni se
presentaron fixtures como confirmaciones bancarias.

Los registros pagados históricos se preservan en el ensayo, pero no se convierten
automáticamente en derechos de pago verificados. La interfaz informa del pendiente
y evita que el titular contrate otra vez por confusión. La activación gratuita
funciona independientemente de los proveedores.

## Copia de cuentas existentes y recuperación

`copia_cuentas_final_ensayo.json` verifica una copia **únicamente en .testtmp**:

| Datos | Origen | Copia | Comparación |
| --- | ---: | ---: | --- |
| Usuarios | 179 | 179 | Contenido e IDs iguales |
| Perfiles | 158 | 158 | Contenido e IDs iguales |
| Planes | 3 | 3 | Contenido e IDs iguales |
| Configuración de asistente | 1 | 1 | Contenido e IDs iguales |
| Conversaciones | 50 | 50 | Contenido e IDs iguales |
| Mensajes IA | 190 | 190 | Contenido e IDs iguales |
| Suscripciones | 157 | 157 | Contenido e IDs iguales |
| Historiales de pago | 42 | 42 | Datos históricos, no nuevos cobros |
| Historial de chat legado | 5 | 5 | Contenido e IDs iguales |

Permisos y grupos se reconcilian por claves lógicas. Los IDs de usuario y sus
relaciones permanecen iguales; los contadores nunca se bajan respecto del origen.
quick_check OK y cero errores FK. Se detectó un grupo de correos repetidos:
no se fusionó ni modificó ningún usuario; el login nuevo exige nombre de usuario
para esa ambigüedad, evitando seleccionar una cuenta arbitraria por email.

No se importaron sesiones firmadas con una clave anterior. Los usuarios deberán
iniciar sesión en el perfil nuevo. El consumo antiguo estaba desactivado y no
tenía ledger durable que transferir; no se inventaron saldos históricos.

La copia final no se utilizó para registrar usuarios sintéticos o pruebas HTTP.
Su SHA-256 quedó registrado. No promover `reader-stage-20261031`: contiene
actividad sintética y es sólo el servidor de ensayo.
La base de cuentas copiada ocupa 557.056 bytes, sin incluir la clave protegida
ni los índices bibliográficos, que conservan sus almacenes actuales.

## Pruebas y evidencias

- `aceptacion_cierre.json`: **41 pruebas dirigidas aprobadas**, sólo SQLite
  aislado. Concurrencia de invitado y última unidad diaria autenticada, replay,
  expiración, cambio de día/plan, duplicados, aislamiento, validadores/hasher,
  CSRF/cookies HTTPS, recibos pagados, fallos de ledger y recuperación atómica.
- `compatibilidad_final.json`: **42 pruebas existentes aprobadas**, incluyendo
  demo, cuotas antiguas y pagos con proveedores simulados. Ningún cobro real.
- `regresiones_demo_final.json`: **210 regresiones existentes aprobadas**.
- **246 comprobaciones JS del chat, 4 de reintentos y 4 del control de scroll**
  aprobadas. Los cuatro casos nuevos reproducen la carrera entre un gesto de
  lectura y una escritura SSE, su persistencia, volver al final y un envío nuevo.
- `http_sse_reinicio.json`: HTTP/SSE real en 8006, cuenta sintética, gratuito,
  bloqueo de segunda consulta invitada, dos recomendaciones y seguimiento.
  Reinicio sólo de ese servidor: sesión/plan/consumo/contexto conservados;
  logout/login no restablece consumo. `http_sse_final.json` confirma **12 de 12
  criterios** sobre el cierre transaccional final, incluso con progress=false.
- Matriz de navegador Chromium/Edge con mensajes y tarjetas reales: 320, 360,
  375, 390, 414, 430, tablet 768, horizontal 844 y escritorio 1280. Se detectaron
  y corrigieron gutters negativos, pie no ajustado, altura máxima heredada y
  desplazamiento suave que interfería con la lectura. Ver resultados por intento;
  no interpretar el código de salida antiguo como aprobado si el JSON marca fallo.
  El comprobador ahora falla si algún criterio móvil falla. **movil_08/captura.json:
  14/14 criterios aprobados, cero excepciones JavaScript**, dos portadas cargadas,
  las nueve dimensiones sin desbordamiento, lectura anterior conservada y campo
  visible al reducir el viewport de 844 a 360 px. Capturas móvil/escritorio
  inspeccionadas. Intentos fallidos anteriores se conservan como evidencia.

El fallo de lectura era una carrera: el cliente compartido escribía scrollTop
antes de entregar el evento de desplazamiento del usuario. El nuevo módulo
protege únicamente la instancia del chat del perfil optativo; no modifica el
prototipo global ni el JavaScript compartido servido a la demo. El viewport y
los dos contenedores de scroll usan desplazamiento inmediato en este perfil.

`preservacion_cierre.json` comprueba hashes originales de .env/memoria/RAG sin
cambios, los mismos usuarios/planes/conversaciones en MySQL, proxy Funnel
idéntico a 127.0.0.1:8003 y puerta Basic vigente (401 en páginas; 404 en
admin/.env/backups). MySQL80, Tailscale y chromoting siguen Running. Se utilizó
el Host HTTPS autorizado al comprobar loopback; otro Host es rechazado con400.

Los ensayos de backend real emplean rutas locales rápidas existentes, no un
benchmark de todas las respuestas del LLM. La emulación no equivale a pruebas
físicas de Chrome Android/Safari. La publicación HTTPS nueva no se ha probado,
porque todavía no está autorizada su activación.

`cierre_ensayo.json`: detenido únicamente el servidor propio8006 después de
las pruebas. Waitress público8003 sigue respondiendo con autenticación y
Funnel permanece activo. Ningún servicio remoto fue detenido.

## Manual y limpieza conservadora

`MANUAL_DE_USUARIO_LITMATE.md`: 35 secciones y aproximadamente 3.600 palabras en
español. Distingue demo actual/perfil preparado y no anuncia pagos, recuperación,
favoritos o dispositivos no comprobados como disponibles.

Se reutilizó `scripts/repository/inventory.py`. Los inventarios de este directorio
clasifican código/configuración, datos protegidos, documentación operativa,
evidencia y candidatos reproducibles. Se identificaron aproximadamente 4,3 MB
de cachés Python; no se garantiza que estén libres mientras hay procesos activos.
`searxng/compose.env` es configuración necesaria referenciada por el arranque y
no se leyó ni se cambió. El parche histórico permanece pendiente de revisión.

**Cero archivos existentes borrados o movidos.** Backups, modelos, bases,
volcados, RAG y evidencia de la defensa se conservan. Los informes internos no
se publican por el gateway. Las nuevas reglas de .gitignore protegen sólo
data/accounts y claves DPAPI; no ocultan migraciones ni código necesario.

## Despliegue propuesto — no ejecutar sin autorización

1. Verificar respaldo y estado de servicios, sin detener Tailscale/Funnel.
2. Preparar una copia de ensayo NUEVA y reciente con clone_stage (destino estricto
   .testtmp), comparar origen/destino y conservar recibo y firma protegida.
3. Tras autorización, `scripts/accounts/promote_stage.py` prepara una base NUEVA
   en data/accounts. Exige el recibo, huella exacta, ausencia de consumo/sesiones
   de ensayo y destino inexistente; verifica de nuevo todos los datos. No inicia
   servicios ni escribe MySQL. La promoción real no se ha ejecutado.
4. Reiniciar sólo Waitress desde la consola del operador y usar el comando nuevo
   siguiente. Debe mantener la misma contraseña Basic privada, introducida sólo
   en el prompt; no se conoce ni se cambia su valor.

```powershell
.\venv\Scripts\python.exe -B iniciar_demo.py --modo https --host xato.taila70665.ts.net --puerto 8003 --cuentas-db data/accounts/users.sqlite3 --carpeta data/accounts/runtime --comprobar-despliegue --google-books-sin-facturacion
```

El comando no ejecuta migraciones. No aplicar migrate a MySQL. No sincronizar
simultáneamente cuentas nuevas hacia los dos almacenes: después de aprobar la
transición, la base privada sería el único escritor para cuentas/cuotas; MySQL
conservaría su copia original protegida y el catálogo. Las sesiones previas de
demo pueden invalidarse al cambiar de perfil; conservar sus archivos no equivale
a migrar automáticamente el hilo.

5. Probar desde el teléfono: invitado una vez, segunda bloqueada, registro/login,
   Planes, Gratis, consumo, tarjetas, seguimiento y navegación. Probar teclado real
   y Safari si está disponible. No declarar éxito público antes de esa prueba.

### Reversión de funcionamiento

Con autorización del operador, detener sólo el nuevo Waitress y regresar al
comando anterior, sin cuentas-db:

```powershell
.\venv\Scripts\python.exe -B iniciar_demo.py --modo https --host xato.taila70665.ts.net --puerto 8003 --carpeta .testtmp/demo-https-20261103 --comprobar-despliegue --google-books-sin-facturacion
```

No borrar la base privada ni su clave, no restaurar Git destructivamente y no
importar hacia MySQL. La reversión vuelve a la demo; las cuentas nuevas quedan
conservadas para reactivar el perfil posteriormente. El proxy sigue apuntando a
8003, sin cambios de Funnel/firewall/escritorio remoto.

## Pendientes explícitos

- Autorización y preparación del almacenamiento persistente real; despliegue y
  prueba HTTPS móvil del perfil nuevo.
- Proveedor de pagos/sandbox autorizado, emisión del recibo tras verificación
  auténtica y revisión de las suscripciones históricas pagadas.
- Recuperación/verificación por correo: se mantiene backend dummy, no envía.
- Favoritos, listas, lectura, fotos personales, eliminación de cuenta y una
  interfaz más completa de historial requieren trabajos posteriores de separación
  de datos. No se publicaron accesos al almacenamiento original para aparentarlos.
- Prueba física de teclado Android/Safari. Voz externa sigue desactivada; se
  conserva el fallback del navegador y no se promete audio audible en headless.
- Política futura de retención del contenido de replay. No hay borrado automático
  de datos privados ni limpieza efectiva de cachés sin autorización.

## Repetir comprobaciones aisladas

```powershell
.\venv\Scripts\python.exe -B -m scripts.accounts.test_accounts --output reports/accounts_20261031/aceptacion_otro_ensayo.json
node static/js/verificar_chat_seguro.js
node scripts/demo/test_finalize_retry.cjs
node scripts/accounts/test_reader_scroll.cjs
```

El informe de salida debe ser nuevo. Estos tests usan SQLite temporal o fixtures;
no son cobros ni una prueba de calidad general del modelo. Para HTTP/navegador,
usar exclusivamente el servidor propio de ensayo en8006 y carpetas nuevas dentro
de reports; sus cuentas sintéticas no deben trasladarse al almacén real.

## Archivos principales

- `reader_accounts/`: router, modelos/migración, identidad, cuota, autenticación,
  transporte/finalización, comprobación de recibos y pruebas.
- `litmate_project/reader_settings.py`, `iniciar_demo.py`, `core/demo_gateway.py`.
- `core/literary_ai_views.py`: identidad de rate-limit por perfil, transporte
  protegido y extracción reutilizable de persistencia; no cambia el motor factual.
- `core/views.py`: no consultar listas privadas del MySQL original desde cuentas
  separadas. Plantillas originales con condiciones sólo del perfil nuevo.
- `templates/accounts/`, `static/css/reader-mobile.css`, `static/js/reader-transport.js`.
- `scripts/accounts/`: auditoría read-only, preparación/copia/promoción controladas,
  aceptación y ensayo HTTP/SSE. `scripts/demo/capturar_demo.*`: matriz reproducible.
- `.gitignore`, manual, este informe e historial de continuidad.
