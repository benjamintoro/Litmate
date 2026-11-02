# Recorrido de ocho minutos — versión comprobada el 31-10-2026

Este guion utiliza preguntas reales de `recorrido_cierre.json` y la grabación
`grabacion_defensa/`. No garantiza encontrar cualquier libro ni demostrar una
exactitud del 99 %. La recomendación por género está verificada; la similitud
profunda con filtros estrictos todavía puede devolver pocas opciones o abstenerse.

Antes de presentar: dejar el PC de casa despierto, servicios iniciados y perfil
de demo abierto. Si se autoriza Funnel, probar desde datos móviles antes de salir.
Usar una sola ventana de conversación para este recorrido; no lanzar benchmarks
en paralelo. Respetar los límites de solicitudes. No mostrar terminales con claves.

| Tiempo | Acción en el chat | Qué demuestra |
|---|---|---|
| 0:00–0:40 | Entrar al chat y explicar su especialización literaria. | Interfaz, avatar y tarjetas existentes; acceso protegido. |
| 0:40–1:30 | «Recuerdo un libro donde un niño vive en un planeta pequeño y cuida una rosa». | Identificación fundamentada de *El principito*, expresada como posible coincidencia. |
| 1:30–2:10 | «¿Qué pistas te hicieron pensar en ese libro?» | Reutiliza planeta, niño y rosa de una fuente, sin afirmar que sea una combinación universalmente única. |
| 2:10–3:10 | «¿De qué trata?» y «¿Qué relación hay entre el principito y el zorro?» | Argumento y relación documentada, conservando la obra. La relación disponible es breve. |
| 3:10–4:10 | «Recomiéndame dos novelas de fantasía en español». | Cantidad, idioma y dos tarjetas verificadas. En esta base: Harry Potter y el misterio del príncipe; Choque de Reyes. Son entregas de series; no afirmar que sean autoconclusivas. |
| 4:10–5:10 | «Ya leí el primero y no me interesa el segundo». Después: «Dame otros dos libros de fantasía en español». | Memoria privada de lecturas y rechazos. Aparecen El Camino de los Reyes y El Hobbit sin repetir las dos anteriores. |
| 5:10–6:00 | «Cuéntame más del segundo» y «¿Dónde puedo encontrarlo?». | Selecciona El Hobbit; reutiliza su sinopsis y conserva sus botones. No asegura stock ni precio. |
| 6:00–7:00 | Mostrar el ensayo registrado de La mala costumbre. Si se ejecuta en vivo: «¿De qué trata La mala costumbre de Alana S. Portero?». | Obra ausente al inicio, consultada fuera y conservada en la copia de demo. Investigación medida: 4,43 s; sesión nueva sin red pública: 0,62 s. La evidencia describe una premisa, no toda la trama. |
| 7:00–8:00 | Explicar procedencia, incertidumbre y separación entre MySQL, memoria/RAG y modelo local. | La IA no se convierte en su propia fuente; una búsqueda sin pruebas debe abstenerse. Aclarar que falta certificar el acceso externo si no se ha hecho aún. |

Opcional: «¿Quiénes son sus protagonistas?» después de la trama está probado,
pero la lista sigue siendo parcial y algunos perfiles recuperados son
interpretativos. No presentarla como análisis exhaustivo del reparto.

## Contingencia auténtica

Abrir en un navegador `grabacion_defensa/funcionamiento_real.webp`: animación de
capturas reales de Edge, sin audio, con ocho turnos y 16 respuestas HTTP 200
registradas (ocho SSE y ocho finalizaciones). No es un vídeo MP4 ni una simulación
de respuestas. Sus pausas corresponden al ritmo de captura/lectura del ensayo;
no sirven para medir la latencia del servidor.

- `grabacion_defensa/frame-001.png`: identificación.
- `grabacion_defensa/frame-026.png`: seguimiento contextual de El Hobbit y botones.
- `grabacion_defensa/captura.json`: texto recibido, tiempos de interfaz y estados HTTP.

No usar las carpetas de ensayos fallidos como prueba de funcionamiento. Se
conservaron para documentar los errores encontrados, no para ocultarlos.

Si no hay conexión en el instituto, identificar claramente la grabación como
respaldo y utilizar esas capturas. Si se presenta localmente en el PC de casa,
el perfil `--modo local` funciona sin Tailscale ni publicación. Para comprobar
el acceso remoto y detenerlo, seguir `servidor_remoto.md`.
