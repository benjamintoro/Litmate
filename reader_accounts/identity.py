"""Identidad aleatoria firmada; sin IP, huella de dispositivo o datos personales."""
import hashlib
import secrets
from django.core import signing
from django.conf import settings

COOKIE = 'litmate_visitor_v1'
SALT = 'litmate-reader-visitor-v1'


class VisitorIdentityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        raw = request.COOKIES.get(COOKIE, '')
        try:
            value = signing.loads(raw, salt=SALT)
            if not isinstance(value, str) or len(value) != 43:
                raise signing.BadSignature()
            fresh = False
        except (signing.BadSignature, ValueError, TypeError):
            value, fresh = secrets.token_urlsafe(32), True
        request.reader_identity_established = not fresh
        request.reader_actor = ('u:' + str(request.user.pk) if request.user.is_authenticated
                                else 'g:' + hashlib.sha256(value.encode()).hexdigest())
        response = self.get_response(request)
        if fresh:
            response.set_cookie(COOKIE, signing.dumps(value, salt=SALT), max_age=365 * 24 * 3600,
                                httponly=True, secure=settings.SESSION_COOKIE_SECURE, samesite='Lax')
        return response
