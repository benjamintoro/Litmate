"""Reseñas académicas identificadas; nunca adopta cuentas ni contenido ajenos."""
from uuid import NAMESPACE_URL, uuid5

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Libro
from reader_accounts.content_policy import validate_reader_text
from reader_accounts.models import PostLike, SocialComment, SocialPost, SocialProfile

READERS = ['Alba', 'Mateo', 'Clara', 'Tomás', 'Elena', 'Nicolás', 'Lucía', 'Gabriel',
           'Valentina', 'Julián', 'Inés', 'Bruno', 'Marina', 'Diego', 'Emilia', 'Simón',
           'Camila', 'Felipe', 'Violeta', 'Andrés']
REVIEWS = [
    ('1984', 'George Orwell', 5, 'El vínculo entre lenguaje, vigilancia y poder invita a leer con atención. Una buena propuesta para discutir la libertad y el control de la información, sin adelantar el desenlace.'),
    ('Orgullo y Prejuicio', 'Jane Austen', 4, 'La ironía y los cambios de percepción entre los personajes sostienen el interés. Lo propondría para conversar sobre prejuicios, expectativas sociales y primeras impresiones.'),
    ('Don Quijote de la Mancha', 'Miguel de Cervantes', 5, 'El contraste entre los ideales de don Quijote y la mirada de Sancho abre muchas lecturas. Recomendaría una edición anotada para acompañar el lenguaje y las referencias.'),
    ('El Hobbit', 'J.R.R. Tolkien', 4, 'La aventura de Bilbo combina descubrimiento, ingenio y humor. Su viaje permite conversar sobre cómo cambia un personaje cuando abandona la seguridad de lo conocido.'),
    ('Dune', 'Frank Herbert', 5, 'La combinación de ecología, política y poder exige atención y recompensa una lectura pausada. El mundo construido es uno de sus grandes atractivos; conviene familiarizarse con sus términos.'),
    ('Fahrenheit 451', 'Ray Bradbury', 5, 'Una novela breve que deja preguntas amplias sobre censura, lectura y pensamiento crítico. Su fuerza está en las imágenes y en las conversaciones que puede abrir después de leerla.'),
    ('El principito', 'Antoine de Saint-Exupéry', 4, 'La sencillez del relato permite volver a sus preguntas sobre el afecto y la responsabilidad. Funciona bien como lectura compartida porque admite interpretaciones distintas según la edad.'),
    ('Fundación', 'Isaac Asimov', 4, 'La perspectiva histórica y los dilemas de organización social resultan estimulantes. El peso de las ideas y de los conflictos colectivos puede atraer especialmente a lectores de ciencia ficción.'),
    ('Cien años de soledad', 'Gabriel García Márquez', 5, 'La memoria familiar, el paso del tiempo y la repetición dan forma a una lectura muy rica. Los nombres requieren atención; un mapa de personajes puede ayudar sin revelar acontecimientos.'),
    ('La sombra del viento', 'Carlos Ruiz Zafón', 4, 'La atmósfera de Barcelona y el misterio alrededor de los libros sostienen la curiosidad. Es una propuesta atractiva para quienes disfrutan relatos donde la lectura forma parte de la propia historia.'),
]
COMMENTS = [
    ('¿Qué aspecto elegirían para conversar en un club de lectura: el lenguaje o las decisiones de los personajes?',
     'Empezaría por un pasaje breve y después compararía nuestras interpretaciones, sin revelar el final.'),
    ('Me interesa la idea de leerlo con calma. ¿Les parece útil acompañarlo con notas de contexto?',
     'Las notas pueden ayudar, aunque prefiero consultarlas después de cada capítulo para mantener el ritmo.'),
    ('Lo añadiría a una lista de lectura compartida. ¿Qué pregunta propondrían para comenzar?',
     'Podríamos conversar sobre qué cambia en nuestra forma de mirar al protagonista a medida que avanza el relato.'),
]
MARKER = 'Perfil ficticio de demostración de reseñas LitMate (20261118).'


def seed_demo_reviews():
    # Verificar todos los vínculos antes de escribir una cuenta.
    books = []
    for title, author, _, body in REVIEWS:
        matches = list(Libro.objects.filter(titulo=title, autor__nombre=author)[:2])
        if len(matches) != 1:
            raise CommandError('El catálogo debe identificar de forma única: ' + title)
        books.append(matches[0])
        validate_reader_text(body)
    with transaction.atomic(using='accounts'):
        profiles = []
        for index, name in enumerate(READERS, 1):
            username, alias = f'resenas_demo_{index:02}', f'resena-demo-{index:02}'
            user = User.objects.filter(username=username).first()
            if user and (user.has_usable_password() or not SocialProfile.objects.filter(
                    user=user, alias=alias, biography=MARKER).exists()):
                raise CommandError('Identificador ocupado; no se modifica la cuenta existente.')
            if user is None:
                user = User(username=username, email=f'resena{index:02}@example.invalid')
                user.set_unusable_password()
                user.save()
            profile, _ = SocialProfile.objects.get_or_create(user=user, defaults={
                'alias': alias, 'display_name': name + ' · Demo', 'biography': MARKER,
                'published': True, 'genres': 'Lectura y conversación literaria'})
            profiles.append(profile)
        posts = []
        for index, ((_, _, stars, body), book) in enumerate(zip(REVIEWS, books)):
            post, _ = SocialPost.objects.get_or_create(author=profiles[index],
                submission_id=uuid5(NAMESPACE_URL, f'litmate/reviews-demo-20261118/{index}'), defaults={
                    'body': 'Reseña de demostración · Opinión ficticia para mostrar LitMate.\n\n' + body,
                    'is_review': True, 'rating': stars, 'catalogue_id': book.pk,
                    'visibility': SocialPost.Visibility.PUBLIC, 'allow_comments': True})
            posts.append(post)
            for offset in (0, 1):
                # Los diez lectores adicionales también participan, sin suplantar identidades.
                commenter = profiles[10 + (index + offset) % 10]
                comment = 'Comentario de demostración. ' + COMMENTS[index % len(COMMENTS)][offset]
                validate_reader_text(comment)
                SocialComment.objects.get_or_create(post=post, author=commenter,
                    submission_id=uuid5(NAMESPACE_URL, f'litmate/reviews-demo-comment/{index}/{offset}'),
                    defaults={'body': comment})
            for offset in (2, 4, 6):
                PostLike.objects.get_or_create(post=post, author=profiles[(index + offset) % 20])
        return {'demo_profiles': len(profiles), 'reviews': len(posts),
                'comments': SocialComment.objects.filter(post__in=posts).count(),
                'hearts': PostLike.objects.filter(post__in=posts).count(),
                'all_content_identified_as_demo': True, 'online_presence_faked': False}


class Command(BaseCommand):
    help = 'Crea 10 reseñas, 20 comentarios y 30 corazones con 20 perfiles ficticios identificados.'

    def add_arguments(self, parser):
        parser.add_argument('--autorizar-datos-demo', action='store_true')

    def handle(self, *args, **options):
        if not options['autorizar_datos_demo']:
            raise CommandError('La creación exige --autorizar-datos-demo.')
        import json
        self.stdout.write(json.dumps(seed_demo_reviews(), ensure_ascii=False))
