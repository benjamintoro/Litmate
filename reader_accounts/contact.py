"""Formulario original y recepción persistente en el almacén privado."""
import logging

from django import forms
from django.contrib import messages
from django.db import DatabaseError, transaction
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from core.models import MensajeContacto
from .social_policy import action_limit

logger = logging.getLogger(__name__)


class ContactForm(forms.Form):
    name = forms.CharField(label='Nombre', max_length=150)
    email = forms.EmailField(label='Correo electrónico', max_length=254)
    phone = forms.CharField(label='Teléfono opcional', max_length=50, required=False)
    message = forms.CharField(label='Mensaje', max_length=5000, widget=forms.Textarea)
    website = forms.CharField(required=False, widget=forms.HiddenInput)

    def clean_website(self):
        if self.cleaned_data.get('website'):
            raise forms.ValidationError('No fue posible validar el formulario.')
        return ''


@never_cache
@require_http_methods(['GET', 'HEAD', 'POST'])
@csrf_protect
@action_limit('contact', 4)
def contact(request):
    form = ContactForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST':
        if not form.is_valid():
            return render(request, 'contact.html', {'form': form}, status=400)
        try:
            # El mismo modelo del formulario original se enruta a accounts.
            with transaction.atomic(using='accounts'):
                MensajeContacto.objects.create(
                    nombre=form.cleaned_data['name'],
                    email=form.cleaned_data['email'],
                    telefono=form.cleaned_data['phone'],
                    mensaje=form.cleaned_data['message'],
                )
        except DatabaseError:
            logger.warning('No se pudo registrar un mensaje de contacto.')
            form.add_error(None, 'No pudimos guardar tu mensaje. Conserva el texto y vuelve a intentarlo.')
            return render(request, 'contact.html', {'form': form}, status=503)
        messages.success(request, 'Tu mensaje quedó registrado para revisión del equipo de LitMate.')
        return redirect('contact')
    return render(request, 'contact.html', {'form': form})
