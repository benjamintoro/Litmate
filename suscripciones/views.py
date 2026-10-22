import datetime
import uuid
import logging
from decimal import Decimal
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.http import Http404, JsonResponse, HttpResponse
from django.utils import timezone
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt

from .models import PlanSuscripcion, SuscripcionUsuario, HistorialPago
from .payment_safety import simulation_allowed
from .services import TransbankService, MercadoPagoService, PayPalService

logger = logging.getLogger('litmate')


def planes_view(request):
    """Muestra la tabla comparativa de planes de suscripción disponibles."""
    planes = PlanSuscripcion.objects.filter(activo=True).order_by('orden', 'precio')
    suscripcion_actual = None
    if request.user.is_authenticated:
        suscripcion_actual = getattr(request.user, 'suscripcion', None)

    context = {
        'planes': planes,
        'suscripcion_actual': suscripcion_actual,
    }
    return render(request, 'suscripciones/planes.html', context)


@login_required(login_url='login')
def checkout_view(request, plan_slug):
    """
    Vista de Checkout seguro para la contratación de un plan con soporte multipasarela:
    Transbank (Webpay Plus), Mercado Pago y PayPal.
    """
    plan = get_object_or_404(PlanSuscripcion, slug=plan_slug, activo=True)
    suscripcion_actual = getattr(request.user, 'suscripcion', None)

    # Si el plan es gratuito, activarlo directamente sin cobro
    if plan.precio == 0:
        suscripcion, _ = SuscripcionUsuario.objects.update_or_create(
            usuario=request.user,
            defaults={
                'plan': plan,
                'estado': 'activa',
                'fecha_inicio': timezone.now(),
                'fecha_fin': None,
                'auto_renovar': False
            }
        )
        messages.success(request, f"¡Tu plan {plan.nombre} ha sido activado con éxito!")
        return redirect('suscripciones:mi_suscripcion')

    # Cálculos en CLP y USD referencial para PayPal
    subtotal = plan.precio
    iva = round(subtotal * Decimal('0.19'), 0)
    total = subtotal
    total_usd = round(float(total) / 950.0, 2)

    context = {
        'plan': plan,
        'suscripcion_actual': suscripcion_actual,
        'subtotal': subtotal,
        'iva': iva,
        'total': total,
        'total_usd': total_usd,
        'perfil': getattr(request.user, 'perfil', None),
    }
    return render(request, 'suscripciones/checkout.html', context)


@login_required(login_url='login')
def iniciar_pago_gateway_view(request):
    """
    Router principal de pasarelas de pago.
    Recibe la solicitud del usuario y lo redirige a la API correspondiente (Transbank, Mercado Pago o PayPal).
    """
    if request.method != 'POST':
        return redirect('suscripciones:planes')

    plan_id = request.POST.get('plan_id')
    metodo_pago = request.POST.get('metodo_pago', 'webpay_plus')
    plan = get_object_or_404(PlanSuscripcion, id=plan_id, activo=True)

    # Guardar en sesión el plan que se está intentando comprar
    request.session['checkout_plan_id'] = plan.id
    request.session['checkout_metodo_pago'] = metodo_pago
    request.session.pop('checkout_amount_usd', None)

    # Construir URLs de retorno absolutas
    host = request.get_host()
    protocol = 'https' if request.is_secure() else 'http'
    base_url = f"{protocol}://{host}"

    # 1. 🇨🇱 TRANSBANK WEBPAY PLUS (Y TARJETAS VISA/MASTERCARD/REDCOMPRA)
    if metodo_pago in ['webpay_plus', 'tarjeta_credito', 'visa', 'mastercard', 'redcompra', 'google_pay', 'apple_pay', 'bank_transfer']:
        buy_order = f"ORD-{request.user.id}-{int(timezone.now().timestamp())}"
        session_id = f"SESS-{request.user.id}-{uuid.uuid4().hex[:6]}"
        return_url = f"{base_url}{reverse('suscripciones:webpay_commit')}"

        tbk_service = TransbankService()
        result = tbk_service.crear_transaccion(
            buy_order=buy_order,
            session_id=session_id,
            amount=int(plan.precio),
            return_url=return_url
        )

        if result.get("success"):
            # Si es simulación local
            if result.get("is_simulated"):
                return redirect(result.get("url"))
            
            # Formulario auto-submit para redirección a Transbank Webpay
            context = {
                'url': result.get("url"),
                'token': result.get("token")
            }
            return render(request, 'suscripciones/webpay_redirect.html', context)
        else:
            messages.error(request, "No se pudo conectar con Transbank Webpay. Intenta nuevamente.")
            return redirect('suscripciones:checkout', plan_slug=plan.slug)

    # 2. ⚡ MERCADO PAGO CHECKOUT PRO
    elif metodo_pago == 'mercado_pago':
        external_ref = f"MP-{request.user.id}-{plan.id}-{int(timezone.now().timestamp())}"
        back_urls = {
            "success": f"{base_url}{reverse('suscripciones:mercadopago_callback')}",
            "failure": f"{base_url}{reverse('suscripciones:pago_cancelado')}",
            "pending": f"{base_url}{reverse('suscripciones:mercadopago_callback')}"
        }

        mp_service = MercadoPagoService()
        result = mp_service.crear_preferencia(
            plan=plan,
            usuario=request.user,
            external_reference=external_ref,
            back_urls=back_urls
        )

        if result.get("success"):
            return redirect(result.get("init_point"))
        else:
            messages.error(request, "No se pudo generar la preferencia de pago en Mercado Pago.")
            return redirect('suscripciones:checkout', plan_slug=plan.slug)

    # 3. 🅿️ PAYPAL ORDERS API v2
    elif metodo_pago == 'paypal':
        return_url = f"{base_url}{reverse('suscripciones:paypal_callback')}"
        cancel_url = f"{base_url}{reverse('suscripciones:pago_cancelado')}"
        # El precio de PayPal se expresa en USD referencial; el callback debe
        # comprobar el monto real de la orden, no sólo el plan guardado.
        expected_usd = max(1.0, round(float(plan.precio) / 950.0, 2))
        request.session['checkout_amount_usd'] = f"{expected_usd:.2f}"

        pp_service = PayPalService()
        result = pp_service.crear_orden(
            plan=plan,
            usuario=request.user,
            return_url=return_url,
            cancel_url=cancel_url
        )

        if result.get("success") and result.get("url"):
            return redirect(result.get("url"))
        else:
            messages.error(request, "No se pudo iniciar la orden en PayPal.")
            return redirect('suscripciones:checkout', plan_slug=plan.slug)

    messages.error(request, "Método de pago no reconocido.")
    return redirect('suscripciones:checkout', plan_slug=plan.slug)


def _checkout_plan(request):
    """Recupera sólo el plan que este usuario guardó al iniciar el pago."""
    plan_id = request.session.get('checkout_plan_id')
    if not plan_id:
        return None
    return PlanSuscripcion.objects.filter(id=plan_id, activo=True).first()


def _amount_covers(amount, plan):
    try:
        return Decimal(str(amount)) >= Decimal(str(plan.precio))
    except (TypeError, ValueError, ArithmeticError):
        return False


def _usd_amount_covers(amount, currency, expected):
    if str(currency or '').upper() != 'USD' or expected is None:
        return False
    try:
        return Decimal(str(amount)) >= Decimal(str(expected))
    except (TypeError, ValueError, ArithmeticError):
        return False


@login_required(login_url='login')
@csrf_exempt
def webpay_commit_view(request):
    """
    Callback de retorno para Transbank Webpay Plus.
    Recibe el token_ws (o TBK_TOKEN en caso de anulación), confirma la transacción y activa la suscripción.
    """
    token_ws = request.POST.get('token_ws') or request.GET.get('token_ws')
    tbk_token = request.POST.get('TBK_TOKEN') or request.GET.get('TBK_TOKEN')

    # Si el usuario canceló en el portal de Transbank
    if tbk_token and not token_ws:
        logger.info("[Webpay Plus] El usuario canceló la transacción en el portal de Transbank.")
        return redirect('suscripciones:pago_cancelado')

    if not token_ws:
        messages.error(request, "Token de transacción no recibido desde Webpay.")
        return redirect('suscripciones:planes')

    tbk_service = TransbankService()
    resultado = tbk_service.confirmar_transaccion(token_ws)

    plan = _checkout_plan(request)
    if plan is None:
        messages.error(request, "No encontramos el plan de esta compra. Inicia el pago nuevamente.")
        return redirect('suscripciones:planes')

    if resultado.get("success"):
        if (not resultado.get('is_simulated')
                and not _amount_covers(resultado.get('amount'), plan)):
            logger.warning("[Webpay Plus] Monto no coincide con el plan; no se activa la suscripción.")
            messages.error(request, "El monto pagado no coincide con el plan seleccionado.")
            return redirect('suscripciones:pago_cancelado')
        txn_ref = f"TBK-{resultado.get('authorization_code', uuid.uuid4().hex[:6].upper())}"
        try:
            pago, sub = _completar_suscripcion_usuario(
                usuario=request.user,
                plan=plan,
                metodo_pago='Webpay Plus',
                monto=plan.precio if resultado.get('is_simulated') else resultado.get('amount'),
                txn_referencia=txn_ref,
                metadata=resultado
            )
        except ValueError as exc:
            logger.warning("[Webpay Plus] Pago no aplicado: %s", exc)
            return redirect('suscripciones:pago_cancelado')
        return redirect('suscripciones:pago_exitoso', transaccion_id=txn_ref)
    else:
        messages.error(request, "La transacción en Webpay Plus fue rechazada o no pudo ser autorizada.")
        return redirect('suscripciones:pago_cancelado')


@login_required(login_url='login')
def mercadopago_callback_view(request):
    """
    Callback de retorno para Mercado Pago Checkout Pro.

    El estado de la URL no es una prueba de pago: se consulta la API y se
    comprueba que la referencia pertenece a este usuario y a este plan.
    """
    payment_id = request.GET.get('payment_id') or request.GET.get('collection_id') or request.GET.get('token')
    if not payment_id:
        return redirect('suscripciones:pago_cancelado')
    plan = _checkout_plan(request)
    if plan is None:
        messages.error(request, "No encontramos el plan de esta compra. Inicia el pago nuevamente.")
        return redirect('suscripciones:planes')

    verificacion = MercadoPagoService().verificar_pago(payment_id)
    if not verificacion.get('success'):
        logger.warning("[Mercado Pago] Pago no verificado: %s", verificacion.get('status'))
        return redirect('suscripciones:pago_cancelado')

    if verificacion.get('is_simulated'):
        if not simulation_allowed():
            return redirect('suscripciones:pago_cancelado')
        monto = plan.precio
    else:
        raw = verificacion.get('raw_data') or {}
        reference = str(verificacion.get('external_reference')
                        or raw.get('external_reference') or '')
        expected = f"MP-{request.user.id}-{plan.id}-"
        if not reference.startswith(expected):
            logger.warning("[Mercado Pago] Referencia externa no corresponde al usuario o plan.")
            return redirect('suscripciones:pago_cancelado')
        monto = verificacion.get('transaction_amount', raw.get('transaction_amount'))
        if not _amount_covers(monto, plan):
            logger.warning("[Mercado Pago] Monto no coincide con el plan.")
            return redirect('suscripciones:pago_cancelado')

    txn_ref = f"MP-{verificacion.get('payment_id') or payment_id}"
    try:
        pago, sub = _completar_suscripcion_usuario(
            usuario=request.user,
            plan=plan,
            metodo_pago='Mercado Pago',
            monto=monto,
            txn_referencia=txn_ref,
            metadata={'payment_id': payment_id, 'verification': verificacion}
        )
    except ValueError as exc:
        logger.warning("[Mercado Pago] Pago no aplicado: %s", exc)
        return redirect('suscripciones:pago_cancelado')
    return redirect('suscripciones:pago_exitoso', transaccion_id=txn_ref)


@login_required(login_url='login')
def paypal_callback_view(request):
    """
    Callback de retorno para PayPal Orders API v2.

    Una captura sólo activa la suscripción si PayPal confirma la orden y la
    referencia de compra corresponde al usuario y al plan de esta sesión.
    """
    order_id = request.GET.get('token') or request.GET.get('order_id')
    if not order_id:
        return redirect('suscripciones:pago_cancelado')
    plan = _checkout_plan(request)
    if plan is None:
        messages.error(request, "No encontramos el plan de esta compra. Inicia el pago nuevamente.")
        return redirect('suscripciones:planes')

    resultado = PayPalService().capturar_orden(order_id)
    if not resultado.get("success"):
        messages.error(request, "No se pudo completar la captura del pago con PayPal.")
        return redirect('suscripciones:pago_cancelado')

    if not resultado.get('is_simulated'):
        raw = resultado.get('raw_data') or {}
        expected = f"LITMATE-{request.user.id}-{plan.id}"
        units = raw.get('purchase_units') or []
        matched = next((unit for unit in units if isinstance(unit, dict)
                        and expected in {str(unit.get('custom_id')),
                                         str(unit.get('reference_id'))}), None)
        if matched is None:
            logger.warning("[PayPal] Orden no corresponde al usuario o plan.")
            return redirect('suscripciones:pago_cancelado')
        amount = matched.get('amount') or {}
        if not _usd_amount_covers(amount.get('value'), amount.get('currency_code'),
                                  request.session.get('checkout_amount_usd')):
            logger.warning("[PayPal] Monto o moneda no coinciden con el plan.")
            return redirect('suscripciones:pago_cancelado')

    txn_ref = f"PP-{order_id}"
    try:
        pago, sub = _completar_suscripcion_usuario(
            usuario=request.user,
            plan=plan,
            metodo_pago='PayPal',
            monto=plan.precio,
            txn_referencia=txn_ref,
            metadata=resultado
        )
    except ValueError as exc:
        logger.warning("[PayPal] Pago no aplicado: %s", exc)
        return redirect('suscripciones:pago_cancelado')
    return redirect('suscripciones:pago_exitoso', transaccion_id=txn_ref)


def simulador_gateway_view(request):
    """
    Simulador Sandbox interactivo para desarrollo y pruebas.

    No se publica en producción: de lo contrario cualquiera podría generar
    tokens simulados y saltarse la pasarela.
    """
    if not simulation_allowed():
        raise Http404
    provider = request.GET.get('provider', 'webpay')
    token = request.GET.get('token', 'TBK_MOCK_1234')
    amount = request.GET.get('amount', '9990')
    amount_usd = request.GET.get('amount_usd', '10.50')
    buy_order = request.GET.get('buy_order', 'ORD-DEV-1')
    ref = request.GET.get('ref', '')

    context = {
        'provider': provider,
        'token': token,
        'amount': amount,
        'amount_usd': amount_usd,
        'buy_order': buy_order,
        'ref': ref
    }
    return render(request, 'suscripciones/simulador_gateway.html', context)


def pago_cancelado_view(request):
    """Pantalla informativa cuando una transacción es cancelada o rechazada."""
    return render(request, 'suscripciones/pago_cancelado.html')


def _completar_suscripcion_usuario(usuario, plan, metodo_pago, monto, txn_referencia, metadata=None):
    """
    Registra un pago verificado y activa la suscripción de forma idempotente.

    Nunca acepta usuarios anónimos, planes ausentes ni una referencia ya usada
    por otra cuenta. Un reintento del mismo pago devuelve el registro existente.
    """
    if not getattr(usuario, 'is_authenticated', False) or not getattr(usuario, 'pk', None):
        raise ValueError('usuario no autenticado')
    if plan is None:
        raise ValueError('plan no encontrado')
    try:
        monto_decimal = Decimal(str(monto))
    except (TypeError, ValueError, ArithmeticError) as exc:
        raise ValueError('monto inválido') from exc
    if monto_decimal < 0:
        raise ValueError('monto negativo')
    txn_referencia = str(txn_referencia or '')[:255]
    if not txn_referencia:
        raise ValueError('referencia de pago ausente')

    dias = 365 if plan.periodo == 'anual' else 30
    fecha_fin = timezone.now() + datetime.timedelta(days=dias)

    with transaction.atomic():
        existente = (HistorialPago.objects.select_for_update()
                     .filter(referencia_transaccion=txn_referencia).first())
        if existente is not None:
            if existente.usuario_id != usuario.pk:
                raise ValueError('referencia de pago pertenece a otra cuenta')
            return existente, existente.suscripcion

        suscripcion, _ = SuscripcionUsuario.objects.update_or_create(
            usuario=usuario,
            defaults={
                'plan': plan,
                'estado': 'activa',
                'fecha_inicio': timezone.now(),
                'fecha_fin': fecha_fin,
                'auto_renovar': True,
                'id_suscripcion_externa': txn_referencia,
                'fecha_cancelacion': None,
                'motivo_cancelacion': None,
                'metadatos': metadata or {}
            }
        )

        pago = HistorialPago.objects.create(
            suscripcion=suscripcion,
            usuario=usuario,
            plan=plan,
            monto=monto_decimal,
            moneda='CLP',
            metodo_pago=metodo_pago,
            estado='completado',
            referencia_transaccion=txn_referencia
        )

    logger.info("Suscripción activada con éxito (%s): %s -> %s (Ref: %s)",
                metodo_pago, usuario.username, plan.nombre, txn_referencia)
    return pago, suscripcion


@login_required(login_url='login')
def pago_exitoso_view(request, transaccion_id):
    """Página de confirmación de pago y emisión de comprobante digital."""
    pago = get_object_or_404(HistorialPago, referencia_transaccion=transaccion_id, usuario=request.user)
    suscripcion = getattr(request.user, 'suscripcion', None)

    context = {
        'pago': pago,
        'suscripcion': suscripcion,
        'plan': pago.plan,
        'fecha_hoy': timezone.now(),
    }
    return render(request, 'suscripciones/pago_exitoso.html', context)


@login_required(login_url='login')
def cancelar_suscripcion_view(request):
    """Permite al usuario desactivar la renovación automática."""
    if request.method != 'POST':
        return redirect('suscripciones:mi_suscripcion')

    suscripcion = getattr(request.user, 'suscripcion', None)
    if suscripcion and suscripcion.plan.precio > 0:
        suscripcion.auto_renovar = False
        suscripcion.motivo_cancelacion = request.POST.get('motivo', 'Cancelado por el usuario')
        suscripcion.fecha_cancelacion = timezone.now()
        suscripcion.save()
        messages.info(request, "Tu renovación automática ha sido desactivada. Mantendrás tus beneficios hasta el fin del periodo actual.")
    
    return redirect('suscripciones:mi_suscripcion')


@login_required
def mi_suscripcion_view(request):
    """Muestra el estado de la suscripción del usuario autenticado."""
    suscripcion = getattr(request.user, 'suscripcion', None)
    pagos = HistorialPago.objects.filter(usuario=request.user).order_by('-fecha_pago')[:10]

    context = {
        'suscripcion': suscripcion,
        'pagos': pagos,
    }
    return render(request, 'suscripciones/mi_suscripcion.html', context)


@login_required
def api_estado_suscripcion(request):
    """API endpoint JSON para consultar el estado y límites de suscripción."""
    suscripcion = getattr(request.user, 'suscripcion', None)
    if not suscripcion:
        return JsonResponse({
            'autenticado': True,
            'tiene_suscripcion': False,
            'plan': 'Sin suscripción',
            'es_valida': False,
            'limite_consultas_ia_diarias': 10,
            'acceso_ia_avanzada': False,
        })

    return JsonResponse({
        'autenticado': True,
        'tiene_suscripcion': True,
        'plan': suscripcion.plan.nombre,
        'plan_slug': suscripcion.plan.slug,
        'estado': suscripcion.estado,
        'es_valida': suscripcion.es_valida,
        'fecha_fin': suscripcion.fecha_fin.isoformat() if suscripcion.fecha_fin else None,
        'limite_consultas_ia_diarias': suscripcion.plan.limite_consultas_ia_diarias,
        'acceso_ia_avanzada': suscripcion.plan.acceso_ia_avanzada,
    })
