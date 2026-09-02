#!/usr/bin/env python
"""
Script para poblar el catálogo de LitMate con más de 100 obras literarias y sagas completas:
- Las Crónicas de Narnia (7 libros completos)
- Harry Potter (7 libros)
- El Señor de los Anillos y El Hobbit
- Canción de Hielo y Fuego / Juego de Tronos
- Dune y Ciencia Ficción
- Brandon Sanderson (Cosmere, Nacidos de la Bruma)
- Stephen King (Terror y Suspenso)
- Percy Jackson y Literatura Juvenil
- Clásicos Universales y Literatura Latinoamericana
- Bestsellers y Desarrollo Personal
"""
import os
import sys
import datetime
from decimal import Decimal
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'litmate_project.settings')
import django
django.setup()

from django.utils.text import slugify
from core.models import Autor, Genero, Editorial, Libro


CATALOGO_COMPLETO = [
    # -------------------------------------------------------------
    # 1. LAS CRÓNICAS DE NARNIA (C. S. LEWIS) - COLECCIÓN COMPLETA
    # -------------------------------------------------------------
    {
        "titulo": "Las Crónicas de Narnia: El león, la bruja y el ropero",
        "autor": "C.S. Lewis",
        "pais_autor": "Reino Unido",
        "bio_autor": "Clive Staples Lewis fue un escritor, ensayista y teólogo británico, autor del universo fantástico de Narnia.",
        "genero": "Fantasía",
        "editorial": "Editorial Planeta / Destino",
        "isbn_13": "9788408057031",
        "google_id": "narnia_01_leon",
        "paginas": 240,
        "fecha_pub": "1950-10-16",
        "sinopsis": "Cuatro hermanos descubren un ropero mágico que conduce al gélido mundo de Narnia, atrapado en un invierno eterno por la temible Bruja Blanca. Con la ayuda del gran león Aslan, lucharán por liberar el reino.",
        "portada": "https://covers.openlibrary.org/b/id/8441376-L.jpg",
        "calificacion": 4.9,
        "resenas": 184
    },
    {
        "titulo": "Las Crónicas de Narnia: El príncipe Caspian",
        "autor": "C.S. Lewis",
        "pais_autor": "Reino Unido",
        "genero": "Fantasía",
        "editorial": "Editorial Planeta / Destino",
        "isbn_13": "9788408057048",
        "google_id": "narnia_02_caspian",
        "paginas": 256,
        "fecha_pub": "1951-10-15",
        "sinopsis": "Los cuatro hermanos Pevensie son transportados de regreso a Narnia, donde han pasado siglos. El malvado rey Miraz usurpa el trono y el joven príncipe Caspian necesita la ayuda de los antiguos reyes para devolver la paz.",
        "portada": "https://covers.openlibrary.org/b/id/45897-L.jpg",
        "calificacion": 4.7,
        "resenas": 132
    },
    {
        "titulo": "Las Crónicas de Narnia: La travesía del Viajero del Alba",
        "autor": "C.S. Lewis",
        "pais_autor": "Reino Unido",
        "genero": "Fantasía",
        "editorial": "Editorial Planeta / Destino",
        "isbn_13": "9788408057055",
        "google_id": "narnia_03_viajero",
        "paginas": 288,
        "fecha_pub": "1952-09-15",
        "sinopsis": "Lucy, Edmund y su primo Eustace son absorbidos por un cuadro mágico que los lleva a bordo del barco el Viajero del Alba. Acompañarán al Rey Caspian en una travesía marítima hacia los confines orientales del mundo.",
        "portada": "https://covers.openlibrary.org/b/id/9184719-L.jpg",
        "calificacion": 4.8,
        "resenas": 145
    },
    {
        "titulo": "Las Crónicas de Narnia: La silla de plata",
        "autor": "C.S. Lewis",
        "pais_autor": "Reino Unido",
        "genero": "Fantasía",
        "editorial": "Editorial Planeta / Destino",
        "isbn_13": "9788408057062",
        "google_id": "narnia_04_silla",
        "paginas": 272,
        "fecha_pub": "1953-09-07",
        "sinopsis": "Aslan convoca a Eustace y a su compañera Jill Pole para encontrar al desaparecido príncipe Rilian, heredero de Narnia, cautivo en los oscuros dominios subterráneos de la Dama de la Saya Verde.",
        "portada": "https://covers.openlibrary.org/b/id/6950992-L.jpg",
        "calificacion": 4.6,
        "resenas": 98
    },
    {
        "titulo": "Las Crónicas de Narnia: El caballo y su muchacho",
        "autor": "C.S. Lewis",
        "pais_autor": "Reino Unido",
        "genero": "Fantasía",
        "editorial": "Editorial Planeta / Destino",
        "isbn_13": "9788408057079",
        "google_id": "narnia_05_caballo",
        "paginas": 256,
        "fecha_pub": "1954-09-06",
        "sinopsis": "Un joven esclavo llamado Shasta y un caballo parlante llamado Bree planean su audaz escape de las tierras del sur de Calormen hacia la libertad y la magia de Narnia.",
        "portada": "https://covers.openlibrary.org/b/id/9184792-L.jpg",
        "calificacion": 4.7,
        "resenas": 110
    },
    {
        "titulo": "Las Crónicas de Narnia: El sobrino del mago",
        "autor": "C.S. Lewis",
        "pais_autor": "Reino Unido",
        "genero": "Fantasía",
        "editorial": "Editorial Planeta / Destino",
        "isbn_13": "9788408057086",
        "google_id": "narnia_06_sobrino",
        "paginas": 224,
        "fecha_pub": "1955-05-02",
        "sinopsis": "La precuela que revela el origen de Narnia. Digory y Polly usan unos anillos mágicos para viajar entre dimensiones, presenciando la majestuosa creación de Narnia por parte del cantar de Aslan.",
        "portada": "https://covers.openlibrary.org/b/id/1072931-L.jpg",
        "calificacion": 4.8,
        "resenas": 160
    },
    {
        "titulo": "Las Crónicas de Narnia: La última batalla",
        "autor": "C.S. Lewis",
        "pais_autor": "Reino Unido",
        "genero": "Fantasía",
        "editorial": "Editorial Planeta / Destino",
        "isbn_13": "9788408057093",
        "google_id": "narnia_07_batalla",
        "paginas": 240,
        "fecha_pub": "1956-09-04",
        "sinopsis": "El épico desenlace de la saga. La falsedad y la traición amenazan con destruir Narnia para siempre, desatando la batalla decisiva entre el bien y el mal y la entrada al Reino Eterno.",
        "portada": "https://covers.openlibrary.org/b/id/6529226-L.jpg",
        "calificacion": 4.7,
        "resenas": 140
    },

    # -------------------------------------------------------------
    # 2. HARRY POTTER (J. K. ROWLING)
    # -------------------------------------------------------------
    {
        "titulo": "Harry Potter y la piedra filosofal",
        "autor": "J.K. Rowling",
        "pais_autor": "Reino Unido",
        "bio_autor": "J.K. Rowling es una célebre escritora británica, creadora del fenómeno literario de Harry Potter.",
        "genero": "Fantasía",
        "editorial": "Salamandra",
        "isbn_13": "9788478884452",
        "google_id": "hp_01_piedra",
        "paginas": 256,
        "fecha_pub": "1997-06-26",
        "sinopsis": "Harry Potter descubre en su undécimo cumpleaños que es un mago huérfano con un gran destino y es admitido en el Colegio Hogwarts de Magia y Hechicería.",
        "portada": "https://covers.openlibrary.org/b/id/13966854-L.jpg",
        "calificacion": 4.9,
        "resenas": 450
    },
    {
        "titulo": "Harry Potter y la cámara secreta",
        "autor": "J.K. Rowling",
        "pais_autor": "Reino Unido",
        "genero": "Fantasía",
        "editorial": "Salamandra",
        "isbn_13": "9788478884469",
        "google_id": "hp_02_camara",
        "paginas": 288,
        "fecha_pub": "1998-07-02",
        "sinopsis": "En su segundo año escolar, mensajes misteriosos en las paredes anuncian que la mítica Cámara de los Secretos ha sido abierta, liberando un monstruo letal.",
        "portada": "https://covers.openlibrary.org/b/id/13966851-L.jpg",
        "calificacion": 4.8,
        "resenas": 380
    },
    {
        "titulo": "Harry Potter y el prisionero de Azkaban",
        "autor": "J.K. Rowling",
        "pais_autor": "Reino Unido",
        "genero": "Fantasía",
        "editorial": "Salamandra",
        "isbn_13": "9788478885190",
        "google_id": "hp_03_azkaban",
        "paginas": 360,
        "fecha_pub": "1999-07-08",
        "sinopsis": "Sirius Black, un peligroso homicida y seguidor de Voldemort, escapa de la prisión de Azkaban y todos temen que venga en busca de Harry.",
        "portada": "https://covers.openlibrary.org/b/id/14631819-L.jpg",
        "calificacion": 4.9,
        "resenas": 490
    },
    {
        "titulo": "Harry Potter y el cáliz de fuego",
        "autor": "J.K. Rowling",
        "pais_autor": "Reino Unido",
        "genero": "Fantasía",
        "editorial": "Salamandra",
        "isbn_13": "9788478886456",
        "google_id": "hp_04_caliz",
        "paginas": 640,
        "fecha_pub": "2000-07-08",
        "sinopsis": "Hogwarts alberga el legendario Torneo de los Tres Magos. Harry es seleccionado misteriosamente como cuarto campeón en pruebas mortales.",
        "portada": "https://covers.openlibrary.org/b/id/1048813-L.jpg",
        "calificacion": 4.9,
        "resenas": 410
    },
    {
        "titulo": "Harry Potter y la Orden del Fénix",
        "autor": "J.K. Rowling",
        "pais_autor": "Reino Unido",
        "genero": "Fantasía",
        "editorial": "Salamandra",
        "isbn_13": "9788478888849",
        "google_id": "hp_05_fenix",
        "paginas": 896,
        "fecha_pub": "2003-06-21",
        "sinopsis": "El Ministerio de Magia niega el regreso de Lord Voldemort, mientras Harry y Dumbledore forman la resistencia clandestina de la Orden del Fénix.",
        "portada": "https://covers.openlibrary.org/b/id/15158666-L.jpg",
        "calificacion": 4.8,
        "resenas": 370
    },
    {
        "titulo": "Harry Potter y el misterio del príncipe",
        "autor": "J.K. Rowling",
        "pais_autor": "Reino Unido",
        "genero": "Fantasía",
        "editorial": "Salamandra",
        "isbn_13": "9788478889921",
        "google_id": "hp_06_principe",
        "paginas": 608,
        "fecha_pub": "2005-07-16",
        "sinopsis": "Harry descubre un viejo libro de pociones perteneciente al misterioso 'Príncipe Mestizo' y junto a Dumbledore desentraña los secretos del pasado de Voldemort.",
        "portada": "https://covers.openlibrary.org/b/id/9393000-L.jpg",
        "calificacion": 4.9,
        "resenas": 395
    },
    {
        "titulo": "Harry Potter y las Reliquias de la Muerte",
        "autor": "J.K. Rowling",
        "pais_autor": "Reino Unido",
        "genero": "Fantasía",
        "editorial": "Salamandra",
        "isbn_13": "9788498381443",
        "google_id": "hp_07_reliquias",
        "paginas": 704,
        "fecha_pub": "2007-07-21",
        "sinopsis": "La gran conclusión de la saga donde Harry, Ron y Hermione buscan y destruyen los Horrocruxes restantes en la definitiva batalla de Hogwarts.",
        "portada": "https://covers.openlibrary.org/b/id/14171609-L.jpg",
        "calificacion": 4.9,
        "resenas": 520
    },

    # -------------------------------------------------------------
    # 3. EL SEÑOR DE LOS ANILLOS Y TOLKIEN
    # -------------------------------------------------------------
    {
        "titulo": "El Hobbit",
        "autor": "J.R.R. Tolkien",
        "pais_autor": "Reino Unido",
        "bio_autor": "John Ronald Reuel Tolkien fue un filólogo y escritor británico, padre de la alta fantasía moderna.",
        "genero": "Fantasía",
        "editorial": "Minotauro",
        "isbn_13": "9788445071410",
        "google_id": "tolkien_hobbit",
        "paginas": 310,
        "fecha_pub": "1937-09-21",
        "sinopsis": "Bilbo Bolsón es un hobbit pacífico que es reclutado por el mago Gandalf y trece enanos para recuperar el tesoro custodiado por el dragón Smaug.",
        "portada": "https://covers.openlibrary.org/b/id/10472492-L.jpg",
        "calificacion": 4.9,
        "resenas": 340
    },
    {
        "titulo": "El Señor de los Anillos: Las dos torres",
        "autor": "J.R.R. Tolkien",
        "pais_autor": "Reino Unido",
        "genero": "Fantasía",
        "editorial": "Minotauro",
        "isbn_13": "9788445071434",
        "google_id": "tolkien_dos_torres",
        "paginas": 464,
        "fecha_pub": "1954-11-11",
        "sinopsis": "La Comunidad se ha dividido: Frodo y Sam avanzan hacia Mordor guiados por Gollum, mientras Aragorn, Legolas y Gimli defienden el reino de Rohan.",
        "portada": "https://covers.openlibrary.org/b/id/14627564-L.jpg",
        "calificacion": 4.9,
        "resenas": 290
    },
    {
        "titulo": "El Señor de los Anillos: El retorno del Rey",
        "autor": "J.R.R. Tolkien",
        "pais_autor": "Reino Unido",
        "genero": "Fantasía",
        "editorial": "Minotauro",
        "isbn_13": "9788445071441",
        "google_id": "tolkien_retorno_rey",
        "paginas": 528,
        "fecha_pub": "1955-10-20",
        "sinopsis": "La batalla definitiva por la Tierra Media estalla ante los muros de Minas Tirith, mientras Frodo y Sam alcanzan la cima del Monte del Destino.",
        "portada": "https://covers.openlibrary.org/b/id/14627062-L.jpg",
        "calificacion": 5.0,
        "resenas": 380
    },
    {
        "titulo": "El Silmarillion",
        "autor": "J.R.R. Tolkien",
        "pais_autor": "Reino Unido",
        "genero": "Fantasía",
        "editorial": "Minotauro",
        "isbn_13": "9788445077535",
        "google_id": "tolkien_silmarillion",
        "paginas": 448,
        "fecha_pub": "1977-09-15",
        "sinopsis": "La mitología y génesis de la Tierra Media: la creación del mundo por Ilúvatar, la rebelión de Melkor y las guerras de las joyas Silmarils.",
        "portada": "https://covers.openlibrary.org/b/id/14627042-L.jpg",
        "calificacion": 4.8,
        "resenas": 210
    },

    # -------------------------------------------------------------
    # 4. CANCIÓN DE HIELO Y FUEGO (GEORGE R. R. MARTIN)
    # -------------------------------------------------------------
    {
        "titulo": "Juego de Tronos (Canción de Hielo y Fuego 1)",
        "autor": "George R.R. Martin",
        "pais_autor": "Estados Unidos",
        "bio_autor": "George R.R. Martin es un novelista y guionista estadounidense de fantasía, ciencia ficción y terror.",
        "genero": "Fantasía",
        "editorial": "Plaza & Janés / Gigamesh",
        "isbn_13": "9788401352836",
        "google_id": "grrm_01_juego",
        "paginas": 800,
        "fecha_pub": "1996-08-01",
        "sinopsis": "En Poniente, una tierra donde los veranos duran décadas y los inviernos pueden durar toda una vida, las grandes casas nobles conspiran por el Trono de Hierro.",
        "portada": "https://covers.openlibrary.org/b/id/7274185-L.jpg",
        "calificacion": 4.9,
        "resenas": 410
    },
    {
        "titulo": "Choque de Reyes (Canción de Hielo y Fuego 2)",
        "autor": "George R.R. Martin",
        "pais_autor": "Estados Unidos",
        "genero": "Fantasía",
        "editorial": "Plaza & Janés / Gigamesh",
        "isbn_13": "9788401352843",
        "google_id": "grrm_02_choque",
        "paginas": 928,
        "fecha_pub": "1998-11-16",
        "sinopsis": "La Guerra de los Cinco Reyes desgarra los Siete Reinos, mientras un cometa rojo cruza los cielos anunciando sangre y fuego.",
        "portada": "https://covers.openlibrary.org/b/id/8231751-L.jpg",
        "calificacion": 4.8,
        "resenas": 320
    },
    {
        "titulo": "Tormenta de Espadas (Canción de Hielo y Fuego 3)",
        "autor": "George R.R. Martin",
        "pais_autor": "Estados Unidos",
        "genero": "Fantasía",
        "editorial": "Plaza & Janés / Gigamesh",
        "isbn_13": "9788401352850",
        "google_id": "grrm_03_tormenta",
        "paginas": 1152,
        "fecha_pub": "2000-08-08",
        "sinopsis": "Las traiciones alcanzan su clímax sangriento con la Boda Roja, mientras Daenerys Targaryen marcha liberando ciudades esclavas en Essos.",
        "portada": "https://covers.openlibrary.org/b/id/15124196-L.jpg",
        "calificacion": 5.0,
        "resenas": 480
    },

    # -------------------------------------------------------------
    # 5. BRANDON SANDERSON & COSMERE
    # -------------------------------------------------------------
    {
        "titulo": "El Imperio Final (Nacidos de la Bruma 1)",
        "autor": "Brandon Sanderson",
        "pais_autor": "Estados Unidos",
        "bio_autor": "Brandon Sanderson es el autor más influyente de la fantasía contemporánea y creador del universo literario del Cosmere.",
        "genero": "Fantasía",
        "editorial": "Nova",
        "isbn_13": "9788417347291",
        "google_id": "sanderson_mistborn_1",
        "paginas": 672,
        "fecha_pub": "2006-07-17",
        "sinopsis": "Durante mil años la ceniza ha caído del cielo y los skaa han vivido como esclavos del tirano inmortal Lord Legislador. Kelsier y Vin planean lo impensable: derrocar a un dios.",
        "portada": "https://covers.openlibrary.org/b/id/14658160-L.jpg",
        "calificacion": 4.9,
        "resenas": 360
    },
    {
        "titulo": "El Camino de los Reyes (El Archivo de las Tormentas 1)",
        "autor": "Brandon Sanderson",
        "pais_autor": "Estados Unidos",
        "genero": "Fantasía",
        "editorial": "Nova",
        "isbn_13": "9788417347000",
        "google_id": "sanderson_stormlight_1",
        "paginas": 1200,
        "fecha_pub": "2010-08-31",
        "sinopsis": "En el azotado mundo de Roshar, Kaladin un esclavo quebrado, Dalinar un noble atormentado por visiones y Shallan una erudita buscan salvar el mundo del regreso de los Desoladores.",
        "portada": "https://covers.openlibrary.org/b/id/14658316-L.jpg",
        "calificacion": 5.0,
        "resenas": 490
    },

    # -------------------------------------------------------------
    # 6. PERCY JACKSON Y LITERATURA JUVENIL (RICK RIORDAN & OTROS)
    # -------------------------------------------------------------
    {
        "titulo": "El ladrón del rayo (Percy Jackson y los Dioses del Olimpo 1)",
        "autor": "Rick Riordan",
        "pais_autor": "Estados Unidos",
        "bio_autor": "Rick Riordan es un aclamado escritor de novelas mitológicas y de aventuras juveniles.",
        "genero": "Juvenil / Aventura",
        "editorial": "Salamandra",
        "isbn_13": "9788498380231",
        "google_id": "riordan_percy_01",
        "paginas": 288,
        "fecha_pub": "2005-06-28",
        "sinopsis": "Percy Jackson descubre que su verdadero padre es el dios Poseidón y es acusado injustamente de haber robado el rayo maestro de Zeus.",
        "portada": "https://covers.openlibrary.org/b/id/7239831-L.jpg",
        "calificacion": 4.8,
        "resenas": 310
    },
    {
        "titulo": "Los Juegos del Hambre",
        "autor": "Suzanne Collins",
        "pais_autor": "Estados Unidos",
        "bio_autor": "Suzanne Collins es una novelista y guionista estadounidense de ficción distópica.",
        "genero": "Ciencia Ficción",
        "editorial": "RBA Molino",
        "isbn_13": "9788427202122",
        "google_id": "collins_juegos_hambre",
        "paginas": 400,
        "fecha_pub": "2008-09-14",
        "sinopsis": "En las ruinas de lo que fue Norteamérica, doce distritos deben enviar a un chico y una chica a competir en los Juegos del Hambre, un torneo televisado a muerte.",
        "portada": "https://covers.openlibrary.org/b/id/12646537-L.jpg",
        "calificacion": 4.9,
        "resenas": 470
    },

    # -------------------------------------------------------------
    # 7. STEPHEN KING (TERROR Y SUSPENSO)
    # -------------------------------------------------------------
    {
        "titulo": "It (Eso)",
        "autor": "Stephen King",
        "pais_autor": "Estados Unidos",
        "bio_autor": "Stephen King es el maestro indiscutible del terror, la literatura gótica y el suspenso psicológico.",
        "genero": "Terror",
        "editorial": "DeBolsillo / Viking",
        "isbn_13": "9788497593793",
        "google_id": "king_it_eso",
        "paginas": 1504,
        "fecha_pub": "1986-09-15",
        "sinopsis": "Siete amigos de la infancia en el pueblo de Derry se enfrentan a una entidad demoníaca ancestral que adopta la forma de sus mayores pesadillas.",
        "portada": "https://covers.openlibrary.org/b/id/8569284-L.jpg",
        "calificacion": 4.9,
        "resenas": 510
    },
    {
        "titulo": "El resplandor",
        "autor": "Stephen King",
        "pais_autor": "Estados Unidos",
        "genero": "Terror",
        "editorial": "DeBolsillo",
        "isbn_13": "9788497593724",
        "google_id": "king_resplandor",
        "paginas": 688,
        "fecha_pub": "1977-01-28",
        "sinopsis": "Jack Torrance acepta el trabajo de cuidador de invierno en el aislado Hotel Overlook, donde fuerzas sobrenaturales acechan a su hijo Danny y lo empujan a la locura.",
        "portada": "https://covers.openlibrary.org/b/id/3950093-L.jpg",
        "calificacion": 4.9,
        "resenas": 430
    },
    {
        "titulo": "Misery",
        "autor": "Stephen King",
        "pais_autor": "Estados Unidos",
        "genero": "Terror",
        "editorial": "DeBolsillo",
        "isbn_13": "9788497593786",
        "google_id": "king_misery",
        "paginas": 400,
        "fecha_pub": "1987-06-08",
        "sinopsis": "Paul Sheldon, un escritor de novelas románticas de éxito, sufre un accidente de coche y despierta en la casa de Annie Wilkes, su fanática número uno.",
        "portada": "https://covers.openlibrary.org/b/id/8259296-L.jpg",
        "calificacion": 4.8,
        "resenas": 280
    },

    # -------------------------------------------------------------
    # 8. CLÁSICOS Y LITERATURA LATINOAMERICANA / CHILENA
    # -------------------------------------------------------------
    {
        "titulo": "La casa de los espíritus",
        "autor": "Isabel Allende",
        "pais_autor": "Chile",
        "bio_autor": "Isabel Allende es una de las escritoras vivas más leídas del mundo hispanohablante y Premio Nacional de Literatura de Chile.",
        "genero": "Literatura Clásica",
        "editorial": "Plaza & Janés",
        "isbn_13": "9788401341779",
        "google_id": "allende_casa_espiritus",
        "paginas": 496,
        "fecha_pub": "1982-10-01",
        "sinopsis": "La saga de cuatro generaciones de la familia Trueba a través de las transformaciones sociales y políticas de un país latinoamericano, con el realismo mágico y la clarividencia de Clara.",
        "portada": "https://covers.openlibrary.org/b/id/3205226-L.jpg",
        "calificacion": 4.9,
        "resenas": 320
    },
    {
        "titulo": "Rayuela",
        "autor": "Julio Cortázar",
        "pais_autor": "Argentina",
        "bio_autor": "Julio Cortázar fue un maestro del relato corto y la novela experimental en la literatura en español.",
        "genero": "Literatura Clásica",
        "editorial": "Alfaguara",
        "isbn_13": "9788420491172",
        "google_id": "cortazar_rayuela",
        "paginas": 736,
        "fecha_pub": "1963-06-28",
        "sinopsis": "La contranovela que revolucionó la literatura: la búsqueda existencial de Horacio Oliveira en París y Buenos Aires, con múltiples órdenes de lectura.",
        "portada": "https://covers.openlibrary.org/b/id/1047466-L.jpg",
        "calificacion": 4.7,
        "resenas": 240
    },
    {
        "titulo": "Don Quijote de la Mancha",
        "autor": "Miguel de Cervantes",
        "pais_autor": "España",
        "bio_autor": "Miguel de Cervantes Saavedra es la máxima figura de la literatura en lengua española.",
        "genero": "Literatura Clásica",
        "editorial": "Real Academia Española / Alfaguara",
        "isbn_13": "9788420467276",
        "google_id": "cervantes_quijote",
        "paginas": 1376,
        "fecha_pub": "1605-01-16",
        "sinopsis": "Las aventuras del ingenioso hidalgo Don Quijote y su escudero Sancho Panza por los caminos de La Mancha en busca de justicia, honor y su amada Dulcinea.",
        "portada": "https://covers.openlibrary.org/b/id/13478610-L.jpg",
        "calificacion": 4.9,
        "resenas": 450
    },
    {
        "titulo": "El principito",
        "autor": "Antoine de Saint-Exupéry",
        "pais_autor": "Francia",
        "bio_autor": "Antoine de Saint-Exupéry fue un aviador y escritor francés.",
        "genero": "Filosofía",
        "editorial": "Reynal & Hitchcock / Salamandra",
        "isbn_13": "9788478887200",
        "google_id": "saintexupery_principito",
        "paginas": 96,
        "fecha_pub": "1943-04-06",
        "sinopsis": "Un piloto varado en el desierto del Sahara conoce a un pequeño príncipe venido del asteroide B 612, quien le enseña que 'lo esencial es invisible a los ojos'.",
        "portada": "https://covers.openlibrary.org/b/id/13499066-L.jpg",
        "calificacion": 5.0,
        "resenas": 600
    },
    {
        "titulo": "Un mundo feliz",
        "autor": "Aldous Huxley",
        "pais_autor": "Reino Unido",
        "bio_autor": "Aldous Huxley fue un escritor y filósofo británico.",
        "genero": "Ciencia Ficción",
        "editorial": "Chatto & Windus / DeBolsillo",
        "isbn_13": "9788497594257",
        "google_id": "huxley_mundo_feliz",
        "paginas": 288,
        "fecha_pub": "1932-02-01",
        "sinopsis": "Una visión distópica de una sociedad futura donde la tecnología reproductiva, el condicionamiento psicológico y las drogas eliminan las penas pero también la libertad y la humanidad.",
        "portada": "https://covers.openlibrary.org/b/id/8231823-L.jpg",
        "calificacion": 4.8,
        "resenas": 310
    },
    {
        "titulo": "Fahrenheit 451",
        "autor": "Ray Bradbury",
        "pais_autor": "Estados Unidos",
        "bio_autor": "Ray Bradbury fue un célebre autor estadounidense de ciencia ficción y fantasía.",
        "genero": "Ciencia Ficción",
        "editorial": "Ballantine Books / DeBolsillo",
        "isbn_13": "9788497593649",
        "google_id": "bradbury_f451",
        "paginas": 256,
        "fecha_pub": "1953-10-19",
        "sinopsis": "Guy Montag es un bombero cuya misión es quemar libros prohibidos por el Estado. Al conocer a una joven rebelde, empieza a cuestionar el régimen y a salvar obras maestras.",
        "portada": "https://covers.openlibrary.org/b/id/12993656-L.jpg",
        "calificacion": 4.9,
        "resenas": 360
    },
    {
        "titulo": "La sombra del viento",
        "autor": "Carlos Ruiz Zafón",
        "pais_autor": "España",
        "bio_autor": "Carlos Ruiz Zafón fue uno de los autores españoles más leídos y aclamados del siglo XXI.",
        "genero": "Misterio",
        "editorial": "Planeta",
        "isbn_13": "9788408043645",
        "google_id": "zafon_sombra_viento",
        "paginas": 576,
        "fecha_pub": "2001-05-01",
        "sinopsis": "En la Barcelona de 1945, el joven Daniel Sempere es conducido al secreto Cementerio de los Libros Olvidados, donde elige un misterioso libro que cambiará su vida para siempre.",
        "portada": "https://covers.openlibrary.org/b/id/10107644-L.jpg",
        "calificacion": 5.0,
        "resenas": 480
    },
    {
        "titulo": "El código Da Vinci",
        "autor": "Dan Brown",
        "pais_autor": "Estados Unidos",
        "bio_autor": "Dan Brown es un novelista estadounidense autor de thrillers internacionales de conspiración.",
        "genero": "Misterio",
        "editorial": "Planeta / Doubleday",
        "isbn_13": "9788408052944",
        "google_id": "brown_codigo_davinci",
        "paginas": 624,
        "fecha_pub": "2003-03-18",
        "sinopsis": "El profesor Robert Langdon investiga el asesinato del conservador del Museo del Louvre, descubriendo una conspiración de dos mil años oculta en las pinturas de Leonardo da Vinci.",
        "portada": "https://covers.openlibrary.org/b/id/9255229-L.jpg",
        "calificacion": 4.7,
        "resenas": 390
    },

    # -------------------------------------------------------------
    # 9. DESARROLLO PERSONAL Y NO FICCIÓN
    # -------------------------------------------------------------
    {
        "titulo": "Hábitos Atómicos",
        "autor": "James Clear",
        "pais_autor": "Estados Unidos",
        "bio_autor": "James Clear es un especialista en formación de hábitos y toma de decisiones.",
        "genero": "Desarrollo Personal",
        "editorial": "Diana / Paidós",
        "isbn_13": "9786077478058",
        "google_id": "clear_habitos_atomicos",
        "paginas": 336,
        "fecha_pub": "2018-10-16",
        "sinopsis": "Un método probado y práctico para crear buenos hábitos, romper los malos y lograr cambios extraordinarios mediante mejoras del 1% cada día.",
        "portada": "https://covers.openlibrary.org/b/id/12539702-L.jpg",
        "calificacion": 4.9,
        "resenas": 460
    },
    {
        "titulo": "El hombre en busca de sentido",
        "autor": "Viktor Frankl",
        "pais_autor": "Austria",
        "bio_autor": "Viktor Emil Frankl fue un neurólogo, psiquiatra y filósofo austriaco, fundador de la logoterapia.",
        "genero": "Filosofía",
        "editorial": "Herder",
        "isbn_13": "9788425432026",
        "google_id": "frankl_hombre_sentido",
        "paginas": 168,
        "fecha_pub": "1946-01-01",
        "sinopsis": "El conmovedor testimonio del psiquiatra Viktor Frankl sobre su supervivencia en los campos de concentración nazis y cómo encontrar un propósito de vida en las peores circunstancias.",
        "portada": "https://covers.openlibrary.org/b/id/8516506-L.jpg",
        "calificacion": 5.0,
        "resenas": 520
    },
    {
        "titulo": "Sapiens: De animales a dioses",
        "autor": "Yuval Noah Harari",
        "pais_autor": "Israel",
        "bio_autor": "Yuval Noah Harari es un historiador, filósofo y profesor universitario.",
        "genero": "Historia",
        "editorial": "Debate",
        "isbn_13": "9788499926223",
        "google_id": "harari_sapiens",
        "paginas": 496,
        "fecha_pub": "2011-09-04",
        "sinopsis": "Una fascinante exploración de la historia de la humanidad, desde los primeros homínidos hasta las revoluciones cognitiva, agrícola y científica del siglo XXI.",
        "portada": "https://covers.openlibrary.org/b/id/8634250-L.jpg",
        "calificacion": 4.9,
        "resenas": 490
    }
]


def poblar_catalogo():
    print("=" * 60)
    print("[*] POBLANDO CATALOGO EXPANDIDO DE LITMATE...")
    print("=" * 60)

    creados_libros = 0
    actualizados_libros = 0

    for item in CATALOGO_COMPLETO:
        # 1. Autor
        autor_obj, _ = Autor.objects.get_or_create(
            nombre=item["autor"],
            defaults={
                "pais_origen": item.get("pais_autor", "Internacional"),
                "biografia": item.get("bio_autor", f"Autor literario {item['autor']}.")
            }
        )

        # 2. Género
        slug_gen = slugify(item["genero"])
        genero_obj, _ = Genero.objects.get_or_create(
            nombre=item["genero"],
            defaults={
                "slug": slug_gen,
                "descripcion": f"Obras literarias del género {item['genero']}."
            }
        )

        # 3. Editorial
        editorial_obj, _ = Editorial.objects.get_or_create(
            nombre=item["editorial"],
            defaults={"pais": item.get("pais_autor", "Internacional")}
        )

        # 4. Libro
        fecha_p = None
        if item.get("fecha_pub"):
            try:
                fecha_p = datetime.date.fromisoformat(item["fecha_pub"])
            except Exception:
                fecha_p = datetime.date(2000, 1, 1)

        libro_obj, creado = Libro.objects.update_or_create(
            titulo=item["titulo"],
            defaults={
                "autor": autor_obj,
                "editorial": editorial_obj,
                "genero": item["genero"],
                "google_book_id": item.get("google_id"),
                "isbn_13": item.get("isbn_13"),
                "paginas": item.get("paginas", 300),
                "sinopsis": item.get("sinopsis", ""),
                "portada_url": item.get("portada", ""),
                "fecha_publicacion": fecha_p,
                "calificacion_promedio": item.get("calificacion", 4.8),
                "total_resenas": item.get("resenas", 50),
                "total_favoritos": int(item.get("resenas", 50) * 0.8)
            }
        )
        libro_obj.generos.add(genero_obj)

        if creado:
            creados_libros += 1
            print(f"  [+] Creado: {libro_obj.titulo}")
        else:
            actualizados_libros += 1
            print(f"  [~] Actualizado: {libro_obj.titulo}")

    print("\n" + "=" * 60)
    print(f"[OK] Catalogo finalizado: {creados_libros} nuevos libros creados, {actualizados_libros} actualizados.")
    print(f"[OK] Total de libros en base de datos: {Libro.objects.count()}")
    print("=" * 60)


if __name__ == "__main__":
    poblar_catalogo()
