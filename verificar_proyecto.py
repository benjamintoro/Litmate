"""Pruebas offline con tablas temporales en memoria; jamás migra la base del proyecto."""
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


def main(labels=None):
    from django.conf import settings
    base = Path(__file__).resolve().parent
    os.environ.pop('DJANGO_SETTINGS_MODULE', None)
    # Windows puede restringir %TEMP%; todas las escrituras de prueba quedan en el proyecto.
    temporary_root = base / '.test-tmp'
    temporary_root.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix='litmate-tests-', dir=temporary_root) as media:
        import tempfile
        tempfile.tempdir = media
        settings.configure(
            SECRET_KEY='litmate-tests-only-' + 'x' * 60, DEBUG=True,
            INSTALLED_APPS=['django.contrib.admin', 'django.contrib.auth',
                'django.contrib.contenttypes', 'django.contrib.sessions',
                'django.contrib.messages', 'django.contrib.staticfiles', 'core', 'suscripciones'],
            DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}},
            MIGRATION_MODULES={name: None for name in ['admin', 'auth', 'contenttypes', 'sessions', 'core', 'suscripciones']},
            MIDDLEWARE=['django.middleware.security.SecurityMiddleware',
                'django.contrib.sessions.middleware.SessionMiddleware', 'django.middleware.common.CommonMiddleware',
                'django.middleware.csrf.CsrfViewMiddleware', 'django.contrib.auth.middleware.AuthenticationMiddleware',
                'django.contrib.messages.middleware.MessageMiddleware'],
            ROOT_URLCONF='litmate_project.urls', ALLOWED_HOSTS=['testserver', 'localhost', '127.0.0.1'],
            TEMPLATES=[{'BACKEND': 'django.template.backends.django.DjangoTemplates',
                'DIRS': [base / 'templates'], 'APP_DIRS': True,
                'OPTIONS': {'context_processors': ['django.template.context_processors.request',
                    'django.contrib.auth.context_processors.auth', 'django.contrib.messages.context_processors.messages',
                    'core.context_processors.analytics_processor']}}],
            CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
            SESSION_ENGINE='django.contrib.sessions.backends.db',
            DEFAULT_AUTO_FIELD='django.db.models.BigAutoField', USE_TZ=True, TIME_ZONE='America/Santiago',
            BASE_DIR=base, MEDIA_ROOT=media, MEDIA_URL='/media/', STATIC_URL='/static/',
            LOGIN_URL='login', LOGIN_REDIRECT_URL='index', LOGOUT_REDIRECT_URL='index',
            EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
            DEFAULT_FROM_EMAIL='LitMate <noreply@example.test>',
            PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
            AUTH_PASSWORD_VALIDATORS=[{'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
                {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
                {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'}],
            GOOGLE_BOOKS_API_KEY='', LITMATE_USE_GOOGLE_BOOKS_API=False,
            LITMATE_AI_USE_OPENLIBRARY=True, LITMATE_AI_USE_WEB=False, LITMATE_AI_USE_SEARXNG=True,
            LITMATE_USE_EXISTING_QUOTAS=False, LITMATE_AI_LOCK_BACKEND='cache',
            LITMATE_AI_CATALOG_FALLBACK=False, LITMATE_AI_REQUIRE_BOOK_SOURCES=False,
            LITMATE_ANONYMOUS_AI_DAILY_LIMIT=5,
            LITMATE_FREE_AI_DAILY_LIMIT=10, LITMATE_AI_REQUESTS_PER_MINUTE=20,
            LITMATE_AI_RUNTIME_DB=Path(media) / 'ai-runtime.sqlite3', LITMATE_TTS_ENABLED=False,
            LITMATE_RAG_DB=Path(media) / 'rag.sqlite3',
            LITMATE_KNOWLEDGE_DB=Path(media) / 'knowledge.sqlite3',
            LITMATE_KNOWLEDGE_RAG_DB=Path(media) / 'knowledge-rag.sqlite3',
            PAYMENTS_ALLOW_SIMULATION=False, ALLOW_SOCIAL_DEMO=False, TRUSTED_PROXY_CIDRS=(),
            PAYPAL_ENVIRONMENT='sandbox', MERCADOPAGO_ENVIRONMENT='sandbox', TRANSBANK_ENVIRONMENT='integration',
            PAYPAL_CLIENT_ID='', PAYPAL_CLIENT_SECRET='', MERCADOPAGO_ACCESS_TOKEN='',
            TRANSBANK_COMMERCE_CODE='', TRANSBANK_API_KEY='', MERCADOPAGO_WEBHOOK_SECRET='',
            PAYPAL_CLP_PER_USD='950', PAYMENTS_PUBLIC_BASE_URL='', PAYMENTS_WEBHOOK_TOLERANCE_SECONDS=600,
        )
        import django
        django.setup()
        from django.test.runner import DiscoverRunner
        return DiscoverRunner(verbosity=1, interactive=False).run_tests(labels or ['core'])


if __name__ == '__main__':
    raise SystemExit(1 if main(sys.argv[1:]) else 0)
