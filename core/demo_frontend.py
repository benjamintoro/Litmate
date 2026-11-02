"""Sólo el URLconf de demo usa estas previsualizaciones sin escrituras.

La autenticación Basic protege el recorrido público. No equivale a iniciar
sesión en una cuenta personal de Django ni habilita sus datos privados.
"""
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.forms import PasswordResetForm
from django.core.exceptions import ImproperlyConfigured
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods, require_POST

from .forms import UserLoginForm, UserRegisterForm


FORM_PAGES = {
    '/login/': ('registration/login.html', UserLoginForm,
                'El acceso a esta demo ya está protegido con el usuario demo. '
                'El formulario se muestra como vista previa: no inicia sesiones de cuentas personales.'),
    '/registro/': ('registration/register.html', UserRegisterForm,
                   'Vista previa de registro: esta demo de solo lectura no crea cuentas.'),
    '/password-reset/': ('registration/password_reset_form.html', PasswordResetForm,
                         'Vista previa de recuperación: esta demo no cambia contraseñas ni envía correos.'),
    '/contact/': ('contact.html', None,
                  'Vista previa de contacto: esta demo no guarda mensajes ni envía correos.'),
}


def require_demo():
    if not getattr(settings, 'LITMATE_DEMO_READ_ONLY', False):
        raise ImproperlyConfigured('Las vistas de demostración requieren el perfil de solo lectura.')


@ensure_csrf_cookie
@require_http_methods(['GET', 'HEAD', 'POST'])
def form_preview(request):
    require_demo()
    template, form_class, notice = FORM_PAGES[request.path]
    # No validar credenciales ni conservar los datos enviados. CSRF sigue activo.
    context = {'demo_notice': notice}
    if form_class:
        context['form'] = form_class()
    return render(request, template, context)


@require_http_methods(['GET', 'HEAD'])
def payment_preview(request, plan_slug):
    require_demo()
    messages.info(request, 'Los planes pueden consultarse; la contratación y los pagos están desactivados en esta demo.')
    return redirect('suscripciones:planes')


@require_http_methods(['GET', 'HEAD'])
def social_preview(request, provider):
    require_demo()
    messages.info(request, 'El acceso social no se activa en esta demo. Utiliza las credenciales privadas de demostración.')
    return redirect('login')


@require_POST
def logout_preview(request):
    require_demo()
    # HTTP Basic pertenece al navegador, no al login de Django. No borrar el
    # contexto literario al pulsar una acción que no puede cerrar Basic Auth.
    messages.info(request, 'Para cerrar el acceso demo, cierra todas las ventanas privadas del navegador. La conversación se conserva durante la navegación.')
    return redirect('index')


@require_POST
def tracking_disabled(request):
    require_demo()
    return JsonResponse({'status': 'ok', 'tracked': False, 'demo_read_only': True})
