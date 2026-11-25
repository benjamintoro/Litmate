"""Filtro proporcional de términos ofensivos para reseñas y comentarios."""
import re
import unicodedata

from django.conf import settings
from django.core.exceptions import ValidationError


DEFAULT_TERMS = ('mierda', 'puta', 'puto', 'putas', 'putos', 'culiao', 'culiaos',
                 'culiado', 'culiados', 'weon', 'weona', 'weones', 'huevon',
                 'huevona', 'huevones', 'conchetumare', 'ctm', 'maricon',
                 'maricones', 'gilipollas', 'cabron', 'cabrona')


def normalized_words(text):
    text = unicodedata.normalize('NFKD', text.casefold())
    text = ''.join(character for character in text if not unicodedata.combining(character))
    text = text.translate(str.maketrans({'0': 'o', '1': 'i', '3': 'e', '4': 'a', '5': 's', '7': 't', '@': 'a', '$': 's'}))
    words = re.findall(r'[a-z]+', text)
    # Reconoce también intentos sencillos de separar una palabra por puntos o espacios.
    joined = re.sub(r'(?<![a-z])(?:[a-z][\W_]+){2,}[a-z](?![a-z])',
                    lambda match: re.sub('[^a-z]', '', match.group()), text)
    return set(words + re.findall('[a-z]+', joined))


def validate_reader_text(value):
    terms = getattr(settings, 'LITMATE_REVIEW_PROHIBITED_TERMS', DEFAULT_TERMS)
    if normalized_words(value).intersection(term.casefold() for term in terms):
        raise ValidationError('El texto contiene lenguaje ofensivo. Revisa su redacción antes de publicar.',
                              code='offensive_language')
