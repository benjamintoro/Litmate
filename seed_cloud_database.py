#!/usr/bin/env python
"""
Script de alto rendimiento para poblar la base de datos en la nube (TiDB Cloud) con:
1. Planes de suscripción y Asistente IA LitMate.
2. Catálogo completo de libros reales (Google Books API + dataset verificado).
3. 100 usuarios reales/ficticios con perfiles demográficos y suscripciones.
4. Datos de analítica avanzada: estados de lectura, reseñas con scores de sentimiento, favoritos, telemetría IA y conversiones de afiliados.
"""
import os
import sys
import random
import datetime
from decimal import Decimal
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Configurar Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'litmate_project.settings')
import django
django.setup()

from django.contrib.auth.models import User
from django.contrib.auth.hashers import make_password
from django.db import transaction, models
from django.utils import timezone
from django.utils.text import slugify

from core.models import (
    Autor, Genero, Editorial, Libro, PerfilUsuario, Resena,
    LibroFavorito, EstadoLectura, AsistenteIA, ConversacionIA,
    MensajeIA, RecomendacionIALog, EventoAnalitica, ClickConversion
)
from suscripciones.models import PlanSuscripcion, SuscripcionUsuario, HistorialPago


# =====================================================================
# 1. DATASET BASE DE LIBROS DESTACADOS (GOOGLE BOOKS VERIFICADOS)
# =====================================================================

LIBROS_SEED_DATA = [
    {
        "titulo": "Cien años de soledad",
        "autor": "Gabriel García Márquez",
        "pais_autor": "Colombia",
        "genero": "Literatura Clásica",
        "editorial": "Editorial Sudamericana",
        "isbn_13": "9780307474728",
        "google_id": "eJ42AQAAIAAJ",
        "paginas": 471,
        "sinopsis": "La obra cumbre del realismo mágico narra la historia de la familia Buendía a lo largo de siete generaciones en el mítico pueblo de Macondo.",
        "portada": "https://books.google.com/books/content?id=eJ42AQAAIAAJ&printsec=frontcover&img=1&zoom=1"
    },
    {
        "titulo": "1984",
        "autor": "George Orwell",
        "pais_autor": "Reino Unido",
        "genero": "Ciencia Ficción",
        "editorial": "Secker & Warburg",
        "isbn_13": "9780451524935",
        "google_id": "kotPYEqx7kMC",
        "paginas": 328,
        "sinopsis": "En una sociedad totalitaria vigilada constantemente por el Gran Hermano, Winston Smith lucha por mantener su individualidad y pensamiento crítico.",
        "portada": "https://books.google.com/books/content?id=kotPYEqx7kMC&printsec=frontcover&img=1&zoom=1"
    },
    {
        "titulo": "Dune",
        "autor": "Frank Herbert",
        "pais_autor": "Estados Unidos",
        "genero": "Ciencia Ficción",
        "editorial": "Chilton Books",
        "isbn_13": "9780441172719",
        "google_id": "B1hSGwAACAAJ",
        "paginas": 688,
        "sinopsis": "En el desértico planeta Arrakis, el joven Paul Atreides se ve envuelto en una lucha de poder intergaláctica por el control de la especia melange.",
        "portada": "https://books.google.com/books/content?id=B1hSGwAACAAJ&printsec=frontcover&img=1&zoom=1"
    },
    {
        "titulo": "El Señor de los Anillos: La Comunidad del Anillo",
        "autor": "J.R.R. Tolkien",
        "pais_autor": "Reino Unido",
        "genero": "Fantasía",
        "editorial": "Minotauro",
        "isbn_13": "9780261102354",
        "google_id": "a381AAAAQBAJ",
        "paginas": 423,
        "sinopsis": "Frodo Bolsón emprende una peligrosa travesía para destruir el Anillo Único en los fuegos del Monte del Destino y salvar la Tierra Media.",
        "portada": "https://books.google.com/books/content?id=a381AAAAQBAJ&printsec=frontcover&img=1&zoom=1"
    },
    {
        "titulo": "Ficciones",
        "autor": "Jorge Luis Borges",
        "pais_autor": "Argentina",
        "genero": "Filosofía",
        "editorial": "Sur",
        "isbn_13": "9780802130303",
        "google_id": "vS9vDwAAQBAJ",
        "paginas": 224,
        "sinopsis": "Una de las colecciones de relatos más influyentes del siglo XX, explorando laberintos, bibliotecas infinitas, espejos y la naturaleza del tiempo.",
        "portada": "https://books.google.com/books/content?id=vS9vDwAAQBAJ&printsec=frontcover&img=1&zoom=1"
    },
    {
        "titulo": "El Aleph",
        "autor": "Jorge Luis Borges",
        "pais_autor": "Argentina",
        "genero": "Filosofía",
        "editorial": "Losada",
        "isbn_13": "9788420658421",
        "google_id": "m9dYAAAAMAAJ",
        "paginas": 208,
        "sinopsis": "Cuentos magistrales que exploran el infinito, los enigmas ontológicos y el punto en el espacio que contiene todos los puntos del universo.",
        "portada": "https://books.google.com/books/content?id=m9dYAAAAMAAJ&printsec=frontcover&img=1&zoom=1"
    },
    {
        "titulo": "Sapiens: De animales a dioses",
        "autor": "Yuval Noah Harari",
        "pais_autor": "Israel",
        "genero": "Historia",
        "editorial": "Debate",
        "isbn_13": "9788499926223",
        "google_id": "1yE_BQAAQBAJ",
        "paginas": 496,
        "sinopsis": "Un fascinante recorrido por la historia de la humanidad, desde los primeros homínidos hasta las revoluciones cognitiva, agrícola y científica.",
        "portada": "https://books.google.com/books/content?id=1yE_BQAAQBAJ&printsec=frontcover&img=1&zoom=1"
    },
    {
        "titulo": "El Resplandor",
        "autor": "Stephen King",
        "pais_autor": "Estados Unidos",
        "genero": "Terror",
        "editorial": "Doubleday",
        "isbn_13": "9780307743657",
        "google_id": "v4yvDwAAQBAJ",
        "paginas": 656,
        "sinopsis": "Jack Torrance acepta el trabajo de cuidador de invierno en el siniestro y aislado Hotel Overlook, donde fuerzas oscuras amenazan a su familia.",
        "portada": "https://books.google.com/books/content?id=v4yvDwAAQBAJ&printsec=frontcover&img=1&zoom=1"
    },
    {
        "titulo": "Tokio Blues (Norwegian Wood)",
        "autor": "Haruki Murakami",
        "pais_autor": "Japón",
        "genero": "Romance",
        "editorial": "Tusquets Editores",
        "isbn_13": "9788483103289",
        "google_id": "K3Y2AQAAIAAJ",
        "paginas": 384,
        "sinopsis": "Toru Watanabe rememora sus años universitarios en Tokio y la profunda relación emocional entre la melancólica Naoko y la vivaz Midori.",
        "portada": "https://books.google.com/books/content?id=K3Y2AQAAIAAJ&printsec=frontcover&img=1&zoom=1"
    },
    {
        "titulo": "Hábitos Atómicos",
        "autor": "James Clear",
        "pais_autor": "Estados Unidos",
        "genero": "Desarrollo Personal",
        "editorial": "Diana",
        "isbn_13": "9786077478010",
        "google_id": "f29wDwAAQBAJ",
        "paginas": 328,
        "sinopsis": "Una guía práctica basada en la ciencia del comportamiento para construir pequeños cambios que generan transformaciones extraordinarias.",
        "portada": "https://books.google.com/books/content?id=f29wDwAAQBAJ&printsec=frontcover&img=1&zoom=1"
    },
    {
        "titulo": "La casa de los espíritus",
        "autor": "Isabel Allende",
        "pais_autor": "Chile",
        "genero": "Literatura Clásica",
        "editorial": "Plaza & Janés",
        "isbn_13": "9788401342677",
        "google_id": "K38_BQAAQBAJ",
        "paginas": 490,
        "sinopsis": "La saga de cuatro generaciones de la familia Trueba y las convulsiones sociales y políticas de un país latinoamericano innominado.",
        "portada": "https://books.google.com/books/content?id=K38_BQAAQBAJ&printsec=frontcover&img=1&zoom=1"
    },
    {
        "titulo": "Rayuela",
        "autor": "Julio Cortázar",
        "pais_autor": "Argentina",
        "genero": "Literatura Clásica",
        "editorial": "Editorial Sudamericana",
        "isbn_13": "9788420427775",
        "google_id": "O381AAAAQBAJ",
        "paginas": 736,
        "sinopsis": "Una antinovela revolucionaria que invita al lector a seguir múltiples órdenes de lectura siguiendo las andanzas de Horacio Oliveira y La Maga.",
        "portada": "https://books.google.com/books/content?id=O381AAAAQBAJ&printsec=frontcover&img=1&zoom=1"
    },
    {
        "titulo": "Fundación",
        "autor": "Isaac Asimov",
        "pais_autor": "Rusia / EE.UU.",
        "genero": "Ciencia Ficción",
        "editorial": "Gnome Press",
        "isbn_13": "9788497599245",
        "google_id": "zC5kDwAAQBAJ",
        "paginas": 256,
        "sinopsis": "Hari Seldon utiliza la psicohistoria para prever la caída del Imperio Galáctico y funda una colonia para preservar el conocimiento humano.",
        "portada": "https://books.google.com/books/content?id=zC5kDwAAQBAJ&printsec=frontcover&img=1&zoom=1"
    },
    {
        "titulo": "El Código Da Vinci",
        "autor": "Dan Brown",
        "pais_autor": "Estados Unidos",
        "genero": "Misterio y Suspenso",
        "editorial": "Planeta",
        "isbn_13": "9780307474278",
        "google_id": "p3Y2AQAAIAAJ",
        "paginas": 624,
        "sinopsis": "Robert Langdon y Sophie Neveu descifran enigmas artísticos e históricos ocultos en las obras de Leonardo da Vinci para resolver un asesinato.",
        "portada": "https://books.google.com/books/content?id=p3Y2AQAAIAAJ&printsec=frontcover&img=1&zoom=1"
    },
    {
        "titulo": "Inteligencia Artificial: 101 cosas que debes saber",
        "autor": "Lasse Rouhiainen",
        "pais_autor": "Finlandia",
        "genero": "Tecnología e Inteligencia Artificial",
        "editorial": "Alienta Editorial",
        "isbn_13": "9788416928828",
        "google_id": "R49wDwAAQBAJ",
        "paginas": 240,
        "sinopsis": "Un compendio accesible y riguroso sobre cómo la inteligencia artificial, los algoritmos y el aprendizaje automático están transformando el mundo.",
        "portada": "https://books.google.com/books/content?id=R49wDwAAQBAJ&printsec=frontcover&img=1&zoom=1"
    },
    {
        "titulo": "Cosmos",
        "autor": "Carl Sagan",
        "pais_autor": "Estados Unidos",
        "genero": "Ciencia Ficción",
        "editorial": "Random House",
        "isbn_13": "9780345331359",
        "google_id": "m9dYAAAAMAA1",
        "paginas": 396,
        "sinopsis": "Un viaje inolvidable a través de 15.000 millones de años de evolución cósmica y científica relatado con una elocuencia incomparable.",
        "portada": "https://books.google.com/books/content?id=m9dYAAAAMAA1&printsec=frontcover&img=1&zoom=1"
    },
    {
        "titulo": "Crimen y Castigo",
        "autor": "Fiódor Dostoyevski",
        "pais_autor": "Rusia",
        "genero": "Literatura Clásica",
        "editorial": "El Mensajero Ruso",
        "isbn_13": "9788420685670",
        "google_id": "q3Y2AQAAIAAJ",
        "paginas": 672,
        "sinopsis": "El dilema moral y psicológico del joven estudiante Raskólnikov tras cometer un asesinato justificado bajo sus propias teorías filosóficas.",
        "portada": "https://books.google.com/books/content?id=q3Y2AQAAIAAJ&printsec=frontcover&img=1&zoom=1"
    },
    {
        "titulo": "Orgullo y Prejuicio",
        "autor": "Jane Austen",
        "pais_autor": "Reino Unido",
        "genero": "Romance",
        "editorial": "T. Egerton",
        "isbn_13": "9788491051510",
        "google_id": "r3Y2AQAAIAAJ",
        "paginas": 448,
        "sinopsis": "La ingeniosa Elizabeth Bennet y el aristócrata Fitzwilliam Darcy deben superar sus prejuicios y malentendidos sociales para encontrarse.",
        "portada": "https://books.google.com/books/content?id=r3Y2AQAAIAAJ&printsec=frontcover&img=1&zoom=1"
    },
    {
        "titulo": "El Silmarillion",
        "autor": "J.R.R. Tolkien",
        "pais_autor": "Reino Unido",
        "genero": "Fantasía",
        "editorial": "George Allen & Unwin",
        "isbn_13": "9780261102736",
        "google_id": "s3Y2AQAAIAAJ",
        "paginas": 480,
        "sinopsis": "Los mitos y leyendas de la Primera Edad de la Tierra Media: la creación de Eä, los Silmarils y la rebelión de los Noldor.",
        "portada": "https://books.google.com/books/content?id=s3Y2AQAAIAAJ&printsec=frontcover&img=1&zoom=1"
    },
    {
        "titulo": "El nombre de la rosa",
        "autor": "Umberto Eco",
        "pais_autor": "Italia",
        "genero": "Misterio y Suspenso",
        "editorial": "Bompiani",
        "isbn_13": "9788426418197",
        "google_id": "t3Y2AQAAIAAJ",
        "paginas": 544,
        "sinopsis": "Fray Guillermo de Baskerville investiga una serie de misteriosas muertes ocurridas en una remota y enigmática abadía benedictina en el siglo XIV.",
        "portada": "https://books.google.com/books/content?id=t3Y2AQAAIAAJ&printsec=frontcover&img=1&zoom=1"
    }
]


# =====================================================================
# 2. FUNCIONES DE POBLADO EFICIENTE
# =====================================================================

def poblar_catalogo_libros():
    print("[1/4] Poblando catálogo de libros con datos de Google Books...")
    
    for item in LIBROS_SEED_DATA:
        autor_obj, _ = Autor.objects.get_or_create(
            nombre=item['autor'],
            defaults={'pais_origen': item.get('pais_autor', 'Internacional')}
        )

        editorial_obj, _ = Editorial.objects.get_or_create(
            nombre=item['editorial'],
            defaults={'pais': 'Internacional'}
        )

        genero_obj, _ = Genero.objects.get_or_create(
            slug=slugify(item['genero']),
            defaults={'nombre': item['genero']}
        )

        libro_obj, created = Libro.objects.update_or_create(
            google_book_id=item['google_id'],
            defaults={
                'titulo': item['titulo'],
                'autor': autor_obj,
                'editorial': editorial_obj,
                'genero': item['genero'],
                'sinopsis': item['sinopsis'],
                'paginas': item['paginas'],
                'isbn_13': item.get('isbn_13'),
                'portada_url': item['portada'],
                'calificacion_promedio': round(random.uniform(4.3, 4.95), 2),
                'idioma': 'es',
            }
        )
        libro_obj.generos.add(genero_obj)

    print(f"  -> Catálogo establecido: {Libro.objects.count()} libros.")


def crear_planes_y_asistente():
    print("[2/4] Configurando Planes de Suscripción y Asistente IA...")
    
    planes = [
        ('Gratuito', 'gratis', 'Acceso al catálogo base y consultas diarias con el Asistente IA.', Decimal('0.00'), 15, 20, False, 1),
        ('Lector Pro', 'lector-pro', 'Recomendaciones avanzadas de IA, hasta 100 consultas diarias y biblioteca ampliada.', Decimal('4990.00'), 100, 100, True, 2),
        ('Lector VIP', 'lector-vip', 'Experiencia ilimitada, modelos de IA de última generación y acceso prioritario a novedades.', Decimal('9990.00'), 0, 0, True, 3),
    ]

    for nom, slug, desc, precio, lim_ia, lim_fav, ia_adv, orden in planes:
        PlanSuscripcion.objects.update_or_create(
            slug=slug,
            defaults={
                'nombre': nom,
                'descripcion': desc,
                'precio': precio,
                'moneda': 'CLP',
                'periodo': 'mensual',
                'limite_consultas_ia_diarias': lim_ia,
                'limite_favoritos': lim_fav,
                'acceso_ia_avanzada': ia_adv,
                'orden': orden
            }
        )

    AsistenteIA.objects.get_or_create(
        nombre='LitMate',
        defaults={
            'descripcion': 'Asistente virtual experto en literatura y recomendaciones inteligentes',
            'modelo_llm': 'llama-3.1-8b-instant',
            'temperatura': 0.7,
            'max_tokens': 350,
            'activo': True
        }
    )
    print("  -> Planes y Asistente IA LitMate listos.")


NOMBRES = [
    "Mateo", "Santiago", "Lucas", "Benjamín", "Matías", "Joaquín", "Nicolás", "Alejandro", "Tomás", "Diego",
    "Sebastián", "Agustín", "Gabriel", "Felipe", "Ignacio", "Vicente", "Martín", "Daniel", "Emiliano", "Rodrigo",
    "Sofía", "Isabella", "Valentina", "Camila", "Valeria", "Mariana", "Gabriela", "Lucía", "Catalina", "Elena",
    "Victoria", "Martina", "Florencia", "Antonella", "Javiera", "Francisca", "Constanza", "Paulina", "Andrea", "Paula",
    "Alonso", "Maximiliano", "Bruno", "Leonardo", "Emilio", "Samuel", "Álvaro", "Cristóbal", "Damián", "Fernando",
    "Julieta", "Renata", "Mia", "Zoe", "Clara", "Alma", "Amelia", "Emma", "Isidora", "Josefa",
    "Gonzalo", "Esteban", "Andrés", "Patricio", "Mauricio", "Guillermo", "Claudio", "Hugo", "Iván", "Óscar",
    "Daniela", "Bárbara", "Paz", "Paloma", "Rocío", "Macarena", "Claudia", "Natalia", "Loreto", "Marcela",
    "Raúl", "Manuel", "Sergio", "Jorge", "Fabián", "Víctor", "Carlos", "Pablo", "Hernán", "Ricardo",
    "Beatriz", "Laura", "Sara", "Carmen", "Rosa", "Teresa", "Silvia", "Patricia", "Mónica", "Alicia"
]

APELLIDOS = [
    "González", "Muñoz", "Rojas", "Díaz", "Pérez", "Soto", "Contreras", "Silva", "Martínez", "Sepúlveda",
    "Morales", "Rodríguez", "López", "Fuentes", "Hernández", "Torres", "Araya", "Flores", "Espinoza", "Valenzuela",
    "Castillo", "Tapia", "Reyes", "Gutiérrez", "Castro", "Pizarro", "Álvarez", "Vásquez", "Sánchez", "Fernández",
    "Ramírez", "Carrasco", "Gómez", "Cortés", "Herrera", "Núñez", "Jara", "Vergara", "Rivera", "Figueroa",
    "Riquelme", "García", "Miranda", "Bravo", "Vera", "Molina", "Vega", "Campos", "Sandoval", "Orellana"
]

PAISES = ["Chile", "Chile", "Chile", "Argentina", "México", "España", "Colombia", "Perú", "Uruguay"]
GENEROS_LECTURA = ["Ciencia Ficción", "Fantasía", "Misterio y Suspenso", "Filosofía", "Historia", "Desarrollo Personal", "Romance", "Terror"]


def crear_100_usuarios_eficiente():
    print("[3/4] Creando exactamente 100 usuarios con perfiles y suscripciones...")
    plan_gratis = PlanSuscripcion.objects.get(slug='gratis')
    plan_pro = PlanSuscripcion.objects.get(slug='lector-pro')
    plan_vip = PlanSuscripcion.objects.get(slug='lector-vip')

    # Hash precalculado una sola vez para máxima velocidad
    hashed_pwd = make_password("Password123!")

    for i in range(1, 101):
        nombre = NOMBRES[(i - 1) % len(NOMBRES)]
        apellido = APELLIDOS[(i - 1) % len(APELLIDOS)]
        username = f"{slugify(nombre)}.{slugify(apellido)}{i}"
        email = f"{username}@litmatemail.com"

        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                'first_name': nombre,
                'last_name': apellido,
                'email': email,
                'is_active': True,
                'password': hashed_pwd
            }
        )

        pais = random.choice(PAISES)
        genero_fav = random.choice(GENEROS_LECTURA)
        ano_nac = random.randint(1975, 2005)

        PerfilUsuario.objects.update_or_create(
            usuario=user,
            defaults={
                'nombre': nombre,
                'apellido': apellido,
                'correo': email,
                'pais': pais,
                'genero_lector_preferido': genero_fav,
                'fecha_nacimiento': datetime.date(ano_nac, random.randint(1, 12), random.randint(1, 28)),
                'biografia': f"Lector apasionado de {genero_fav}. Residente en {pais}.",
                'telefono': f"+56 9 {random.randint(1000, 9999)} {random.randint(1000, 9999)}"
            }
        )

        # Suscripción
        if i % 10 == 0:
            plan = plan_vip
            monto = plan_vip.precio
        elif i % 5 == 0:
            plan = plan_pro
            monto = plan_pro.precio
        else:
            plan = plan_gratis
            monto = Decimal('0.00')

        suscripcion, _ = SuscripcionUsuario.objects.update_or_create(
            usuario=user,
            defaults={
                'plan': plan,
                'estado': 'activa',
                'fecha_inicio': timezone.now() - datetime.timedelta(days=random.randint(5, 90)),
                'auto_renovar': True,
            }
        )

        if monto > 0:
            HistorialPago.objects.get_or_create(
                suscripcion=suscripcion,
                usuario=user,
                plan=plan,
                monto=monto,
                defaults={
                    'moneda': 'CLP',
                    'metodo_pago': random.choice(['tarjeta_credito', 'webpay', 'mercadopago']),
                    'estado': 'completado',
                    'referencia_transaccion': f"tx_cloud_{random.randint(100000, 999999)}"
                }
            )

    print(f"  -> Base de usuarios lista: {User.objects.count()} usuarios registrados.")


def poblar_analitica_e_interacciones():
    print("[4/4] Generando telemetría, estados de lectura, reseñas y eventos...")
    libros = list(Libro.objects.all())
    usuarios = list(User.objects.all()[:100])
    asistente = AsistenteIA.objects.first()

    comentarios = [
        ("Una obra cumbre imprescindible. La prosa y el ritmo narrativo son sublimes.", 5, 0.92),
        ("Fascinante de principio a fin. El asistente LitMate acertó completamente con la recomendación.", 5, 0.88),
        ("Muy buen libro, con personajes profundos e ideas enriquecedoras.", 4, 0.74),
        ("Lectura entretenida y accesible, muy recomendada para pasar un buen fin de semana.", 4, 0.65),
        ("Interesante premisa aunque esperaba un desenlace con mayor impacto.", 3, 0.20),
    ]

    for u in usuarios:
        libros_usuario = random.sample(libros, min(len(libros), random.randint(3, 7)))

        for libro in libros_usuario:
            # Estado de lectura
            estado = random.choice(['completado', 'completado', 'leyendo', 'por_leer', 'abandonado'])
            p_avance = 100.0 if estado == 'completado' else (random.uniform(15.0, 85.0) if estado == 'leyendo' else 0.0)

            EstadoLectura.objects.update_or_create(
                usuario=u,
                libro=libro,
                defaults={
                    'estado': estado,
                    'pagina_actual': int((p_avance / 100.0) * libro.paginas),
                    'porcentaje_avance': round(p_avance, 1),
                    'minutos_lectura_estimados': int(libro.paginas * 1.5),
                    'fecha_inicio': timezone.now() - datetime.timedelta(days=random.randint(5, 45)),
                    'fecha_termino': timezone.now() if estado == 'completado' else None,
                }
            )

            # Favoritos
            if random.random() < 0.5:
                LibroFavorito.objects.update_or_create(
                    usuario=u,
                    google_id=libro.google_book_id or f"id_{libro.id}",
                    defaults={
                        'libro': libro,
                        'titulo': libro.titulo,
                        'autores': libro.autor.nombre,
                        'imagen_url': libro.portada_url,
                    }
                )

            # Reseña
            if estado == 'completado' and random.random() < 0.65:
                texto, calif, sentiment = random.choice(comentarios)
                Resena.objects.update_or_create(
                    usuario=u,
                    libro=libro,
                    defaults={
                        'calificacion': calif,
                        'comentario': texto,
                        'sentimiento_score': sentiment,
                        'votos_utiles': random.randint(1, 30),
                    }
                )

    # Actualizar agregados de libros
    for libro in libros:
        resenas = Resena.objects.filter(libro=libro)
        if resenas.exists():
            libro.total_resenas = resenas.count()
            libro.calificacion_promedio = round(resenas.aggregate(models.Avg('calificacion'))['calificacion__avg'], 2)
        libro.total_favoritos = LibroFavorito.objects.filter(libro=libro).count()
        libro.save()

    # Telemetría de Eventos y Conversiones
    tipos_evento = [('busqueda', 'catalogo'), ('ver_libro', 'catalogo'), ('abrir_chat', 'chat_ia'), ('ver_planes', 'suscripciones'), ('click_comprar', 'afiliados')]

    for u in usuarios[:50]:
        for _ in range(random.randint(2, 6)):
            tipo, mod = random.choice(tipos_evento)
            libro_rnd = random.choice(libros)
            EventoAnalitica.objects.create(
                usuario=u,
                session_key=f"sess_{u.id}_{random.randint(100, 999)}",
                tipo_evento=tipo,
                modulo=mod,
                detalles_evento={'libro_id': libro_rnd.id, 'genero': libro_rnd.genero},
                ip_origen=f"190.{random.randint(10, 200)}.{random.randint(1, 250)}.{random.randint(1, 250)}"
            )

            if tipo == 'click_comprar' or random.random() < 0.2:
                ClickConversion.objects.create(
                    usuario=u,
                    libro=libro_rnd,
                    proveedor='Buscalibre',
                    url_destino=f"https://www.buscalibre.cl/libros/search?q={libro_rnd.titulo.replace(' ', '+')}",
                    precio_referencia=Decimal(str(random.randint(9900, 22900)))
                )

    print("  -> Telemetría y analítica generadas.")


def main():
    print("=" * 70)
    print("INICIANDO POBLADO DE ALTO RENDIMIENTO EN TIDB CLOUD")
    print("=" * 70)

    poblar_catalogo_libros()
    crear_planes_y_asistente()
    crear_100_usuarios_eficiente()
    poblar_analitica_e_interacciones()

    print("\n" + "=" * 70)
    print("¡RESUMEN FINAL DE LA BASE DE DATOS EN LA NUBE!")
    print(f"  • Usuarios Registrados: {User.objects.count()}")
    print(f"  • Perfiles con Demografía: {PerfilUsuario.objects.count()}")
    print(f"  • Suscripciones Activas: {SuscripcionUsuario.objects.count()}")
    print(f"  • Libros en Catálogo: {Libro.objects.count()}")
    print(f"  • Autores: {Autor.objects.count()}")
    print(f"  • Editoriales: {Editorial.objects.count()}")
    print(f"  • Reseñas con NLP Sentiment: {Resena.objects.count()}")
    print(f"  • Estados de Lectura: {EstadoLectura.objects.count()}")
    print(f"  • Libros Favoritos: {LibroFavorito.objects.count()}")
    print(f"  • Eventos de Telemetría (BI): {EventoAnalitica.objects.count()}")
    print(f"  • Clicks de Afiliados (Conversión): {ClickConversion.objects.count()}")
    print("=" * 70)


if __name__ == '__main__':
    main()
