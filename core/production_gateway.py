"""Límite WSGI de producción: proxy local explícito, host y rutas cerradas."""
import base64
import binascii
import hashlib
import hmac
import ipaddress
import threading
import time
from urllib.parse import urlsplit
from reader_accounts.gateway import reader_methods


class ProductionGateway:
    def __init__(self, application, config, *, password=None):
        self.application, self.config = application, config
        self.expected = None
        self.failures=[]
        self.lock=threading.Lock()
        if config.gate == 'basic':
            if not password or len(password)<16:
                raise ValueError('El modo basic requiere una clave explícita de al menos 16 caracteres.')
            self.expected = hashlib.sha256(('demo:'+password).encode()).digest()

    def __call__(self, environ, start_response):
        def reject(status, text, headers=()):
            body=text.encode('utf8')
            start_response(status,[('Content-Type','text/plain; charset=utf-8'),('Content-Length',str(len(body))),
                ('Cache-Control','no-store'),('X-Content-Type-Options','nosniff'),*headers])
            return [body]
        try:
            remote=ipaddress.ip_address(environ.get('REMOTE_ADDR',''))
            if not remote.is_loopback:
                return reject('403 Forbidden','Origen de proxy no permitido.')
            authority=urlsplit('//'+environ.get('HTTP_HOST',''))
            public=urlsplit(self.config.origin)
            if (authority.hostname!=self.config.host or authority.username or authority.password
                    or authority.port not in (None,public.port or 443) or authority.path or authority.query or authority.fragment):
                return reject('400 Bad Request','Host no permitido.')
        except ValueError:
            return reject('400 Bad Request','Solicitud no válida.')
        path=environ.get('PATH_INFO','/')
        methods=reader_methods(path)
        if path in ('/_health/live/','/_health/ready/'):
            methods={'GET','HEAD'}
        if path.startswith('/operacion/'):
            methods={'GET','HEAD','POST'}
        if not methods or '\\' in path or any(part.startswith('.') for part in path.split('/') if part):
            return reject('404 Not Found','Recurso no disponible.')
        if self.expected is not None:
            header=environ.get('HTTP_AUTHORIZATION','')
            supplied=b''
            if len(header)<=1024 and header.startswith('Basic '):
                try:supplied=base64.b64decode(header[6:],validate=True)
                except (ValueError,binascii.Error):pass
            if not hmac.compare_digest(hashlib.sha256(supplied).digest(),self.expected):
                if header:
                    with self.lock:
                        now=time.monotonic()
                        self.failures=[t for t in self.failures if now-t<60][-30:]
                        limited=len(self.failures)>=10
                        self.failures.append(now)
                    if limited:
                        return reject('429 Too Many Requests','Demasiados intentos.',[('Retry-After','60')])
                return reject('401 Unauthorized','Acceso restringido.',[('WWW-Authenticate','Basic realm="LitMate", charset="UTF-8"')])
        environ.pop('HTTP_AUTHORIZATION',None)
        for name in ('HTTP_X_FORWARDED_PROTO','HTTP_X_FORWARDED_HOST','HTTP_X_FORWARDED_FOR','HTTP_FORWARDED'):
            environ.pop(name,None)
        # El listener se limita a loopback y el operador declara terminación TLS
        # en su proxy. Ninguna cabecera enviada por el visitante cambia este dato.
        environ['wsgi.url_scheme']='https'
        if environ.get('REQUEST_METHOD','GET') not in methods:
            return reject('405 Method Not Allowed','Método no permitido.',[('Allow',', '.join(sorted(methods)))])
        return self.application(environ,start_response)


def build_production_application(config, *, password=None):
    from django.core.wsgi import get_wsgi_application
    from whitenoise import WhiteNoise
    app=WhiteNoise(get_wsgi_application(),root=str(config.root/'static'),prefix='/static/',max_age=300)
    import django.contrib.admin
    from pathlib import Path
    app.add_files(str(Path(django.contrib.admin.__file__).parent/'static'),prefix='/static/')
    return ProductionGateway(app,config,password=password)
