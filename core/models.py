from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.utils.text import slugify
import re



# =====================================================================
# --- 1. CATÁLOGO LITERARIO ---
# =====================================================================

class Autor(models.Model):
    """Información de autores de libros."""
    nombre = models.CharField(max_length=200, db_index=True)
    pais_origen = models.CharField(max_length=100, blank=True, null=True)
    ano_nacimiento = models.IntegerField(blank=True, null=True)
    biografia = models.TextField(blank=True, null=True)
    foto_url = models.URLField(max_length=500, blank=True, null=True)

    class Meta:
        verbose_name = 'Autor'
        verbose_name_plural = 'Autores'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class Genero(models.Model):
    """Categorías y géneros literarios para clasificación y analítica."""
    nombre = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    descripcion = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name = 'Género Literario'
        verbose_name_plural = 'Géneros Literarios'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class Editorial(models.Model):
    """Casas editoriales."""
    nombre = models.CharField(max_length=200, unique=True)
    pais = models.CharField(max_length=100, blank=True, null=True)

    class Meta:
        verbose_name = 'Editorial'
        verbose_name_plural = 'Editoriales'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class Libro(models.Model):
    """Catálogo central de libros enriquecido desde Google Books / APIs."""
    google_book_id = models.CharField(max_length=100, unique=True, null=True, blank=True, db_index=True)
    isbn_10 = models.CharField(max_length=20, blank=True, null=True, db_index=True)
    isbn_13 = models.CharField(max_length=20, blank=True, null=True, db_index=True)
    titulo = models.CharField(max_length=255, db_index=True)
    autor = models.ForeignKey(Autor, on_delete=models.CASCADE, related_name='libros')
    editorial = models.ForeignKey(Editorial, on_delete=models.SET_NULL, null=True, blank=True, related_name='libros')
    generos = models.ManyToManyField(Genero, related_name='libros', blank=True)
    genero = models.CharField(max_length=100, blank=True, default='')  # Compatibilidad
    sinopsis = models.TextField(blank=True)
    paginas = models.IntegerField(default=0)
    idioma = models.CharField(max_length=10, default='es')
    fecha_publicacion = models.DateField(null=True, blank=True)
    portada_url = models.URLField(max_length=500, blank=True, null=True)
    
    # Métricas agregadas para analítica y rankings rápidos
    calificacion_promedio = models.FloatField(default=0.0)
    total_resenas = models.IntegerField(default=0)
    total_favoritos = models.IntegerField(default=0)
    embedding_id = models.CharField(max_length=100, blank=True, null=True, help_text="Vector ID en Pinecone")
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Libro'
        verbose_name_plural = 'Libros'
        ordering = ['titulo']

    def __str__(self):
        return f"{self.titulo} - {self.autor.nombre}"


# =====================================================================
# --- 2. PERFILES Y COMPORTAMIENTO DE USUARIO ---
# =====================================================================

class PerfilUsuario(models.Model):
    """Perfil extendido del usuario con variables demográficas para análisis de datos."""
    usuario = models.OneToOneField(User, on_delete=models.CASCADE, related_name='perfil')
    nombre = models.CharField(max_length=100, null=True, blank=True)
    apellido = models.CharField(max_length=100, null=True, blank=True)
    correo = models.EmailField(unique=True, null=True, blank=True)
    telefono = models.CharField(max_length=20, blank=True, null=True)
    pais = models.CharField(max_length=100, default='Chile', blank=True)
    genero_lector_preferido = models.CharField(max_length=100, blank=True, null=True, help_text="Género favorito para recomendaciones")
    fecha_nacimiento = models.DateField(null=True, blank=True)
    imagen = models.ImageField(default='default.jpg', upload_to='profile_pics')
    biografia = models.TextField(blank=True, null=True, verbose_name='Sobre mí')
    meta_anual_libros = models.IntegerField(default=12, help_text="Meta anual de libros a leer")
    tiendas_favoritas = models.CharField(max_length=255, default='buscalibre,amazon,fch', blank=True)
    alertas_precio_activas = models.BooleanField(default=True)
    fecha_registro = models.DateTimeField(auto_now_add=True)
    ultima_conexion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Perfil de Usuario'
        verbose_name_plural = 'Perfiles de Usuarios'

    def __str__(self):
        return f'Perfil de {self.usuario.username}'


class ListaLectura(models.Model):
    """Listas personalizadas creadas por el usuario (ej: 'Mis clásicos para el invierno', 'Libros de Ciencia Ficción')."""
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='listas_lectura')
    nombre = models.CharField(max_length=150)
    descripcion = models.TextField(blank=True, default='')
    es_publica = models.BooleanField(default=False)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Lista de Lectura'
        verbose_name_plural = 'Listas de Lectura'
        ordering = ['-fecha_creacion']

    def __str__(self):
        return f"{self.nombre} ({self.usuario.username})"


class ElementoListaLectura(models.Model):
    """Libros pertenecientes a una lista personalizada."""
    ESTADO_CHOICES = (
        ('por_leer', 'Planeo / Por leer'),
        ('leyendo', 'Leyendo'),
        ('completado', 'Completado / Leído'),
    )
    lista = models.ForeignKey(ListaLectura, on_delete=models.CASCADE, related_name='elementos')
    google_id = models.CharField(max_length=100)
    titulo = models.CharField(max_length=255)
    autores = models.CharField(max_length=255, blank=True, default='')
    imagen_url = models.URLField(max_length=500, blank=True, null=True)
    estado_lectura = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='por_leer')
    nota_personal = models.CharField(max_length=255, blank=True, default='')
    fecha_agregado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Elemento de Lista'
        verbose_name_plural = 'Elementos de Listas'
        unique_together = ('lista', 'google_id')

    def __str__(self):
        return f"{self.titulo} en {self.lista.nombre} ({self.estado_lectura})"


class Resena(models.Model):
    """Reseñas de libros con métricas para análisis de sentimiento NLP."""
    CALIFICACION_CHOICES = [(i, f'{i} estrellas') for i in range(1, 6)]

    libro = models.ForeignKey(Libro, on_delete=models.CASCADE, related_name='resenas')
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='resenas')
    calificacion = models.IntegerField(choices=CALIFICACION_CHOICES, default=5)
    comentario = models.TextField()
    votos_utiles = models.IntegerField(default=0, help_text="Upvotes de la comunidad")
    sentimiento_score = models.FloatField(default=0.0, help_text="Score NLP (-1.0 muy negativo a +1.0 muy positivo)")
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Reseña'
        verbose_name_plural = 'Reseñas'
        ordering = ['-fecha_creacion']

    def __str__(self):
        return f'Reseña de {self.usuario.username} ({self.calificacion}★) para {self.libro.titulo}'


class LibroFavorito(models.Model):
    """Libros guardados en favoritos."""
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='favoritos')
    libro = models.ForeignKey(Libro, on_delete=models.CASCADE, null=True, blank=True, related_name='favoritos_usuario')
    google_id = models.CharField(max_length=100)
    titulo = models.CharField(max_length=255)
    autores = models.CharField(max_length=255)
    imagen_url = models.URLField(max_length=500, blank=True, null=True)
    fecha_agregado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Libro Favorito'
        verbose_name_plural = 'Libros Favoritos'
        unique_together = ('usuario', 'google_id') 

    def __str__(self):
        return f"{self.titulo} - {self.usuario.username}"


class EstadoLectura(models.Model):
    """Tracking de progreso de lectura y hábitos lectores para analítica."""
    ESTADO_CHOICES = (
        ('por_leer', 'Por Leer / En Lista'),
        ('leyendo', 'Leyendo Actualmente'),
        ('completado', 'Leído / Completado'),
        ('abandonado', 'Abandonado'),
    )

    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='estados_lectura')
    libro = models.ForeignKey(Libro, on_delete=models.CASCADE, related_name='estados_lectura')
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='por_leer')
    pagina_actual = models.IntegerField(default=0)
    porcentaje_avance = models.FloatField(default=0.0)
    minutos_lectura_estimados = models.IntegerField(default=0)
    fecha_inicio = models.DateTimeField(null=True, blank=True)
    fecha_termino = models.DateTimeField(null=True, blank=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Estado de Lectura'
        verbose_name_plural = 'Estados de Lectura'
        unique_together = ('usuario', 'libro')

    def __str__(self):
        return f"{self.usuario.username} - {self.libro.titulo} ({self.get_estado_display()})"


# =====================================================================
# --- 3. ASISTENTE DE IA, RAG Y TELEMETRÍA LLM ---
# =====================================================================

class AsistenteIA(models.Model):
    """Configuración y personalidad del Asistente de IA."""
    nombre = models.CharField(max_length=100, default='LitMate')
    descripcion = models.CharField(max_length=255, blank=True, default='Asistente virtual experto en literatura y recomendaciones')
    prompt_sistema = models.TextField(
        default=(
            "Eres LitMate, un asistente virtual experto en literatura. Tu misión es dar recomendaciones, "
            "resumir tramas y hablar sobre libros. Sé amigable, conversacional y entusiasta.\n"
            "Habla como un humano experto, no como un robot. Nunca digas 'Según los datos proporcionados'.\n\n"
            "REGLA DE ORO PARA ENLACES: Si recomiendas un libro o el usuario pide dónde comprarlo/leerlo, "
            "NUNCA digas que no puedes dar enlaces. Si no te he pasado un link directo en el contexto, "
            "GENERA tú mismo un enlace de compra dinámico usando esta estructura exacta: "
            "https://www.buscalibre.cl/libros/search?q=titulo+del+libro+autor "
            "(asegúrate de reemplazar los espacios del título y autor por signos de suma '+')."
        )
    )
    modelo_llm = models.CharField(max_length=100, default='llama-3.1-8b-instant')
    temperatura = models.FloatField(default=0.7)
    max_tokens = models.IntegerField(default=350)
    activo = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Asistente de IA'
        verbose_name_plural = 'Asistentes de IA'

    def __str__(self):
        return f"{self.nombre} ({self.modelo_llm})"


class ConversacionIA(models.Model):
    """Sesión o hilo de conversación con el asistente de IA."""
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='conversaciones_ia')
    asistente = models.ForeignKey(AsistenteIA, on_delete=models.SET_NULL, null=True, blank=True, related_name='conversaciones')
    session_key = models.CharField(max_length=100, blank=True, null=True, help_text="Para usuarios anónimos")
    titulo = models.CharField(max_length=255, default='Nueva conversación')
    total_mensajes = models.IntegerField(default=0)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    ultima_actividad = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Conversación de IA'
        verbose_name_plural = 'Conversaciones de IA'
        ordering = ['-ultima_actividad']

    def __str__(self):
        user_info = self.usuario.username if self.usuario else f"Anónimo ({self.session_key})"
        return f"{self.titulo} - {user_info}"


class MensajeIA(models.Model):
    """Mensaje individual con telemetría de tokens, latencia e intención."""
    ROL_CHOICES = (
        ('user', 'Usuario'),
        ('assistant', 'Asistente'),
        ('system', 'Sistema'),
    )

    conversacion = models.ForeignKey(ConversacionIA, on_delete=models.CASCADE, related_name='mensajes')
    rol = models.CharField(max_length=20, choices=ROL_CHOICES, default='user')
    contenido = models.TextField()
    tokens_prompt = models.IntegerField(default=0)
    tokens_completion = models.IntegerField(default=0)
    tokens_utilizados = models.IntegerField(default=0)
    latencia_ms = models.IntegerField(default=0, help_text="Tiempo de respuesta en milisegundos")
    intencion_detectada = models.CharField(max_length=100, blank=True, null=True, help_text="Ej: recomendacion, resumen, busqueda")
    feedback_usuario = models.IntegerField(default=0, help_text="1=Like, -1=Dislike, 0=Sin calificar")
    metadata_json = models.JSONField(default=dict, blank=True, help_text="Libros sugeridos, fuentes RAG, etc.")
    fecha_envio = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Mensaje de IA'
        verbose_name_plural = 'Mensajes de IA'
        ordering = ['fecha_envio']

    def __str__(self):
        return f"[{self.rol}] {self.contenido[:40]}..."


class RecomendacionIALog(models.Model):
    """Registro de recomendaciones generadas por la IA para evaluar CTR y precisión."""
    mensaje = models.ForeignKey(MensajeIA, on_delete=models.SET_NULL, null=True, blank=True, related_name='recomendaciones_log')
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='recomendaciones_ia_log')
    libro = models.ForeignKey(Libro, on_delete=models.CASCADE, related_name='recomendaciones_ia_log')
    similitud_score = models.FloatField(default=0.0, help_text="Cosine similarity / relevancia RAG")
    fue_clickeado = models.BooleanField(default=False)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Log de Recomendación IA'
        verbose_name_plural = 'Logs de Recomendaciones IA'


# =====================================================================
# --- 4. ANALÍTICA DE EVENTOS Y CONVERSIONES (BI & BIG DATA) ---
# =====================================================================

class EventoAnalitica(models.Model):
    """Event stream para registrar comportamiento y embudos de conversión."""
    usuario = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='eventos_analitica')
    session_key = models.CharField(max_length=100, blank=True, null=True)
    tipo_evento = models.CharField(max_length=50, db_index=True, help_text="Ej: busqueda, ver_libro, abrir_chat, ver_planes")
    modulo = models.CharField(max_length=50, db_index=True, help_text="Ej: catalogo, chat_ia, suscripciones")
    detalles_evento = models.JSONField(default=dict, blank=True)
    ip_origen = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Evento de Analítica'
        verbose_name_plural = 'Eventos de Analítica'
        ordering = ['-timestamp']

    def __str__(self):
        user_info = self.usuario.username if self.usuario else "Anónimo"
        return f"{self.tipo_evento} ({self.modulo}) - {user_info} en {self.timestamp.strftime('%Y-%m-%d %H:%M')}"


class ClickConversion(models.Model):
    """Tracking de clicks a librerías externas para monetización y afiliados."""
    usuario = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='clicks_conversion')
    libro = models.ForeignKey(Libro, on_delete=models.CASCADE, null=True, blank=True, related_name='clicks_conversion')
    proveedor = models.CharField(max_length=50, default='Buscalibre')
    url_destino = models.URLField(max_length=500)
    precio_referencia = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Click de Conversión'
        verbose_name_plural = 'Clicks de Conversión'
        ordering = ['-timestamp']

    def __str__(self):
        libro_titulo = self.libro.titulo if self.libro else "General"
        return f"{self.proveedor} -> {libro_titulo} (${self.precio_referencia})"


# =====================================================================
# --- 5. MODELOS COMPLEMENTARIOS / LEGACY ---
# =====================================================================

class PreguntaFrecuente(models.Model):
    pregunta = models.CharField(max_length=255)
    respuesta = models.TextField()

    def __str__(self):
        return self.pregunta   


class HistorialChatbot(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    mensaje_usuario = models.TextField()
    respuesta_chatbot = models.TextField()
    fecha_interaccion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'Interacción de {self.usuario.username} el {self.fecha_interaccion}'


class Recomendacion(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    libro = models.ForeignKey(Libro, on_delete=models.CASCADE)
    fecha_recomendacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'Recomendación de {self.libro.titulo} para {self.usuario.username}'


class MensajeContacto(models.Model):
    """Mensajes enviados por usuarios a través del formulario de contacto."""
    nombre = models.CharField(max_length=150)
    email = models.EmailField()
    telefono = models.CharField(max_length=50, blank=True, null=True)
    mensaje = models.TextField()
    fecha_envio = models.DateTimeField(auto_now_add=True)
    leido = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'Mensaje de Contacto'
        verbose_name_plural = 'Mensajes de Contacto'
        ordering = ['-fecha_envio']

    def __str__(self):
        return f"Mensaje de {self.nombre} ({self.email}) - {self.fecha_envio.strftime('%Y-%m-%d %H:%M')}"