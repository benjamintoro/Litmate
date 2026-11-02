import re
from core.demo_gateway import allowed_methods


def reader_methods(path):
    if path == '/cuenta/activar-gratis/':
        return {'POST'}
    if path in {'/perfil/', '/suscripciones/mi-suscripcion/'} or re.fullmatch(r'/cuenta/conversaciones/\d+/', path):
        return {'GET', 'HEAD'}
    return allowed_methods(path)
