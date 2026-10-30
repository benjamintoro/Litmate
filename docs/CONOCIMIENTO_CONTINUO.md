# Conocimiento continuo local

LitMate reutiliza sus almacenes e importadores. No se instalaron Celery, Redis, otro modelo ni paquetes nuevos. No hay entrenamiento autónomo ni APIs de pago.

## Flujo y almacenamiento

1. Al finalizar una respuesta, `literary_ai_views.remember` llama a `continuous_knowledge.observe_answer`.
2. Sólo una identidad pública ya admitida y no ambigua puede generar una tarea. Se guardan ID, categoría y código técnico; no se guardan preguntas, respuestas, nombres de lectores ni el contenido de una corrección.
3. `memory_jobs` conserva requisito, proveedor, prioridad, estado, intentos, próxima ejecución, lease y fechas de verificación. La restricción existente evita tareas duplicadas.
4. `actualizar_conocimiento --continuous` ejecuta **un lote y termina**. Reutiliza evidencia vigente; si falta, emplea los adaptadores autorizados existentes.
5. `remember_evidence` admite únicamente fuentes con identidad, política de almacenamiento, licencia y pruebas literales válidas. Mantiene versiones, conflictos, FTS y entidades en su transacción.
6. El índice auxiliar BM25 se reconstruye mediante staging atómico sólo cuando cambia la revisión o la política de lectura. Reutiliza la infraestructura RAG; no calcula embeddings en este modo.
7. MySQL conserva referencias `KBRelation(predicate='memory_evidence')` cuando hay una URL exacta de catálogo existente. `KBProjection` registra el avance. **Los pasajes, roles y su procedencia siguen en el almacén narrativo SQLite existente**; no se duplicaron tablas ni se migraron todos los hechos a MySQL.

Tablas reutilizadas: `memory_works`, `memory_aliases`, `memory_entities`, `memory_sources`, `memory_assertions`, `memory_history`, `memory_conflicts`, `memory_jobs`, `memory_usage`, `memory_meta` y `memory_fts`; además de los modelos `KBRecord`, `KBRelation` y `KBProjection` existentes. No hay migración de esquema nueva.

Las categorías incluyen identidad/metadatos, sinopsis/argumento, personajes, relaciones, acontecimientos, temas/géneros, contexto histórico y adaptaciones. Admitir una categoría no garantiza encontrarla: personajes requieren papeles publicados y las secciones de contexto o adaptaciones no se usan como argumento. Obras desconocidas o identidades ambiguas no generan hechos ni una identidad pública inventada; primero deben resolverse mediante la búsqueda bibliográfica habitual.

## Ejecutar manualmente con MySQL local

```powershell
Set-Location G:\Proyecto\Litmate
.\venv\Scripts\python.exe -B -m scripts.knowledge.continuous_worker
```

Solicita la contraseña de forma oculta y configura MySQL sólo en ese proceso. No lee como contraseña local la configuración remota de TiDB ni modifica `.env`.

Por defecto: cinco obras para revisar, dos tareas, presupuesto de 30 segundos, ocho segundos por tarea, pausa de dos segundos, una lectura narrativa por tarea y sin llamadas al LLM. Un lote explícito permite hasta 25 obras, 20 tareas y 120 segundos. No se encolan nuevos títulos indiscriminadamente.

El comando Django subyacente, cuando la terminal ya tiene configurada la conexión prevista:

```powershell
.\venv\Scripts\python.exe -B manage.py actualizar_conocimiento --continuous --max-works 5 --max-jobs 2 --max-seconds 30 --job-seconds 8 --pause 2
```

La proyección SQL es opcional (`--project-mysql`) y rechaza motores remotos: en este lote sólo se habilita para MySQL local. El wrapper anterior la activa con la conexión local explícita.

Los informes del wrapper se crean con nombre nuevo en `reports/continuous_runs/`. Una ejecución fallida no sobreescribe un informe anterior. Los errores de conexión se registran por clase, sin DSN ni contraseñas.

## Límites, pausa y reanudación

- Un lease global impide dos ejecuciones continuas simultáneas. Cada tarea tiene además un token de propiedad; otro trabajador no puede confirmarla con un token vencido.
- Un proceso interrumpido deja tareas recuperables al vencer su lease. El ordenador apagado no cuenta como una ejecución.
- Pausas y backoff se conservan: errores vacíos/sin evidencia esperan al menos 15 minutos; otros fallos usan espera exponencial. Después de cinco fallos nuevos se conserva la tarea para revisión, sin bucle permanente.
- Una nueva carencia sobre una tarea completada conserva una pausa de un día. Una corrección del lector se marca pendiente de comprobación y no se promueve a verdad.
- Demanda agregada y un cursor persistente priorizan obras consultadas y recorren también obras menos populares.
- Prioridad de proceso reducida en Windows; máximo de RAM del proceso de 512 MiB y reserva de disco de 10 GiB comprobados entre trabajos. Son controles de admisión, no límites duros del sistema operativo. No incluyen la RAM de MySQL/Ollama ni garantizan cancelar instantáneamente una llamada en curso.
- No se inicia un residente al arrancar Django. El trabajador es independiente del chat.

Detener futuras tareas del lote:

```powershell
New-Item -ItemType File -Path G:\Proyecto\Litmate\data\enrichment.stop -Force
```

El socket en curso conserva su timeout. Para reanudar, elimina **sólo ese marcador** y vuelve a ejecutar el comando:

```powershell
Remove-Item -LiteralPath G:\Proyecto\Litmate\data\enrichment.stop
```

Para desactivar además la observación de carencias en un nuevo proceso Django, establece `$env:LITMATE_AUTO_ENRICHMENT='False'` en esa terminal antes de arrancarlo. No borra trabajos ni conocimiento.

## Programar una vez al día en Windows

**No se creó ninguna tarea programada.** Estos pasos son manuales y requieren tu decisión.

Primero, crea una credencial cifrada con DPAPI, fuera del repositorio y con el mismo usuario Windows que ejecutará la tarea:

```powershell
$credentialDirectory = Join-Path $env:LOCALAPPDATA 'LitMate'
New-Item -ItemType Directory -Path $credentialDirectory -Force | Out-Null
Read-Host 'Contraseña MySQL local' -AsSecureString | ConvertFrom-SecureString | Set-Content -LiteralPath (Join-Path $credentialDirectory 'mysql-password.dpapi') -Encoding ASCII
```

El archivo cifrado queda ligado al usuario y al equipo. No lo copies a Git ni a otro usuario. Para probar el lanzador:

```powershell
& G:\Proyecto\Litmate\scripts\windows\enrich_once.ps1
```

En el Programador de tareas configura manualmente:

1. Una tarea diaria bajo ese mismo usuario.
2. Programa `powershell.exe`.
3. Argumentos `-NoProfile -NonInteractive -WindowStyle Hidden -File "G:\Proyecto\Litmate\scripts\windows\enrich_once.ps1"`.
4. Iniciar en `G:\Proyecto\Litmate`.
5. Ejecutar cuando esté disponible tras un inicio omitido; no iniciar otra instancia si ya hay una activa.
6. Opcionalmente, exigir alimentación de corriente e inactividad del equipo.

La contraseña sólo se descifra en memoria para el proceso hijo; se restaura el entorno al terminar. MySQL debe estar disponible. Si falta la credencial o el servidor, la ejecución falla sin incorporar información y puede reintentarse posteriormente.

## Fuentes, verificaciones y límites reales

Open Library aporta metadatos según la política existente; sus sinopsis no se almacenan automáticamente como texto libre de derechos. Wikidata aporta afirmaciones CC0; pertenecer a una obra no prueba el papel de un personaje. Wikipedia usa APIs oficiales, revisiones y atribución CC BY-SA, con pasajes acotados. Se conserva el catálogo autorizado de Project Gutenberg sin descargar novelas en este trabajador. No se hace scraping masivo de comercios ni extracción ilimitada mediante SearXNG.

Los lectores HTTP existentes conservan controles de SSRF, TLS, redirecciones, robots, límites y detección de instrucciones maliciosas. El permiso de lectura no se convierte en permiso de almacenamiento. Una página de desambiguación queda excluida aun cuando mencione al autor correcto; los snapshots antiguos se rechazan al recuperarlos y al rehidratarlos desde RAG.

`quarantine_source` permite registrar una revocación técnica comprobada en `memory_meta`, manteniendo fuentes, hechos y versiones para revisión. Una corrección del lector no activa esa revocación como si fuera prueba independiente.

La verificación de este trabajador comprueba procedencia, identidad, licencia, literalidad, conflictos detectables y cobertura del requisito. **No equivale a corroboración factual independiente entre varios autores.** No se afirmará que una lista parcial esté completa ni que el sistema alcance un 99 % de exactitud por superar pruebas unitarias.

Se necesita ampliar cobertura en obras sin secciones estructuradas, idiomas distintos del español y relaciones complejas. No se añadieron entrenamientos, motores comerciales ni extracción universal de acontecimientos. La documentación del piloto y sus limitaciones está en `reports/continuous_20261029/README.md`.

## Tipos específicos de enriquecimiento (reparación del 29 de octubre)

El trabajador existente acepta `--requirement` repetido, hasta seis categorías. Sin el parámetro mantiene `summary` y `characters`. `main_characters` requiere clasificación explícita de principal/protagonista; una lista de pertenencia no lo satisface. `relationships` admite sólo relaciones con sujeto, predicado, objeto y prueba literal. Esto no garantiza responder cualquier pregunta sobre esa obra.

También admite `plot_development` (pasaje distribuido de la sección Argumento, no trama completa) y `character_roster` (al menos tres etiquetas con roles literales; no certifica que sean todos los personajes ni todos principales). La procedencia, identidad y licencia siguen siendo obligatorias. Un lote con requisitos explícitos sólo reclama esas categorías; no consume por accidente tareas anteriores de otro tipo. Los lotes automáticos conservan la prioridad de las demandas pendientes.

Ejemplo manual acotado, con una identidad pública que ya exista:

```powershell
.\venv\Scripts\python.exe -B -m scripts.knowledge.continuous_worker --work-id litmate:dbf1b649da3901c4fabe7152 --requirement relationships --max-jobs 1 --max-seconds 30 --job-seconds 12 --output reports/continuous_runs/relaciones_nueva.json
```

Solicita contraseña oculta. Usa un archivo de salida nuevo. El proceso termina tras un lote; no registra tareas de Windows. Conserva leases, backoff, parada, límites y reanudación existentes. Los perfiles conocidos se vuelven a consultar mediante API cuando hace falta nueva evidencia; leer caché no actualiza su verificación.

Para comprobar persistencia sin búsquedas ni nuevas escrituras:

```powershell
.\venv\Scripts\python.exe -B -m scripts.knowledge.continuous_worker --verify-only --work-id litmate:dbf1b649da3901c4fabe7152 --output reports/continuous_runs/verificacion_nueva.json
```

Resultados y límites del piloto: `reports/integral_20261029/README.md`. No se centralizaron todos los pasajes en MySQL; se conservan anclas/referencias y la memoria narrativa autorizada con RAG rehidratable. No hay entrenamiento autónomo de pesos ni uso de respuestas del modelo como prueba.
