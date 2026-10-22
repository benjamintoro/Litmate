"""Normalización de peticiones, no de títulos ni de evidencia del lector.

Solo corrige formas frecuentes de las órdenes. El mensaje original siempre se
conserva para la generación, la auditoría y la memoria; no se corrigen pasajes.
"""
import re
import unicodedata


def request_text(message):
    value = ''.join(char for char in unicodedata.normalize('NFKD', str(message or ''))
                    if not unicodedata.combining(char)).casefold()
    # No reinterpretar palabras dentro de un título o texto proporcionado.
    if re.search(r'[«»“”"\n]', value):
        return value
    value = re.sub(r'^\s*[¡¿]*(?:hola|holaa|buenas|buenos dias|buenas tardes|buenas noches|oye|hey)'
                   r'\b[\s,!.:;]*(?:litmate[\s,!.:;]*)?', '', value)
    value = re.sub(r'\b(?:recomendame|recomiendame|recomiendeme|recomiendanos|'
                   r'recomiendemen|recomiendaman|recomiedame|recominedame)\b', 'recomiendame', value)
    value = re.sub(r'\b(?:porfa|porfis|porfavor)\b', 'por favor', value)
    return re.sub(r'\s+', ' ', value).strip()
