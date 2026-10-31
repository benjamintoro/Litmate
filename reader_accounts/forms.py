from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from core.forms import UserLoginForm


class ReaderLoginForm(UserLoginForm):
    def clean(self):
        value = str(self.data.get('username_or_email', '')).strip()
        if value and User.objects.filter(email__iexact=value).count() > 1:
            raise ValidationError('Utiliza tu nombre de usuario para este acceso.')
        return super().clean()
