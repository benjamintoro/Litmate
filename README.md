# LitMate

Asistente literario Django con Ollama local, búsqueda bibliográfica, SearXNG,
RAG y conocimiento persistente. La interfaz, las aplicaciones Django y los
almacenes existentes conservan sus rutas.

## Ejecutar en Windows

Desde la raíz del repositorio, con el entorno `venv` existente:

```powershell
.\venv\Scripts\python.exe -B iniciar_mysql_local.py --http-desarrollo
```

El lanzador solicita la contraseña de forma oculta y selecciona MySQL local
sólo para ese proceso. No importa datos, no cambia `.env` ni aplica migraciones.
Consulta la [guía MySQL](docs/guides/MYSQL_LOCAL.md) para verificaciones y retorno
a la configuración anterior. No hay sincronización automática entre motores.

## Documentación y herramientas

- [Guía del asistente](docs/guides/README_ASISTENTE_IA.md).
- [Índice de documentación](docs/README.md).
- [Organización y dependencias del repositorio](docs/architecture/REPOSITORY_LAYOUT.md).
- [Conocimiento bibliográfico persistente MySQL y RAG](docs/architecture/KNOWLEDGE_REPOSITORY.md).
- [Herramientas auxiliares y compatibilidad de comandos](scripts/README.md).
- [Informes y auditorías](reports/README.md).
- [Continuidad del desarrollo](reportes/continuidad_opencode.md).

Las guías históricas son referencias de su fecha; no se deben volver a pegar
sus bloques de código sobre la aplicación actual.

## Pruebas aisladas

```powershell
.\venv\Scripts\python.exe -B verificar_proyecto.py
node verificar_chat_seguro.js
```

El ejecutor Python utiliza SQLite temporal. Ollama, Docker/SearXNG y MySQL se
comprueban por separado cuando están disponibles. Las dependencias se mantienen
en `requirements.txt` y sus archivos de compatibilidad existentes.
