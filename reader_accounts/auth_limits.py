"""Límites atómicos sin confiar en cabeceras IP ni penalizar una IP compartida."""
import functools
import hashlib
import time
from django.http import HttpResponse
from core.ai_concurrency import rate_increment


def auth_limit(limit):
    def decorate(view):
        @functools.wraps(view)
        def guarded(request, *args, **kwargs):
            if request.method == 'POST':
                principal = (request.POST.get('username_or_email') or request.POST.get('username') or request.POST.get('email') or '').strip().casefold()
                identifiers = ['visitor:' + request.reader_actor]
                if principal:
                    identifiers.append('principal:' + principal)
                try:
                    for identifier in identifiers:
                        key = 'reader-auth:' + hashlib.sha256(identifier.encode()).hexdigest() + ':' + str(int(time.time()) // 60)
                        if rate_increment(key, 120) > limit:
                            response = HttpResponse('Demasiados intentos. Espera un minuto.', status=429)
                            response['Retry-After'] = '60'
                            return response
                except Exception:
                    return HttpResponse('No fue posible comprobar el límite de acceso. Inténtalo más tarde.', status=503)
            return view(request, *args, **kwargs)
        return guarded
    return decorate
