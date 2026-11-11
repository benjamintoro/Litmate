from django.conf import settings
from django.db import models
from .checkout_models import SimulatedOrder
from .social_models import (
    AnnualReading, Follow, PostLike, ProfileCover, SharedList, SharedReading, SocialComment,
    SocialPost, SocialProfile, SocialReport,
)


class AccountEmail(models.Model):
    """Unicidad transaccional del correo, sin cambiar auth.User existente."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    normalized = models.CharField(max_length=254, unique=True)


class UsageBucket(models.Model):
    actor = models.CharField(max_length=80)
    period = models.CharField(max_length=10)
    used = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['actor', 'period'], name='reader_actor_period')]


class QueryOperation(models.Model):
    bucket = models.ForeignKey(UsageBucket, on_delete=models.PROTECT)
    actor = models.CharField(max_length=80)
    request_id = models.CharField(max_length=64)
    fingerprint = models.CharField(max_length=64)
    status = models.CharField(max_length=12, default='pending')
    stream_token = models.CharField(max_length=128, null=True, unique=True)
    result = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['actor', 'request_id'], name='reader_actor_request')]
        indexes = [models.Index(fields=['actor', 'status', 'expires_at'], name='reader_pending_expiry')]


class PaymentEvent(models.Model):
    """Idempotencia de confirmaciones verificadas; no guarda tarjetas ni payloads."""
    provider = models.CharField(max_length=50)
    event_id = models.CharField(max_length=100)
    digest = models.CharField(max_length=64)
    payment = models.ForeignKey('suscripciones.HistorialPago', on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['provider', 'event_id'], name='reader_provider_event')]
