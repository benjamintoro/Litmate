"""Tarjetas del chat construidas con fichas, nunca con HTML o enlaces del modelo."""
from urllib.parse import urlencode, urlsplit
from .literary_ai import clean_text, normalized, safe_source_url

GOOGLE_HOSTS = {'books.google.com', 'books.google.cl', 'books.google.es', 'play.google.com',
                'books.google.com.ar', 'books.google.com.mx', 'books.google.co.uk'}
COVER_HOSTS = GOOGLE_HOSTS | {'books.googleusercontent.com', 'covers.openlibrary.org'}


def allowed_url(value, hosts):
    url = safe_source_url(value)
    return url if url and urlsplit(url).hostname.lower() in hosts else ''


def cover_url(value):
    url = safe_source_url(value)
    if not url:
        return ''
    host = urlsplit(url).hostname.lower()
    return url if host in COVER_HOSTS or host.endswith('.googleusercontent.com') else ''


def build_book_cards(result):
    """Conserva orden de respuesta y exige la misma identidad que en la fuente."""
    if result.status != 'answered':
        return []
    sources = {source.get('id'): source for source in result.sources if isinstance(source, dict)}
    cards, seen = [], set()
    for book in result.books[:5]:
        if not isinstance(book, dict):
            continue
        source = sources.get(book.get('source_id'))
        if not source or source.get('kind') not in {'book', 'excerpt'}:
            continue
        title, author = clean_text(source.get('title'), 220), clean_text(source.get('author'), 220)
        identity = normalized(title), normalized(author)
        if (not title or identity in seen or identity !=
                (normalized(book.get('title')), normalized(book.get('author')))):
            continue
        seen.add(identity)
        links = []
        query = title + (' ' + author if author and author != 'Autor no informado' else '')
        google_url = allowed_url(source.get('url'), GOOGLE_HOSTS)
        google_url = google_url or allowed_url(source.get('preview_url'), GOOGLE_HOSTS)
        original = allowed_url(source.get('url'), {'openlibrary.org', 'www.wikidata.org', 'wikidata.org'})
        if not google_url and original:
            # A catalogue record permits a clearly labelled search, never a
            # fabricated Google volume ID or a claim of product availability.
            google_url = 'https://books.google.com/books?' + urlencode({'q': query})
        if google_url:
            links.append({'label': 'Google Books', 'url': google_url})
        if original:
            links.append({'label': 'Open Library' if urlsplit(original).hostname == 'openlibrary.org'
                          else 'Wikidata', 'url': original})
        links.extend([
            {'label': 'Amazon', 'url': 'https://www.amazon.com/s?' + urlencode({'k': query, 'i': 'stripbooks'})},
            {'label': 'Buscalibre', 'url': 'https://www.buscalibre.cl/libros/search?' + urlencode({'q': query})},
        ])
        # La tarjeta puede recibir una descripción editorial verificada sin
        # un campo synopsis separado. No usar materias ni texto arbitrario.
        synopsis = source.get('synopsis') or (source.get('research_summary')
                    if source.get('synopsis_source_url') else '')
        if not synopsis and source.get('policy') != 'openlibrary-minimal-metadata-v1':
            description = str(source.get('description') or '')
            if (source.get('description_source') and set(str(source.get('source') or '').split(' / ')) & {
                    'Open Library', 'Google Books API', 'Catálogo LitMate'}
                    or 'sinopsis editorial:' in description.lower() and
                    set(str(source.get('source') or '').split(' / ')) & {'Google Books API', 'Open Library'}):
                from .books_google import source_synopsis
                synopsis = source_synopsis(source)
        cards.append({'id': str(source.get('book_id') or source.get('id', '')),
                      'title': title, 'author': author,
                      'synopsis': clean_text(synopsis, 420),
                      'image_url': cover_url(source.get('image_url')),
                      'links': links})
    return cards
