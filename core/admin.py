from django.contrib import admin
from .models import (
    Autor, Genero, Editorial, Libro, Resena, PerfilUsuario, LibroFavorito,
    EstadoLectura, AsistenteIA, ConversacionIA, MensajeIA,
    RecomendacionIALog, EventoAnalitica, ClickConversion,
    PreguntaFrecuente, HistorialChatbot, Recomendacion, MensajeContacto
)


@admin.register(MensajeContacto)
class MensajeContactoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'email', 'telefono', 'fecha_envio', 'leido')
    list_filter = ('leido', 'fecha_envio')
    search_fields = ('nombre', 'email', 'mensaje')
    readonly_fields = ('fecha_envio',)


@admin.register(Autor)
class AutorAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'pais_origen', 'ano_nacimiento')
    search_fields = ('nombre', 'pais_origen')
    list_filter = ('pais_origen',)


@admin.register(Genero)
class GeneroAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'slug')
    search_fields = ('nombre', 'slug')
    prepopulated_fields = {'slug': ('nombre',)}


@admin.register(Editorial)
class EditorialAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'pais')
    search_fields = ('nombre', 'pais')


@admin.register(Libro)
class LibroAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'autor', 'editorial', 'calificacion_promedio', 'total_resenas', 'total_favoritos', 'fecha_publicacion')
    search_fields = ('titulo', 'autor__nombre', 'isbn_10', 'isbn_13', 'google_book_id')
    list_filter = ('generos', 'editorial', 'fecha_publicacion')
    filter_horizontal = ('generos',)


@admin.register(Resena)
class ResenaAdmin(admin.ModelAdmin):
    list_display = ('libro', 'usuario', 'calificacion', 'sentimiento_score', 'votos_utiles', 'fecha_creacion')
    list_filter = ('calificacion', 'fecha_creacion')
    search_fields = ('libro__titulo', 'usuario__username', 'comentario')


@admin.register(PerfilUsuario)
class PerfilUsuarioAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'nombre', 'apellido', 'pais', 'genero_lector_preferido', 'fecha_registro')
    list_filter = ('pais', 'genero_lector_preferido', 'fecha_registro')
    search_fields = ('usuario__username', 'nombre', 'apellido', 'correo')


@admin.register(LibroFavorito)
class LibroFavoritoAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'autores', 'usuario', 'fecha_agregado')
    search_fields = ('titulo', 'autores', 'usuario__username')


@admin.register(EstadoLectura)
class EstadoLecturaAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'libro', 'estado', 'porcentaje_avance', 'actualizado_en')
    list_filter = ('estado', 'actualizado_en')
    search_fields = ('usuario__username', 'libro__titulo')


@admin.register(AsistenteIA)
class AsistenteIAAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'modelo_llm', 'temperatura', 'max_tokens', 'activo', 'fecha_actualizacion')
    list_filter = ('activo', 'modelo_llm')
    search_fields = ('nombre', 'descripcion', 'prompt_sistema')


class MensajeIAInline(admin.TabularInline):
    model = MensajeIA
    extra = 0
    readonly_fields = ('rol', 'contenido', 'fecha_envio')


@admin.register(ConversacionIA)
class ConversacionIAAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'usuario', 'session_key', 'total_mensajes', 'fecha_creacion', 'ultima_actividad')
    list_filter = ('fecha_creacion', 'ultima_actividad')
    search_fields = ('titulo', 'usuario__username', 'session_key')
    inlines = [MensajeIAInline]


@admin.register(MensajeIA)
class MensajeIAAdmin(admin.ModelAdmin):
    list_display = ('conversacion', 'rol', 'contenido_resumido', 'fecha_envio')
    list_filter = ('rol', 'fecha_envio')
    search_fields = ('contenido', 'conversacion__titulo')

    def contenido_resumido(self, obj):
        return obj.contenido[:60] + "..." if len(obj.contenido) > 60 else obj.contenido
    contenido_resumido.short_description = "Contenido"


@admin.register(RecomendacionIALog)
class RecomendacionIALogAdmin(admin.ModelAdmin):
    list_display = ('libro', 'usuario', 'similitud_score', 'fue_clickeado', 'fecha')
    list_filter = ('fue_clickeado', 'fecha')
    search_fields = ('libro__titulo', 'usuario__username')


@admin.register(EventoAnalitica)
class EventoAnaliticaAdmin(admin.ModelAdmin):
    list_display = ('tipo_evento', 'modulo', 'usuario', 'session_key', 'timestamp')
    list_filter = ('tipo_evento', 'modulo', 'timestamp')
    search_fields = ('tipo_evento', 'modulo', 'usuario__username', 'session_key')
    readonly_fields = ('timestamp',)


@admin.register(ClickConversion)
class ClickConversionAdmin(admin.ModelAdmin):
    list_display = ('proveedor', 'libro', 'usuario', 'precio_referencia', 'timestamp')
    list_filter = ('proveedor', 'timestamp')
    search_fields = ('libro__titulo', 'usuario__username', 'proveedor')


@admin.register(PreguntaFrecuente)
class PreguntaFrecuenteAdmin(admin.ModelAdmin):
    list_display = ('pregunta',)
    search_fields = ('pregunta', 'respuesta')


@admin.register(HistorialChatbot)
class HistorialChatbotAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'fecha_interaccion')
    search_fields = ('usuario__username', 'mensaje_usuario', 'respuesta_chatbot')
    list_filter = ('fecha_interaccion',)


@admin.register(Recomendacion)
class RecomendacionAdmin(admin.ModelAdmin):
    list_display = ('usuario', 'libro', 'fecha_recomendacion')
    search_fields = ('usuario__username', 'libro__titulo')