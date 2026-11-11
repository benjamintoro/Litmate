from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from core.forms import UserLoginForm
from django import forms
from django.contrib.auth.forms import PasswordResetForm
from core.models import PerfilUsuario, ListaLectura
from urllib.parse import urlsplit


class ReaderLoginForm(UserLoginForm):
    def clean(self):
        value = str(self.data.get('username_or_email', '')).strip()
        if value and User.objects.filter(email__iexact=value).count() > 1:
            raise ValidationError('Utiliza tu nombre de usuario para este acceso.')
        return super().clean()


class ReaderProfileForm(forms.ModelForm):
    """No permite cambiar propietario, email de acceso ni archivos arbitrarios."""
    photo = forms.FileField(label='Fotografía de perfil', required=False,
        help_text='JPEG o PNG, hasta 2 MiB y 4 megapíxeles. Se guarda una copia privada sin metadatos.',
        widget=forms.ClearableFileInput(attrs={'accept': 'image/jpeg,image/png'}))
    remove_photo = forms.BooleanField(label='Quitar mi fotografía y usar el avatar predeterminado', required=False)
    class Meta:
        model = PerfilUsuario
        fields = ('nombre', 'apellido', 'pais', 'biografia', 'genero_lector_preferido', 'meta_anual_libros')
        widgets = {'biografia': forms.Textarea(attrs={'rows': 3, 'maxlength': 2000})}

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('photo') and cleaned.get('remove_photo'):
            self.add_error('remove_photo', 'Elige una fotografía nueva o quita la actual; no ambas opciones.')
        return cleaned

    def clean_photo(self):
        upload = self.cleaned_data.get('photo')
        if not upload:
            return None
        from .avatars import normalize
        return normalize(upload)

    def clean_biografia(self):
        value = self.cleaned_data['biografia'] or ''
        if len(value) > 2000:
            raise ValidationError('Utiliza un máximo de 2000 caracteres.')
        return value

    def clean_meta_anual_libros(self):
        value = self.cleaned_data['meta_anual_libros']
        if not 1 <= value <= 1000:
            raise ValidationError('Elige una meta entre 1 y 1000 libros.')
        return value


class ReadingListForm(forms.ModelForm):
    class Meta:
        model = ListaLectura
        fields = ('nombre', 'descripcion')  # Las listas siguen siendo privadas.
        widgets = {'descripcion': forms.Textarea(attrs={'rows': 2, 'maxlength': 2000})}

    def clean_nombre(self):
        name = self.cleaned_data['nombre']
        # Sólo compara listas del propietario. La creación conserva su reintento
        # idempotente; la edición valida dentro de la transacción IMMEDIATE.
        if self.instance.usuario_id and ListaLectura.objects.filter(
                usuario_id=self.instance.usuario_id, nombre__iexact=name).exclude(pk=self.instance.pk).exists():
            raise ValidationError('Ya tienes una lista con ese nombre.')
        return name

    def clean_descripcion(self):
        value = self.cleaned_data['descripcion']
        if len(value) > 2000:
            raise ValidationError('Utiliza un máximo de 2000 caracteres.')
        return value


class BookSnapshotForm(forms.Form):
    google_id = forms.CharField(max_length=100)
    titulo = forms.CharField(max_length=255)
    autores = forms.CharField(max_length=255, required=False)
    imagen_url = forms.URLField(max_length=500, required=False)

    def clean_google_id(self):
        value = self.cleaned_data['google_id']
        if any(ord(c) < 32 for c in value):
            raise ValidationError('Identificador no válido.')
        return value

    def clean_imagen_url(self):
        value = self.cleaned_data.get('imagen_url', '')
        if not value:
            return ''
        try:
            parts = urlsplit(value)
            port = parts.port
        except ValueError:
            return ''
        host = (parts.hostname or '').lower()
        allowed = ('books.google.com', 'books.google.es', 'covers.openlibrary.org',
                   'books.googleusercontent.com', 'upload.wikimedia.org')
        if parts.scheme != 'https' or parts.username or parts.password or port not in (None, 443) or host not in allowed:
            # No se solicita la URL en el servidor, ni se conserva un tracker arbitrario.
            return ''
        return value


class ReaderPasswordResetForm(PasswordResetForm):
    def send_mail(self, subject_template_name, email_template_name, context, from_email,
                  to_email, html_email_template_name=None):
        # Django normalmente registra y absorbe el fallo SMTP. Aquí debe llegar
        # a la vista para no mostrar una solicitud completada tras un fallo real.
        from django.core.mail import EmailMultiAlternatives
        from django.template.loader import render_to_string
        subject = ''.join(render_to_string(subject_template_name, context).splitlines())
        message = EmailMultiAlternatives(subject, render_to_string(email_template_name, context), from_email, [to_email])
        if html_email_template_name:
            message.attach_alternative(render_to_string(html_email_template_name, context), 'text/html')
        if message.send(fail_silently=False) != 1:
            raise OSError('No se confirmó la aceptación del correo por el backend.')

    def get_users(self, email):
        # Correos históricos duplicados no permiten elegir una cuenta inequívoca.
        if User.objects.filter(email__iexact=email, is_active=True).count() != 1:
            return iter(())
        return super().get_users(email)
