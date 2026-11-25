"""Portabilidad privada con reautenticación; no exporta secretos ni elimina datos."""
from django import forms
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from core.models import (PerfilUsuario, LibroFavorito, ListaLectura,
                         ElementoListaLectura, ConversacionIA, MensajeIA)
from suscripciones.models import SuscripcionUsuario, HistorialPago
from .auth_limits import auth_limit


class ExportForm(forms.Form):
    password = forms.CharField(label='Tu contraseña actual', widget=forms.PasswordInput,
                               max_length=256)

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_password(self):
        if not self.user.check_password(self.cleaned_data['password']):
            raise forms.ValidationError('No pudimos confirmar tu contraseña.')
        return None


def own_export(user):
    """Todas las consultas tienen propietario; las columnas son una lista cerrada."""
    def records(queryset, *fields):
        return list(queryset.values(*fields))

    conversations = ConversacionIA.objects.filter(usuario=user)
    lists = ListaLectura.objects.filter(usuario=user)
    return {
        'format': 'litmate-personal-export-v1',
        'account': {'username': user.username, 'email': user.email,
                    'first_name': user.first_name, 'last_name': user.last_name},
        'profile': records(PerfilUsuario.objects.filter(usuario=user), 'nombre', 'apellido',
                           'pais', 'genero_lector_preferido', 'fecha_nacimiento', 'biografia',
                           'meta_anual_libros', 'telefono', 'correo'),
        'favorites': records(LibroFavorito.objects.filter(usuario=user), 'google_id', 'titulo', 'autores'),
        'lists': records(lists, 'id', 'nombre', 'descripcion'),
        'reading': records(ElementoListaLectura.objects.filter(lista__usuario=user),
                           'lista_id', 'google_id', 'titulo', 'autores', 'estado_lectura', 'nota_personal'),
        'conversations': records(conversations, 'id', 'titulo', 'fecha_creacion', 'ultima_actividad'),
        'messages': records(MensajeIA.objects.filter(conversacion__usuario=user),
                            'conversacion_id', 'rol', 'contenido', 'fecha_envio'),
        'subscription': records(SuscripcionUsuario.objects.filter(usuario=user),
                                'plan__nombre', 'estado', 'fecha_inicio', 'fecha_fin', 'auto_renovar'),
        'payments': records(HistorialPago.objects.filter(usuario=user),
                            'plan__nombre', 'monto', 'moneda', 'estado', 'fecha_pago'),
        'scope': 'Datos personales listados; no incluye sesiones, contraseñas, claves, '
                 'recibos internos, archivos de fotografía ni copias de respaldo.',
    }


@never_cache
@login_required
@auth_limit(3)
@require_http_methods(['GET', 'POST'])
def export_data(request):
    form = ExportForm(request.POST if request.method == 'POST' else None, user=request.user)
    if request.method == 'POST' and form.is_valid():
        try:
            response = JsonResponse(own_export(request.user), json_dumps_params={'ensure_ascii': False})
        except DatabaseError:
            form.add_error(None, 'No pudimos preparar la copia. Inténtalo más tarde.')
            return render(request, 'accounts/export.html', {'form': form}, status=503)
        response['Content-Disposition'] = 'attachment; filename="litmate-mis-datos.json"'
        response['X-Content-Type-Options'] = 'nosniff'
        return response
    return render(request, 'accounts/export.html', {'form': form})
