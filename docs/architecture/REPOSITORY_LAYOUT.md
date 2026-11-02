# Organización del repositorio — primer lote

Se separaron documentación, informes históricos y dos analizadores offline.
La aplicación Django, los módulos de IA y sus pruebas mantienen sus rutas.

```text
Litmate/
  README.md                        entrada principal
  AGENTS.md                        instrucciones del agente, sin cambios
  manage.py                        entrada Django, sin cambios
  iniciar_mysql_local.py           arranque MySQL, sin cambios
  preparar_mysql.py                herramienta de datos, sin cambios
  verificar_proyecto.py            ejecutor aislado, sin cambios
  README_ASISTENTE_IA.md            enlace compatible a la guía trasladada
  MYSQL_LOCAL.md                    enlace compatible a la guía trasladada
  LEEME.md                         enlace compatible al índice y archivo histórico
  analizar_evaluacion_ia.py         entrada compatible
  resumir_benchmark_ia.py           entrada compatible
  docs/
    guides/                        asistente y MySQL
    architecture/                  rendimiento y organización
    archive/                       guía versión 3 y paquete histórico
  reports/
    archive/                       seis informes antes ubicados en la raíz
    reorganization_20261028/        inventario, resultados y comprobaciones
  scripts/
    analysis/                      implementación única de los dos analizadores
    repository/                    inventario estático reproducible
  core/                            integración Django e IA existente
  suscripciones/                   aplicación y migraciones existentes
  litmate_project/                 configuración Django existente
  templates/                      sin cambios
  static/                         sin cambios
  searxng/                        configuración y volumen Docker, sin cambios
  reportes/                       resultados operativos compatibles, sin mover
  data/, media/, backups/         datos y respaldos, sin mover
```

## Dependencias comprobadas

El [inventario](../../reports/reorganization_20261028/inventory.md) registra
354 archivos de código/documentación/configuración, 261 módulos Python,
2.703 imports, cuatro llamadas de importación dinámica/recarga, 31 anclajes
`__file__`, 121 archivos de pruebas en `core` y diez archivos de migraciones
(incluidos los `__init__.py`). No se leyó `.env` ni se recorrieron almacenes,
respaldos o uploads. `core/data` sí se inventarió como recurso del código.

Se evaluaron 46 módulos candidatos a una separación futura por responsabilidades.
`core.literary_ai` aparece importado desde 88 archivos, `literary_identity` desde
51 y `literary_quality` desde 36. Moverlos en este lote ampliaría considerablemente
el alcance y las posibilidades de imports circulares o parches de pruebas rotos.

No hay configuración CI ni scripts PowerShell versionados en el inventario actual.
Docker usa `./searxng` respecto a `docker-compose.ia.yml`; ambos permanecen en su
ubicación. Los requisitos tienen referencias `-r` relativas y se mantienen en raíz.

## Qué permanece en core y por qué

- Modelos, `apps.py`, URLs, vistas, formularios, administración y migraciones:
  conservar `app_label`, identidad de tablas, ContentTypes y dependencias.
- `literary_ai_views`, cuotas, sesiones y voz: integración con Django/HTTP/SSE.
- Motor, identidad, evidencia, auditoría, proveedores, cachés, RAG, biblioteca,
  conocimiento y memoria: fuerte red de imports relativos y pruebas que parchean
  rutas `core.*`; sin beneficio demostrado por moverlos en este primer lote.
- Recursos en `core/data`: varios cargadores usan `Path(__file__).parent / 'data'`.
- Pruebas: imports cruzados de fixtures y descubrimiento predeterminado
  `DiscoverRunner(...).run_tests(['core'])`. Trasladarlas requiere configurar y
  verificar el descubrimiento y mantener compatibilidad de sus imports.
- `database_transfer` y `mysql_activation`: rutas usadas por lanzadores públicos;
  se mantienen con todos sus controles de integridad.

`reportes/` no es sólo documentación: contiene evidencias ligadas por hashes,
salidas predeterminadas y scripts locales de diagnóstico. No se renombra ni
reescribe indiscriminadamente. Las instrucciones de continuidad conservan su ruta.

## Próximo lote seguro

1. Separar sólo un grupo de pruebas de herramientas a `tests/tools`, ajustando
   descubrimiento y manteniendo imports de fixtures antiguos cuando sean necesarios.
   Comprobar que el número e identidad de casos descubiertos no disminuyen.
2. Evaluar después un módulo hoja de IA con pocos dependientes y sin recursos
   relativos. Mantener un alias real de módulo `core.*`, no copias divergentes.
   Comprobar mocks y estado compartido antes de otro traslado.
3. Reservar para lotes posteriores `literary_ai`, identidad, calidad, memoria y RAG.
   Comparar resultados HTTP/SSE y las huellas de migraciones antes y después.
4. No crear `config/`, `requirements/` ni `literary_ai/` hasta tener un movimiento
   concreto y probado que justifique esas carpetas.

Los scripts nuevos no cambian CWD global ni configuran Django al importarse.
Las entradas compatibles de raíz reutilizan el mismo objeto de módulo que su
implementación para conservar los parches y evitar estado duplicado.
