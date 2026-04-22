# litmate_project/core/chatbot_data.py
import re

# Patrones de conversación social
SOCIAL_PATTERNS = {
    'saludo': {
        'pattern': r'\b(hola|buenos|buenos días|buenas tardes|buenas noches|hi)\b',
        'responses': [
            "¡Hola! ¿En qué puedo ayudarte con libros?",
            "¡Hola! Estoy aquí para recomendarte libros.",
            "¡Hola! ¿Qué libro buscas?"
        ]
    },
    'gracias': {
        'pattern': r'\b(gracias|agradec|thanks)\b',
        'responses': [
            "¡De nada! Me encanta ayudarte con libros.",
            "¡Es un placer! Vuelve cuando quieras.",
            "¡Me alegra haberte ayudado!"
        ]
    },
    'como_estas': {
        'pattern': r'\b(cómo estás|como estas|qué tal|que tal|how are you)\b',
        'responses': [
            "¡Muy bien, gracias! Feliz de ayudarte a encontrar tu próxima lectura.",
            "¡Excelente! Estoy aquí para ayudarte con libros.",
            "¡Genial! ¿Qué necesitas?"
        ]
    },
    'despedida': {
        'pattern': r'\b(adios|adiós|chao|hasta luego|bye|nos vemos)\b',
        'responses': [
            "¡Hasta pronto! Que disfrutes de tu lectura.",
            "¡Nos vemos! Vuelve cuando quieras.",
            "¡Adiós! Que disfrutes."
        ]
    },
    'nombre': {
        'pattern': r'\b(cómo te llamas|como te llamas|cuál es tu nombre|quién eres)\b',
        'responses': [
            "Me llamo LitMate, tu asistente de libros.",
            "Soy LitMate, tu compañero de lectura."
        ]
    }
}

# Patrones de preguntas sobre libros
BOOK_QUERY_PATTERNS = {
    'personajes': {
        'pattern': r'\b(personajes?|protagonistas?|quienes? aparecen?)\b',
        'response_template': "Los personajes principales de {title} son: {details}."
    },
    'trama': {
        'pattern': r'\b(trama|argumento|de que trata|historia|sinopsis)\b',
        'response_template': "La historia de {title} trata sobre: {details}."
    },
    'autor': {
        'pattern': r'\b(autor|escritor|quien escribio|escribió|quién escribió)\b',
        'response_template': "{title} fue escrito por {details}."
    },
    'opiniones': {
        'pattern': r'\b(opiniones|reseñas|que tal es|vale la pena)\b',
        'response_template': "Sobre {title}: {details}."
    },
    'serie': {
        'pattern': r'\b(serie|saga|continuación|orden|colección)\b',
        'response_template': "En cuanto a la serie de {title}: {details}."
    },
    'link': {
        'pattern': r'\b(link|enlace|donde|dónde|comprar|lectura|leerlo)\b',
        'response_template': "📚 Leer en Google Books: {link}"
    }
}

# La información de libros ahora se obtiene dinámicamente de Google Books API
# Esto permite que el chatbot funcione con cualquier libro sin necesidad de actualizaciones manuales

# Patrones de Géneros
GENRE_PATTERNS = {
    'fantasía': r'\b(narnia|tolkien|harry potter|fantasia|fantasía|dragones|magia)\b',
    'ciencia ficción': r'\b(sci-?fi|ciencia.?ficcion|espacio|futuro|robots?)\b',
    'misterio': r'\b(misterio|detective|crimen|thriller|suspense?)\b',
    'romance': r'\b(romance?|amor|pareja|romántico)\b',
    'juvenil': r'\b(juvenil|jóvenes?|adolescentes?|young.?adult|ya)\b',
    'infantil': r'\b(niños?|infantil|children|kids)\b'
}

def detect_genre(text):
    """Detecta géneros mencionados en el texto."""
    if not isinstance(text, str):
        return []
    text = text.lower()
    return [genre for genre, pattern in GENRE_PATTERNS.items() if re.search(pattern, text, re.I)]
