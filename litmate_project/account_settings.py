"""Política de cuentas compartida, independiente del transporte web."""
import os
from email.utils import parseaddr
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured


def apply_account_settings(config):
    account = os.environ.get('LITMATE_ACCOUNTS_DB', '')
    if not account or not Path(account).is_absolute():
        raise ImproperlyConfigured('Indica la ruta absoluta de la base privada de cuentas.')
    if Path(account).resolve() == Path(config['DATABASES']['default'].get('NAME', '')).resolve():
        raise ImproperlyConfigured('Las cuentas deben estar separadas del catálogo.')
    config.update(LITMATE_ACCOUNTS_ENABLED=True, LITMATE_USE_EXISTING_QUOTAS=False,
        LITMATE_COMMUNITY_ENABLED=os.environ.get('LITMATE_COMMUNITY_ENABLED') == '1',
        LITMATE_PAYMENT_SANDBOX=False,
        LITMATE_SIMULATED_CHECKOUT_ENABLED=os.environ.get('LITMATE_SIMULATED_CHECKOUT_ENABLED') == '1',
        LITMATE_CHECKOUT_TEST_SCENARIOS=os.environ.get('LITMATE_CHECKOUT_TEST_SCENARIOS') == '1', ROOT_URLCONF='reader_accounts.urls',
        INSTALLED_APPS=[*config['INSTALLED_APPS'], 'reader_accounts'],
        DATABASE_ROUTERS=['reader_accounts.router.AccountsRouter'],
        DATABASES={**config['DATABASES'], 'accounts': {
            'ENGINE':'django.db.backends.sqlite3', 'NAME':account,
            'OPTIONS':{'timeout':10, 'transaction_mode':'IMMEDIATE'}, 'TEST':{'DEPENDENCIES':[]}}},
        SESSION_ENGINE='django.contrib.sessions.backends.db', SESSION_COOKIE_NAME='litmate_reader_sessionid',
        SESSION_EXPIRE_AT_BROWSER_CLOSE=False, SESSION_COOKIE_AGE=14*24*3600,
        TIME_ZONE='America/Santiago', LITMATE_AVATAR_ROOT=Path(account).parent/'avatars',
        MIDDLEWARE=[*config['MIDDLEWARE'], 'reader_accounts.identity.VisitorIdentityMiddleware'],
        EMAIL_BACKEND='django.core.mail.backends.dummy.EmailBackend', EMAIL_TIMEOUT=10)
    config['TEMPLATES'] = [{**entry, 'OPTIONS':{**entry['OPTIONS'], 'context_processors':[
        *entry['OPTIONS']['context_processors'], 'reader_accounts.context.presentation']}} for entry in config['TEMPLATES']]
    enabled = os.environ.get('LITMATE_READER_EMAIL_ENABLED') == '1'
    config['LITMATE_READER_EMAIL_ENABLED'] = enabled
    if enabled:
        if not all(config.get(key) for key in ('EMAIL_HOST','EMAIL_HOST_USER','EMAIL_HOST_PASSWORD','EMAIL_USE_TLS')):
            raise ImproperlyConfigured('El correo requiere SMTP autenticado con TLS configurado.')
        # El usuario SMTP no siempre es una dirección remitente (p. ej. Resend).
        # Se admite un remitente aprobado mediante entorno, sin editar .env.
        from django.core.validators import validate_email
        from django.core.exceptions import ValidationError
        sender = os.environ.get('LITMATE_READER_FROM_EMAIL') or config.get('DEFAULT_FROM_EMAIL', '')
        try:
            validate_email(parseaddr(sender)[1])
        except (ValidationError, TypeError, ValueError) as error:
            raise ImproperlyConfigured('Configura un remitente válido y verificado por tu proveedor.') from error
        config['DEFAULT_FROM_EMAIL'] = sender
        config['EMAIL_BACKEND'] = 'django.core.mail.backends.smtp.EmailBackend'
