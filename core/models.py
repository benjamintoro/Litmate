from django.db import models
from django.contrib.auth.models import User

# Modelo para los Autores
class Autor(models.Model):
    nombre = models.CharField(max_length=200)
    biografia = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.nombre


# Modelo para los Libros
class Libro(models.Model):
    titulo = models.CharField(max_length=255)
    autor = models.ForeignKey(Autor, on_delete=models.CASCADE)
    sinopsis = models.TextField()
    genero = models.CharField(max_length=100)
    fecha_publicacion = models.DateField(null=True, blank=True)

    def __str__(self):
        return self.titulo


# Modelo para las Reseñas
class Resena(models.Model):
    libro = models.ForeignKey(Libro, on_delete=models.CASCADE, related_name='resenas')
    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    calificacion = models.IntegerField()
    comentario = models.TextField()
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'Reseña de {self.usuario.username} para {self.libro.titulo}'


# Modelo Mejorado para Perfil de Usuario
class PerfilUsuario(models.Model):
    usuario = models.OneToOneField(User, on_delete=models.CASCADE, related_name='perfil')
    # Campos nuevos
    imagen = models.ImageField(default='default.jpg', upload_to='profile_pics')
    biografia = models.TextField(blank=True, null=True, verbose_name='Sobre mí')
    telefono = models.CharField(max_length=20, blank=True, null=True)
    
    # Mantenemos compatibilidad con tu código anterior si usabas estos campos
    correo = models.EmailField(unique=True, null=True, blank=True)
    nombre = models.CharField(max_length=100, null=True, blank=True)

    def __str__(self):
        return f'Perfil de {self.usuario.username}'

# NUEVO: Modelo para Favoritos
class LibroFavorito(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='favoritos')
    google_id = models.CharField(max_length=100)
    titulo = models.CharField(max_length=255)
    autores = models.CharField(max_length=255)
    imagen_url = models.URLField(blank=True, null=True)
    fecha_agregado = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('usuario', 'google_id') 

    def __str__(self):
        return f"{self.titulo} - {self.usuario.username}"

# Modelo para preguntas frecuentes
class PreguntaFrecuente(models.Model):
    pregunta = models.CharField(max_length=255)
    respuesta = models.TextField()

    def __str__(self):
        return self.pregunta   

# Modelo para el historial de interacciones del chatbot
class HistorialChatbot(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    mensaje_usuario = models.TextField()
    respuesta_chatbot = models.TextField()
    fecha_interaccion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'Interacción de {self.usuario.username} el {self.fecha_interaccion}'

# Modelo para recomendaciones personalizadas
class Recomendacion(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    libro = models.ForeignKey(Libro, on_delete=models.CASCADE)
    fecha_recomendacion = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'Recomendación de {self.libro.titulo} para {self.usuario.username}'