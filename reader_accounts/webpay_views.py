from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST

from . import webpay
from .checkout_models import WebpayTransaction
from .checkout_views import gate, own_order, validate_fields
from .social_policy import action_limit


@gate
@login_required
@require_POST
@action_limit('checkout', 30)
def start(request, order_id):
    validate_fields(request, [])
    own_order(request, order_id)
    if not webpay.enabled():
        raise Http404
    entry = webpay.start(request.user, order_id)
    response = render(request, 'accounts/checkout/webpay_redirect.html', {'entry': entry})
    response['Referrer-Policy'] = 'no-referrer'
    return response


@csrf_exempt
@sensitive_post_parameters('token_ws', 'TBK_TOKEN')
@never_cache
@require_http_methods(['GET', 'POST'])
def returned(request):
    """Transbank regresa sin cookie Lax en POST. El token se verifica por API."""
    if not webpay.enabled():
        raise Http404
    data = request.POST if request.method == 'POST' else request.GET
    if set(data) - {'token_ws', 'TBK_TOKEN', 'TBK_ORDEN_COMPRA', 'TBK_ID_SESION'}:
        return HttpResponseBadRequest('Retorno no válido.')
    if any(len(data.getlist(key)) != 1 for key in data) or ('token_ws' in data and 'TBK_TOKEN' in data):
        return HttpResponseBadRequest('Retorno no válido.')
    token = data.get('token_ws') or data.get('TBK_TOKEN')
    try:
        order = webpay.complete(token, aborted='TBK_TOKEN' in data)
    except WebpayTransaction.DoesNotExist:
        raise Http404
    except webpay.CheckoutError as error:
        return render(request, 'accounts/checkout/error.html', {'error': str(error)}, status=409)
    response = redirect('sim_receipt', order_id=order.pk)
    response['Referrer-Policy'] = 'no-referrer'
    return response
