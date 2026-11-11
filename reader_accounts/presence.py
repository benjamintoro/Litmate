"""Presencia efímera por lector para la instancia única de Waitress.

Cada pestaña visible envía un pulso. Las entradas caducan a los 90 segundos.
No conserva direcciones IP ni interviene en las estadísticas de lectura.
"""
import threading
import time

from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

WINDOW_SECONDS = 90
_seen = {}
_lock = threading.Lock()


@never_cache
@require_POST
@csrf_protect
def heartbeat(request):
    now = time.monotonic()
    with _lock:
        expired = [key for key, (_, seen) in _seen.items() if now - seen >= WINDOW_SECONDS]
        for key in expired:
            del _seen[key]
        # Identidad firmada del middleware, compartida por pestañas del lector.
        visitor = request.reader_visitor_hash
        if request.reader_identity_established and (visitor in _seen or len(_seen) < 20000):
            _seen[visitor] = (request.reader_actor, now)
        count = len({actor for actor, _ in _seen.values()})
    return JsonResponse({'online': count, 'window_seconds': WINDOW_SECONDS})
