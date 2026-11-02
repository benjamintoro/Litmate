# Lote 1 — SearXNG y recuperación

## Reproducción y causas

Contenedor `litmate-searxng-1`, imagen fijada `ddd642cae6ea…`, versión
`2026.10.11-ad46ebd7d`, escuchando sólo en `127.0.0.1:8080`.

La prueba inicial no se limitó a `docker ps`: consultó JSON general,
bibliográfico, novela, manga y motores aislados. «El nombre de la rosa» devolvió
resultados de otros motores y `openlibrary: unexpected crash`. Al ejecutar los
documentos reales por `ResultContainer.extend` se obtuvo:

```text
result.publishedDate.strftime('%Y-%m-%d %H:%M:%S%z')
AttributeError: 'list' object has no attribute 'strftime'
```

El motor dejaba `publish_date` como lista cuando todas las fechas eran inválidas;
por ser una lista no vacía, tampoco entraba al fallback `first_publish_year`.
No era un problema de credenciales, MySQL o formato manga. Dos de tres pruebas
offline iniciales reprodujeron exactamente ese defecto.

La configuración oficial del motor heredaba `timeout: 10`; el cliente Django
espera 6 s. Esa diferencia permite trabajos tardíos. La advertencia histórica
`ResultContainer.add_unresponsive_engine after ResultContainer.close` **no se
reprodujo** en esta ejecución: no se declara demostrada su causa histórica exacta.

Mwmbl respondió antes y después (109 resultados en la consulta aislada de cierre).
Sus timeouts históricos no se reprodujeron; no se lo deshabilitó para ocultarlos.
Al arrancar una vez apareció un 429 de Wikipedia: se respetó su suspensión.

## Cambios

- `docker-compose.ia.yml`: monta sólo el motor corregido, como módulo distinto
  y de lectura; conserva digest, volúmenes, secreto y puerto local.
- `searxng/engines/openlibrary.py`: parche AGPL del motor oficial; normaliza
  fechas, campos escalares/listas, URL y documentos mal formados. Pide campos
  específicos a la API, sin `fields=*` ni scraping.
- `searxng/settings.yml`: mantiene el nombre `openlibrary`, usa el módulo
  `litmate_openlibrary` y fija tiempos 4/3/3 s para OL/Mwmbl/Wikipedia.
- `searxng/limiter.toml`: configuración explícita de conexión directa,
  `trusted_proxies=[]`; desaparece el aviso de archivo ausente.
- `core/literary_search.py::search_searx`: valida tipos por resultado, conserva
  descubrimientos bibliográficos sin sinopsis, distingue `empty` de
  `unavailable`, mantiene resultados parciales y añade caché por origen,
  consulta e integrantes de motores. Los parciales se conservan sólo 30 s;
  los fallos técnicos no se convierten en resultados vacíos cacheados.
- `scripts/knowledge/searx_engine_regression.py`: seis regresiones con el API
  real de resultados de la imagen, sin red.

La primera tentativa de montar sobre `openlibrary.py` no fue efectiva porque la
imagen seguía importando su bytecode precompilado. Se conservó ese fallo y se
cambió a un módulo de nombre inequívoco; no se borraron archivos de la imagen.

La advertencia IP permanece: el cliente es directo, sin proxy. El middleware
utiliza `REMOTE_ADDR`. No se fabricaron cabeceras ni se debilitó la confianza
de proxies para silenciarla. Detalles operativos en `searxng/README.md`.

## Resultados reales

`searx_motores_cierre.json`:

| Consulta | Motores | Resultados | Fallos | Tiempo |
|---|---|---:|---:|---:|
| El nombre de la rosa | Open Library aislado | 10 | 0 | 1,027 s |
| literature | Mwmbl aislado | 109 | 0 | 0,721 s |
| Naruto manga | Los tres | 56 | 0 | 0,312 s |
| literatura chilena | Los tres | 31 | 0 | 0,306 s |

`searx_cierre.json`: Papelucho, El nombre de la rosa y El Señor de los Anillos
obtuvieron 20/139/138 resultados JSON, sin motores fallidos; el adaptador real
de Django recibió cinco candidatos válidos en cada consulta. Los resultados
son descubrimientos, **no cinco afirmaciones literarias verificadas**. Hay
resultados irrelevantes de Mwmbl que deben seguir filtrándose por identidad.

Los logs del último cierre no contienen `AttributeError`, timeout ni falta de
`limiter.toml`; conservan el aviso IP descrito. No se garantiza disponibilidad
permanente de proveedores externos.

Pruebas sintéticas: motor con timeout/excepción, sobres mal formados, filas
mal formadas mezcladas con válidas, caché, todos los motores fallidos y
resultados parciales. El cooldown evita repetir una conexión fallida y no
imprime el mensaje libre de la excepción.

La integración directa existente con Open Library no fue deshabilitada. Sus
políticas HTTP, límites y caché continúan disponibles como alternativa. Se
conservan SSRF, redirecciones seguras, robots y presupuestos externos.

## Artefactos y pendientes

Evidencia local: `searx_antes.json`, `docker_antes.log`,
`motor_regresion_antes.txt`, `motor_regresion_despues.txt` (montaje inefectivo),
`motor_regresion_despues_efectivo.txt`, `motor_final.txt`, `searx_cierre.json`,
`searx_motores_cierre.json`, `docker_cierre.log`.

Pendientes: observar disponibilidad y cuotas a largo plazo; comprobar
compatibilidad del parche antes de actualizar el digest; configurar un proxy
real y su dirección de confianza únicamente si cambia el despliegue. No se
justifican servicios pagados, motores HTML de Google o actualizaciones globales.
