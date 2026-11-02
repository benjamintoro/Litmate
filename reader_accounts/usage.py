"""Reserva durable, atómica e idempotente, independiente de las cachés de IA."""
import datetime
import hashlib
import re
from zoneinfo import ZoneInfo
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from suscripciones.models import SuscripcionUsuario
from .models import QueryOperation, UsageBucket

DB = 'accounts'
ZONE = ZoneInfo('America/Santiago')
GUEST_MESSAGE = ('Has utilizado tu consulta gratuita de invitado. Para seguir conversando con LitMate, '
                 'inicia sesión o crea una cuenta y elige tu plan. El plan gratuito no requiere tarjeta.')
DAILY_MESSAGE = ('Has alcanzado el límite diario de consultas de tu plan. Podrás volver a consultar '
                 'cuando se renueve tu cuota o elegir otro plan.')


class UsageError(Exception):
    def __init__(self, code, text, status=429):
        self.code, self.text, self.status = code, text, status
        super().__init__(text)


def entitlement(user):
    if not user.is_authenticated:
        return 'Invitado', 1, 'lifetime', None
    now = timezone.now()
    sub = SuscripcionUsuario.objects.filter(usuario=user, estado='activa').select_related('plan').first()
    if sub is None or (sub.fecha_fin and sub.fecha_fin <= now):
        raise UsageError('plan_required', 'Elige tu plan para empezar. El plan gratuito no requiere tarjeta.', 403)
    if sub.plan.precio > 0:
        from .payments import verified_payment
        if not verified_payment(sub):
            raise UsageError('paid_confirmation_required', 'Tu plan está guardado, pero necesita confirmación verificable del pago. No lo contrates otra vez; contacta con el responsable.', 403)
    limit = sub.plan.limite_consultas_ia_diarias
    if limit < 0:
        raise UsageError('plan_configuration', 'El plan necesita revisión. Inténtalo más tarde.', 503)
    local = now.astimezone(ZONE)
    reset = datetime.datetime.combine(local.date() + datetime.timedelta(days=1), datetime.time(), tzinfo=ZONE)
    return sub.plan.nombre, limit, local.date().isoformat(), reset


def _expire(actor):
    stale = QueryOperation.objects.filter(actor=actor, status='pending', expires_at__lte=timezone.now())
    for op in stale:
        UsageBucket.objects.filter(pk=op.bucket_id, used__gt=0).update(used=F('used') - 1)
        op.status = 'failed'
        op.result = {'error': 'operation_expired', 'response': 'La operación caducó sin confirmarse. Puedes enviar una consulta nueva.'}
        op.save(update_fields=['status', 'result'])


def reserve(actor, user, request_id, message):
    if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,64}', request_id):
        raise UsageError('request_id_required', 'La solicitud necesita un identificador de operación válido.', 400)
    fingerprint = hashlib.sha256(message.strip().encode()).hexdigest()
    with transaction.atomic(using=DB):
        # BEGIN IMMEDIATE en SQLite; bloqueo de escritura antes de leer contadores.
        _expire(actor)
        previous = QueryOperation.objects.filter(actor=actor, request_id=request_id).first()
        if previous:
            if previous.fingerprint != fingerprint:
                raise UsageError('operation_conflict', 'Ese identificador corresponde a otra consulta.', 409)
            if previous.status == 'pending':
                raise UsageError('operation_pending', 'La consulta ya está en curso. Espera su respuesta.', 409)
            return previous, True
        _, limit, period, _ = entitlement(user)
        bucket, _ = UsageBucket.objects.get_or_create(actor=actor, period=period)
        available = UsageBucket.objects.filter(pk=bucket.pk)
        if limit:
            available = available.filter(used__lt=limit)
        if not available.update(used=F('used') + 1):
            raise UsageError('guest_limit' if period == 'lifetime' else 'quota_exceeded',
                             GUEST_MESSAGE if period == 'lifetime' else DAILY_MESSAGE)
        op = QueryOperation.objects.create(bucket=bucket, actor=actor, request_id=request_id,
            fingerprint=fingerprint, expires_at=timezone.now() + datetime.timedelta(seconds=120))
        return op, False


def finish(op_id, result, *, failed=False):
    with transaction.atomic(using=DB):
        op = QueryOperation.objects.select_for_update().get(pk=op_id)
        if op.status != 'pending':
            return False
        if op.expires_at <= timezone.now():
            _expire(op.actor)
            return False
        if failed:
            UsageBucket.objects.filter(pk=op.bucket_id, used__gt=0).update(used=F('used') - 1)
        op.status, op.result = ('failed' if failed else 'completed'), result
        op.save(update_fields=['status', 'result'])
        return True


def info(actor, user):
    with transaction.atomic(using=DB):
        _expire(actor)
        name, limit, period, reset = entitlement(user)
        bucket = UsageBucket.objects.filter(actor=actor, period=period).first()
        used = bucket.used if bucket else 0
    return {'plan': name, 'limite': limit, 'usadas': used,
            'restantes': max(0, limit - used) if limit else None,
            'es_ilimitado': limit == 0, 'renovacion': reset.isoformat() if reset else None,
            'zona_horaria': 'America/Santiago', 'invitado': period == 'lifetime'}
