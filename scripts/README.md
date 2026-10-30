# Herramientas auxiliares

La operación del repositorio bibliográfico se documenta en
[MySQL y RAG](../docs/architecture/KNOWLEDGE_REPOSITORY.md). `scripts/knowledge/mysql_control.py`
usa contraseña oculta, verifica respaldos y permite proyección, diagnóstico y
revisión administrativa; no cambia credenciales ni entrena el modelo.

Desde la raíz, con el entorno existente:

```powershell
.\venv\Scripts\python.exe -B scripts/analysis/resumir_benchmark_ia.py --help
.\venv\Scripts\python.exe -B scripts/analysis/analizar_evaluacion_ia.py --help
.\venv\Scripts\python.exe -B scripts/repository/inventory.py --output reports/inventory_nuevo.json
```

`analysis/` contiene las implementaciones de los dos analizadores offline.
Los comandos e imports antiguos de la raíz siguen disponibles y delegan a
los mismos módulos. Los argumentos de archivos siguen resolviéndose respecto
al directorio de trabajo del usuario; el traslado no cambia esa semántica.

`repository/inventory.py` analiza imports con AST y registra rutas y huellas sin
importar Django, leer credenciales, abrir bases o recorrer uploads y respaldos.
Rechaza sobrescribir un inventario existente.

`repository/check_layout.py` comprueba copias, huellas protegidas y enlaces
locales antes y después del corte, usando el manifiesto del respaldo del lote.
`python -m scripts.repository.verify_runtime --output reports/runtime_nuevo.json`
comprueba Django/MySQL con contraseña oculta, sin importar datos ni aplicar
migraciones, y consulta la disponibilidad de Ollama y SearXNG. No inicia esos
servicios. Ejecutar sólo cuando se desee una comprobación real local.

Se conservan en la raíz `manage.py`, `iniciar_mysql_local.py`, `preparar_mysql.py`,
`iniciar_buscador.py`, `verificar_proyecto.py`, `verificar_asistente.py` y los
otros evaluadores. Varios dependen de `__file__`, del directorio de trabajo o
de llamadas desde comandos Django; requieren otro lote de pruebas antes de moverse.
