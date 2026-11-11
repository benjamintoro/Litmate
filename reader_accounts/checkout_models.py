"""Pedidos de demostración vinculados al historial comercial existente."""
import uuid
from django.conf import settings
from django.db import models


class SimulatedOrder(models.Model):
    METHODS = [('debit', 'Débito simulado'), ('credit', 'Crédito simulado'), ('transfer', 'Transferencia simulada')]
    STATES = [('pending', 'Pendiente'), ('approved', 'Aprobada'), ('rejected', 'Rechazada'),
              ('cancelled', 'Cancelada'), ('temporary_error', 'Error temporal')]
    KINDS = [('purchase', 'Contratación o cambio de plan'), ('manual_renewal', 'Renovación voluntaria'),
             ('scheduled_renewal', 'Renovación mensual de prueba')]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    payment = models.OneToOneField('suscripciones.HistorialPago', on_delete=models.PROTECT, related_name='simulated_order')
    submission_id = models.UUIDField()
    method = models.CharField(max_length=12, choices=METHODS)
    kind = models.CharField(max_length=20, choices=KINDS, default='purchase')
    state = models.CharField(max_length=20, choices=STATES, default='pending')
    scenario = models.CharField(max_length=12, default='approved')
    attempts = models.PositiveIntegerField(default=0)
    plan_name = models.CharField(max_length=100)
    period = models.CharField(max_length=20)
    source_reference = models.CharField(max_length=255, blank=True)
    activated_at = models.DateTimeField(null=True)
    access_until = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        constraints = [models.UniqueConstraint(fields=['user', 'submission_id'], name='checkout_unique_submission')]
