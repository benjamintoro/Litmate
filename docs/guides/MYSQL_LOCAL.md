> Los comandos de esta guía se ejecutan desde la raíz del proyecto, junto a `manage.py`.

# MySQL local y respaldo de LitMate

El repositorio bibliográfico posterior añade cinco tablas mediante
`core.0008_bibliographic_repository`. El primer lote dejó 41 tablas y 3.273 filas,
con todas las 2.945 filas originales preservadas. El arranque sigue siendo el
mismo. Consulta la [guía de conocimiento MySQL/RAG](../architecture/KNOWLEDGE_REPOSITORY.md)
y el [informe del lote](../../reports/knowledge_20261028/README.md). Las cifras
de importación y activación originales de las secciones siguientes son históricas.

## Arranque local explícito, verificado el 28/10/2026

El servidor de desarrollo quedó iniciado en **http://127.0.0.1:8000/** con el alias Django `default` conectado realmente a `litmate_db`, MySQL 8.0.46, mediante mysqlclient. La configuración guardada de TiDB no se reemplazó. Para volver a iniciar MySQL local en una terminal nueva:

```powershell
Set-Location 'G:\Proyecto\Litmate'
.\venv\Scripts\python.exe -B iniciar_mysql_local.py --http-desarrollo --puerto 8000
```

Introduce la contraseña MySQL únicamente en la entrada oculta. No se ejecutan importaciones, migraciones ni limpieza de tablas. No inicies un segundo servidor en el mismo puerto; detén antes el anterior o indica otro puerto de desarrollo, por ejemplo `--puerto 8001`.

El lanzador configura sólo su proceso:

```text
DB_ENGINE=mysql
DB_MYSQL_DRIVER=mysqlclient
DB_NAME=litmate_db
DB_USER=litmate_app
DB_HOST=127.0.0.1
DB_PORT=3306
DB_SSL_CA=
DB_PASSWORD=(entrada local oculta; nunca escribirla en este documento)
```

`--http-desarrollo` fija además `DEBUG=True` exclusivamente en ese proceso, que escucha sólo en loopback. Es necesario para HTTP de desarrollo cuando el entorno hereda `DEBUG=False` y cookies `Secure` de producción. CSRF sigue habilitado: se comprobó 403 sin token y 200 con token válido. No modifica el modo de producción ni sirve para un despliegue público HTTPS.

`DB_ENGINE` prevalece sobre `USE_SQLITE`. `DB_SQLITE_PATH` sólo selecciona un archivo cuando el motor es SQLite. La contraseña local puede suministrarse opcionalmente mediante `LITMATE_MYSQL_PASSWORD` en el entorno temporal; el lanzador nunca reutiliza silenciosamente la contraseña TiDB de `DB_PASSWORD`.

Para repetir la comprobación real de páginas, SSE y memoria conversacional:

```powershell
.\venv\Scripts\python.exe -B iniciar_mysql_local.py --solo-verificar --http-desarrollo
```

Cada verificación crea una sesión anónima normal en MySQL y registros temporales normales en los almacenes auxiliares de IA. No los elimina para falsear los conteos. El verificador toma como referencia el estado actual y no exige que la actividad nueva coincida con una instantánea antigua. Para verificar y después dejar el servidor funcionando, usar `--verificar-y-servir` en lugar de `--solo-verificar`.

Resultados y limitaciones de esta activación: `reportes/mysql_activacion_20261028/resultados.md`. Se conservaron 179 usuarios, 55 libros, 50 conversaciones autenticadas importadas y 190 mensajes. Dos conversaciones de comprobación anónimas añadieron dos filas `django_session`: total observado 2.945 filas. Las demás tablas conservaron sus huellas.

### Regresar a la selección anterior

Detén el lanzador con Ctrl+C/Ctrl+Break en su terminal y abre una terminal nueva sin las variables locales anteriores. Como `.env` quedó intacto, `python manage.py runserver` vuelve a seleccionar la configuración guardada anterior (TiDB en este proyecto). No hay transferencia ni sincronización automática de datos nuevos hacia TiDB.

Si necesitas detener el servidor que quedó iniciado desde Codex, comprueba primero que el proceso del puerto corresponda al lanzador:

```powershell
$litmateListener = Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort 8000 -State Listen
$litmateProcess = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $litmateListener.OwningProcess)
if ($litmateProcess.CommandLine -notlike '*iniciar_mysql_local.py*') {
    throw 'El puerto pertenece a otro proceso; no se detiene.'
}
Stop-Process -Id $litmateProcess.ProcessId
```

Ese comando detiene el servidor, no borra bases. Conserva MySQL con las nuevas sesiones; no restaures una copia vieja para regresar. Si hubiera nuevas escrituras de usuarios, respáldalas antes de decidir cuál motor será la fuente definitiva.

## Qué se encontró

La configuración efectiva previa utilizaba **TiDB remoto**, no `db.sqlite3`. No había una base Django SQLite en la raíz. Se conservó esa selección: no se editó `.env` ni se cambió automáticamente el destino de la aplicación.

Los datos Django comprenden usuarios, permisos, catálogo, listas, reseñas, favoritos, conversaciones, mensajes, sesiones, suscripciones, pagos, analítica y precios. El origen tenía 36 tablas y 2.943 filas, incluidas 26 entradas de historial de migraciones.

La memoria y recuperación de IA tienen SQLite independientes: `data/literary_memory.sqlite3`, `litmate_knowledge.sqlite3`, `litmate_knowledge_rag.sqlite3`, `litmate_answers.sqlite3`, `litmate_ia_runtime.sqlite3`, `litmate_ia_stream.sqlite3`, `data/adquisicion/ledger.sqlite3` y los tres almacenes de `data/biblioteca/` (catálogo, RAG y vectores). **No pasan a MySQL al cambiar DATABASES**. Ollama/modelos y SearXNG/Docker también permanecen separados. La caché Django observada era LocMem, sin Redis obligatorio; la integración antigua opcional con Pinecone no estaba configurada en settings.

## Respaldo definitivo

`backups/mysql_preparacion_20261028_03/` contiene:

- `database/`: exportación comprimida de todas las tablas, columnas, DDL original, restricciones y próximos IDs.
- `django.sqlite3`: copia portable comprobada contra el origen; conserva claves, filas, relaciones, contraseñas **hasheadas**, sesiones, JSON, fechas, importes y contadores de IDs.
- `files/`: 88 archivos de `data`, `media` y almacenes configurados. Las diez SQLite se respaldaron con la API online de SQLite, incluyendo datos confirmados en WAL. Los demás archivos se comprobaron mediante SHA-256 antes y después de copiarlos.
- `manifest.json`: conteos, huellas de filas y claves, hashes de archivos, procedencia y verificaciones. Los IDs y fechas del historial `django_migrations` se generan al construir el esquema nuevo; se compara el conjunto exacto de migraciones aplicadas. No se confunden esos metadatos con datos de usuarios.

La instantánea de Django usa una transacción de lectura repetible. Cada SQLite auxiliar tiene su propia instantánea: no existe una transacción global entre todos los almacenes. Por ello, detener Django y los trabajadores antes del corte final sigue siendo necesario. El importador rechaza un origen que haya cambiado desde el respaldo.

El primer respaldo `_01` se conserva, pero su copia SQLite no preservaba los contadores reservados de TiDB. `_02` quedó incompleto por un fallo TLS del cliente nativo de Windows al conectar con TiDB; no tiene manifiesto completo y no sirve para importar. Utilizar **`_03`**. No se borraron esas copias.

Los respaldos contienen información privada y están excluidos de Git mediante `backups/`. No contienen `.env` ni su contraseña de conexión. Conservar también una copia privada en otro disco. No usar `backups/.../django.sqlite3` directamente para trabajar: modificarla invalidaría su hash.

```powershell
.\venv\Scripts\python.exe -B preparar_mysql.py verificar --respaldo backups/mysql_preparacion_20261028_03
```

Para crear otra instantánea, usar una carpeta nueva; nunca se sobrescribe una anterior:

```powershell
.\venv\Scripts\python.exe -B preparar_mysql.py respaldo --salida backups/otra_instantanea
```

## Conectar e importar

Desde `G:\Proyecto\Litmate`, sin contraseña en comandos ni argumentos:

```powershell
.\venv\Scripts\python.exe -B preparar_mysql.py comprobar-mysql --respaldo backups/mysql_preparacion_20261028_03
```

El programa pregunta la contraseña mediante `getpass`, con entrada oculta. No la guarda. Los valores predeterminados son `127.0.0.1:3306`, `litmate_db`, `litmate_app`. `LITMATE_MYSQL_PASSWORD` permite automatizar usando únicamente el entorno temporal del proceso, sin reutilizar por accidente la contraseña TiDB de `DB_PASSWORD`.

Con Django y sus trabajadores detenidos:

```powershell
.\venv\Scripts\python.exe -B preparar_mysql.py importar-mysql --respaldo backups/mysql_preparacion_20261028_03 --aplicacion-detenida
```

El importador comprueba respaldo, frescura del origen, destino vacío, MySQL compatible, utf8mb4, InnoDB, modo estricto y colisiones de claves únicas según el cotejamiento real de MySQL, **antes de crear tablas**. Construye directamente el estado final del esquema derivado de las migraciones existentes, sin reproducir operaciones históricas DROP sobre modelos desaparecidos. Restaura los datos ya migrados de la instantánea y registra su historial; no vuelve a ejecutar migraciones de datos. Después copia en orden de dependencias sin desactivar claves foráneas, conserva IDs y próximos contadores y compara tablas, columnas, índices, restricciones, filas, claves y relaciones dentro y después del commit. No ejecuta migraciones en TiDB.

MySQL no revierte DDL como una transacción de datos. Si falla la importación antes del commit, se revierten sus filas, pero el esquema puede permanecer. No se elimina automáticamente. Sólo si quedó el mismo esquema y **cero filas de aplicación** puede reanudarse así:

```powershell
.\venv\Scripts\python.exe -B preparar_mysql.py importar-mysql --respaldo backups/mysql_preparacion_20261028_03 --aplicacion-detenida --reanudar-esquema-vacio
```

Se rechaza la reanudación si existe cualquier fila de aplicación, falta una tabla/índice/restricción o difiere el historial de migraciones. Una base ya importada no se mezcla ni sobrescribe. MySQL 8 usa `information_schema_stats_expiry=0` **sólo en la sesión**, sin cambiar la configuración global ni desactivar controles. TiDB se comprueba mediante el próximo ID reservado de `SHOW CREATE TABLE`, igual que al exportarlo: su `SHOW TABLE STATUS` devolvió 0 para `auth_permission` y no sirve para esa comparación. La comprobación SQLite convierte `sqlite_sequence` (último valor) a próximo ID sumando 1.

Después de una importación exitosa, repetir una comprobación independiente:

```powershell
.\venv\Scripts\python.exe -B preparar_mysql.py verificar-mysql --respaldo backups/mysql_preparacion_20261028_03
```

Los informes nuevos `mysql_*.json` quedan en `reportes/mysql_20261028/`, sin datos de filas ni contraseñas y sin modificar el respaldo. Los informes iniciales dentro del directorio del respaldo se conservan. `imported=true` y la comparación posterior exitosa son las evidencias de traslado; una mera conexión o `makemigrations --check` no prueban una migración. Las trazas registran conteos, máximo ID numérico, próximo ID y etapa/transacción antes y después del commit.

El cotejamiento local observado fue `utf8mb4_0900_ai_ci`, que compara texto de manera distinta de SQLite y de cotejamientos binarios. El preflight comprueba las claves únicas con las reglas del propio servidor. Ante una colisión se aborta, sin fusionar registros; debe revisarse el cotejamiento antes de reintentar.

## Selección del motor, sin editar .env

`litmate_project/database_settings.py` acepta `DB_ENGINE=sqlite|mysql`; esta variable tiene prioridad sobre `USE_SQLITE`. En ausencia de `DB_ENGINE` se respeta la selección anterior por `USE_SQLITE`/`DB_HOST`. Un fallo de MySQL **no provoca un cambio silencioso a SQLite**.

MySQL local usa `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` y opcionalmente `DB_SSL_CA`. El puerto local predeterminado es 3306; se conserva 4000 para la configuración remota anterior. Las conexiones usan utf8mb4, modo estricto y tiempos de espera acotados. Django documenta estos requisitos y las diferencias de cotejamiento en sus [notas de MySQL](https://docs.djangoproject.com/en/5.2/ref/databases/#mysql-notes).

`DB_MYSQL_DRIVER=auto` conserva PyMySQL para el remoto anterior y prefiere `mysqlclient` en local. Puede fijarse `mysqlclient` o `pymysql` para un proceso. Ambos están declarados; no se instaló nada durante esta tarea. El proceso de transferencia desde TiDB puede usar PyMySQL para ambos alias; el cliente nativo local se comprobó por separado. No se deshabilita TLS para solucionar el fallo del cliente Windows con TiDB.

Después de validar la importación, abrir una sesión local temporal para ejecutar Django con MySQL nativo:

```powershell
$litmateCredential = Get-Credential -UserName 'litmate_app' -Message 'MySQL local de LitMate'
$litmateKeys = @('DB_ENGINE', 'DB_MYSQL_DRIVER', 'DB_NAME', 'DB_USER', 'DB_PASSWORD', 'DB_HOST', 'DB_PORT', 'DB_SSL_CA')
$litmatePrevious = @{}
foreach ($litmateKey in $litmateKeys) {
    $litmatePrevious[$litmateKey] = [Environment]::GetEnvironmentVariable($litmateKey, 'Process')
}
try {
    $env:DB_ENGINE = 'mysql'
    $env:DB_MYSQL_DRIVER = 'mysqlclient'
    $env:DB_NAME = 'litmate_db'
    $env:DB_USER = 'litmate_app'
    $env:DB_HOST = '127.0.0.1'
    $env:DB_PORT = '3306'
    $env:DB_SSL_CA = ''
    $env:DB_PASSWORD = $litmateCredential.GetNetworkCredential().Password
    .\venv\Scripts\python.exe manage.py check --database default
    if ($LASTEXITCODE -ne 0) { throw 'No se inicia Django: falló la comprobación.' }
    .\venv\Scripts\python.exe manage.py runserver
} finally {
    foreach ($litmateKey in $litmateKeys) {
        [Environment]::SetEnvironmentVariable($litmateKey, $litmatePrevious[$litmateKey], 'Process')
    }
    $litmateCredential = $null
}
```

La contraseña sólo pasa por memoria y el entorno del proceso y sus hijos; no se imprime, no va en el historial del comando ni en un archivo. Al detener el servidor se restaura el entorno anterior. Una selección permanente puede configurarse localmente más adelante, después del corte validado; esta tarea no modificó `.env`.

## Google Books con confirmación de ausencia de facturación

Tras comprobar que el proyecto de Google Cloud asociado a la clave local **no tiene una cuenta de facturación vinculada**, el arranque permite una activación explícita y reversible:

```powershell
.\venv\Scripts\python.exe -B iniciar_mysql_local.py --http-desarrollo --google-books-sin-facturacion
```

El parámetro declara `LITMATE_GOOGLE_BOOKS_CONFIRMED_NO_BILLING=True` y `LITMATE_USE_GOOGLE_BOOKS_API=True` sólo dentro de ese proceso. Reutiliza la clave ya configurada localmente; no la recibe en la línea de comandos, no modifica `.env`, no activa facturación ni verifica automáticamente la consola de Google Cloud. El usuario confirmó esa condición el 29 de octubre de 2026. Al omitir el parámetro se conserva la configuración habitual. Detén el servidor anterior con Ctrl+C antes de arrancarlo de nuevo, para no ocupar dos veces el mismo puerto.

La API sigue sujeta a disponibilidad y cuotas. Ante errores de clave, acceso o cuota, el asistente conserva sus fuentes alternativas y no amplía la consulta fallida. No es una búsqueda ilimitada ni una descarga de textos completos.

## Alternativa SQLite

Para comprobar o usar el estado del respaldo, crear **una copia nueva de trabajo**:

```powershell
.\venv\Scripts\python.exe -B preparar_mysql.py verificar --respaldo backups/mysql_preparacion_20261028_03
if ($LASTEXITCODE -ne 0) { throw 'Respaldo no válido.' }
if (Test-Path -LiteralPath '.\db_local_restaurada.sqlite3') { throw 'El destino ya existe.' }
Copy-Item -LiteralPath '.\backups\mysql_preparacion_20261028_03\django.sqlite3' -Destination '.\db_local_restaurada.sqlite3'
$env:DB_ENGINE = 'sqlite'
$env:DB_SQLITE_PATH = 'db_local_restaurada.sqlite3'
.\venv\Scripts\python.exe manage.py check --database default
```

Esas dos variables sólo afectan a esa terminal. Para volver a la selección del archivo .env, cerrar la terminal o restaurar sus valores anteriores. **Si ya hubo nuevas escrituras en MySQL, no volver a una copia SQLite antigua:** detener la aplicación y respaldar/exportar primero el estado MySQL actual mediante el mismo procedimiento. No hay sincronización bidireccional automática.

## Pruebas

```powershell
.\venv\Scripts\python.exe -B verificar_proyecto.py core.test_database_transfer
.\venv\Scripts\python.exe -B verificar_proyecto.py core
.\venv\Scripts\python.exe -m pip check
.\venv\Scripts\python.exe manage.py makemigrations --check --dry-run
```

`verificar_proyecto.py` usa SQLite temporal y no migra la base del proyecto. Las pruebas ejercitan migraciones reales en archivos temporales, WAL, corrupción, contraseñas hasheadas, claves, M2M, JSON, importes, contadores, selección de controlador y rechazo de destinos ocupados. Los informes de esta tarea distinguen esas pruebas aisladas de la conexión/importación MySQL real.
