# Expansión progresiva del catálogo — 28 de octubre de 2026

Este lote reutiliza el importador Gutenberg, el ledger/outbox, la memoria SQLite
y el repositorio MySQL existentes. No crea otra arquitectura, no requiere
migraciones, paquetes nuevos ni servicios de pago. No modifica `.env`, el diseño
del chat, los modelos de Ollama ni los datos de lectores.

## Fuente y alcance

Se reutiliza `data/adquisicion/pg_catalog_20261027.csv.gz`, 5.597.116 bytes,
SHA256 `ebf4f6e54a34dddbcd26ca8a5ef593c9cf3e0ab8b331628ea7a49170a196a07e`.
El catálogo tiene 79.674 entradas. Los metadatos están admitidos por la
[política oficial de acceso automatizado de Gutenberg](https://www.gutenberg.org/policy/robot_access.html)
y sus [catálogos descargables](https://www.gutenberg.org/ebooks/offline_catalogs.html).
No se descarga ningún texto completo. El permiso del catálogo no concede
derechos sobre las novelas, sus traducciones o sus imágenes.

También se evaluaron fuentes oficiales:

- [Open Library](https://openlibrary.org/developers/api): para volumen recomienda
  dumps mensuales, no recorrer masivamente la API. Ya existe el importador;
  no se descargó un dump enorme sólo para seleccionar once mil filas.
- [BNE](https://www.bne.es/es/perfiles/bibliotecarios/suministro-registros):
  suministro de registros CC0 y adaptador MARCXML existente. La consulta de la
  página devolvió HTTP 403 en esta sesión; no se evadió el bloqueo.
- [Library of Congress](https://loc.gov/cds/products/marcDist.php): distribución
  MARC abierta, de gran volumen; falta adaptar y validar ese formato aquí.
- [National Diet Library](https://www.ndl.go.jp/en/data/dl_bib_records.pdf): posible
  fuente para bibliografía japonesa; no se implementó ni se atribuye cobertura manga.

Google Books, Wikidata y Wikipedia conservan sus integraciones de investigación
existentes. No se usan como endpoints de descarga masiva. No se extraen datos
masivamente de Amazon, Buscalibre ni otros comercios.

## Selección y seguridad

Se excluyen los IDs ya presentes en MySQL y los pares normalizados título/autor
que ya figuran en la memoria. Se evita seleccionar de nuevo el mismo par e idioma
dentro de cada lote, sin fusionar ni borrar ediciones. El identificador Gutenberg
se conserva como **edición**, no como obra canónica entre proveedores.

Muestreo reproducible por idioma, tema declarado y siglo de nacimiento del autor.
Este último es sólo un criterio de diversidad: **no es la fecha de publicación**.
No se infiere nacionalidad ni país del idioma. Los planes congelados se guardan
en `seleccion1000.json` y `seleccion10000.json`, junto al hash del catálogo.

El importador admite `selected_ids`; cada selección tiene un checkpoint separado.
Los descartes se confirman cada 250 filas y cada registro admitido conserva
checkpoint atómico. La publicación sigue requiriendo verificar el hash completo.
La finalización exige también que no queden elementos pendientes en el outbox de
memoria. Se mantienen las validaciones de permisos, autoría ambigua e identidad.

MySQL recibe bloques de 25, con un máximo de 250 registros por ejecución y
20 segundos entre controles. Hay pausa entre bloques, lease de exclusión,
cuota lógica de 256 MiB y margen mínimo de 10 GiB en disco. La cuota lógica
no equivale al tamaño físico de InnoDB ni impone una cuota al servidor completo.

## Qué se mide

- Todos los IDs y URLs primarias de las nuevas ediciones, estado y procedencia.
- Huellas de cada fila MySQL anterior y restricciones FK. Sólo crecen tablas KB;
  sus controles operativos pueden avanzar, nunca desaparecer o retroceder.
- Filas originales de obras, fuentes, entidades, afirmaciones y conflictos de
  la memoria; comprobación SQLite `quick_check` sin modificarla.
- Por lote, 120 títulos seleccionados por hash reproducible: recuperación de
  autoría SQL, respuesta determinista, abstenciones, errores y p50/p95.
- Auditoría final adicional de recuperación top 5 en memoria, y HTTP/SSE real
  con MySQL/CSRF y tarjetas `sqlkb:` pertenecientes al lote nuevo.
- RSS del proceso de importación, tamaños SQLite, cuota lógica SQL y estimaciones
  de InnoDB. Las estadísticas de `information_schema.tables` pueden estar
  desactualizadas; no se presentan como medición exacta del disco utilizado.

Una etiqueta de autor publicada por el catálogo no equivale a corroboración
independiente ni revisión humana. `verified_at` sigue vacío. Este CSV no proporciona
sinopsis o personajes: esos campos no se inventan ni se rellenan con texto generado.

## Reanudación y comprobación

Usar el Python del venv. Los comandos piden la contraseña oculta y seleccionan
MySQL local sólo en su proceso. No importan nuevamente la base original.

```powershell
.\venv\Scripts\python.exe -B -m scripts.knowledge.expand_catalog --catalog data/adquisicion/pg_catalog_20261027.csv.gz --backup backups/expansion_20261028_01 --output reports/expansion_20261028/reanudacion1000.json --selection reports/expansion_20261028/seleccion1000.json --ledger data/adquisicion/expansion1000_20261028.sqlite3 --maximum 1000 --execute

.\venv\Scripts\python.exe -B -m scripts.knowledge.expand_catalog --catalog data/adquisicion/pg_catalog_20261027.csv.gz --backup backups/expansion_20261028_02 --output reports/expansion_20261028/reanudacion10000.json --selection reports/expansion_20261028/seleccion10000.json --ledger data/adquisicion/expansion10000_20261028.sqlite3 --maximum 10000 --previous-report reports/expansion_20261028/lote1000.json --execute

.\venv\Scripts\python.exe -B -m scripts.knowledge.audit_expansion --backup backups/expansion_20261028_01 --selections reports/expansion_20261028/seleccion1000.json reports/expansion_20261028/seleccion10000.json --output reports/expansion_20261028/nueva_auditoria.json
```

No es necesario repetir la ingesta si ya terminó. Las salidas deben tener nombres
nuevos; se conservan las ejecuciones anteriores, incluidos los fallos de prueba.
Datos, planes JSON y resultados detallados permanecen locales e ignorados por Git.

## Pruebas y limitaciones detectadas

Las 64 pruebas dirigidas finales pasaron en 12,390 segundos. Cubren selección,
reanudación, checkpoints separados, outbox pendiente, preservación de originales,
importador, repositorio, respaldo/transferencia y activación MySQL. Las 233
comprobaciones JavaScript del chat también pasaron.

La suite general ejecutó 1.927 pruebas en 102,896 segundos: 5 fallos, 2 errores
y 1 omisión. Los mismos 7 problemas se reprodujeron en 33 pruebas dirigidas,
tanto con la memoria actual como con una copia aislada del respaldo PREVIO:
personajes de Dune/endpoints, recuerdos Platero/Metamorfosis, alias Don Quijote y
selección de sinopsis de Tolkien. No se afirma que toda la suite esté aprobada.
No se modificaron esas rutas para hacer pasar artificialmente esta expansión.

Artefactos: `pruebas_generales.txt`, `revalidacion_ajenos.txt`, `baseline_ajenos.txt`,
`pruebas_dirigidas_final.txt` (detectó una conexión SQLite sin cerrar en una prueba
nueva de Windows), `pruebas_dirigidas_corregidas.txt` (62 OK),
`pruebas_dirigidas_cierre.txt` (64 OK), `pruebas_js.txt`.
La conexión se corrigió con cierre explícito; no se desactivó la comprobación.

Los benchmarks de autoría no prueban exactitud de tramas o personajes ni una tasa
global de error inferior al 1 %. Faltan fuentes autorizadas con cobertura moderna,
infantil reciente y manga, además de descripciones y personajes verificables.

Resultados, tamaños, respaldos y capacidad adicional en [RESULTADOS.md](RESULTADOS.md).
