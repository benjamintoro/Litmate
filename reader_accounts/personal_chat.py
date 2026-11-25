"""Consultas privadas de biblioteca sin LLM ni acciones de escritura implícitas."""
import re
import unicodedata
from core.models import LibroFavorito
from .library import own_readings, present_book


def intent(message):
    text = ''.join(c for c in unicodedata.normalize('NFKD', message.casefold()) if not unicodedata.combining(c))
    text = re.sub(r'[^a-z0-9 ]', '', text).strip()
    text = ' '.join(text.split())
    if text in {'recomiendame uno de mis favoritos', 'recomiendame un libro de mis favoritos'}:
        return 'suggest_favorite'
    if text in {'muestrame mi lista de lectura', 'ver mi lista de lectura'}:
        return 'reading_list'
    if re.fullmatch(r'(?:muestrame|dime|ver|cuales son) mis (?:libros )?favoritos', text):
        return 'favorites'
    if text in {'que libros tengo pendientes', 'que tengo pendiente de leer', 'muestrame mis pendientes'}:
        return 'pending'
    if text in {'recomiendame algo de mi lista', 'recomiendame un libro de mi biblioteca', 'que leo de mi lista'}:
        return 'suggest'
    if re.match(r'^(?:elimina|borra|quita|guarda|agrega)\b', text) and re.search(r'\b(?:mis favoritos|mi lista|mi biblioteca)\b', text):
        return 'manual_action'
    return None


def answer(message, user):
    kind = intent(message)
    if kind is None:
        return None
    if not user.is_authenticated:
        return {'response': 'Inicia sesión para consultar tu biblioteca privada. Encontrarás tus libros en Mi cuenta → Mi biblioteca.', 'books': []}
    if kind == 'manual_action':
        return {'response': 'Puedes gestionar tus libros desde Mi cuenta → Mi biblioteca. No he modificado ni eliminado nada; utiliza sus controles para confirmar la acción.', 'books': []}
    if kind in {'favorites', 'suggest_favorite'}:
        rows = LibroFavorito.objects.filter(usuario=user).order_by('-pk')
        introduction = 'Estos son algunos de tus favoritos guardados:'
        if kind == 'suggest_favorite':
            introduction = 'Puedes retomar este libro que guardaste entre tus favoritos:'
    else:
        rows = own_readings(user)
        if kind != 'reading_list':
            rows = rows.filter(estado_lectura='por_leer')
        introduction = 'Estos son algunos de los libros que tienes pendientes:'
        if kind == 'reading_list':
            introduction = 'Estos son algunos de los libros de tu organizador de lectura:'
        if kind == 'suggest':
            introduction = 'Te propongo empezar por este libro que guardaste como pendiente:'
    books = [present_book(book) for book in rows[:(1 if kind in {'suggest', 'suggest_favorite'} else 6)]]
    if not books:
        return {'response': 'Todavía no tienes libros en esa sección de tu biblioteca. Puedes añadirlos desde las fichas del catálogo.', 'books': []}
    # Sólo los datos guardados por ese propietario, sin fabricar sinopsis,
    # convertir notas privadas en evidencia global ni enviarlas al modelo.
    return {'response': introduction + '\n\n' + '\n'.join(
        f'{i}. {book.titulo} — {book.autores or "Autor no informado"}' for i, book in enumerate(books, 1)),
        'books': [{'id': b.google_id, 'title': b.titulo, 'author': b.autores or 'Autor no informado',
                   'image_url': b.display_cover, 'synopsis': '', 'links': []} for b in books]}


def remember_private_turn(request, operation, message, personal):
    """Reutiliza historial privado, sin observar/entrenar/indexar la biblioteca."""
    import copy
    from types import SimpleNamespace
    from django.db import transaction
    from core import literary_ai_views
    from core.literary_focus import remember_focus
    state = copy.deepcopy(request.session.get(literary_ai_views.HISTORY_KEY, {}))
    turn = {'accepted': True, 'question': message, 'answer': personal['response'],
        'sources': [], 'books': personal['books'], 'basis': 'personal_library', 'intent': 'library'}
    remember_focus(state, turn)
    state['turns'] = (state.get('turns', []) + [turn])[-literary_ai_views.MAX_HISTORY:]
    if request.user.is_authenticated:
        request.reader_operation_id = operation.pk
        result = literary_ai_views.ChatResult(text=personal['response'], status='answer', remember=True,
            books=personal['books'], basis='personal_library', intent='library')
        with transaction.atomic(using='accounts'):
            literary_ai_views.persist_turn_records(request, state, message, result, 0,
                SimpleNamespace(usage={}, provider='private_library', calls=0))
    request.session[literary_ai_views.HISTORY_KEY] = state
    request.session.modified = True
