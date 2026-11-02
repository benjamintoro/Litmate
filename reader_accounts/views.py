"""Reutiliza usuarios, formularios y planes existentes; sin pagos simulados."""
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction, DatabaseError
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST
from django.views.decorators.cache import never_cache
from core.forms import UserRegisterForm
from .forms import ReaderLoginForm
from core.models import PerfilUsuario, ConversacionIA
from .auth_limits import auth_limit
from suscripciones.models import PlanSuscripcion, SuscripcionUsuario
from .models import AccountEmail
from .usage import info, UsageError


@never_cache
@ensure_csrf_cookie
@auth_limit(6)
def register(request):
    if request.user.is_authenticated:
        return redirect('suscripciones:planes')
    form = UserRegisterForm(request.POST or None)
    if request.method == 'POST' and not request.POST.get('website_url_check') and form.is_valid():
        user = form.save(commit=False)
        try:
            validate_password(form.cleaned_data['password'], user)
            with transaction.atomic(using='accounts'):
                if type(user).objects.filter(username__iexact=user.username).exists():
                    raise IntegrityError('duplicate identity')
                user.set_password(form.cleaned_data['password'])
                user.save()
                AccountEmail.objects.create(user=user, normalized=user.email.strip().lower())
                PerfilUsuario.objects.create(usuario=user, nombre=user.first_name or user.username, correo=user.email)
            auth_login(request, user)
            messages.success(request, 'Tu cuenta está creada. Elige tu plan; el gratuito no requiere tarjeta.')
            return redirect('suscripciones:planes')
        except ValidationError as error:
            form.add_error('password', error)
        except IntegrityError:
            form.add_error(None, 'El usuario o correo ya está registrado.')
    return render(request, 'registration/register.html', {'form': form})


@never_cache
@ensure_csrf_cookie
@auth_limit(8)
def login(request):
    if request.user.is_authenticated:
        return redirect('suscripciones:planes')
    form = ReaderLoginForm(request.POST or None)
    if request.method == 'POST' and not request.POST.get('website_url_check') and form.is_valid():
        auth_login(request, form.cleaned_data['user'])
        request.session.set_expiry(14 * 24 * 3600 if form.cleaned_data.get('remember_me') else 0)
        return redirect('suscripciones:planes')
    return render(request, 'registration/login.html', {'form': form})


@require_POST
def logout(request):
    auth_logout(request)  # La cookie de visitante separada no se borra.
    return redirect('index')


@never_cache
@ensure_csrf_cookie
def plans(request):
    sub = (SuscripcionUsuario.objects.filter(usuario=request.user).select_related('plan').first()
           if request.user.is_authenticated else None)
    from .payments import verified_payment
    return render(request, 'accounts/plans.html', {
        'planes': PlanSuscripcion.objects.filter(activo=True).order_by('orden', 'precio'),
        'suscripcion_actual': sub,
        'reader_accounts_enabled': True,
        'paid_verification_pending': bool(sub and sub.plan.precio > 0 and not verified_payment(sub)),
    })


@login_required
@require_POST
def activate_free(request):
    # Nunca confiar en plan/precio/estado enviados por el navegador.
    with transaction.atomic(using='accounts'):
        plan = get_object_or_404(PlanSuscripcion, slug=request.POST.get('plan', ''), precio=0, activo=True)
        sub = SuscripcionUsuario.objects.select_for_update().filter(usuario=request.user).first()
        if sub and sub.plan_id == plan.pk and sub.es_valida:
            return redirect('chatbot_page')
        if sub and sub.es_valida and sub.plan.precio > 0:
            return JsonResponse({'response': 'Tu plan pagado sigue activo. El cambio necesita revisar su contratación; no se modificará automáticamente.'}, status=409)
        SuscripcionUsuario.objects.update_or_create(usuario=request.user, defaults={
            'plan': plan, 'estado': 'activa', 'fecha_inicio': timezone.now(), 'fecha_fin': None,
            'auto_renovar': False, 'id_suscripcion_externa': None,
        })
    return redirect('chatbot_page')


@never_cache
def quota(request):
    try:
        return JsonResponse({'status': 'ok', 'cuota': info(request.reader_actor, request.user)})
    except UsageError as error:
        return JsonResponse({'error': error.code, 'response': error.text}, status=error.status)
    except DatabaseError:
        return JsonResponse({'error': 'storage_unavailable', 'response': 'El consumo no está disponible. Inténtalo más tarde.'}, status=503)


@never_cache
@login_required
def account(request):
    return render(request, 'accounts/account.html', {
        'conversaciones': ConversacionIA.objects.filter(usuario=request.user)[:20]})


@never_cache
@login_required
def conversation(request, pk):
    conv = get_object_or_404(ConversacionIA, pk=pk, usuario=request.user)
    return JsonResponse({'titulo': conv.titulo, 'mensajes': list(conv.mensajes.values('rol', 'contenido'))})


@never_cache
@ensure_csrf_cookie
def chat_page(request):
    return render(request, 'accounts/chatbot.html')


def payment_disabled(request):
    raise Http404('Contratación no disponible')
