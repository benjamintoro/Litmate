import time
import functools
import logging
from django.core.cache import cache
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render

logger = logging.getLogger('litmate')


def get_client_ip(request):
    """Obtiene la dirección IP real del cliente detrás de proxies o directa."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR', '127.0.0.1')
    return ip


def check_honeypot(request, field_name='website_url_check'):
    """
    Verifica si un bot completó el campo trampa (honeypot) invisible.
    Retorna True si es un bot (debe ser bloqueado), False si es un usuario legítimo.
    """
    if request.method == 'POST':
        honeypot_value = request.POST.get(field_name, '').strip()
        if honeypot_value:
            logger.warning(f"[Anti-Spam] Honeypot activado desde IP {get_client_ip(request)} con valor: '{honeypot_value}'")
            return True
    return False


def check_rate_limit(key, limit=5, period=60):
    """
    Verifica si una clave ha superado el límite de peticiones dentro de un periodo (segundos).
    Retorna (is_limited: bool, remaining_seconds: int, current_count: int).
    """
    now = time.time()
    cache_key = f"ratelimit_{key}"
    history = cache.get(cache_key, [])
    
    # Filtrar solo marcas de tiempo dentro del periodo activo
    valid_history = [t for t in history if now - t < period]
    
    if len(valid_history) >= limit:
        oldest = valid_history[0]
        retry_after = int(period - (now - oldest)) + 1
        return True, max(1, retry_after), len(valid_history)
    
    valid_history.append(now)
    cache.set(cache_key, valid_history, timeout=period + 10)
    return False, 0, len(valid_history)


def ratelimit(limit=5, period=60, key_prefix='rl', json_response=False):
    """
    Decorador para proteger vistas contra ataques de fuerza bruta y spam.
    Ejemplo: @ratelimit(limit=5, period=60, key_prefix='login')
    """
    def decorator(view_func):
        @functools.wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            ip = get_client_ip(request)
            user_id = request.user.id if hasattr(request, 'user') and request.user.is_authenticated else 'anon'
            unique_key = f"{key_prefix}_{ip}_{user_id}"
            
            is_limited, retry_after, count = check_rate_limit(unique_key, limit=limit, period=period)
            
            if is_limited:
                logger.warning(f"[RateLimit] Excedido límite en '{key_prefix}' por IP {ip}. Reintentar en {retry_after}s.")
                if json_response or request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', ''):
                    response = JsonResponse({
                        'status': 'error',
                        'msg': f'Has superado el límite de solicitudes permitidas. Por favor espera {retry_after} segundos antes de intentar nuevamente.',
                        'retry_after': retry_after
                    }, status=429)
                    response['Retry-After'] = str(retry_after)
                    return response
                
                response = render(request, '429.html', {'retry_after': retry_after}, status=429)
                response['Retry-After'] = str(retry_after)
                return response
            
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator
