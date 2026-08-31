#!/usr/bin/env python
"""
Generación ultra rápida con bulk_create para poblar todas las interacciones y telemetría en TiDB Cloud.
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

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'litmate_project.settings')
import django
django.setup()

from django.contrib.auth.models import User
from django.db import transaction, models
from django.utils import timezone
from core.models import (
    Libro, PerfilUsuario, Resena, LibroFavorito, EstadoLectura,
    AsistenteIA, ConversacionIA, MensajeIA, RecomendacionIALog,
    EventoAnalitica, ClickConversion
)

def run():
    print("Iniciando batch seed de interacciones y analítica...")
    users = list(User.objects.all()[:100])
    libros = list(Libro.objects.all())
    asistente = AsistenteIA.objects.first()

    if not users or not libros:
        print("Error: Se requieren usuarios y libros.")
        return

    estados_list = []
    favoritos_list = []
    resenas_list = []
    eventos_list = []
    clicks_list = []

    comentarios = [
        ("Una obra cumbre imprescindible. La prosa y el ritmo narrativo son sublimes.", 5, 0.92),
        ("Fascinante de principio a fin. El asistente LitMate acertó completamente con la recomendación.", 5, 0.88),
        ("Muy buen libro, con personajes profundos e ideas enriquecedoras.", 4, 0.74),
        ("Lectura entretenida y accesible, muy recomendada para pasar un buen fin de semana.", 4, 0.65),
        ("Interesante premisa aunque esperaba un desenlace con mayor impacto.", 3, 0.20),
    ]

    for u in users:
        sample_libros = random.sample(libros, min(len(libros), random.randint(3, 6)))
        for libro in sample_libros:
            estado = random.choice(['completado', 'completado', 'leyendo', 'por_leer', 'abandonado'])
            p_avance = 100.0 if estado == 'completado' else (random.uniform(15.0, 85.0) if estado == 'leyendo' else 0.0)
            pags = libro.paginas or 300

            estados_list.append(EstadoLectura(
                usuario=u,
                libro=libro,
                estado=estado,
                pagina_actual=int((p_avance / 100.0) * pags),
                porcentaje_avance=round(p_avance, 1),
                minutos_lectura_estimados=int(pags * 1.5),
                fecha_inicio=timezone.now() - datetime.timedelta(days=random.randint(5, 45)),
                fecha_termino=timezone.now() if estado == 'completado' else None,
            ))

            if random.random() < 0.5:
                favoritos_list.append(LibroFavorito(
                    usuario=u,
                    libro=libro,
                    google_id=libro.google_book_id or f"id_{libro.id}",
                    titulo=libro.titulo,
                    autores=libro.autor.nombre,
                    imagen_url=libro.portada_url,
                ))

            if estado == 'completado' and random.random() < 0.65:
                texto, calif, sentiment = random.choice(comentarios)
                resenas_list.append(Resena(
                    usuario=u,
                    libro=libro,
                    calificacion=calif,
                    comentario=texto,
                    sentimiento_score=sentiment,
                    votos_utiles=random.randint(1, 30),
                ))

        # Eventos y Clicks
        for _ in range(random.randint(2, 4)):
            tipo, mod = random.choice([('busqueda', 'catalogo'), ('ver_libro', 'catalogo'), ('abrir_chat', 'chat_ia'), ('ver_planes', 'suscripciones'), ('click_comprar', 'afiliados')])
            l_rnd = random.choice(libros)
            eventos_list.append(EventoAnalitica(
                usuario=u,
                session_key=f"sess_{u.id}_{random.randint(100, 999)}",
                tipo_evento=tipo,
                modulo=mod,
                detalles_evento={'libro_id': l_rnd.id, 'genero': l_rnd.genero},
                ip_origen=f"190.{random.randint(10, 200)}.{random.randint(1, 250)}.{random.randint(1, 250)}"
            ))
            if tipo == 'click_comprar' or random.random() < 0.25:
                clicks_list.append(ClickConversion(
                    usuario=u,
                    libro=l_rnd,
                    proveedor='Buscalibre',
                    url_destino=f"https://www.buscalibre.cl/libros/search?q={l_rnd.titulo.replace(' ', '+')}",
                    precio_referencia=Decimal(str(random.randint(9900, 22900)))
                ))

    print(f"Insertando {len(estados_list)} estados de lectura...")
    EstadoLectura.objects.bulk_create(estados_list, ignore_conflicts=True)

    print(f"Insertando {len(favoritos_list)} favoritos...")
    LibroFavorito.objects.bulk_create(favoritos_list, ignore_conflicts=True)

    print(f"Insertando {len(resenas_list)} reseñas con score de sentimiento...")
    Resena.objects.bulk_create(resenas_list, ignore_conflicts=True)

    print(f"Insertando {len(eventos_list)} eventos de telemetría...")
    EventoAnalitica.objects.bulk_create(eventos_list, ignore_conflicts=True)

    print(f"Insertando {len(clicks_list)} conversiones a librerías...")
    ClickConversion.objects.bulk_create(clicks_list, ignore_conflicts=True)

    # Conversaciones IA
    print("Creando sesiones y mensajes de IA con telemetría...")
    for u in users[:40]:
        conv = ConversacionIA.objects.create(
            usuario=u,
            asistente=asistente,
            titulo=f"Consulta de lectura de {u.first_name}",
            total_mensajes=2
        )
        l_rnd = random.choice(libros)
        msg_u = MensajeIA.objects.create(
            conversacion=conv,
            rol='user',
            contenido=f"¿Qué me puedes recomendar similar a {l_rnd.titulo}?",
            tokens_prompt=16,
            intencion_detectada="recomendacion"
        )
        msg_bot = MensajeIA.objects.create(
            conversacion=conv,
            rol='assistant',
            contenido=f"Te sugiero explorar '{l_rnd.titulo}' de {l_rnd.autor.nombre}. Destaca por su narrativa y profundidad temática.",
            tokens_completion=45,
            tokens_utilizados=61,
            latencia_ms=random.randint(480, 950),
            feedback_usuario=random.choice([1, 1, 1, 0, -1]),
            metadata_json={'libro_id': l_rnd.id, 'score_rag': 0.93}
        )

    # Actualizar promedios en Libros
    for libro in libros:
        resenas = Resena.objects.filter(libro=libro)
        if resenas.exists():
            libro.total_resenas = resenas.count()
            libro.calificacion_promedio = round(resenas.aggregate(models.Avg('calificacion'))['calificacion__avg'], 2)
        libro.total_favoritos = LibroFavorito.objects.filter(libro=libro).count()
        libro.save()

    print("¡Batch seeding de analítica completado exitosamente!")

if __name__ == '__main__':
    run()
