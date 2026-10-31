# Resultado medido del lote

## Conversación HTTP/SSE final

Artefactos: `verified_http.json`, `jack_recheck.json`, `measured_summary.json`.
MySQL local real; memoria, RAG y cachés de prueba aislados. Google Books habilitado
en el proceso, con la autorización previa de ausencia de facturación. Las banderas
no se guardaron en `.env`.

| Solicitud | Resultado comprobado | Tiempo |
|---|---|---:|
| Libro de Heinz Wuth | Esto es ciencia & cocina, ficha y descripción reales | 2,154 s |
| Género del libro anterior | temas de cocina y ciencia; conserva identidad | 0,470 s |
| Otros similares | The Science of Sugar Confectionery, W. P. Edwards; una opción, sin relleno | 6,735 s |
| Por qué se parece el primero | recupera las descripciones de la referencia y la opción ordinal | 6,613 s |
| Otro sobre química en la cocina | Chemistry of Cookery, W. Mattieu Williams; una opción | 3,354 s |
| Libros de Jack, dentro de esa ejecución | fallo temporal real de proveedores, reconocido | 4,359 s |
| Jack, repetición aislada posterior | tres publicaciones verificadas, tres tarjetas, 0 llamadas al modelo | 2,701 s |

No hubo errores HTTP/SSE ni modificaciones de conteos MySQL o hashes originales
en esos turnos. Las llamadas de los turnos tercero y cuarto fueron de traducción
y verificación de presentación: no se atribuye todo el tiempo a búsqueda.

La ejecución anterior al cambio extractivo tardó 9,502 s para identificar a Heinz
y 17,324 s para Jack. Es una comparación de consultas públicas equivalentes con
Google habilitado, no un experimento controlado de disponibilidad de red. La
primera línea base sin Google habilitado tampoco constituye una comparación
exclusiva del código. No se ocultan estas diferencias de configuración.

La muestra final de seis turnos dio media 3,948 s y mediana 3,857 s. Incluye un
fallo real, por lo que «seis bajo diez segundos» no significa seis respuestas
útiles ni una tasa de exactitud demostrada. Es demasiado pequeña para afirmar
un p95 habitual garantizado. No se demostró una tasa de errores menor al 1 %.

## Generalización y límites encontrados

- Se ejecutaron nueve conversaciones reales adicionales: fantasía oscura,
  historia chilena y peruana, filosofía, astronomía, manga, romance, microbiología
  y grabado. Sus 18 turnos están en `independent_conversations.json`.
- Esa matriz encontró dos errores nuevos (Babar tras una novela filosófica y una
  novela romántica médica tras un manual científico). Se reprodujeron con obras
  sintéticas y corrigieron público frente a tema y tipo de publicación. No hubo
  listas negras de títulos. Los filtros se reutilizan en ambos recorridos.
- `holdouts_corrected.json` ya no ofrece esas dos selecciones irrelevantes, pero
  ambos seguimientos llegaron a unos 35 s y fallaron en recuperación/generación.
  No se cuentan como recomendaciones resueltas. Después se reforzó además la
  auditoría de recomendaciones de materias desconocidas.
- Otras búsquedas de similares no recuperaron una alternativa suficientemente
  documentada. Eso limita la cobertura. Un filtro seguro no reemplaza la falta
  de metadatos ni un motor bloqueado.
- Se conserva el caso intermedio que volvió a recomendar la referencia mediante
  un respaldo exterior (`closure_http.json`). La regresión de ese respaldo y la
  conversación posterior comprueban el arreglo de no repetición.
- El idioma aún puede fallar en descripciones extranjeras complejas, como se
  documenta en el lote previo de calidad. La explicación de similitud muestra
  evidencia temática; no promete semejanza completa de argumentos o enfoques.

## Verificaciones

- `tests_release.json`: 525 pruebas Django dirigidas aprobadas, 0 fallos, 0 errores;
  12,552 s de suite. SQLite y almacenes auxiliares desechables, sin MySQL de producción.
- Módulo nuevo: 27 pruebas, con subcasos por categorías, privacidad y frase con
  puntuación natural; última ejecución aprobada tras ampliar ese subcaso.
- `node verificar_chat_seguro.js`: 246 comprobaciones aprobadas de formato,
  atribuciones, seguridad, SSE, HTTP, CSRF y voz; sin modificar JavaScript.
- `git diff --check`: sin incidencias.
- `integrity_final.json`: `.env`, memoria literaria y RAG conservan los hashes
  iniciales; SQLite quick_check OK, cero problemas de claves externas. Los cinco
  almacenes auxiliares comprobados por las conversaciones permanecen intactos.

No se instalaron dependencias, modelos ni tareas automáticas. No se ejecutaron
migraciones, importaciones globales ni operaciones destructivas. El trabajo
anterior y los respaldos se conservaron. No hubo commits ni push.

## Pendiente concreto

Mejorar cobertura y síntesis de los seguimientos complejos que aún rechazan o
agotan su presupuesto; medirlos con el mismo conjunto antes de cambiar modelos.
Mejorar la fidelidad gramatical de ciertas traducciones y las comparaciones
literarias extensas. La disponibilidad de Google Books y buscadores externos
continúa siendo variable; un reintento exitoso no garantiza disponibilidad futura.
