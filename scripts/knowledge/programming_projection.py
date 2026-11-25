"""Proyección aditiva del ledger oficial al catálogo visible existente."""
from contextlib import closing
import json

from django.db import connection, transaction
from django.utils.text import slugify

from core.bibliographic_repository import digest
from core.knowledge_models import KBRecord
from core.literary_acquisition import _connect, _book_projection
from core.literary_genres import classify_categories
from core.models import Autor, Genero, Libro


def materialize_programming(ledger, *, maximum=250):
    """No actualiza libros existentes; conserva los IDs y la evidencia de origen."""
    if not 1 <= maximum <= 500:
        raise ValueError('Lote de 1 a 500 obras.')
    if (connection.vendor != 'mysql' or connection.settings_dict.get('HOST') not in {'localhost','127.0.0.1'}
            or not (connection.settings_dict['NAME'] == 'litmate_db'
                    or connection.settings_dict['NAME'].startswith('litmate_catalog_restore_'))):
        raise ValueError('Selecciona explícitamente el catálogo local o su restauración aislada.')
    result = {'created_books': 0, 'existing_books': 0, 'unresolved': 0, 'not_programming': 0, 'books': []}
    with closing(_connect(ledger)) as source:
        records = source.execute("SELECT r.record FROM acquisition_records r JOIN acquisition_outbox o USING(record_id) "
            "WHERE r.kind='work' AND o.state IN ('done','pending') ORDER BY r.record_id LIMIT ?", (maximum,)).fetchall()
        for row in records:
            raw = json.loads(row[0])
            identity = _book_projection(source, raw)
            status = KBRecord.objects.filter(pk=digest('openlibrary', raw['external_id']), status='source_metadata').exists()
            if not identity or not status:
                result['unresolved'] += 1
                continue
            book, _ = identity
            categories = book.get('categories', [])
            if 'programming' not in classify_categories(categories):
                result['not_programming'] += 1
                continue
            name = book['author']
            if not name or len(name) > 200:
                result['unresolved'] += 1
                continue
            with transaction.atomic():
                existing = list(Libro.objects.select_related('autor').filter(
                    titulo=book['title'], autor__nombre=name)[:2])
                if len(existing) > 1:
                    result['unresolved'] += 1
                    continue
                if existing:
                    current = existing[0]
                    result['existing_books'] += 1
                else:
                    author = Autor.objects.filter(nombre=name).order_by('pk').first()
                    if author is None:
                        author = Autor.objects.create(nombre=name)
                    language = {'eng':'en','spa':'es','fra':'fr','fre':'fr','deu':'de','ger':'de',
                                'por':'pt','ita':'it'}.get(book.get('language'), book.get('language') or 'und')
                    provenance = ('Información catalográfica; sin sinopsis ni texto completo. '
                                  'Fuente: ' + book['url'] + '\nMaterias originales: ' + '; '.join(categories))
                    current = Libro.objects.create(titulo=book['title'], autor=author, genero='Programación',
                        idioma=language, sinopsis=provenance, portada_url=None)
                    for category in dict.fromkeys(['Programación', *categories]):
                        if not 1 <= len(category) <= 100:
                            continue
                        category_slug = slugify(category)[:75] or 'materia'
                        category_slug += '-' + digest(category)[:12]
                        genre, _ = Genero.objects.get_or_create(nombre=category, defaults={'slug':category_slug})
                        current.generos.add(genre)
                    result['created_books'] += 1
            result['books'].append({'catalogue_id': current.pk, 'title': current.titulo,
                'author': current.autor.nombre, 'source_url': book['url'], 'source_id': raw['external_id'],
                'original_categories': categories, 'full_text_imported': False})
    return result
