# Demo LitMate — 3 de noviembre de 2026

> **Actualización del 31-10-2026:** este documento conserva la ronda histórica.
> Para el estado vigente, consultar [resultados actuales](resultados_actuales.md),
> [servidor remoto](servidor_remoto.md) y [guion de ocho minutos](guion_8_minutos.md).
> MySQL ya se autenticó y se probó realmente. Su escucha no está restringida a
> loopback: la regla de firewall quedó sólo preparada por decisión del usuario.
> Funnel continúa desactivado. No confundir las cifras y límites antiguos de abajo
> con el cierre de esta revisión.

Estado congelado para la demostración académica. No se rehizo la aplicación ni se
cambiaron el diseño, las tarjetas, los avatares, la voz ni `.env`.

## Versión y cambios

- Base: commit `6c8dd18`.
- Cambios locales sin commit ni push:
  - `core/ai_narrative_answers.py`: evita `KeyError` cuando una fuente no trae `kind`.
  - `core/genre_recommendations.py`: permite auditar títulos cortos (`1984`, `Dune`)
    usando identidad bibliográfica, sin inventar contenido.
  - `core/test_chat_deadline.py`: actualiza dos expectativas de orden que ya no
    describían el ranking actual; las pruebas ahora comprueban la lista publicada.
- No se modificaron `.env`, migraciones, datos de producción, respaldos, portadas,
  tarjetas ni componentes visuales.

## Servicios comprobados

- MySQL80: servicio `Running`, escucha en `127.0.0.1:3306`. **La autenticación local
  no se pudo verificar porque la contraseña no está disponible en esta sesión.**
- Ollama: `http://127.0.0.1:11434`, con `qwen3.5:9b-q4_K_M`, `qwen3:8b` y
  `embeddinggemma:latest`.
- SearXNG: contenedor `litmate-searxng-1`, `healthy`, en `127.0.0.1:8080`.
- Respaldo verificado: `backups/contenido_20261030_03`, 41 tablas, 37.407 filas,
  93 archivos. `preparar_mysql.py verificar` devolvió `backup_verified: true`.
  - `manifest.json` SHA-256: `697A7D0C9F69EA14CDEF6BB8DF21EB0077251B9ECCD3055E291BC1BB7926341C`
  - `django.sqlite3` SHA-256: `5C33A32CFD28BAFF54A656D13F4910A52DC5C685D169E9B9305BECB4009B0837`

## Arranque exacto

Abrir PowerShell en `G:\Proyecto\Litmate`.

### 1. Buscador local

```powershell
.\venv\Scripts\python.exe -B iniciar_buscador.py
```

Comprueba el contenedor y la API JSON en `http://127.0.0.1:8080`.

### 2. Ollama

```powershell
ollama list
```

Debe aparecer el modelo configurado para la aplicación. No hace falta descargar
nada durante la demo.

### 3. Aplicación con MySQL local

```powershell
.\venv\Scripts\python.exe -B iniciar_mysql_local.py --verificar-y-servir --http-desarrollo --puerto 8000
```

La contraseña se introduce únicamente en el prompt oculto. El lanzador comprueba
la conexión, el esquema y la activación antes de servir. No ejecuta migraciones ni
importaciones.

Si la contraseña local no está disponible, usar la alternativa SQLite sobre una
copia nueva del respaldo (nunca abrir el respaldo directamente):

```powershell
if (Test-Path '.\db_demo_20261103.sqlite3') { throw 'El archivo de demo ya existe.' }
Copy-Item '.\backups\contenido_20261030_03\django.sqlite3' '.\db_demo_20261103.sqlite3'
$env:DB_ENGINE = 'sqlite'
$env:DB_SQLITE_PATH = 'db_demo_20261103.sqlite3'
.\venv\Scripts\python.exe -B manage.py check --database default
.\venv\Scripts\python.exe -B manage.py runserver 127.0.0.1:8000 --noreload
```

Esta alternativa se usó para las pruebas HTTP/SSE de abajo. La copia de trabajo
`.testtmp/demo.sqlite3` ya existe y no debe confundirse con el respaldo.

### 4. Abrir la interfaz

`http://127.0.0.1:8000/chat/`

## Tres conversaciones recomendadas

Resultados reales de la última ronda HTTP/SSE (30-10-2026 02:23), con Ollama y
SearXNG activos y una copia SQLite del respaldo. Cada turno devolvió HTTP 200.

### A. Recomendación por género

Mensaje:

> Recomiéndame novelas de fantasía

Resultado: 3 tarjetas, 0,495 s.

1. *Choque de Reyes (Canción de Hielo y Fuego 2)* — George R.R. Martin.
2. *El Camino de los Reyes (El Archivo de las Tormentas 1)* — Brandon Sanderson.
3. *El Hobbit* — J.R.R. Tolkien.

### B. Trama, personajes y autoría

1. > Cuéntame de qué trata El principito

   Respuesta desde ficha local verificada, 0,260 s, 1 tarjeta.
   Menciona el planeta diminuto, la rosa, el zorro y el aviador.

2. > ¿Quiénes son los personajes principales de El principito?

   Respuesta desde Wikipedia, 1,635 s, 1 tarjeta. Devuelve una **lista parcial**
   con El principito como personaje principal; no es un reparto completo.

3. > ¿Quién escribió El principito?

   Respuesta desde ficha local, 0,366 s: Antoine de Saint-Exupéry.

### C. Contexto sobre una recomendación

1. > Recomiéndame libros sobre la Segunda Guerra Mundial

   Respuesta local, 0,078 s, 3 tarjetas:

   1. *La segunda guerra mundial* — Antony Beevor.
   2. *Se desataron todos los infiernos* — Max Hastings.
   3. *Si esto es un hombre* — Primo Levi.

2. > Cuéntame más del segundo

   Respuesta contextual, 0,269 s: *Se desataron todos los infiernos*, de Max
   Hastings, con su fuente. No vuelve a recomendar ni inventa una trama.

### D. Contexto de personajes (opcional)

1. > Dime los personajes de Papelucho y el marciano

   0,147 s: Papelucho y Det, con roles verificados.

2. > ¿Y qué sucede con Det?

   0,373 s: conserva a Det y su papel de amigo extraterrestre.

No usar «personajes principales de Papelucho»: el clasificador estricto devuelve
una abstención honesta. La formulación anterior sí está verificada.

## Búsqueda externa y fallback local

Comprobaciones anteriores, con el mismo código:

- `La sombra del viento`: autoría en 2,871 s y trama en 3,877 s desde Wikipedia.
- `El infinito en un junco`: 3,263 s desde Wikipedia.
- Título desconocido `Zzyzx y el faro de cristal`: abstención honesta en 8,509 s;
  no inventó una respuesta.

Con SearXNG/web desactivados y un proceso nuevo:

- `Cuéntame de qué trata El principito`: 0,249 s desde ficha local.
- `¿De qué trata La sombra del viento?`: 0,583 s desde la memoria persistida por la
  investigación externa anterior.

La memoria externa se conserva en `data/literary_memory.sqlite3`. No se borró ni se
sustituyó por una respuesta preparada.

## Pruebas

- Antes de los arreglos: 2.092 pruebas, 3 fallos, 3 errores, 1 omitida.
- Después de los dos arreglos de producción: 3 fallos, 1 error. Dos fallos eran las
  expectativas de orden de la Segunda Guerra Mundial, ya actualizadas; las dos
  pruebas de detalles públicos pasan aisladas.
- Comprobaciones dirigidas posteriores:
  - `core.test_ai_public_details`: 29/29 correctas.
  - `core.test_genre_recommendations` + `core.test_narrative_answers`: 39/39.
  - Las dos pruebas de orden actualizadas: 2/2.
- **No se repitió la suite completa al final**: el proyecto ejecuta las pruebas
  contra el TiDB remoto (`test_test`) y el servidor de pruebas quedó bloqueado en
  consultas de `test_bibliographic_repository`. No es un fallo del código de la
  demo; no se borró ni recreó esa base sin autorización. No ejecutar la suite
  completa justo antes de la demostración.

## Límites que deben mencionarse si aparecen

- La contraseña de MySQL local no está verificada; el arranque MySQL debe probarse
  antes de la demo con el comando de arriba. Si falla, usar SQLite y decirlo.
- `Cosmos`, de Carl Sagan, está mal clasificado como «Ciencia Ficción» en el catálogo
  local. No usar la demo de ciencia ficción con ese título.
- `La casa de los espíritus` sin fuentes externas puede responder desde el modelo
  en unos 30 s **sin cita**. No presentarlo como respuesta verificada.
- Las búsquedas externas dependen de Wikipedia/SearXNG y pueden ser intermitentes.
  Si fallan, LitMate debe abstenererse o usar la memoria local; nunca inventar.
- El respaldo `contenido_20261030_03` es la referencia de datos. No abrir ni editar
  `django.sqlite3` directamente.

## Cierre

La versión queda congelada con los tres archivos modificados sin commit. Para
volver al estado exacto de la base: `git diff` y `git status`; para los datos:
`backups/contenido_20261030_03`. No se hizo push.
