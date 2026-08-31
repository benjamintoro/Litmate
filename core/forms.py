from django import forms
from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
# pyrefly: ignore [missing-import]
from .models import PerfilUsuario

# --- FORMULARIO DE INICIO DE SESIÓN MEJORADO ---
class UserLoginForm(forms.Form):
    username_or_email = forms.CharField(
        label="Usuario o Correo Electrónico",
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': 'Ingresa tu usuario o correo',
            'autocomplete': 'username',
            'required': True,
        })
    )
    password = forms.CharField(
        label="Contraseña",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': 'Ingresa tu contraseña',
            'autocomplete': 'current-password',
            'required': True,
            'id': 'loginPasswordInput'
        })
    )
    remember_me = forms.BooleanField(
        required=False,
        initial=True,
        label="Recordarme en este dispositivo",
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    def clean(self):
        cleaned_data = super().clean()
        username_or_email = cleaned_data.get('username_or_email')
        password = cleaned_data.get('password')

        if username_or_email and password:
            # Primero intentar autenticar como username
            user = authenticate(username=username_or_email, password=password)
            
            # Si falla, intentar buscar el usuario por email
            if user is None:
                try:
                    user_obj = User.objects.filter(email__iexact=username_or_email).first()
                    if user_obj:
                        user = authenticate(username=user_obj.username, password=password)
                except Exception:
                    user = None

            if user is None:
                raise ValidationError("Usuario, correo electrónico o contraseña incorrectos.")
            
            if not user.is_active:
                raise ValidationError("Esta cuenta está desactivada. Por favor contacta a soporte.")

            cleaned_data['user'] = user

        return cleaned_data


# --- FORMULARIO DE REGISTRO MEJORADO ---
class UserRegisterForm(forms.ModelForm):
    first_name = forms.CharField(
        label="Nombre",
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Tu nombre'})
    )
    last_name = forms.CharField(
        label="Apellido",
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Tu apellido'})
    )
    email = forms.EmailField(
        label="Correo Electrónico",
        required=True,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'nombre@ejemplo.com', 'autocomplete': 'email'})
    )
    password = forms.CharField(
        label="Contraseña",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Mínimo 8 caracteres',
            'autocomplete': 'new-password',
            'id': 'registerPasswordInput'
        })
    )
    password_confirm = forms.CharField(
        label="Confirmar Contraseña",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Repite tu contraseña',
            'autocomplete': 'new-password',
            'id': 'registerPasswordConfirmInput'
        })
    )

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Elige un nombre de usuario único', 'autocomplete': 'username'}),
        }

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if username:
            username = username.strip()
            if len(username) < 3:
                raise ValidationError("El nombre de usuario debe tener al menos 3 caracteres.")
            if User.objects.filter(username__iexact=username).exists():
                raise ValidationError("Este nombre de usuario ya está registrado.")
        return username

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if email:
            email = email.strip().lower()
            if User.objects.filter(email__iexact=email).exists():
                raise ValidationError("Este correo electrónico ya está registrado.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        password_confirm = cleaned_data.get("password_confirm")

        if password:
            if len(password) < 8:
                self.add_error('password', "La contraseña debe tener al menos 8 caracteres.")
            if password_confirm and password != password_confirm:
                self.add_error('password_confirm', "Las contraseñas no coinciden.")

        return cleaned_data

# --- FORMULARIO PARA EDITAR DATOS DEL USUARIO ---
class UserUpdateForm(forms.ModelForm):
    email = forms.EmailField(widget=forms.EmailInput(attrs={'class': 'form-control'}))

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
        }

# --- FORMULARIO PARA EDITAR EL PERFIL (Foto y Bio) ---
class ProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = PerfilUsuario
        fields = ['imagen', 'biografia']
        widgets = {
            'biografia': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Cuéntanos sobre tus gustos literarios...'}),
            'imagen': forms.FileInput(attrs={'class': 'form-control-file'}),
        }

