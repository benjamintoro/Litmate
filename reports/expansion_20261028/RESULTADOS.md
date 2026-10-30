# Resultados verificados de la expansión

| Medida | Lote 1 | Lote 2 | Cierre |
|---|---:|---:|---:|
| Registros nuevos MySQL | 1.000 | 10.000 | 11.000 nuevos; 11.100 totales |
| Duplicados insertados / conflictos / rechazos SQL | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |
| IDs, etiquetas de autor y enlaces primarios válidos | 1.000/1.000 | 10.000/10.000 | 100 % |
| Nuevas sinopsis / personajes | 0 / 0 | 0 / 0 | Sin crecimiento narrativo |
| Muestra final: autor esperado recuperado en SQL | 120/120 | 120/120 | 240/240 |
| Respuestas rápidas correctas de autoría | 98/120 | 103/120 | 201/240; 39 abstenciones |
| Respuestas de autoría erróneas en la muestra | 0 | 0 | No prueba tasa global <1 % |
| Recuperación de memoria top 5 | 117/120 | 120/120 | 237/240 |
| p95 SQL + ruta de autoría | 11,70 ms | 10,28 ms | Local, sin generación LLM |
| p95 recuperación de memoria | 9,11 ms | 11,26 ms | Índice existente |
| HTTP/SSE real al cierre | 0,2774 s | 0,1979 s | Ambas conversaciones aprobadas |

HTTP real: «¿Quién escribió Ang Katipunan?» y «¿Quién escribió Elämän polulla?»,
autores Gabriel Beato Francisco y Niilo Mantere según fichas primarias, tarjetas
SQL nuevas, CSRF, cero llamadas a Ollama. Sesiones firmadas: no se crearon lectores
ni historial MySQL. No había servidor en el puerto 8000 al inicio; se utilizaron
servidores loopback efímeros. No se afirma que quede un servidor permanente activo.

La medición inicial del primer lote dio 100/120 respuestas rápidas; al cierre
son 98/120. Dos casos adicionales se abstienen al aumentar la ambigüedad. No se
eliminó esa protección para mejorar el porcentaje.

## Cobertura real, duplicados y procedencia

- Memoria: **2.256 → 13.250 pares título/autor**, crecimiento **10.994**;
  fuentes **2.388 → 13.383**, crecimiento **10.995**; autores normalizados
  **842 → 5.776**. Se conservan 7 descripciones admitidas y 37 personajes en 3 obras.
- Todas las obras, fuentes, entidades y afirmaciones originales siguen presentes,
  con su contenido intacto. Seis fuentes renovaron sólo timestamps de vigencia;
  URL, hash, texto y demás campos permanecieron iguales. No se cuenta esa
  renovación como conocimiento nuevo.
- Cinco ediciones seleccionadas ya figuraban en memoria con título sin «(Novela)»:
  PG47388, PG44358, PG44529, PG25054 y PG48954. Otra pareja, PG67205/PG73215,
  comparte título/autor en dos idiomas. Se conservaron los IDs de edición SQL;
  no se borraron o fusionaron registros. La selección futura utiliza la misma
  normalización `work_identity` que la memoria, con regresión específica.
- Selección 1: 2.383 entradas conocidas excluidas y 177 repeticiones del mismo
  título/autor/idioma evitadas. Selección 2: 3.391 y 170, respectivamente. No sumar
  los dos conteos de conocidas como registros únicos: se leyó el mismo catálogo.
- Otras 27.338 entradas del catálogo no superaban las reglas existentes de
  autoría, tipo o campos obligatorios. No son rechazos entre los 11.000 seleccionados.
- Diversidad: **42 idiomas**, 321 registros en español y 12 en japonés. Temas
  declarados: 3.344 ficción, 1.634 historia, 1.018 poesía, 444 infantil/juvenil,
  209 artes, 166 ciencia, 148 ensayo y 4.037 otros. No hay manga identificado.
- 506 etiquetas son genéricas: 342 «Various», 144 «Anonymous», 20 «Unknown».
  No se presentan como autores individuales confirmados. Todas las autorías son
  atribuciones del catálogo, no corroboración independiente; revisión humana: 0.
  `verified_at` SQL permanece NULL. No se inventan sinopsis, personajes o fechas.

## Almacenamiento y respaldos

- Memoria SQLite: **11.628.544 → 60.592.128 bytes**, aumento 48.963.584 (46,70 MiB).
- Ledgers nuevos: **2.285.568 + 22.339.584 bytes** (23,48 MiB).
- Cuota lógica SQL: **767.306 → 88.281.552 bytes**, aumento 87.514.246 (83,46 MiB),
  incluyendo payload y versiones. No equivale a disco físico InnoDB. Las estadísticas
  observadas no se actualizaron inmediatamente; no se reportan como tamaño exacto.
- Pico RSS del importador: **123,12 MiB** en lote 1; **192,82 MiB** en lote 2.
  No incluye MySQL/Ollama. Reevaluación: unos 11,1 GiB de RAM libres y 104 GiB
  de disco libres antes del respaldo final. No se instalaron modelos ni dependencias.
- Respaldos verificados, con SQLite portable y snapshots auxiliares:
  `backups/expansion_20261028_01`: **41 tablas, 3.273 filas, 89 archivos**;
  `_02`: **41 tablas, 6.274 filas, 90 archivos**;
  `_03`: **41 tablas, 36.275 filas, 91 archivos**.
- Las 3.273 filas MySQL anteriores están preservadas; sólo avanzaron los controles
  operativos de proyección. Las FK pasaron. No se reimportó la base original.
- `.env` SHA256 intacto:
  `1d8e35effc765d26ecb73f3e2ee26c886a1e3d98b1bc45590c356b8604008e74`.
  Manifest del respaldo `mysql_preparacion_20261028_03` intacto:
  `89e44e64babf9278643e5ef45c607a61de6e3e65973b050bccba7e1efccb1005`.

## Próximo límite y pendientes

Nueva evaluación sin ingesta: **38.773 candidatos** todavía admisibles y no
representados según estas reglas; no equivalen a obras canónicas verificadas
entre proveedores. La siguiente muestra se concentra en inglés, alemán, finés y
francés. Seguir sólo con Gutenberg no cubre los huecos de literatura moderna/manga.

Los recursos medidos permiten plantear otro lote **de hasta 10.000**, reservando
de forma conservadora al menos 1 GiB adicional para datos/índices y respaldo,
manteniendo 10 GiB libres y repitiendo la evaluación de RAM, integridad y latencia.
Es una estimación prudente, no capacidad validada para millones. **No se ejecutó
un tercer lote**. Priorizar fuentes autorizadas con narrativa y épocas recientes,
las abstenciones y las siete incidencias preexistentes descritas en el README.

Pruebas: **64 dirigidas aprobadas**, 233 comprobaciones JS aprobadas. Suite general:
1.927 ejecutadas, 5 fallos, 2 errores, 1 omisión. Mismos siete problemas reproducidos
con copia aislada de la memoria previa. No se declara aprobada la suite completa.

Artefactos locales: `lote1000.json`, `lote10000.json`, `auditoria_final.json`,
`capacidad_candidatos.json`, planes congelados y salidas de pruebas. Cero peticiones
de descarga, cero textos completos descargados y cero APIs de pago en esta fase.

Archivos de esta fase: `core/literary_gutenberg.py`, `core/bibliographic_expansion.py`,
`core/bibliographic_http_probe.py`, `core/test_bibliographic_expansion.py`,
`scripts/knowledge/expand_catalog.py`, `scripts/knowledge/audit_expansion.py`,
`.gitignore`, informes de esta carpeta y `reportes/continuidad_opencode.md`.
Todos los cambios previos se conservaron. Sin commits, push, migraciones o edición de `.env`.
