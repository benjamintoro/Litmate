"""Compatibilidad del catálogo de lectura entre perfiles web."""
from django.conf import settings


def catalogue_read_only():
    return getattr(settings, 'LITMATE_CATALOGUE_READ_ONLY', getattr(settings, 'LITMATE_DEMO_READ_ONLY', False))
