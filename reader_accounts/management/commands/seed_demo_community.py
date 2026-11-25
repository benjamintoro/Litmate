"""Añade una comunidad ficticia identificada, sin escribir sobre cuentas existentes."""
from uuid import NAMESPACE_URL, uuid5

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from reader_accounts.models import Follow, PostLike, SocialComment, SocialPost, SocialProfile

READERS = [
    'Alba', 'Mateo', 'Clara', 'Tomás', 'Elena', 'Nicolás', 'Lucía', 'Gabriel',
    'Valentina', 'Julián', 'Inés', 'Bruno', 'Marina', 'Diego', 'Emilia', 'Simón',
    'Camila', 'Felipe', 'Violeta', 'Andrés', 'Antonia', 'Martín', 'Isidora',
    'Lucas', 'Florencia', 'Rafael', 'Josefina', 'Daniel', 'Amanda', 'Samuel',
]
DISCUSSIONS = [
    ('Frankenstein', 'Mary Shelley', 'Me interesa cómo la novela plantea la responsabilidad de quien crea algo que luego no sabe cuidar. ¿Qué decisión del protagonista les hizo pensar más?'),
    ('La metamorfosis', 'Franz Kafka', 'La reacción de la familia me dejó pensando tanto como la transformación. ¿La releerían desde la mirada de la hermana?'),
    ('Orgullo y prejuicio', 'Jane Austen', 'Disfruté cómo los primeros juicios cambian al conocer mejor a los personajes. ¿Con qué personaje cambiaron más de opinión?'),
    ('Don Quijote', 'Miguel de Cervantes', 'Me gusta el contraste entre los ideales de don Quijote y la mirada de Sancho. Busco una edición con buenas notas para continuar la lectura.'),
    ('La guerra de los mundos', 'H. G. Wells', 'Me atrae el punto de vista humano ante una amenaza desconocida. ¿Qué otras novelas de contacto extraterrestre recomendarían?'),
    ('El hobbit', 'J. R. R. Tolkien', 'Estoy disfrutando el tono de aventura y la evolución de Bilbo. Me gustaría conversar sobre viajes literarios que empiezan con pocas ganas de salir de casa.'),
    ('1984', 'George Orwell', 'La relación entre lenguaje y poder me parece una buena puerta para debatir esta novela. Prefiero conversar sin revelar el final.'),
    ('Jane Eyre', 'Charlotte Brontë', 'La voz narrativa me hizo seguir leyendo. ¿Suelen fijarse primero en la historia o en la forma en que el personaje cuenta su vida?'),
    ('Drácula', 'Bram Stoker', 'El formato de diarios y cartas cambia mucho el ritmo de la lectura. ¿Qué otras novelas construyen su historia con documentos?'),
    ('Alicia en el país de las maravillas', 'Lewis Carroll', 'Me divierte leer sus juegos de lógica en voz alta. ¿Qué escenas les gustaría comentar en un club de lectura?'),
]
RESPONSES = [
    'Me sumo a la conversación. También me interesa cómo cambia nuestra mirada al releer una obra.',
    'Buena pregunta. Para el club de lectura propondría elegir un pasaje y comparar nuestras interpretaciones sin adelantar el final.',
    'Me dieron ganas de añadirlo a mi lista de pendientes. ¿Recomiendan una traducción o edición en particular?',
    'La perspectiva del narrador me parece importante para esa discusión. Me gustaría escuchar otras lecturas.',
    'Gracias por abrir este hilo. Disfruto cuando una lectura deja preguntas que podemos conversar entre todos.',
]


def seed_demo():
    profiles = []
    with transaction.atomic(using='accounts'):
        for index, name in enumerate(READERS, 1):
            username = f'comunidad_demo_{index:02}'
            alias = f'demo_lector_{index:02}'
            user = User.objects.filter(username=username).first()
            if user and not SocialProfile.objects.filter(user=user, alias=alias,
                    biography__startswith='Perfil ficticio').exists():
                raise CommandError('Un identificador está ocupado. Se conserva la cuenta existente.')
            if user is None:
                user = User(username=username, email=f'lector{index:02}@example.invalid')
                user.set_unusable_password()
                user.save()
            profile, _ = SocialProfile.objects.get_or_create(user=user, defaults={
                'alias': alias, 'display_name': name + ' · Demo', 'published': True,
                'biography': 'Perfil ficticio creado para la demostración académica de LitMate.',
                'genres': ['Fantasía y aventuras', 'Clásicos y narrativa', 'Ciencia ficción'][index % 3],
            })
            profiles.append(profile)
        for index, profile in enumerate(profiles):
            title, author, opinion = DISCUSSIONS[index % len(DISCUSSIONS)]
            variations = ['', '\nMe gustaría leer las opiniones de quienes lo terminaron.',
                          '\nLo propongo como próxima lectura compartida.']
            post, _ = SocialPost.objects.get_or_create(author=profile,
                submission_id=uuid5(NAMESPACE_URL, f'litmate-demo-community/post/{index}'), defaults={
                    'body': f'{title} — {author}\n\n{opinion}' + variations[index // 10],
                    'visibility': SocialPost.Visibility.PUBLIC, 'allow_comments': True,
                })
            for offset in (1, 2):
                commenter = profiles[(index + offset) % len(profiles)]
                SocialComment.objects.get_or_create(post=post, author=commenter,
                    submission_id=uuid5(NAMESPACE_URL, f'litmate-demo-community/comment/{index}/{offset}'),
                    defaults={'body': RESPONSES[(index + offset) % len(RESPONSES)]})
                Follow.objects.get_or_create(follower=commenter, target=profile)
            for offset in (1, 3, 5):
                PostLike.objects.get_or_create(post=post, author=profiles[(index + offset) % len(profiles)])
    return {'synthetic_profiles': len(profiles),
        'posts': SocialPost.objects.filter(author__in=profiles).count(),
        'comments': SocialComment.objects.filter(author__in=profiles).count(),
        'likes': PostLike.objects.filter(author__in=profiles).count()}


class Command(BaseCommand):
    help = 'Crea 30 perfiles Demo, publicaciones y conversaciones ficticias identificadas.'

    def add_arguments(self, parser):
        parser.add_argument('--autorizar-datos-demo', action='store_true')

    def handle(self, *args, **options):
        if not options['autorizar_datos_demo']:
            raise CommandError('Confirma la creación de datos ficticios con --autorizar-datos-demo.')
        self.stdout.write(str(seed_demo()))
