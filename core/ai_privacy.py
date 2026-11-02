"""Detección compartida de texto aportado que debe permanecer en el servidor."""
import re

# Admite calificativos cortos: fragmento de ficción, pasaje del libro, texto privado.
EXCERPT_MARKER = r'\b(?:fragmento|pasaje|extracto|texto)(?:\s+[\wáéíóúüñÁÉÍÓÚÜÑ-]+){0,6}\s*[:«“\"]\s*'


def excerpt_marker(message):
    return re.search(EXCERPT_MARKER, str(message or ''), re.I)


def _quoted_excerpt(message):
    """Recupera un pasaje cuando el lector lo introduce con una frase natural.

    El marcador estricto exige dos puntos cerca de «fragmento». Muchas personas
    escriben «Lee este fragmento y dime...: \"...\"»; en ese caso el bloque
    entrecomillado es la evidencia y no debe perderse.
    """
    text = str(message or '')
    if not re.search(r'\b(?:lee|analiza|comenta|interpreta|revisa)\s+'
                     r'(?:este|el)\s+(?:fragmento|pasaje|extracto|texto)\b', text, re.I):
        return ''
    quoted = re.search('["\u201c](.{20,}?)["\u201d]', text, re.S)
    return quoted.group(1).strip() if quoted else ''


def user_excerpt(message):
    quoted = _quoted_excerpt(message)
    if quoted:
        return quoted
    match = excerpt_marker(message)
    if not match:
        return ''
    return str(message)[match.end():].strip().rstrip('»”"')
