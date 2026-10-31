"""Perfil de demostración separado; sólo lo utiliza iniciar_demo.py."""
from .settings import *  # noqa: F403
from django.core.exceptions import ImproperlyConfigured
import re

DEBUG = False
LITMATE_DEMO_MODE = os.environ.get('LITMATE_DEMO_MODE', '')
LITMATE_DEMO_WORKSPACE = Path(os.environ.get('LITMATE_DEMO_WORKSPACE', ''))
if LITMATE_DEMO_MODE not in {'local', 'https'} or not LITMATE_DEMO_WORKSPACE.is_absolute():
    raise ImproperlyConfigured('Arranca la demostración con iniciar_demo.py.')
if LITMATE_DEMO_MODE == 'https':
    host = os.environ.get('LITMATE_DEMO_HOST', '')
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.[a-z0-9-]+\.ts\.net', host):
        raise ImproperlyConfigured('Indica el nombre DNS exacto asignado por Tailscale, sin URL ni puerto.')
    ALLOWED_HOSTS = [host]
    CSRF_TRUSTED_ORIGINS = ['https://' + host]
else:
    ALLOWED_HOSTS = ['127.0.0.1', 'localhost']
    CSRF_TRUSTED_ORIGINS = []

ROOT_URLCONF = 'litmate_project.demo_urls'
SESSION_ENGINE = 'django.contrib.sessions.backends.file'
SESSION_FILE_PATH = str(LITMATE_DEMO_WORKSPACE / 'sessions')
SESSION_COOKIE_NAME = 'litmate_demo_sessionid'
SESSION_COOKIE_AGE = 3600
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_DOMAIN = None
CSRF_COOKIE_DOMAIN = None
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = LITMATE_DEMO_MODE == 'https'
SECURE_SSL_REDIRECT = LITMATE_DEMO_MODE == 'https'
SECURE_PROXY_SSL_HEADER = None
USE_X_FORWARDED_HOST = False
SECURE_HSTS_SECONDS = 3600 if LITMATE_DEMO_MODE == 'https' else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
X_FRAME_OPTIONS = 'DENY'
MEDIA_ROOT = LITMATE_DEMO_WORKSPACE / 'media'
EMAIL_BACKEND = 'django.core.mail.backends.dummy.EmailBackend'
LITMATE_SOCIAL_DEMO = False
LITMATE_DEMO_READ_ONLY = True
