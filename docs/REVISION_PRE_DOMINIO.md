# Revisión previa al dominio · 21 de noviembre de 2026

Esta rama reúne reseñas con libro y estrellas, comentarios y moderación, cuentas en MySQL, Webpay en integración y el checkout simulado, junto con la ampliación del catálogo y las mejoras del asistente.

El candidato corrige cambios de tema, referencias a recomendaciones recientes, nombres con iniciales y la distinción entre sinopsis y metadatos. También mejora el espacio de lectura del chat en móvil y limita las solicitudes de invitados en el perfil de publicación abierta.

En aislamiento se aprobaron 1.131 pruebas automatizadas y 90 combinaciones de páginas y tamaños en Edge. El recorrido móvil incluyó siete respuestas por streaming, recuperación y borrado del chat, creación de una reseña y comprobante de Pro simulado. Se probaron dos conversaciones de 20 turnos. Quedaron consultas complejas sin respuesta completa.

`fixtures/catalogue/reviewed_books_20261118.json` conserva 15 fichas revisadas y su procedencia. La edición solicitada de *Madre misteriosa: la mano que mece la cuna* es de Marilyn Kaye, ISBN 9788487482915. `scripts/knowledge/reviewed_catalogue_enrichment.py` contiene el ensayo de seis mejoras sobre un catálogo restaurado. La base de 12.616 fichas se gestiona fuera de Git. Parte del catálogo tiene solo metadatos y algunas atribuciones o clasificaciones siguen sin confirmar.

Para ejecutar la copia local protegida, `Iniciar_LitMate.ps1` utiliza el lanzador versionado `scripts/accounts/arrancar_protegido.py`. La configuración de la instancia, credenciales, medios, bases de datos y copias de respaldo se guardan fuera del control de versiones.

El envío a la rama no realiza una publicación de la web. Antes de abrir el dominio, comprobar HTTPS, protección de la administración, restauración de datos y Webpay en integración con el nuevo origen. El conjunto incluye la migración 0007 ya utilizada por reseñas y Webpay. Las correcciones de esta revisión no añaden cambios de esquema.
