# SearXNG local de LitMate

Arranque desde la raíz, con PowerShell y sin modificar `.env`:

```powershell
.\venv\Scripts\python.exe -B iniciar_buscador.py
```

Compose sigue publicando únicamente `127.0.0.1:8080`. Conserva el volumen
`litmate_search_cache` y la imagen fijada por digest. El lanzador entrega un
secreto efímero al proceso; no usar `docker compose config` para publicarlo.

## Parche de compatibilidad de Open Library (29/10/2026)

La imagen `2026.10.11-ad46ebd7d` conserva una lista de fechas cuando ninguna
entrada de `publish_date` puede analizarse. `ResultContainer` intenta ejecutar
`publishedDate.strftime` y provoca `AttributeError: list`. Fue reproducido con
la búsqueda real «El nombre de la rosa» y con dos regresiones offline.

`engines/openlibrary.py` deriva del [motor oficial de esa revisión](https://github.com/searxng/searxng/blob/ad46ebd7d/searx/engines/openlibrary.py),
bajo **AGPL-3.0-or-later**, con su aviso SPDX conservado. La modificación local:

- Utiliza `None` si no hay fecha válida y conserva el fallback del año original.
- Solicita los campos usados, en lugar de `fields=*`.
- Normaliza los tipos de campos opcionales y aísla documentos inválidos.
- Conserva el enlace canónico sin doble barra antes de `/works`.

Se monta en modo lectura como `searx/engines/litmate_openlibrary.py`; el motor
sigue llamándose `openlibrary` para el cliente. El nombre de módulo distinto
es necesario: al montar sobre el archivo original, esta imagen seguía cargando
su bytecode precompilado. Esa primera tentativa falló y se conservó su informe.
No se borró bytecode ni se actualizaron todos los motores.

La [API oficial de Open Library](https://openlibrary.org/dev/docs/api/search)
recomienda pedir campos específicos y advierte del costo de `fields=*`. El
motor directo de Django sigue disponible, con sus límites y caché, aunque
SearXNG no responda.

Los tiempos de los motores son Wikipedia 3 s, Mwmbl 3 s y Open Library 4 s.
Se elimina la herencia de 10 s de Open Library; Django espera 6 s por la
metabúsqueda. Se conservan cero reintentos y la suspensión upstream por errores.

Al cambiar el archivo del motor, reiniciar sólo este contenedor para recargarlo:

```powershell
docker restart litmate-searxng-1
```

La configuración está ligada a esta imagen: antes de cambiar su digest se
deben revisar el API de resultados de SearXNG y estas pruebas. No eliminar el
parche ni reemplazarlo por otro motor sin verificar que upstream resolvió el fallo.

## Comprobaciones

```powershell
.\venv\Scripts\python.exe -B diagnosticar_buscador.py --output reports/search_narrative_20261029/diagnostico_nuevo.json
Get-Content -Raw -Encoding UTF8 scripts/knowledge/searx_engine_regression.py | docker exec -i -e LITMATE_TEST_ENGINE=litmate_openlibrary litmate-searxng-1 /usr/local/searxng/.venv/bin/python -
```

La segunda orden ejecuta seis pruebas **offline** en las clases reales de la
imagen; no consume consultas a proveedores. La primera sí consulta la API y el
adaptador de Django. Utilizar una ruta de salida nueva para preservar evidencia.
`healthy` sólo comprueba el proceso HTTP, no la relevancia ni veracidad de resultados.

## Advertencias y seguridad

`limiter.toml` declara `trusted_proxies=[]` para la conexión directa local. No
se alteró `server.limiter` ni se autorizaron redes como proxies para ocultar
advertencias. No se añade Redis/Valkey ni se abre el buscador a Internet.

La advertencia `X-Forwarded-For nor X-Real-IP header is set` puede aparecer una
vez por arranque. El middleware de esta versión sigue usando `REMOTE_ADDR` en
conexiones directas. No se enviará una IP inventada para silenciarla. Si en el
futuro existe un proxy real, debe retirar cabeceras del cliente, aportar la IP
real y configurar únicamente su dirección como proxy de confianza. Consultar
la [documentación oficial del limiter](https://docs.searxng.org/admin/searx.limiter).

Mwmbl respondió en las comprobaciones de cierre, pero un buscador externo puede
volver a tener timeouts. También se observó un 429 temporal de Wikipedia tras
un arranque; se respetó su suspensión, sin evasión ni reintentos agresivos.
El adaptador conserva resultados útiles cuando falla otro motor, distingue
fallo de búsqueda vacía y aplica caché/cooldown. La API JSON no sustituye las
comprobaciones bibliográficas, SSRF, robots o auditoría de LitMate.
