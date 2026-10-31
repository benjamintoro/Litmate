"""Restricción WSGI de la demo, sin modificar el chat ni confiar en cabeceras IP."""
import base64
import binascii
import hashlib
import hmac
import re
import threading
import time


# Lista cerrada: el URLconf normal conserva sus nombres, pero no se publica
# ninguna ruta nueva por el mero hecho de incorporarla al proyecto.
PUBLIC_PAGES = frozenset({
    '/', '/about/', '/post/', '/libros/', '/chat/', '/chatbot/',
    '/terminos-y-condiciones/', '/politica-de-privacidad/', '/politica-de-cookies/',
    '/suscripciones/planes/', '/api/quick-search/', '/api/libro/precios/', '/api/cuota-ia/',
})
PREVIEW_FORMS = frozenset({'/login/', '/registro/', '/password-reset/', '/contact/'})
POST_ENDPOINTS = frozenset({'/chatbot_query/', '/chatbot_finalize/', '/api/miku-tts/',
                            '/api/track-conversion/', '/logout/'})


def allowed_methods(path):
    if path in PUBLIC_PAGES or path in {'/auth/social/google/', '/auth/social/github/'}:
        return {'GET', 'HEAD'}
    if re.fullmatch(r'/suscripciones/checkout/[a-z0-9-]+/', path):
        return {'GET', 'HEAD'}
    if path in PREVIEW_FORMS:
        return {'GET', 'HEAD', 'POST'}
    if path in POST_ENDPOINTS:
        return {'POST'}
    if path.startswith('/static/') or re.fullmatch(r'/media/tts_cache/miku_[0-9a-f]{64}\.mp3', path):
        return {'GET', 'HEAD'}
    return set()


class DemoGateway:
    def __init__(self, application, *, password, hosts, username='demo', route_policy=allowed_methods):
        if len(password) < 16 or not hosts:
            raise ValueError('La demo requiere una contraseña de al menos 16 caracteres y hosts explícitos.')
        self.application = application
        self.expected = hashlib.sha256((username + ':' + password).encode('utf-8')).digest()
        self.hosts = set(hosts)
        self.lock = threading.Lock()
        self.failures = []
        self.route_policy = route_policy

    def __call__(self, environ, start_response):
        def respond(status, text, headers=()):
            body = text.encode('utf-8')
            start_response(status, [('Content-Type', 'text/plain; charset=utf-8'),
                ('Content-Length', str(len(body))), ('Cache-Control', 'no-store'),
                ('X-Content-Type-Options', 'nosniff'), *headers])
            return [body]
        host = environ.get('HTTP_HOST', '').lower()
        host = host.split(':', 1)[0] if host.count(':') <= 1 else ''
        if host not in self.hosts:
            return respond('400 Bad Request', 'Host no permitido.')
        path = environ.get('PATH_INFO', '/')
        methods = self.route_policy(path)
        if not methods or any(part.startswith('.') for part in path.split('/') if part):
            return respond('404 Not Found', 'Recurso no disponible en la demostración.')
        header = environ.get('HTTP_AUTHORIZATION', '')
        supplied = b''
        if len(header) <= 1024 and header.startswith('Basic '):
            try:
                supplied = base64.b64decode(header[6:], validate=True)
            except (ValueError, binascii.Error):
                pass
        valid = hmac.compare_digest(hashlib.sha256(supplied).digest(), self.expected)
        if not valid:
            limited = False
            if header:
                # El desafío inicial sin Authorization es parte de Basic Auth:
                # imágenes/scripts concurrentes no son adivinación de claves.
                # Cualquier credencial enviada pero inválida sí consume límite.
                with self.lock:
                    now = time.monotonic()
                    self.failures = [stamp for stamp in self.failures if now - stamp < 60][-30:]
                    limited = len(self.failures) >= 10
                    self.failures.append(now)
            if limited:
                return respond('429 Too Many Requests', 'Demasiados intentos de acceso.', [('Retry-After', '60')])
            return respond('401 Unauthorized', 'Introduce las credenciales privadas de la demo.',
                           [('WWW-Authenticate', 'Basic realm="LitMate demo", charset="UTF-8"')])
        # No propagar la contraseña del gateway a Django, logs o errores.
        environ.pop('HTTP_AUTHORIZATION', None)
        if environ.get('REQUEST_METHOD', 'GET') not in methods:
            return respond('405 Method Not Allowed', 'Método no disponible en la demostración.',
                           [('Allow', ', '.join(sorted(methods)))])
        return self.application(environ, start_response)


def build_demo_application(password):
    from django.conf import settings
    from django.core.wsgi import get_wsgi_application
    from django.db.backends.signals import connection_created
    from whitenoise import WhiteNoise
    if not getattr(settings, 'LITMATE_DEMO_READ_ONLY', False):
        raise ValueError('El gateway sólo debe usarse con el perfil de demostración.')
    def read_only_mysql(sender, connection, **kwargs):
        if connection.vendor == 'mysql' and getattr(settings, 'LITMATE_DEMO_READ_ONLY', False):
            with connection.cursor() as cursor:
                cursor.execute('SET SESSION TRANSACTION READ ONLY')
    connection_created.connect(read_only_mysql, weak=False, dispatch_uid='litmate-demo-read-only')
    app = WhiteNoise(get_wsgi_application(), root=str(settings.BASE_DIR / 'static'),
                     prefix='/static/', max_age=300)
    policy = allowed_methods
    if getattr(settings, 'LITMATE_ACCOUNTS_ENABLED', False):
        from reader_accounts.gateway import reader_methods
        policy = reader_methods
    return DemoGateway(app, password=password, hosts=settings.ALLOWED_HOSTS, route_policy=policy)
