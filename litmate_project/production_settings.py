"""LitMate producción: origen configurable y proxy TLS explícito en loopback."""
from .settings import *  # noqa: F403
from .account_settings import apply_account_settings
from .production_config import ProductionConfig

PRODUCTION = ProductionConfig.from_environment(BASE_DIR)
apply_account_settings(globals())
DEBUG = False
ROOT_URLCONF = 'litmate_project.production_urls'
LITMATE_ENVIRONMENT = 'production-test' if PRODUCTION.testing else 'production'
LITMATE_VERSION = '1.0.0'
LITMATE_PRODUCTION_OPEN = PRODUCTION.gate == 'open'
LITMATE_PUBLIC_ORIGIN = PRODUCTION.origin
ALLOWED_HOSTS = [PRODUCTION.host]
CSRF_TRUSTED_ORIGINS = [PRODUCTION.origin]
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = CSRF_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_DOMAIN = CSRF_COOKIE_DOMAIN = None
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = None
USE_X_FORWARDED_HOST = False
SECURE_HSTS_SECONDS = 3600
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_PRELOAD = False
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'
LITMATE_CATALOGUE_READ_ONLY = True
MEDIA_ROOT = PRODUCTION.runtime/'media'
for _name in ('LITMATE_AI_RUNTIME_DB','LITMATE_AI_STREAM_DB','LITMATE_AI_ANSWER_CACHE_DB'):
    globals()[_name] = PRODUCTION.runtime/(_name.lower()+'.sqlite3')
CACHES = {'default': {'BACKEND':'django.core.cache.backends.locmem.LocMemCache', 'LOCATION':'litmate-production'}}
LITMATE_AI_LOCK_BACKEND = 'sqlite'
LITMATE_SIGNUP_GLOBAL_PER_HOUR = 30
LITMATE_SIGNUP_VISITOR_PER_DAY = 3
EMAIL_SUBJECT_PREFIX = '[LitMate] '
LOGGING = {**LOGGING, 'handlers': {**LOGGING['handlers'], 'file':{
    **LOGGING['handlers']['file'], 'filename':PRODUCTION.runtime/'logs/production.log'}}}
