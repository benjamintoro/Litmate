"""Tokens oficiales de Django. Sin proveedor no se simula la entrega del correo."""
from django.conf import settings
from django.contrib.auth import views as auth_views
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError
from django.shortcuts import render
from django.urls import reverse_lazy
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from .auth_limits import auth_limit
from .forms import ReaderPasswordResetForm


class RecoveryView(auth_views.PasswordResetView):
    template_name = 'registration/password_reset_form.html'
    email_template_name = 'accounts/reset_email.txt'
    html_email_template_name = 'accounts/reset_email.html'
    subject_template_name = 'registration/password_reset_subject.txt'
    form_class = ReaderPasswordResetForm
    success_url = reverse_lazy('password_reset_done')


class ChangePasswordView(auth_views.PasswordChangeView):
    """Cambio autenticado oficial: conserva esta sesión e invalida las demás."""
    template_name = 'accounts/edit.html'
    success_url = reverse_lazy('perfil')
    extra_context = {'heading': 'Cambiar contraseña'}

    def form_valid(self, form):
        try:
            response = super().form_valid(form)
        except DatabaseError:
            form.add_error(None, 'No pudimos guardar la contraseña. Inténtalo más tarde.')
            return self.render_to_response(self.get_context_data(form=form), status=503)
        messages.success(self.request, 'Contraseña actualizada. Las otras sesiones deberán volver a iniciar sesión.')
        return response


@never_cache
@login_required
@auth_limit(6)
@require_http_methods(['GET', 'POST'])
def change_password(request):
    return ChangePasswordView.as_view()(request)


@never_cache
@auth_limit(4)
def request_reset(request):
    if not settings.LITMATE_READER_EMAIL_ENABLED:
        return render(request, 'accounts/recovery_unavailable.html')
    try:
        return RecoveryView.as_view()(request)
    except (OSError, TimeoutError):
        return render(request, 'accounts/recovery_unavailable.html', {'temporary_error': True}, status=503)


@never_cache
@auth_limit(6)
def confirm_reset(request, uidb64, token):
    return auth_views.PasswordResetConfirmView.as_view(
        template_name='registration/password_reset_confirm.html',
        success_url=reverse_lazy('password_reset_complete'),
    )(request, uidb64=uidb64, token=token)
