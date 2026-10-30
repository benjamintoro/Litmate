"""Database selection without changing existing deployments implicitly."""
import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured


def database_config(base_dir, environ=None):
    env = os.environ if environ is None else environ
    selected = env.get('DB_ENGINE', '').strip().lower()
    if not selected:
        # Preserve the previous .env selection until an explicit cutover.
        selected = ('sqlite' if env.get('USE_SQLITE', 'False').lower() in
                    {'true', '1', 'yes'} or not env.get('DB_HOST') else 'mysql')
    if selected in {'sqlite', 'sqlite3', 'django.db.backends.sqlite3'}:
        path = Path(env.get('DB_SQLITE_PATH') or Path(base_dir) / 'db.sqlite3')
        if not path.is_absolute():
            path = Path(base_dir) / path
        return {'ENGINE': 'django.db.backends.sqlite3', 'NAME': path,
                'OPTIONS': {'timeout': 20}}
    if selected not in {'mysql', 'django.db.backends.mysql'}:
        raise ImproperlyConfigured('DB_ENGINE debe ser sqlite o mysql.')
    if not env.get('DB_NAME') or not env.get('DB_USER'):
        raise ImproperlyConfigured('MySQL requiere DB_NAME y DB_USER.')
    host = env.get('DB_HOST', '127.0.0.1')
    local = host.lower() in {'127.0.0.1', 'localhost', '::1'}
    options = {'charset': 'utf8mb4', 'connect_timeout': 5,
               'read_timeout': 15, 'write_timeout': 15,
               'init_command': "SET sql_mode='STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION'",
               'isolation_level': 'read committed'}
    ssl_ca = env.get('DB_SSL_CA', '').strip()
    # Keep verified TLS for the legacy TiDB host; do not force cloud TLS on localhost.
    if not ssl_ca and not local:
        import certifi
        ssl_ca = certifi.where()
    if ssl_ca:
        options['ssl'] = {'ca': ssl_ca}
    return {'ENGINE': 'django.db.backends.mysql', 'NAME': env['DB_NAME'],
            'USER': env['DB_USER'], 'PASSWORD': env.get('DB_PASSWORD', ''),
            'HOST': host, 'PORT': env.get('DB_PORT') or ('3306' if local else '4000'),
            'OPTIONS': options, 'CONN_MAX_AGE': 0}
