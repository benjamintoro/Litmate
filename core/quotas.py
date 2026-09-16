import datetime
from django.utils import timezone
from django.core.cache import cache
from suscripciones.models import SuscripcionUsuario
import logging

logger = logging.getLogger('litmate')

# Configuración de límites diarios por plan (consultas por día)
# -1 representa consultas ilimitadas
LIMITES_PLANES = {
    'gratis': 10,
    'basico': 30,
    'lector': 50,
    'pro': 150,
    'premium': -1,
    'unlimited': -1,
    'anonimo': 5,  # Visitantes no registrados
}

def obtener_plan_y_limite(usuario):
    """
    Determina el plan activo y el tope diario de mensajes de IA del usuario.
    """
    if not usuario or not usuario.is_authenticated:
        return 'anonimo', LIMITES_PLANES['anonimo'], 'Visitante no registrado'

    # Administradores y miembros del staff tienen acceso ilimitado
    if usuario.is_superuser or usuario.is_staff:
        return 'admin', -1, 'Administrador'

    try:
        suscripcion = SuscripcionUsuario.objects.filter(
            usuario=usuario,
            estado='activa'
        ).select_related('plan').first()

        if suscripcion and suscripcion.plan:
            plan_slug = suscripcion.plan.slug.lower() if hasattr(suscripcion.plan, 'slug') else ''
            nombre_plan = suscripcion.plan.nombre
            limite = LIMITES_PLANES.get(plan_slug, getattr(suscripcion.plan, 'limite_diario_ia', 15))
            return plan_slug or 'gratis', limite, nombre_plan
    except Exception as e:
        logger.warning(f"Error consultando suscripción para cuota IA: {e}")

    return 'gratis', LIMITES_PLANES['gratis'], 'Plan Gratuito'


def generar_clave_cache_cuota(request):
    """
    Genera una clave única diaria basada en el usuario o su IP.
    """
    hoy_str = timezone.now().strftime('%Y-%m-%d')
    if request.user.is_authenticated:
        return f"cuota_ia_user:{request.user.id}:{hoy_str}"
    
    # Identificar visitantes por IP si no han iniciado sesión
    ip_cliente = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or request.META.get('REMOTE_ADDR', 'anon')
    return f"cuota_ia_ip:{ip_cliente}:{hoy_str}"


def verificar_y_consumir_cuota(request):
    """
    Verifica si el usuario dispone de mensajes restantes hoy.
    Si tiene cuota disponible, incrementa el contador y retorna True.
    """
    plan_slug, limite_diario, nombre_plan = obtener_plan_y_limite(request.user)

    # Si el plan es ilimitado (-1), permitimos el paso directo
    if limite_diario == -1:
        return True, {
            'permitido': True,
            'plan': nombre_plan,
            'limite': 'Ilimitado',
            'usadas': 0,
            'restantes': 'Ilimitado'
        }

    cache_key = generar_clave_cache_cuota(request)
    
    # Tiempo restante hasta la medianoche para expirar la clave
    ahora = timezone.now()
    manana = ahora.replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(days=1)
    segundos_hasta_medianoche = int((manana - ahora).total_seconds())

    usadas_hoy = cache.get(cache_key, 0)

    if usadas_hoy >= limite_diario:
        return False, {
            'permitido': False,
            'plan': nombre_plan,
            'limite': limite_diario,
            'usadas': usadas_hoy,
            'restantes': 0,
            'segundos_reinicio': segundos_hasta_medianoche
        }

    # Incrementar contador y preservar tiempo de expiración
    try:
        nuevo_total = cache.incr(cache_key)
    except ValueError:
        cache.set(cache_key, 1, timeout=segundos_hasta_medianoche)
        nuevo_total = 1

    return True, {
        'permitido': True,
        'plan': nombre_plan,
        'limite': limite_diario,
        'usadas': nuevo_total,
        'restantes': max(0, limite_diario - nuevo_total),
        'segundos_reinicio': segundos_hasta_medianoche
    }


def estado_cuota_usuario(request):
    """
    Consulta informativa de lecturas restantes sin incrementar el contador.
    """
    plan_slug, limite_diario, nombre_plan = obtener_plan_y_limite(request.user)
    
    if limite_diario == -1:
        return {
            'plan': nombre_plan,
            'limite': -1,
            'limite_texto': 'Ilimitado',
            'usadas': 0,
            'restantes': -1,
            'es_ilimitado': True
        }

    cache_key = generar_clave_cache_cuota(request)
    usadas_hoy = cache.get(cache_key, 0)
    
    return {
        'plan': nombre_plan,
        'limite': limite_diario,
        'limite_texto': str(limite_diario),
        'usadas': usadas_hoy,
        'restantes': max(0, limite_diario - usadas_hoy),
        'es_ilimitado': False
    }