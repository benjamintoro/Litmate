from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class PlanSuscripcion(models.Model):
    """Define los niveles o planes de suscripción disponibles en la plataforma."""
    PERIODO_CHOICES = (
        ('mensual', 'Mensual'),
        ('semestral', 'Semestral'),
        ('anual', 'Anual'),
        ('vitalicio', 'Vitalicio'),
    )

    nombre = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, unique=True, help_text="Identificador único (ej: gratis, lector-pro, premium)")
    descripcion = models.TextField(blank=True, help_text="Detalles y beneficios del plan")
    precio = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    moneda = models.CharField(max_length=10, default='CLP')
    periodo = models.CharField(max_length=20, choices=PERIODO_CHOICES, default='mensual')
    
    # Límites y características de la suscripción
    limite_consultas_ia_diarias = models.IntegerField(default=15, help_text="Número de preguntas diarias al asistente IA (0 para ilimitadas)")
    limite_favoritos = models.IntegerField(default=50, help_text="Número máximo de libros favoritos (0 para ilimitados)")
    acceso_ia_avanzada = models.BooleanField(default=False, help_text="Habilita modelos LLM avanzados y funciones premium de IA")
    
    activo = models.BooleanField(default=True, help_text="Indica si el plan está disponible para nuevos suscriptores")
    orden = models.IntegerField(default=0, help_text="Orden de visualización en la tabla de precios")
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Plan de Suscripción'
        verbose_name_plural = 'Planes de Suscripción'
        ordering = ['orden', 'precio']

    def __str__(self):
        return f"{self.nombre} ({self.precio} {self.moneda}/{self.periodo})"


class SuscripcionUsuario(models.Model):
    """Registra la suscripción actual de un usuario a un plan determinado."""
    ESTADO_CHOICES = (
        ('activa', 'Activa'),
        ('pendiente', 'Pendiente de Pago'),
        ('cancelada', 'Cancelada'),
        ('expirada', 'Expirada'),
        ('prueba', 'Periodo de Prueba'),
    )

    usuario = models.OneToOneField(User, on_delete=models.CASCADE, related_name='suscripcion')
    plan = models.ForeignKey(PlanSuscripcion, on_delete=models.PROTECT, related_name='suscripciones_usuarios')
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='activa')
    fecha_inicio = models.DateTimeField(default=timezone.now)
    fecha_fin = models.DateTimeField(null=True, blank=True, help_text="Dejar vacío si es vitalicia o indefinida")
    auto_renovar = models.BooleanField(default=True)
    id_suscripcion_externa = models.CharField(max_length=255, blank=True, null=True, help_text="ID en pasarela de pago (Stripe, Transbank, etc.)")
    fecha_cancelacion = models.DateTimeField(null=True, blank=True)
    motivo_cancelacion = models.CharField(max_length=255, blank=True, null=True, help_text="Motivo de cancelación para análisis de churn")
    metadatos = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = 'Suscripción de Usuario'
        verbose_name_plural = 'Suscripciones de Usuarios'

    def __str__(self):
        return f"Suscripción de {self.usuario.username} - Plan {self.plan.nombre} ({self.estado})"

    @property
    def es_valida(self):
        """Verifica si la suscripción está activa y no ha vencido."""
        if self.estado != 'activa':
            return False
        if self.fecha_fin and self.fecha_fin < timezone.now():
            return False
        return True


class HistorialPago(models.Model):
    """Registro de transacciones y pagos de suscripción."""
    ESTADO_PAGO_CHOICES = (
        ('completado', 'Completado'),
        ('pendiente', 'Pendiente'),
        ('fallido', 'Fallido'),
        ('reembolsado', 'Reembolsado'),
    )

    suscripcion = models.ForeignKey(SuscripcionUsuario, on_delete=models.SET_NULL, null=True, blank=True, related_name='pagos')
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='pagos')
    plan = models.ForeignKey(PlanSuscripcion, on_delete=models.SET_NULL, null=True, blank=True)
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    moneda = models.CharField(max_length=10, default='CLP')
    metodo_pago = models.CharField(max_length=50, default='tarjeta')
    estado = models.CharField(max_length=20, choices=ESTADO_PAGO_CHOICES, default='completado')
    referencia_transaccion = models.CharField(max_length=255, blank=True, null=True, help_text="Código de transacción del proveedor")
    fecha_pago = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Historial de Pago'
        verbose_name_plural = 'Historial de Pagos'
        ordering = ['-fecha_pago']

    def __str__(self):
        return f"Pago #{self.id} - {self.usuario.username} ({self.monto} {self.moneda} - {self.estado})"
