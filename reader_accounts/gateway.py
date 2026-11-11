import re
from django.conf import settings
from core.web_routes import allowed_methods


UUID_PATH = r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}'


def social_methods(path):
    if path == '/comunidad/' or re.fullmatch(
        rf'/(?:comunidad/obra/\d+|comunidad/publicacion/{UUID_PATH}|'
        rf'lectores/{UUID_PATH}(?:/lista/\d+|/imagen/(?:avatar|portada))?)/', path
    ):
        return {'GET', 'HEAD'}
    if path in {'/cuenta/perfil-literario/', '/cuenta/publicaciones/nueva/'} or re.fullmatch(
        rf'/cuenta/publicaciones/{UUID_PATH}/editar/', path
    ):
        return {'GET', 'HEAD', 'POST'}
    if re.fullmatch(
        rf'/(?:lectores/{UUID_PATH}/seguir|cuenta/compartir/(?:lectura|lista)/\d+|'
        rf'cuenta/publicaciones/{UUID_PATH}/eliminar|comunidad/publicacion/{UUID_PATH}/'
        rf'(?:me-gusta|comentar|reportar|comentario/{UUID_PATH}/(?:eliminar|reportar)))/', path
    ):
        return {'POST'}
    return set()


def reader_methods(path):
    if path == '/api/chat/actual/':
        return {'GET', 'HEAD'}
    if path in {'/api/chat/borrar/', '/api/presencia/'}:
        return {'POST'}
    if path == '/contact/':
        return {'GET', 'HEAD', 'POST'}
    if getattr(settings, 'LITMATE_SIMULATED_CHECKOUT_ENABLED', False):
        if re.fullmatch(r'/suscripciones/(?:checkout/[a-z0-9-]+(?:/metodo)?|pedido/' + UUID_PATH + r'|comprobante/' + UUID_PATH + r')/', path):
            return {'GET', 'HEAD', 'POST'} if path.endswith('/metodo/') else {'GET', 'HEAD'}
        if re.fullmatch(r'/suscripciones/pedido/' + UUID_PATH + r'/(?:confirmar|cancelar)/', path) or path == '/suscripciones/simulada/gratuito/':
            return {'POST'}
        if path == '/suscripciones/simulada/cancelar/':
            return {'GET', 'HEAD', 'POST'}
    if getattr(settings, 'LITMATE_COMMUNITY_ENABLED', False) and (methods := social_methods(path)):
        return methods
    if path in {'/cuenta/pagos/', '/cuenta/biblioteca/', '/cuenta/libro/', '/api/biblioteca/estado/', '/cuenta/avatar/', '/api/listas/obtener/', '/password-reset/done/', '/reset/done/'}:
        return {'GET', 'HEAD'}
    if path in {'/perfil/editar/', '/cuenta/password/', '/cuenta/exportar/'} or re.fullmatch(r'/cuenta/listas/\d+/editar/', path):
        return {'GET', 'HEAD', 'POST'}
    if re.fullmatch(r'/reset/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/', path):
        return {'GET', 'HEAD', 'POST'}
    if path in {'/favoritos/agregar/', '/api/listas/crear/', '/api/listas/agregar-libro/', '/api/estado-lectura/'} or re.fullmatch(
        r'/(?:favoritos/eliminar|api/listas/eliminar|api/listas/quitar-libro)/\d+/', path):
        return {'POST'}
    if path == '/cuenta/activar-gratis/':
        return {'POST'}
    if re.fullmatch(r'/cuenta/lecturas/\d+/nota/', path):
        return {'POST'}
    if path in {'/perfil/', '/suscripciones/mi-suscripcion/'} or re.fullmatch(r'/cuenta/conversaciones/\d+/(?:ver/)?', path):
        return {'GET', 'HEAD'}
    return allowed_methods(path)
