# Chat con presupuesto de diez segundos — resultados y límites

> **Objetivo vigente desde el 22-10-2026:** el límite del chat pasó de 10 s a
> **30 s** (29 s de trabajo del backend). El informe vigente es
> `reportes/descubrimiento_30s_20261022/INFORME.md`. Este documento se conserva
> como registro histórico del presupuesto de diez segundos.

Fecha: 22-10-2026. Checkpoint anterior: `147c75e`, etiqueta local
`checkpoint/ia-antes-limite-10s-20261022`. Sin push.
Código guardado en `935f2cb` y `1f3a7b7`.

## Resultado vigente

- **46/46 turnos HTTP/SSE completos antes de 10 s**, máximo **9,025 s**.
- **21 respuestas publicadas**, 17 no disponibles, 5 aclaraciones y 3 rechazos.
- Consulta exacta reportada: **0,016 s**, con tres libros, autores y fuentes.
  «Cuéntame más del segundo»: **0,028 s**, sin perder la obra elegida.
- **1119 pruebas core**, **13 pruebas de pagos** y **198 comprobaciones JS** OK.

Se corrigieron la espera de varios minutos y varios recorridos básicos, pero
**la misión general no está completa**: 17 consultas todavía no obtienen una
respuesta verificable con este presupuesto. Es incorrecto presentar 46 tiempos
acotados como 46 respuestas literarias correctas.

## Problema reproducido

- El endpoint permitía 25 s en rutas rápidas y, después, otro presupuesto de
  hasta 360 s para el modelo. `OllamaJSON` imponía además mínimos de 30/60 s.
- La petición `hola recomiendame libros sobre la segunda guerra mundial` no
  obtenía una respuesta en la reproducción aislada de 20 s sobre `147c75e`.
  Se detuvo ese proceso: **no se conoce su latencia final**, y no se afirma
  haber reproducido una espera exacta de cinco minutos.
- El tema no tenía una materia específica: no se traducía a la categoría real
  `World War, 1939-1945`. La clasificación y las búsquedas podían consumir
  varios turnos del modelo para una recomendación sencilla.
- El navegador no tenía un límite de espera para la petición completa.

## Implementación

- Presupuesto HTTP de **9 s de trabajo** (máximo, incluso con configuraciones
  antiguas de 360 s) y cancelación de la espera del cliente a los **10 s**.
  Se reserva margen para serialización, sesión y transporte local; no es una
  garantía física sobre una red o un sistema operativo bloqueado.
- La búsqueda, los caminos rápidos, la inferencia y el fallback comparten un
  único deadline. El cliente Ollama ya no fuerza mínimos de 30/60 s.
- Espera aislada con solo dos slots y sin cola ilimitada. Un resultado tardío
  no se publica ni se recuerda ni consume cuota. Python no puede matar un hilo
  atascado: este mantiene su slot y su lease hasta finalizar; los sockets HTTP
  cooperativos sí vencen con el presupuesto.
- Respuestas por extracción de fichas originales locales y de catálogos,
  conservando título/autor/ID, enlaces y auditoría literal. No se reemplazan
  con memoria del modelo las pruebas que falten.
- Las búsquedas interactivas usan FTS sin cargar otro modelo de embeddings en
  mitad del turno. Los índices híbridos y la recuperación offline se conservan.
- Una cita sin pasaje local autorizado se detecta antes de la clasificación.
  Las fichas propias prevalecen sobre la biblioteca incluida, incluso si su
  descripción es más breve; nunca se fusiona otra redacción con su procedencia.
- Variantes coloquiales de petición, cantidades, materia de Segunda Guerra
  Mundial y continuidad ordinal. No se corrigen títulos ni pasajes privados.
- Rutas rápidas también con cuotas activas: precomprobación antes de trabajar,
  consumo únicamente si se publica una respuesta.
- Cliente principal y flotante comparten transporte con timeout; no se suman
  2,5 s de animación después de recibir la respuesta completa. Diseño intacto.

## Primera comprobación HTTP real

`http_consulta_inicial.json` conserva una llamada real al endpoint con CSRF,
cookies, middleware y SSE, en un servidor loopback y una base temporal vacía.
No se utilizaron mocks para el endpoint, Ollama ni las fuentes.

- Consulta exacta reportada: **0,080 s** hasta completar SSE.
- Primer texto: **0,079 s**. Estado: `answered`. Llamadas al modelo: **0**.
- Tres libros y tres fuentes editoriales; la respuesta no pide aclarar un
  tema que el lector ya expresó.
- Este dato individual **no es** un p95 general ni una garantía para todas las
  preguntas. La evaluación amplia se conserva en artefactos separados.

## Procedencia de las fichas nuevas

Se consultaron las fichas editoriales públicas durante esta implementación.
Solo se incluyen metadatos y una redacción factual original, sin copiar obras
ni sinopsis completas, precios, portadas o páginas/ediciones dudosas.

1. **La segunda guerra mundial — Antony Beevor**.
   https://pasadopresente.com/colecciones/historia/la-segunda-guerra-mundial
   La ficha respalda el enfoque global y el uso de cartas/diarios de combatientes.
2. **Se desataron todos los infiernos — Max Hastings**.
   https://www.planetadelibros.com.ar/libro-se-desataron-todos-los-infiernos/120454
   La ficha confirma título, autor y enfoque global con experiencias humanas.
3. **Si esto es un hombre — Primo Levi**.
   https://www.planetadelibros.com/libro-si-esto-es-un-hombre/268336
   La ficha confirma autor, materia y testimonio del deportado a Auschwitz;
   se diferencia explícitamente de una historia militar general.

Las cuatro fichas literarias anteriores se reutilizan desde `seed_works`, sin
modificar su SQLite ni afirmar que se hayan vuelto a verificar hoy sus páginas.
No hay una revisión factual independiente certificada de toda la evaluación.

También se verificaron metadatos y descripciones de arranque para seis clásicos:

- *Cien años de soledad* — Penguin Libros, ficha 35974, ISBN 9788497592208.
- *Pedro Páramo* — Fondo de Cultura Económica, ficha `9681605020/F`.
- *El Aleph* — Penguin Libros, ficha 376318, ISBN 9788491057406.
- *La metamorfosis* — artículo público de Wikipedia, contrastado con la ficha
  de Penguin Libros Perú 342112 (ISBN 9786124463686).
- *Platero y yo* — metadatos Gutenberg 9980 y comienzo de su edición HTML
  enlazada, no el resumen automático de la portada del catálogo.
- *Don Quijote de la Mancha* — artículo público para los dos personajes básicos
  y ficha académica de la RAE
  https://www.rae.es/obras-academicas/bcrae/don-quijote-de-la-mancha para título,
  autor y nombre abreviado. RAE se admite como referencia bibliográfica; no se
  añadió una autorización general de alias desde cualquier wiki.

Esta biblioteca es finita y ampliable, no conocimiento universal ni una
investigación web nueva en cada consulta. Algunas preguntas conocidas de la
matriz ayudaron a identificar huecos del corpus: la repetición no es una prueba
ciega de generalización.

## Microbenchmark de modelos ya instalados

`modelos_microbenchmark.json` mide solo una definición muy breve, sin el
pipeline ni auditoría; contexto 8192 y hasta 64 tokens. Incluye carga de modelo
y no controla equivalencia de caché/temperatura inicial.

| Modelo | Tiempo observado | Resultado |
|---|---:|---|
| qwen3.5:9b-q4_K_M | 10,018 s | timeout, latencia final desconocida |
| litmate-qwen35-text:9b-q4_K_M | 7,824 s | definición terminada; 4,420 s de carga |
| qwen3.5:4b | 7,452 s | definición terminada; 4,726 s de carga |

No justifica sustituir el 9B ni sus guardas: no se midió exactitud comparativa.
Se conserva el modelo configurado. Las fichas verificadas evitan cargarlo para
las consultas que pueden resolverse directamente.

## Estado de validación

Los tres fallos de filtros nuevos ya se reprodujeron y corrigieron: tema con
mayúsculas confundido con autor, autores distintos y exclusión de obras previas
en resultados externos. La suite general ejecutada pasó con **1119 pruebas**
en **7,507 s**; se añadieron 41 pruebas respecto de las 1078 iniciales;
también **13 pruebas de pagos** y **198 comprobaciones de JavaScript**.

La primera matriz HTTP (`http_matriz_v1.json`) mide 46 turnos, todos por debajo
de diez segundos; p50 9,0065 s, p95 9,018 s, máximo 9,019 s. Pero solo hubo
9 respuestas publicadas, 27 no disponibles, 4 aclaraciones, 3 rechazos y 3
respuestas HTTP 503: **terminar rápido no equivalía a contestar bien**. Se
conserva este resultado desfavorable, no se borra ni se presenta como éxito de
calidad.

### Cuatro ejecuciones HTTP reales

| Ejecución | Respondidas | No disponibles | Aclaraciones | Rechazos | HTTP 503 | p50 | p95 | Máximo |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| v1 | 9 | 27 | 4 | 3 | 3 | 9,0065 s | 9,018 s | 9,019 s |
| v2 | 23 | 15 | 5 | 3 | 0 | 0,042 s | 9,019 s | 9,033 s |
| v3 | 22 | 16 | 5 | 3 | 0 | 0,041 s | 9,020 s | 9,024 s |
| **v4 vigente** | **21** | **17** | **5** | **3** | **0** | **0,0465 s** | **9,017 s** | **9,025 s** |

Cada ejecución contiene los 42 turnos en vivo de `datos_evaluacion_ia_v2.json`
y cuatro turnos añadidos sobre el caso reportado. En v4 se publicaron **17/42**
respuestas de la matriz original y **4/4** de los turnos añadidos. La evaluación
anterior final3, que no pasaba por HTTP y permitía varios minutos, publicaba
21/42: no se ha demostrado una mejora general de cobertura frente a ella.

Las fuentes externas variaron: autoría de *La Odisea* respondió en v3 y falló
en v4. Por ello no se selecciona v2 por tener el mayor número de respuestas,
ni se atribuyen a precisión los cambios de cobertura o de p50. Las cuatro
ejecuciones mantuvieron 46/46 tiempos menores de diez segundos.

`http_matriz_v4.json` y `analisis_v4.json` son los artefactos vigentes. Su hash
de fuentes es `710dc64e59dc8c8f2c6adba1977997ea803ccec8bc53f60a4a1836dbf39a2d4a`;
`source_files_changed_during_run=false`. Las comprobaciones automáticas no
encontraron términos obligatorios ausentes ni prohibidos presentes en las
respuestas publicadas; **no certifican verdad factual**. Exactitud y tasa de
error factual siguen en `null` por falta de revisión independiente.

Los turnos que vencen no devuelven su cliente al hilo HTTP. Desde v4 su número
de inferencias es **desconocido (`null`)**, no cero. Los ceros de esas filas en
v1-v3 eran un valor del proveedor sintético `deadline`, no una medición de cero
trabajo de GPU. No deben utilizarse para comparar número de llamadas.

La configuración real usa MySQL y sesiones en base de datos. El benchmark usa
una base temporal vacía para no consultar ni alterar datos reales. No se ha
medido la latencia del historial/sesión en la base MySQL de la cuenta real.
El timeout del navegador evita esperar cinco minutos, pero una base o red
bloqueada puede impedir recibir una respuesta útil. No se promete universalmente
una respuesta compleja verificada en diez segundos.

## Archivos y reproducción

- Tiempo y concurrencia: `core/ai_budget.py`, `core/local_llm.py`,
  `core/literary_ai_views.py`, `litmate_project/ai_settings.py`.
- Comprensión/recuperación: `core/literary_language.py`,
  `core/ai_quick_answers.py`, `core/data/verified_readings.json`,
  `core/ai_identification_details.py`, `core/books_google.py`,
  `core/literary_ai.py`, `core/literary_conversation.py`,
  `core/literary_constraints.py`, `core/literary_identity.py`,
  `core/literary_research.py`, `core/literary_search.py`.
- Cliente: `static/js/litmate_safe.js`, `static/js/chatbot.js`,
  `static/js/floating_chat.js`; versiones de assets en las tres plantillas.
- Pruebas: `core/test_chat_deadline.py`, regresiones de identificación,
  personajes y reparación factual, `verificar_chat_seguro.js` y
  `verificar_proyecto.py`.
- Diagnóstico: `core/management/commands/diagnosticar_ia.py` distingue el
  presupuesto del chat del diagnóstico offline. Se ejecutó sin conexiones.
- Benchmark: `evaluar_chat_http.py`; crea exclusivamente tablas y coordinación
  temporales, nunca migra ni consulta las tablas reales de usuarios.

```powershell
.\venv\Scripts\python.exe -B verificar_proyecto.py
.\venv\Scripts\python.exe -B verificar_proyecto.py suscripciones.test_payments
node verificar_chat_seguro.js

.\venv\Scripts\python.exe -B evaluar_chat_http.py `
  --matrix datos_evaluacion_ia_v2.json `
  --message "hola recomiendame libros sobre la segunda guerra mundial" `
  --message "Cuéntame más del segundo" `
  --message "porfa recomendame un libro sobre la II guerra mundial" `
  --message "¿Qué puedo leer sobre la segunda guerra mundial?" `
  --output reportes\nueva_ejecucion_10s\http.json
```

Para aplicar en desarrollo, reiniciar Django con el Python del entorno virtual
y recargar el navegador con **Ctrl+F5**. No se modificó `.env`, no se instalaron
paquetes, no se hicieron cobros, migraciones, despliegues ni push.

## Próximo trabajo

Estabilizar recuperación/caché y aumentar cobertura de consultas complejas,
recomendaciones restringidas, comparación e investigación reciente. Evaluar
modelos o transportes compactos mediante pruebas equivalentes de calidad antes
de sustituir el 9B. No resolver esas carencias quitando auditorías ni aumentando
silenciosamente el límite de espera que pidió el lector.
