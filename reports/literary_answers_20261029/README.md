# Respuestas literarias y presentación — 29 de octubre de 2026

Se trabajó sobre los cambios existentes, sin reconstruir el proyecto. Se conservan las ejecuciones fallidas y los resultados intermedios; `answered` por sí solo no acredita exactitud.

## Causas y correcciones

| Causa demostrada | Corrección general |
| --- | --- |
| La sección Argumento recuperada se sustituía por la introducción. | `bound_sources` conserva el pasaje y su introducción en `narrative_context`, sin mezclar revisiones ni fuentes. |
| Una premisa breve cerraba la recuperación; fechas y notas editoriales aparentaban contenido suficiente. | `retrieve_sources` comprueba oraciones narrativas útiles, conserva el contenido ya aceptado de la conversación y permite ampliar una introducción insuficiente. |
| Con varios snapshots se publicaba el primero, aunque otro tuviera más argumento verificable. | `direct_answer` compara las oraciones completas utilizables antes de elegir. Conserva los validadores de borrador, evidencia y auditoría estricta. |
| Un poema épico no se reconocía como identidad literaria; «La obra» no se consideraba sección narrativa. | Identidad de poemas/epopeyas y atribución a autores de un nombre; encabezados de contenido generales. No se fusionan registros de catálogo por quitar artículos. |
| Los personajes sólo se recuperaban de listas o tablas; se perdían aposiciones del argumento y perfiles vinculados. | `narrative_character_facts`, `_facts` y `_profile_facts` recuperan papeles nominales explícitos y conservan pruebas literales y vínculo a la obra. |
| Una aposición podía continuar tras una raya y atribuir a un personaje la acción de otro. | Límites sintácticos en rayas, paréntesis y puntuación; regresión sintética previa que fallaba. No se infieren roles de mera coocurrencia. |
| Nombres abreviados podían contarse como otro personaje. | `distinct_character_mentions` omite menciones de apellido compuesto insuficientemente diferenciadas en la presentación. No crea alias ni fusiona entidades; una lista de un personaje se marca como parcial. |
| Variantes editoriales del autor bloquearon una continuación. | Una publicación independiente con título y autor explícitos puede seleccionar la ficha correspondiente. Un apellido parecido no verifica identidad; autores contrarios siguen bloqueados y los registros originales no se fusionan. |
| Una película o un título sin espacios no se resolvían. | Alternativas de formato sólo para descubrimiento; `adaptation_answer` explica una relación literaria literalmente documentada y pide aclarar el medio. Una película no se convierte en alias de su novela. |
| Créditos, dominios y marcadores de fuente aparecían entre los párrafos. | El renderer común separa narración, enlaces breves reales y atribución accesible en «Créditos y licencia». El backend mantiene URLs, pruebas, revisiones y licencias. |

También se respetan separadores invisibles de referencias al segmentar oraciones y se actualiza la versión de caché a `extractive-answer-v8-literary-coverage`. No se borraron las respuestas antiguas.

## HTTP/SSE real

Cada consulta empleó Django, MySQL local, HTTP con CSRF y SSE/finalización reales. La memoria narrativa y las cachés se copiaron a directorios temporales. No se sustituyeron proveedores ni respuestas de Ollama por simulaciones. El modelo estuvo disponible, pero la ruta final de estos siete casos no necesitó inferencia.

| Consulta | Línea base, segundos | Cierre, segundos | Resultado del cierre |
| --- | ---: | ---: | --- |
| Trama de Naruto | 2,2300 | 2,1917 | Argumento ampliado con evidencia del manga. |
| Trama de El rey león | 12,3579 | 3,2913 | Identifica la película y su inspiración literaria; solicita aclarar libro/medio. |
| Trama de La Odisea | 21,1010 | 3,1941 | Cinco oraciones del argumento; evita notas de transliteración en la presentación. |
| Trama de BladeRunner | 6,3771 | 2,3177 | Identifica Blade Runner y su relación parcial con la novela de Philip K. Dick. |
| Trama de Frankenstein | 0,4782 | 0,5172 | Explica creación, rechazo, huida y conflicto, sin completar de memoria. |
| Personajes de Frankenstein | 19,9404 | 0,2284 | Recupera Víctor y la criatura desde fuentes vinculadas. |
| Personajes de La Odisea | 5,2384 | 3,9734 | Recupera seis nombres y roles literales; no es una lista exhaustiva. |

Evidencia: `antes.json` y `cierre_7.json`. En el cierre todos los streams terminaron con DONE, las llamadas al modelo fueron cero, y los conteos MySQL y el hash de la memoria original permanecieron iguales durante cada prueba.

Conversación real de la misma sesión (`contexto_cobertura.json`): trama de Frankenstein en **0,6820 s**, seguida de «¿Y sus personajes?» en **0,2795 s**, conservando la identidad. Ejecuciones anteriores de esa continuación fallaron; se conservan en los informes y motivaron la corrección del criterio de suficiencia.

Las repeticiones también documentaron variación externa: El rey león volvió una vez a desambiguación de fichas y una consulta de La Odisea no obtuvo evidencia suficiente. No se sustituyeron esos fallos por datos inventados. Las correcciones finales de selección se comprobaron con regresiones y con `cierre_7.json`; esto no garantiza que un proveedor remoto esté siempre disponible.

## Pruebas y archivos

Regresiones generales: `core/test_literary_answer_depth.py`; compatibilidad en las pruebas existentes de narrativa, identidad, personajes, contexto, recomendaciones, presentación y Wikipedia. La suite general y sus resultados finales se registran también en el informe del sistema continuo.

Frontend: **242 comprobaciones** mediante `node verificar_chat_seguro.js`, incluyendo SSE, historial, enlaces seguros, atribución, tarjetas y voz. No se modificaron las tarjetas «PARA SEGUIR LEYENDO», plantillas, CSS, avatar ni distribución. No se afirma inspección visual manual de todos los navegadores.

Archivos funcionales de este frente:

- `core/ai_narrative_answers.py`, `core/ai_character_answers.py`.
- `core/literary_identity.py`, `core/literary_search.py`, `core/literary_web.py`, `core/literary_quality.py`.
- `core/ai_answer_cache.py`, `static/js/litmate_safe.js`, `verificar_chat_seguro.js`.
- `core/test_literary_answer_depth.py`, `core/test_wikipedia_character_tables.py`.
- `scripts/knowledge/search_narrative_check.py`, `.gitignore`.

Reproducción desde PowerShell 5.1, con contraseña oculta:

```powershell
Set-Location G:\Proyecto\Litmate
.\venv\Scripts\python.exe -B -m scripts.knowledge.search_narrative_check --suite literary --output reports/literary_answers_20261029/nueva_ejecucion.json
.\venv\Scripts\python.exe -B -m scripts.knowledge.search_narrative_check --followup --output reports/literary_answers_20261029/nueva_conversacion.json
node verificar_chat_seguro.js
```

## Límites pendientes

Las listas no agotan todos los personajes ni todos los acontecimientos. Una fuente sin clasificación explícita no permite llamar «principal» a cualquier personaje mencionado. La generación libre de Ollama y su auditoría todavía necesitan evaluación independiente de afirmaciones complejas: una ejecución intermedia del poema añadió detalles insuficientemente respaldados. La vía extractiva evita ese fallo en los casos cerrados, sin desactivar auditorías de otras rutas. Este lote no mide una tasa global de errores inferior al 1 % ni un p95 representativo.

No se cambiaron credenciales, `.env`, el arranque MySQL, pesos del modelo ni servicios de pago. Se conservaron los cambios anteriores y todos los respaldos.
