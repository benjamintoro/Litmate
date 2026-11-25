"""Ensaya mejoras bibliográficas con evidencia revisada en una copia MySQL."""
from django.db import connections, transaction

from core.models import Autor, Libro
from core.literary_identity import normalize_identity


REVIEWED = (
    ('Infierno', 'Dante Alighieri', 'Poesía',
     'Dante se pierde en una selva oscura y se encuentra con Virgilio, quien se ofrece a guiarlo por el Infierno. '
     'El recorrido lo enfrenta con distintas formas de castigo y con las decisiones de quienes las padecen.',
     'https://www.gutenberg.org/cache/epub/1009/pg1009-images.html'),
    ('Madre misteriosa: la mano que mece la cuna', 'Marilyn Kaye', 'Narrativa juvenil',
     'Una desconocida afirma ser la madre biológica de Amy. Su llegada lleva a Amy a investigar su origen '
     'y a replantearse su relación con Nancy, la mujer que la ha criado.',
     'https://www.casadellibro.com/libro-madre-misteriosa-la-mano-que-mece-la-cuna/9788487482915/762920'),
    ('CCNA 200-301 Hands-on Mastery with Packet Tracer', 'Anthony J. Sequeira, Ronald Wong', 'Packet Tracer',
     'Manual de preparación práctica para CCNA 200-301 mediante ejercicios con el simulador Packet Tracer.',
     'https://www.ciscopress.com/store/ccna-200-301-hands-on-mastery-with-packet-tracer-9780135313091'),
    ('Packet Tracer Network Simulator', 'Jesin A', 'Packet Tracer',
     'Guía para construir y simular topologías de red con Cisco Packet Tracer.',
     'https://www.oreilly.com/library/view/packet-tracer-network/9781782170426/pr01.html'),
    ('Das Nibelungenlied', 'Unknown', 'Poesía épica',
     'Poema épico medieval alemán de autoría incierta. Relata la historia de Sigfrido, Crimilda y los burgundios.',
     'https://www.gutenberg.org/cache/epub/14915/pg14915-images.html'),
)
METADATA_PREFIX = 'Información catalográfica; sin sinopsis ni texto completo.'


def rehearse():
    config = connections['default'].settings_dict
    if config['HOST'] not in {'localhost', '127.0.0.1'} or not config['NAME'].startswith('litmate_catalog_restore_'):
        raise ValueError('Selecciona una restauración local del catálogo.')
    results = []
    with transaction.atomic(using='default'):
        for title, author, genre, description, url in REVIEWED:
            matches = list(Libro.objects.select_for_update().filter(titulo__iexact=title, autor__nombre__iexact=author))
            if len(matches) != 1:
                results.append({'title': title, 'status': 'identity_not_unique', 'matches': len(matches)})
                continue
            book = matches[0]
            fields = {}
            if not book.sinopsis.strip() or book.sinopsis.startswith(METADATA_PREFIX):
                fields['sinopsis'] = description + '\n\nFuente de la descripción: ' + url
            if normalize_identity(book.genero) in {'', 'sin clasificar', 'no informado'}:
                fields['genero'] = genre
            if fields:
                Libro.objects.filter(pk=book.pk).update(**fields)
            results.append({'title': title, 'author': author, 'id': book.pk, 'url': url,
                            'status': 'updated' if fields else 'preserved', 'fields': list(fields)})
        # La portada y la cabecera de esta edición identifican a Mrs. Harley.
        # Cambiar el FK de un libro conserva el registro Unknown de otras obras.
        harley = Libro.objects.select_for_update().filter(
            pk=92705, titulo__startswith='A Week of Instruction and Amusement').first()
        if harley and normalize_identity(harley.autor.nombre) == 'unknown' and 'ebooks/25659' in harley.sinopsis:
            author, _ = Autor.objects.get_or_create(nombre='Mrs. Harley')
            url = 'https://www.gutenberg.org/files/25659/25659-h/25659-h.htm'
            details = ('Relatos y lecciones de historia y geografía destinados a la educación infantil, '
                       'presentados como conversaciones de Mrs. Harley con su hija Anne.')
            Libro.objects.filter(pk=harley.pk).update(autor=author, genero='Literatura infantil',
                                                    sinopsis=details + '\n\nFuente de la descripción: ' + url)
            results.append({'title':harley.titulo,'author':author.nombre,'id':harley.pk,'url':url,
                            'status':'updated','fields':['autor','genero','sinopsis']})
    return results
