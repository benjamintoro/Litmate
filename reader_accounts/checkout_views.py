"""Checkout ficticio privado y comprobantes protegidos por propietario."""
from functools import wraps
from uuid import uuid4
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import DatabaseError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from suscripciones.models import HistorialPago
from .checkout_models import SimulatedOrder
from . import simulated_checkout as service
from .social_policy import action_limit
from .views import usage_context


def gate(view):
    @never_cache
    @wraps(view)
    def guarded(request, *args, **kwargs):
        if not service.enabled():
            raise Http404
        try:
            return view(request, *args, **kwargs)
        except service.CheckoutError as error:
            return render(request, 'accounts/checkout/error.html', {'error': str(error)}, status=409)
        except DatabaseError:
            return render(request, 'accounts/checkout/error.html',
                {'error': 'No se pudo guardar la operación. Puedes reintentar el mismo pedido.'}, status=503)
    return guarded


def resume_selection(request):
    slug = request.session.pop('simulated_checkout_plan', None) if service.enabled() else None
    if slug and service.paid_plan(slug):
        return reverse('sim_checkout', args=[slug])
    return reverse('suscripciones:planes')


class MethodForm(forms.Form):
    submission_id = forms.UUIDField(widget=forms.HiddenInput)
    method = forms.ChoiceField(label='Método ficticio', choices=SimulatedOrder.METHODS, widget=forms.RadioSelect)
    renew = forms.BooleanField(label='Confirmo extender voluntariamente el período del mismo plan', required=False)
    scenario = forms.ChoiceField(label='Escenario del entorno de pruebas', choices=service.SCENARIOS, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not service.scenarios_allowed():
            self.fields.pop('scenario')


def validate_fields(request, names):
    if set(request.POST) - set(names) - {'csrfmiddlewaretoken'}:
        raise service.CheckoutError('La solicitud contiene campos inesperados.')
    if any(len(request.POST.getlist(name)) != 1 for name in request.POST):
        raise service.CheckoutError('La solicitud contiene campos repetidos.')


@gate
@require_safe
def checkout(request, plan_slug):
    plan = service.paid_plan(plan_slug)
    if plan is None:
        raise Http404
    if not request.user.is_authenticated:
        request.session['simulated_checkout_plan'] = plan.slug
        return redirect('login')
    current = service.subscription(request.user)
    same = bool(current and current.plan_id == plan.pk and current.es_valida)
    return render(request, 'accounts/checkout/summary.html', {'plan': plan, 'same_plan': same, 'current': current})


@gate
@login_required
@action_limit('checkout', 30)
@require_http_methods(['GET', 'HEAD', 'POST'])
def methods(request, plan_slug):
    plan = service.paid_plan(plan_slug)
    if plan is None:
        raise Http404
    current = service.subscription(request.user)
    same = bool(current and current.plan_id == plan.pk and current.es_valida)
    form = MethodForm(request.POST if request.method == 'POST' else None,
                      initial={'submission_id': uuid4(), 'scenario': 'approved'})
    if request.method == 'POST':
        validate_fields(request, form.fields)
        if form.is_valid():
            order = service.create_order(request.user, plan, method=form.cleaned_data['method'],
                submission_id=form.cleaned_data['submission_id'], renew=form.cleaned_data['renew'],
                scenario=form.cleaned_data.get('scenario') or 'approved')
            return redirect('sim_order', order_id=order.pk)
    return render(request, 'accounts/checkout/methods.html', {'form': form, 'plan': plan, 'same_plan': same},
                  status=400 if form.is_bound else 200)


def own_order(request, order_id):
    return get_object_or_404(SimulatedOrder.objects.select_related('payment__plan'), pk=order_id, user=request.user)


@gate
@login_required
@require_safe
def order(request, order_id):
    entry = own_order(request, order_id)
    if entry.state in ('approved', 'rejected', 'cancelled'):
        return redirect('sim_receipt', order_id=entry.pk)
    return render(request, 'accounts/checkout/confirm.html', {'order': entry})


@gate
@login_required
@require_POST
@action_limit('checkout', 30)
def confirm(request, order_id):
    validate_fields(request, [])
    own_order(request, order_id)
    entry = service.process_order(request.user, order_id)
    return redirect('sim_order' if entry.state == 'temporary_error' else 'sim_receipt', order_id=entry.pk)


@gate
@login_required
@require_POST
@action_limit('checkout', 30)
def cancel_order(request, order_id):
    validate_fields(request, ['confirm'])
    entry = own_order(request, order_id)
    if request.POST.get('confirm') != 'yes':
        raise service.CheckoutError('Confirma que quieres cancelar este pedido.')
    if entry.state == 'approved':
        raise service.CheckoutError('La operación ya fue aprobada. Gestiona el plan desde Mi suscripción.')
    service.process_order(request.user, order_id, cancel=True)
    return redirect('sim_receipt', order_id=order_id)


@gate
@login_required
@require_safe
def receipt(request, order_id):
    entry = own_order(request, order_id)
    if entry.state in ('pending', 'temporary_error'):
        return redirect('sim_order', order_id=entry.pk)
    return render(request, 'accounts/checkout/receipt.html', {'order': entry})


@never_cache
@login_required
@require_safe
def subscription(request):
    if not service.enabled():
        from .views import account
        return account(request)
    current = service.subscription(request.user)
    recent = SimulatedOrder.objects.filter(user=request.user).select_related('payment').first()
    active_order = None
    if current and service.is_simulated(current):
        active_order = SimulatedOrder.objects.filter(user=request.user,
            payment__referencia_transaccion=current.id_suscripcion_externa, state='approved').first()
    return render(request, 'accounts/checkout/subscription.html', {
        'subscription': current, 'active_order': active_order, 'latest_order': recent,
        'simulated_subscription': service.is_simulated(current), **usage_context(request)})


@gate
@login_required
@action_limit('checkout', 30)
@require_http_methods(['GET', 'HEAD', 'POST'])
def cancel_subscription(request):
    if request.method == 'POST':
        validate_fields(request, ['confirm'])
        if request.POST.get('confirm') != 'yes':
            raise service.CheckoutError('Confirma la cancelación.')
        service.cancel_subscription(request.user)
        messages.success(request, 'La cancelación quedó registrada. Conservarás el acceso hasta el vencimiento.')
        return redirect('sim_subscription')
    return render(request, 'accounts/checkout/cancel.html', {'subscription': service.subscription(request.user)})


@gate
@login_required
@require_POST
@action_limit('checkout', 30)
def switch_free(request):
    validate_fields(request, ['confirm'])
    if request.POST.get('confirm') != 'yes':
        raise service.CheckoutError('Confirma el cambio inmediato a Gratuito.')
    service.switch_to_free(request.user)
    messages.success(request, 'Activamos Gratuito conservando tu biblioteca y el consumo diario acumulado.')
    return redirect('sim_subscription')


@never_cache
@login_required
@require_safe
def history(request):
    if not service.enabled():
        from .views import payment_history
        return payment_history(request)
    payments = HistorialPago.objects.filter(usuario=request.user).select_related('plan', 'simulated_order')
    return render(request, 'accounts/checkout/history.html',
                  {'payments': Paginator(payments.order_by('-fecha_pago', '-pk'), 15).get_page(request.GET.get('page'))})
