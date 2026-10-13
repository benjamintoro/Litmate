"""Detección compartida de texto aportado que debe permanecer en el servidor."""
import re

# Admite calificativos cortos: fragmento de ficción, pasaje del libro, texto privado.
EXCERPT_MARKER = r'\b(?:fragmento|pasaje|extracto|texto)(?:\s+[\wáéíóúüñÁÉÍÓÚÜÑ-]+){0,6}\s*[:«“\"]\s*'


def excerpt_marker(message):
    return re.search(EXCERPT_MARKER, str(message or ''), re.I)


def user_excerpt(message):
    match = excerpt_marker(message)
    if not match:
        return ''
    return str(message)[match.end():].strip().rstrip('»”"')
