# Personajes, cohesión narrativa y español — punto de continuidad

Trabajo conservado al recibir la nueva prioridad conversacional `bf415ec9`.
No constituye una declaración de que todos los problemas lingüísticos estén resueltos.

## Causas y correcciones

- `literary_web._character_description` rechazaba roles explícitos breves (capitán,
  arponero, narrador). Se admiten esos roles documentados y sus construcciones
  nominales; se mantienen filtros de adaptación, negación, incertidumbre e identidad.
- `ai_character_answers` separa un personaje principal comprobado de otros personajes
  documentados. No transforma una lista de pertenencia en diez protagonistas.
- Los nombres de pila sólo resuelven relaciones si son únicos entre las identidades
  verificadas de esa obra. Dos personas llamadas Ana conservan su ambigüedad.
- `literary_search._plot_selection` conserva párrafos contiguos, en vez de saltar
  entre posiciones distantes de un argumento. Se reconoce `sequential_excerpt`
  sin reconstruir el índice ni modificar datos almacenados.
- `literary_quality` audita también declaraciones de roles cortos y reconoce Mr.,
  Mrs. y Ms. como abreviaturas: evita publicar una oración que perdió su inicio.
- `ai_narrative_answers` conserva continuaciones con antecedente; sigue usando
  pruebas de hasta 300 caracteres. No se aumentó ese límite para ocultar rechazos.
- `literary_presentation_language` V6 protege nombres documentados y títulos
  originales; normaliza siglos numéricos ingleses sin otra llamada al modelo.

## Comprobaciones reales

`baseline.json` contiene diez preguntas independientes anteriores a estas
correcciones. `conversation_cierre.json` conserva siete turnos posteriores:
todos respondidos, sin llamadas a Ollama, entre 0,410 y 4,482 segundos. MySQL,
memoria original e índices auxiliares conservaron sus controles de integridad.

| Caso | Antes | Después comprobado |
|---|---|---|
| Personajes de Moby Dick | unavailable, 4,676 s | tres roles documentados, 2,709 s (`after.json`) |
| Personajes de La Odisea | siete | diez documentados; principal y secundarios separados |
| Relación Harriet / Emma | no respaldada en ejecución intermedia | amistad explícita, 0,717 s |
| Trama de Emma | fragmentación por Mr. y atribución equivocada en ejecución intermedia | dos oraciones conectadas, 0,937 s |

Los argumentos recuperados pueden ser parciales: la salida de La Odisea y Moby
Dick no representa toda la trama. Las cifras corresponden a estas preguntas,
no a una medición de exactitud general ni a un p95 representativo.

## Límites pendientes

`holdout_final.json` detectó español incorrecto en *The jade cabinet* (por ejemplo,
«cortejadora pernicioso»). La protección de nombres no garantiza una traducción
gramaticalmente correcta. La comparación explícita Emma / Orgullo y prejuicio
falló en una ejecución intermedia. Ambos problemas siguen pendientes.

`tests_directed.json` registra una ronda intermedia de 252 pruebas. La batería
posterior que incluye estas correcciones y las conversacionales está en
`../reparacion_conversacional_20261030/`. No deben sumarse las rondas como si
fueran pruebas distintas. `checkpoint.json` conserva hashes y artefactos.

No se instalaron paquetes, importaron obras globales, cambiaron credenciales,
ejecutaron migraciones ni modificaron tarjetas, voz o avatares.
