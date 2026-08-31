import datetime
import uuid
import logging
from decimal import Decimal
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt

from .models import PlanSuscripcion, SuscripcionUsuario, HistorialPago
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

    if resultado.get("success"):
        plan_id = request.session.get('checkout_plan_id')
        plan = PlanSuscripcion.objects.filter(id=plan_id).first() if plan_id else PlanSuscripcion.objects.filter(slug='lector-vip').first()

        # Activar suscripción y registrar pago
        txn_ref = f"TBK-{resultado.get('authorization_code', uuid.uuid4().hex[:6].upper())}"
        pago, sub = _completar_suscripcion_usuario(
            usuario=request.user,
            plan=plan,
            metodo_pago='Webpay Plus',
            monto=resultado.get('amount', plan.precio),
            txn_referencia=txn_ref,
            metadata=resultado
        )
        return redirect('suscripciones:pago_exitoso', transaccion_id=txn_ref)
    else:
        messages.error(request, "La transacción en Webpay Plus fue rechazada o no pudo ser autorizada.")
        return redirect('suscripciones:pago_cancelado')


def mercadopago_callback_view(request):
    """
    Callback de retorno para Mercado Pago Checkout Pro.
    """
    payment_id = request.GET.get('payment_id') or request.GET.get('collection_id') or request.GET.get('token')
    status = request.GET.get('status') or request.GET.get('collection_status', 'approved')

    if status in ['approved', 'accredited']:
        plan_id = request.session.get('checkout_plan_id')
        plan = PlanSuscripcion.objects.filter(id=plan_id).first() if plan_id else PlanSuscripcion.objects.filter(slug='lector-vip').first()

        txn_ref = f"MP-{payment_id or uuid.uuid4().hex[:8].upper()}"
        pago, sub = _completar_suscripcion_usuario(
            usuario=request.user,
            plan=plan,
            metodo_pago='Mercado Pago',
            monto=plan.precio,
            txn_referencia=txn_ref,
            metadata={'payment_id': payment_id, 'status': status}
        )
        return redirect('suscripciones:pago_exitoso', transaccion_id=txn_ref)
    else:
        return redirect('suscripciones:pago_cancelado')


def paypal_callback_view(request):
    """
    Callback de retorno para PayPal Orders API v2.
    """
    order_id = request.GET.get('token') or request.GET.get('order_id')
    if not order_id:
        return redirect('suscripciones:pago_cancelado')

    pp_service = PayPalService()
    resultado = pp_service.capturar_orden(order_id)

    if resultado.get("success"):
        plan_id = request.session.get('checkout_plan_id')
        plan = PlanSuscripcion.objects.filter(id=plan_id).first() if plan_id else PlanSuscripcion.objects.filter(slug='lector-vip').first()

        txn_ref = f"PP-{order_id}"
        pago, sub = _completar_suscripcion_usuario(
            usuario=request.user,
            plan=plan,
            metodo_pago='PayPal',
            monto=plan.precio,
            txn_referencia=txn_ref,
            metadata=resultado
        )
        return redirect('suscripciones:pago_exitoso', transaccion_id=txn_ref)
    else:
        messages.error(request, "No se pudo completar la captura del pago con PayPal.")
        return redirect('suscripciones:pago_cancelado')


def simulador_gateway_view(request):
    """
    Simulador Sandbox interactivo para desarrollo y pruebas.
    Permite probar en 1 clic los flujos de éxito, rechazo o cancelación de cada pasarela.
    """
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
    Función auxiliar para registrar el pago y activar la suscripción del usuario en TiDB Cloud.
    """
    dias = 365 if plan.periodo == 'anual' else 30
    fecha_fin = timezone.now() + datetime.timedelta(days=dias)

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
        monto=monto,
        moneda='CLP',
        metodo_pago=metodo_pago,
        estado='completado',
        referencia_transaccion=txn_referencia
    )

    logger.info(f"Suscripción activada con éxito ({metodo_pago}): {usuario.username} -> {plan.nombre} (Ref: {txn_referencia})")
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
