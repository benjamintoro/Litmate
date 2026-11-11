from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator

from .avatars import normalize
from .models import SocialPost, SocialProfile


class SocialProfileForm(forms.ModelForm):
    alias = forms.CharField(
        label='Nombre de usuario público', max_length=32, required=False,
        validators=[RegexValidator(r'\A[a-zA-Z0-9][a-zA-Z0-9_.-]{2,31}\Z',
                                   'Usa entre 3 y 32 letras, números, puntos, guiones o guiones bajos.')],
    )
    annual_goal = forms.IntegerField(label='Meta anual de lectura', min_value=1, max_value=1000)
    photo = forms.FileField(label='Fotografía', required=False, widget=forms.FileInput(attrs={'accept': 'image/jpeg,image/png'}))
    cover = forms.FileField(label='Portada', required=False, widget=forms.FileInput(attrs={'accept': 'image/jpeg,image/png'}))
    cover_focus = forms.ChoiceField(label='Encuadre de la portada', required=False, initial='center',
        choices=[('center', 'Centro'), ('top', 'Parte superior'), ('bottom', 'Parte inferior'),
                 ('left', 'Lado izquierdo'), ('right', 'Lado derecho')])
    remove_photo = forms.BooleanField(label='Quitar fotografía', required=False)
    remove_cover = forms.BooleanField(label='Quitar portada', required=False)

    class Meta:
        model = SocialProfile
        fields = ['display_name', 'alias', 'biography', 'genres', 'favorite_author', 'favorite_book',
                  'published', 'share_avatar', 'share_cover', 'share_stats']
        labels = {
            'display_name': 'Nombre visible', 'biography': 'Biografía literaria', 'genres': 'Géneros favoritos',
            'favorite_author': 'Autor favorito', 'favorite_book': 'Libro favorito',
            'published': 'Habilitar mi perfil público', 'share_avatar': 'Mostrar mi fotografía en el perfil público',
            'share_cover': 'Mostrar mi portada en el perfil público',
            'share_stats': 'Compartir estadísticas de lectura y meta anual',
        }
        widgets = {'biography': forms.Textarea(attrs={'rows': 4})}

    def clean_alias(self):
        return self.cleaned_data['alias'].lower()

    def clean_photo(self):
        upload = self.cleaned_data['photo']
        return normalize(upload, square=True) if upload else None

    def clean_cover(self):
        upload = self.cleaned_data['cover']
        positions = {'top': (.5, 0), 'bottom': (.5, 1), 'left': (0, .5), 'right': (1, .5)}
        return normalize(upload, cover=True, centering=positions.get(self.data.get('cover_focus'), (.5, .5))) if upload else None

    def clean(self):
        data = super().clean()
        if sum(upload.size for upload in self.files.values()) > 2 * 1024 * 1024:
            self.add_error(None, 'Las imágenes juntas no pueden superar 2 MiB.')
        if data.get('published') and not data.get('alias'):
            self.add_error('alias', 'El perfil público necesita un nombre de usuario público.')
        if data.get('photo') and data.get('remove_photo'):
            self.add_error('remove_photo', 'Elige subir o quitar la fotografía.')
        if data.get('cover') and data.get('remove_cover'):
            self.add_error('remove_cover', 'Elige subir o quitar la portada.')
        return data


class PostForm(forms.ModelForm):
    submission_id = forms.UUIDField(widget=forms.HiddenInput)
    catalogue_id = forms.IntegerField(min_value=1, max_value=2**63-1, required=False, widget=forms.HiddenInput)

    class Meta:
        model = SocialPost
        fields = ['body', 'catalogue_id', 'visibility', 'spoiler', 'allow_comments']
        labels = {'body': 'Tu publicación', 'visibility': 'Visibilidad',
                  'spoiler': 'Contiene spoilers', 'allow_comments': 'Permitir comentarios'}
        widgets = {'body': forms.Textarea(attrs={'rows': 5, 'maxlength': 2400})}

    def __init__(self, *args, profile, editing=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.profile = profile
        self.selected_book = None
        if editing:
            self.fields.pop('submission_id')

    def clean_catalogue_id(self):
        pk = self.cleaned_data['catalogue_id']
        if pk:
            from core.models import Libro
            self.selected_book = Libro.objects.select_related('autor').filter(pk=pk).first()
            if not self.selected_book:
                raise ValidationError('Selecciona una obra del catálogo.')
        return pk

    def clean_visibility(self):
        visibility = self.cleaned_data['visibility']
        if visibility != SocialPost.Visibility.PRIVATE and not self.profile.published:
            raise ValidationError('Habilita el perfil público en Configuración para compartir una publicación.')
        return visibility


class CommentForm(forms.Form):
    submission_id = forms.UUIDField(widget=forms.HiddenInput)
    body = forms.CharField(label='Tu comentario', max_length=600, widget=forms.Textarea(attrs={'rows': 3}))


class ReportForm(forms.Form):
    reason = forms.CharField(label='Motivo del reporte', max_length=400, widget=forms.Textarea(attrs={'rows': 3}))
