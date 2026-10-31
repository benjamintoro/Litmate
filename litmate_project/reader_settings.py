"""Perfil nuevo, no publicado: bibliografía read-only y cuentas privadas aparte."""
from .demo_settings import *  # noqa: F403

LITMATE_ACCOUNTS_ENABLED = True
LITMATE_USE_EXISTING_QUOTAS = False  # El nuevo ledger reserva antes de la IA.
LITMATE_PAYMENT_SANDBOX = False
ROOT_URLCONF = 'reader_accounts.urls'
INSTALLED_APPS = [*INSTALLED_APPS, 'reader_accounts']
DATABASE_ROUTERS = ['reader_accounts.router.AccountsRouter']
account_path = os.environ.get('LITMATE_ACCOUNTS_DB', '')
if not account_path or not Path(account_path).is_absolute():
    raise ImproperlyConfigured('Indica la ruta absoluta de la base privada de cuentas.')
if Path(account_path).resolve() == Path(DATABASES['default'].get('NAME', '')).resolve():
    raise ImproperlyConfigured('Las cuentas deben estar separadas del catálogo.')
DATABASES = {**DATABASES, 'accounts': {
    'ENGINE': 'django.db.backends.sqlite3', 'NAME': account_path,
    'OPTIONS': {'timeout': 10, 'transaction_mode': 'IMMEDIATE'},
    'TEST': {'DEPENDENCIES': []},
}}
SESSION_ENGINE = 'django.contrib.sessions.backends.db'
SESSION_COOKIE_NAME = 'litmate_reader_sessionid'
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_AGE = 14 * 24 * 3600
TIME_ZONE = 'America/Santiago'
MIDDLEWARE = [*MIDDLEWARE, 'reader_accounts.identity.VisitorIdentityMiddleware']
TEMPLATES = [{**entry, 'OPTIONS': {**entry['OPTIONS'], 'context_processors': [
    *entry['OPTIONS']['context_processors'], 'reader_accounts.context.presentation']}} for entry in TEMPLATES]
# El correo no se habilita suponiendo que exista un proveedor configurado.
EMAIL_BACKEND = 'django.core.mail.backends.dummy.EmailBackend'
