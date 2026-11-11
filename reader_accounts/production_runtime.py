"""Preflight y coordinación local; nunca migra ni publica servicios."""
from contextlib import closing
from pathlib import Path
import json
import os
import socket
import tempfile
import urllib.request
from urllib.parse import urlsplit


class FileLease:
    """Bloqueo liberado por el SO incluso si el proceso se interrumpe."""
    def __init__(self,path):self.path=Path(path);self.stream=None

    def __enter__(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.stream=self.path.open('a+b')
        if self.path.stat().st_size==0:self.stream.write(b'0');self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.stream.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as error:
            self.stream.close();self.stream=None
            raise ValueError('Ya existe otro proceso para esta operación.') from error
        return self

    def __exit__(self,*args):
        if self.stream:
            self.stream.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.stream.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(self.stream,fcntl.LOCK_UN)
            self.stream.close()


def ensure_port_free(port):
    with socket.socket() as sock:
        # No habilitar SO_REUSEADDR en Windows: podría ocultar otro listener.
        sock.bind(('127.0.0.1',port))


def prepare_runtime(config):
    root=config.runtime
    marker=root/'production-owner.json'
    if root.exists() and not marker.is_file():
        raise ValueError('El runtime existente no pertenece a producción; usa una carpeta nueva.')
    root.mkdir(parents=True,exist_ok=True)
    expected={'owner':'litmate-production-v1'}
    if marker.exists() and json.loads(marker.read_text(encoding='utf8'))!=expected:
        raise ValueError('Marcador de producción inválido.')
    if not marker.exists():
        with marker.open('x',encoding='utf8') as f:json.dump(expected,f)
    for name in ('logs','media','backups'):
        directory=root/name;directory.mkdir(exist_ok=True)
        if directory.is_symlink():raise ValueError('No se permiten enlaces en almacenamiento privado.')
        with tempfile.TemporaryFile(dir=directory):pass


def local_json(base, path, *, timeout=1.5):
    parsed=urlsplit(base)
    if parsed.scheme!='http' or parsed.hostname not in ('127.0.0.1','localhost','::1') or parsed.username or parsed.password or parsed.path not in ('','/'):
        raise ValueError('Las dependencias locales requieren una URL loopback explícita.')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):return None
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    with opener.open(base.rstrip('/')+path,timeout=timeout) as response:
        raw=response.read(65537)
        if len(raw)>65536:raise ValueError('Respuesta de dependencia demasiado grande.')
        return json.loads(raw) if raw.strip().startswith((b'{',b'[')) else {'http_status':response.status}


def preflight(config, *, check_dependencies=True):
    from django.conf import settings
    from django.db import connections
    from django.db.migrations.executor import MigrationExecutor
    from .operations import account_health
    errors=[];warnings=[]
    if settings.DEBUG or settings.SECRET_KEY.startswith('django-insecure') or len(settings.SECRET_KEY)<32:
        errors.append('unsafe_django_configuration')
    if not settings.SESSION_COOKIE_SECURE or not settings.CSRF_COOKIE_SECURE or settings.SECURE_PROXY_SSL_HEADER is not None:
        errors.append('unsafe_transport_configuration')
    if settings.SESSION_ENGINE!='django.contrib.sessions.backends.db':errors.append('session_storage')
    if settings.ALLOWED_HOSTS!=[config.host] or settings.CSRF_TRUSTED_ORIGINS!=[config.origin]:errors.append('public_origin')
    if not config.accounts.is_file() or not os.access(config.accounts,os.R_OK|os.W_OK):errors.append('accounts_permissions')
    if not (config.root/'static/js/litmate_safe.js').is_file():errors.append('static_files')
    health=account_health(config.accounts)
    if health['status']!='ok':errors.append('accounts_integrity')
    try:
        if not config.accounts.is_file():raise ValueError('accounts_missing')
        account=connections['accounts']
        executor=MigrationExecutor(account)
        if executor.migration_plan(executor.loader.graph.leaf_nodes()):errors.append('pending_account_migrations')
        catalog=connections['default']
        if catalog.vendor=='sqlite':
            if not config.testing or not Path(catalog.settings_dict['NAME']).resolve().is_relative_to(config.root/'.testtmp'):
                errors.append('catalogue_not_isolated')
            if not Path(catalog.settings_dict['NAME']).is_file():raise ValueError('catalogue_missing')
        elif catalog.vendor!='mysql':errors.append('catalogue_backend')
        with catalog.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.execute('SELECT id FROM core_libro LIMIT 1')
            if catalog.vendor=='mysql':
                cursor.execute('SELECT DATABASE(), @@session.transaction_read_only')
                name,readonly=cursor.fetchone()
                if name!='litmate_db' or not readonly:errors.append('catalogue_not_readonly')
    except Exception:errors.append('database_unavailable')
    services={}
    if check_dependencies:
        try:
            data=local_json(settings.LITMATE_OLLAMA_URL,'/api/tags')
            available=any(model.get('name')==settings.LITMATE_LOCAL_MODEL for model in data.get('models',[]))
            services['ollama']='ok' if available else 'model_missing'
            if not available:errors.append('ollama_model_missing')
        except Exception:
            services['ollama']='unavailable';errors.append('ollama_unavailable')
        try:local_json(settings.LITMATE_SEARXNG_URL,'/healthz');services['searxng']='ok'
        except Exception:services['searxng']='unavailable';warnings.append('searxng_unavailable_local_retrieval_remains')
    if getattr(settings,'LITMATE_READER_EMAIL_ENABLED',False) and os.environ.get('LITMATE_EMAIL_AUTHORIZED')!='1':
        errors.append('email_not_authorized')
    return {'ready':not errors,'errors':errors,'warnings':warnings,'services':services,
            'environment':settings.LITMATE_ENVIRONMENT,'version':settings.LITMATE_VERSION,
            'access_gate':config.gate,'public_origin':config.origin,'listener':'127.0.0.1:'+str(config.port)}
