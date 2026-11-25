"""Pol?tica compartida de rutas web; no habilita autenticaci?n ni publicaci?n."""
import re

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


